// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __testing,
  HostRejection,
  remoteCommand,
  remoteState,
  subscribeRemoteState,
  type WebCredential,
} from "./remoteTransport";
import { configureRemote, stateRefreshIntervalMs } from "./api";

class FakeChannel {
  static nextSendBehavior: ((message: Record<string, any>) => void) | null = null;
  readyState = "connecting";
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: Record<string, any>[] = [];
  sendBehavior = FakeChannel.nextSendBehavior;

  send(raw: string) {
    const message = JSON.parse(raw);
    this.sent.push(message);
    this.sendBehavior?.(message);
  }
  close() { this.readyState = "closed"; }
  open() { this.readyState = "open"; this.onopen?.(); }
  emit(message: Record<string, any>) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }
}

class FakePeer {
  static instances: FakePeer[] = [];
  channel = new FakeChannel();
  connectionState = "new";
  iceGatheringState = "complete";
  localDescription: RTCSessionDescriptionInit | null = null;
  onconnectionstatechange: (() => void) | null = null;
  constructor(_configuration: RTCConfiguration) { FakePeer.instances.push(this); }
  createDataChannel() { return this.channel as unknown as RTCDataChannel; }
  async createOffer() { return { type: "offer" as RTCSdpType, sdp: "offer" }; }
  async setLocalDescription(value: RTCSessionDescriptionInit) { this.localDescription = value; }
  async setRemoteDescription(_value: RTCSessionDescriptionInit) { this.connectionState = "connected"; this.channel.open(); }
  addEventListener() {}
  removeEventListener() {}
  close() { this.connectionState = "closed"; this.channel.close(); }
}

const credential: WebCredential = {
  transport: "discord",
  routes: [{ transport: "discord", endpoint: "https://discord.com/api/webhooks/1/token" }],
  room_id: "room",
  host_public_key: "host-key",
  host_fingerprint: "fingerprint",
  device_id: "device",
  device_token: "secret-token",
  discord_user_id: "123",
  guild_id: "456",
  device_type: "web",
  capabilities: ["state.read", "playback.control"],
};

function signaling(action: string, payload: Record<string, unknown>) {
  if (action === "webrtc/signal" && payload.type === "status") return { available: true, ice_servers: ["stun:example.test"] };
  if (action === "webrtc/signal" && payload.type === "offer") return { answer: { type: "answer", sdp: "answer" } };
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  FakePeer.instances = [];
  FakeChannel.nextSendBehavior = null;
  vi.stubGlobal("RTCPeerConnection", FakePeer);
});

afterEach(() => {
  __testing.reset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("WebRTC transport manager", () => {
  it("negotiates once and delivers pushed state to subscribers", async () => {
    let offers = 0;
    __testing.setExchange(async (_c, action, payload) => {
      if (payload.type === "offer") offers += 1;
      return signaling(action, payload);
    });
    const received: Record<string, any>[] = [];
    const stopA = subscribeRemoteState(credential, state => received.push(state));
    const stopB = subscribeRemoteState(credential, state => received.push(state));
    await vi.runAllTimersAsync();
    expect(offers).toBe(1);
    FakePeer.instances[0].channel.emit({ type: "state", state: { revision: 2, playback: { title: "Pushed" } } });
    expect(received).toHaveLength(2);
    expect(received[0].playback.title).toBe("Pushed");
    configureRemote(credential);
    expect(stateRefreshIntervalMs()).toBe(60000);
    stopA(); stopB();
  });

  it("reuses one command UUID when a delivered direct response is lost", async () => {
    let fallback: Record<string, any> | null = null;
    __testing.setExchange(async (_c, action, payload) => {
      const signal = signaling(action, payload);
      if (signal) return signal;
      if (action === "command") { fallback = payload; return { accepted: true }; }
      throw new Error("unexpected exchange");
    });
    const pending = remoteCommand(credential, "toggle_pause");
    await vi.advanceTimersByTimeAsync(8000);
    await pending;
    const direct = FakePeer.instances[0].channel.sent.find(item => item.type === "command")!.command;
    expect(fallback!.command_id).toBe(direct.command_id);
    expect(fallback!.created_at).toBe(direct.created_at);
  });

  it("does not fallback after an authenticated Host rejection", async () => {
    let fallbackCalls = 0;
    __testing.setExchange(async (_c, action, payload) => {
      const signal = signaling(action, payload);
      if (signal) return signal;
      fallbackCalls += 1;
      return {};
    });
    const pending = remoteCommand(credential, "toggle_pause");
    await vi.advanceTimersByTimeAsync(0);
    const channel = FakePeer.instances[0].channel;
    channel.sendBehavior = message => channel.emit({ type: "response", request_id: message.request_id, ok: false, status: 403, error: "revoked" });
    // The first request was sent before the behavior hook was attached; reply to it explicitly.
    const request = channel.sent.find(item => item.type === "command")!;
    channel.emit({ type: "response", request_id: request.request_id, ok: false, status: 403, error: "revoked" });
    await expect(pending).rejects.toBeInstanceOf(HostRejection);
    expect(fallbackCalls).toBe(0);
  });

  it("falls back with the same envelope when direct send fails before delivery", async () => {
    let fallback: Record<string, any> | null = null;
    __testing.setExchange(async (_c, action, payload) => {
      const signal = signaling(action, payload);
      if (signal) return signal;
      fallback = payload;
      return { accepted: true };
    });
    FakeChannel.nextSendBehavior = () => { throw new Error("network closed before delivery"); };
    const pending = remoteCommand(credential, "toggle_pause");
    await vi.advanceTimersByTimeAsync(0);
    await expect(pending).resolves.toEqual({ accepted: true });
    const direct = FakePeer.instances[0].channel.sent.find(item => item.type === "command")!.command;
    expect(fallback!.command_id).toBe(direct.command_id);
  });

  it("uses bounded reconnect timers while fallback state remains available", async () => {
    let offers = 0;
    __testing.setExchange(async (_c, action, payload) => {
      if (payload.type === "offer") { offers += 1; throw new Error("offline"); }
      if (action === "web/state") return { playback: { title: "Fallback" } };
      return signaling(action, payload);
    });
    const states = await Promise.all([remoteState(credential), remoteState(credential)]);
    expect(states[0].playback.title).toBe("Fallback");
    expect(offers).toBe(1);
    expect(vi.getTimerCount()).toBeLessThanOrEqual(1);
  });
});
