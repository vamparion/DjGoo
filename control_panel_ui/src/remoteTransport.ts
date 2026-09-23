import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { x25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { hkdf } from "@noble/hashes/hkdf.js";

const enc = new TextEncoder();
const dec = new TextDecoder();
const REQUEST = "DJGOO-LINK-1:";
const RESPONSE = "DJGOO-LINK-1-RESPONSE:";
const RESPONSE_ATTACHMENT = "DJGOO-LINK-1-ATTACHMENT:";
const MAX_CONTENT = 1950;

type BrowserTransport = "relay" | "discord";
type Endpoint = { transport: string; endpoint: string; security: string; code: string; room_id: string; host_public_key: string };
export type WebRoute = { transport: BrowserTransport; endpoint: string };
export type WebCredential = {
  transport?: BrowserTransport;
  routes?: WebRoute[];
  webhook_url?: string;
  relay_url?: string;
  room_id: string;
  host_public_key: string;
  host_fingerprint: string;
  device_id: string;
  device_token: string;
  discord_user_id: string;
  guild_id: string;
  device_type: string;
  capabilities: string[];
};

type ExchangeContext = {
  requestId: string;
  secret: Uint8Array;
  salt: Uint8Array;
  envelope: Record<string, unknown>;
  roomId: string;
};

const b64d = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));
const b64e = (b: Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hex = (b: Uint8Array) => [...b].map(x => x.toString(16).padStart(2, "0")).join("");

async function discordJson(response: Response, operation: string): Promise<Record<string, any>> {
  const text = await response.text();
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object") return value;
  } catch {
    // Convert proxy, captive-portal, and stale-cache HTML into a useful error.
  }
  const received = text.trimStart().startsWith("<") ? "a webpage" : "an invalid response";
  throw new Error(`Discord returned ${received} while ${operation}. Refresh DjGoo and try the newest link.`);
}

function discordUrlCandidates(url: string): string[] {
  const parsed = new URL(url);
  const hosts = [parsed.hostname, "discord.com", "discordapp.com", "canary.discord.com"];
  return [...new Set(hosts)].map(host => {
    const candidate = new URL(parsed.toString());
    candidate.hostname = host;
    return candidate.toString();
  });
}

async function pollDiscordMessage(url: string): Promise<Response | null> {
  for (const candidate of discordUrlCandidates(url)) {
    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (response.status !== 429 && response.status < 500) return response;
    } catch {
      // Mobile networks and Discord edges can drop an individual CORS fetch.
      // Continue polling the same encrypted message through another API edge.
    }
  }
  return null;
}

async function createDiscordMessage(url: string, body: string): Promise<Response | null> {
  let lastResponse: Response | null = null;
  for (const candidate of discordUrlCandidates(url)) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetch(candidate + (candidate.includes("?") ? "&wait=true" : "?wait=true"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          cache: "no-store",
        });
        lastResponse = response;
        if (response.status !== 429 && response.status < 500) return response;
        const limited = await response.clone().json().catch(() => ({}));
        const retrySeconds = Math.max(0.5, Math.min(8, Number(limited.retry_after || 1)));
        await new Promise(resolve => setTimeout(resolve, retrySeconds * 1000));
      } catch {
        await new Promise(resolve => setTimeout(resolve, 350 * (attempt + 1)));
      }
    }
  }
  return lastResponse;
}

function validateBrowserEndpoint(endpoint: Endpoint): Endpoint | null {
  const transport = endpoint.transport as BrowserTransport;
  if (transport !== "relay" && transport !== "discord") return null;
  if (!endpoint.room_id || !endpoint.host_public_key) return null;
  if (hex(sha256(b64d(endpoint.host_public_key))) !== endpoint.security.toLowerCase()) {
    throw new Error("Host identity fingerprint does not match");
  }
  const route = new URL(endpoint.endpoint);
  if (transport === "relay") {
    if (route.protocol !== "wss:") throw new Error("Invalid hosted relay route");
  } else {
    const allowed = ["discord.com", "www.discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com", "www.discordapp.com"];
    if (route.protocol !== "https:" || !allowed.includes(route.hostname)) throw new Error("Invalid Discord route");
  }
  return endpoint;
}

function parseInvite(uri: string, allowExpired = false): { endpoints: Endpoint[]; expires_at: number; guild_name: string } {
  if (uri.length > 16384) throw new Error("Pairing invitation is too large");
  const url = new URL(uri);
  if (url.protocol !== "djgoo:" || url.hostname !== "pair") throw new Error("Invalid DjGoo invitation");
  const payload = JSON.parse(dec.decode(b64d(url.searchParams.get("d") || "")));
  if (payload.protocol !== 2 || (!allowExpired && Number(payload.expires_at) <= Date.now() / 1000)) throw new Error("This pairing invitation has expired");
  const raw = Array.isArray(payload.endpoints) ? payload.endpoints : [];
  const endpoints = raw
    .map((item: Endpoint) => validateBrowserEndpoint(item))
    .filter((item: Endpoint | null): item is Endpoint => Boolean(item))
    .sort((a, b) => (a.transport === "relay" ? 0 : 1) - (b.transport === "relay" ? 0 : 1));
  if (!endpoints.length) throw new Error("This invitation has no browser-compatible route");
  return { endpoints, expires_at: Number(payload.expires_at), guild_name: String(payload.guild_name || "") };
}

function routesFromCredential(credential: WebCredential): WebRoute[] {
  const routes: WebRoute[] = [];
  for (const route of credential.routes || []) {
    if ((route.transport === "relay" || route.transport === "discord") && route.endpoint) routes.push(route);
  }
  if (credential.relay_url) routes.push({ transport: "relay", endpoint: credential.relay_url });
  if (credential.webhook_url) routes.push({ transport: "discord", endpoint: credential.webhook_url });
  const seen = new Set<string>();
  return routes.filter(route => {
    const key = `${route.transport}:${route.endpoint}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function remoteTransportKind(credential: WebCredential | null): BrowserTransport | null {
  if (!credential) return null;
  if (credential.transport === "relay" || credential.transport === "discord") return credential.transport;
  return routesFromCredential(credential)[0]?.transport || null;
}

export function inviteMatchesCredential(uri: string, credential: WebCredential): boolean {
  try {
    const { endpoints } = parseInvite(uri, true);
    return endpoints.some(endpoint =>
      endpoint.room_id === credential.room_id
      && endpoint.host_public_key === credential.host_public_key
    );
  } catch {
    return false;
  }
}

export function credentialWithInviteRoutes(uri: string, credential: WebCredential): WebCredential {
  try {
    const { endpoints } = parseInvite(uri, true);
    if (!endpoints.some(endpoint => endpoint.room_id === credential.room_id && endpoint.host_public_key === credential.host_public_key)) return credential;
    const routes = endpoints.map(endpoint => ({ transport: endpoint.transport as BrowserTransport, endpoint: endpoint.endpoint }));
    const preferred = routes[0];
    return {
      ...credential,
      transport: preferred?.transport || credential.transport,
      routes,
      relay_url: routes.find(route => route.transport === "relay")?.endpoint || credential.relay_url,
      webhook_url: routes.find(route => route.transport === "discord")?.endpoint || credential.webhook_url,
    };
  } catch {
    return credential;
  }
}

function prepareExchange(roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>): ExchangeContext {
  const requestId = crypto.randomUUID();
  const secret = x25519.utils.randomSecretKey();
  const clientPublic = x25519.getPublicKey(secret);
  const shared = x25519.getSharedSecret(secret, b64d(hostPublicKey));
  const salt = sha256(enc.encode(roomId));
  const key = hkdf(sha256, shared, salt, enc.encode(`djgoo-relay-v1:${requestId}:request`), 32);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const aad = enc.encode(`djgoo-relay-v1|${roomId}|${requestId}|request`);
  const ciphertext = chacha20poly1305(key, nonce, aad).encrypt(enc.encode(JSON.stringify({ action, payload })));
  return {
    requestId,
    secret,
    salt,
    roomId,
    envelope: { protocol: 1, room_id: roomId, request_id: requestId, client_public_key: b64e(clientPublic), nonce: b64e(nonce), ciphertext: b64e(ciphertext) },
  };
}

async function decodeEncryptedResult(encrypted: Record<string, any>, context: ExchangeContext) {
  if (encrypted.request_id !== context.requestId || encrypted.room_id !== context.roomId) throw new Error("Host response identity changed");
  const responseShared = x25519.getSharedSecret(context.secret, b64d(encrypted.host_ephemeral_public_key));
  const responseKey = hkdf(sha256, responseShared, context.salt, enc.encode(`djgoo-relay-v1:${context.requestId}:response`), 32);
  const responseAad = enc.encode(`djgoo-relay-v1|${context.roomId}|${context.requestId}|response`);
  let plain = chacha20poly1305(responseKey, b64d(encrypted.nonce), responseAad).decrypt(b64d(encrypted.ciphertext));
  if (encrypted.encoding === "gzip-json") {
    const stream = new Blob([plain as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
    plain = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const result = JSON.parse(dec.decode(plain));
  if (!result.ok) throw new Error(String(result.error || "DjGoo Host rejected the request"));
  return result.result;
}

async function exchangeDiscord(routeUrl: string, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  const context = prepareExchange(roomId, hostPublicKey, action, payload);
  const content = REQUEST + b64e(enc.encode(JSON.stringify(context.envelope)));
  if (content.length > MAX_CONTENT) throw new Error("Encrypted request is too large");
  const created = await createDiscordMessage(
    routeUrl,
    JSON.stringify({ content, flags: 4096, allowed_mentions: { parse: [] } }),
  );
  if (!created?.ok) throw new Error(`Discord is busy (${created?.status || "offline"}). DjGoo will retry another secure route when available.`);
  const messageId = String((await discordJson(created, "opening the secure connection")).id || "");
  if (!messageId) throw new Error("Discord did not return a secure message ID. Try the newest DjGoo link.");
  const messageUrl = `${routeUrl}/messages/${messageId}`;
  try {
    const deadline = Date.now() + 25000;
    let delay = 400;
    while (Date.now() < deadline) {
      const response = await pollDiscordMessage(messageUrl);
      if (!response) { await new Promise(r => setTimeout(r, delay = Math.min(delay * 2, 4000))); continue; }
      if (response.status === 429) { await new Promise(r => setTimeout(r, delay = Math.min(delay * 2, 4000))); continue; }
      if (response.ok) {
        const message = await discordJson(response, "waiting for DjGoo Host");
        let responseContent = String(message.content || "");
        if (responseContent.startsWith(RESPONSE_ATTACHMENT)) {
          const attachmentUrl = String(message.attachments?.[0]?.url || "");
          if (attachmentUrl) responseContent = await fetch(attachmentUrl, { cache: "no-store" }).then(item => item.text());
        }
        if (responseContent.startsWith(RESPONSE)) {
          const encrypted = JSON.parse(dec.decode(b64d(responseContent.slice(RESPONSE.length))));
          return await decodeEncryptedResult(encrypted, context);
        }
      }
      await new Promise(r => setTimeout(r, delay));
    }
    throw new Error("DjGoo could not retrieve the Host response from Discord.");
  } finally {
    await fetch(messageUrl, { method: "DELETE" }).catch(() => undefined);
  }
}

function relayClientUrl(routeUrl: string, roomId: string): string {
  const url = new URL(routeUrl);
  if (url.protocol !== "wss:") throw new Error("DjGoo hosted relay must use wss://");
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/v1/client/${encodeURIComponent(roomId)}`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

type PendingRelayRequest = {
  context: ExchangeContext;
  resolve: (value: any) => void;
  reject: (error: Error) => void;
  timer: number;
};

class RelaySocketSession {
  private socket: WebSocket | null = null;
  private opening: Promise<WebSocket> | null = null;
  private pending = new Map<string, PendingRelayRequest>();

  constructor(
    private routeUrl: string,
    private roomId: string,
    private hostPublicKey: string,
  ) {}

  private failPending(error: Error) {
    for (const request of this.pending.values()) {
      window.clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }

  private async open(): Promise<WebSocket> {
    if (this.socket?.readyState === WebSocket.OPEN) return this.socket;
    if (this.opening) return this.opening;

    this.opening = new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(relayClientUrl(this.routeUrl, this.roomId));
      let opened = false;
      const timeout = window.setTimeout(() => {
        try { socket.close(); } catch { /* no-op */ }
        reject(new Error("DjGoo hosted relay connection timed out"));
      }, 12000);

      socket.onopen = () => {
        opened = true;
        window.clearTimeout(timeout);
        this.socket = socket;
        resolve(socket);
      };
      socket.onerror = () => {
        if (!opened) {
          window.clearTimeout(timeout);
          reject(new Error("DjGoo hosted relay connection failed"));
        }
      };
      socket.onclose = () => {
        window.clearTimeout(timeout);
        if (this.socket === socket) this.socket = null;
        this.opening = null;
        this.failPending(new Error("DjGoo hosted relay disconnected; reconnecting"));
        if (!opened) reject(new Error("DjGoo hosted relay closed before connecting"));
      };
      socket.onmessage = event => {
        void this.handleMessage(event);
      };
    }).finally(() => {
      this.opening = null;
    });

    return this.opening;
  }

  private async handleMessage(event: MessageEvent) {
    let response: Record<string, any>;
    try {
      response = JSON.parse(String(event.data || "{}"));
    } catch {
      return;
    }
    if (response.type === "error") {
      const first = this.pending.values().next().value as PendingRelayRequest | undefined;
      if (first) {
        window.clearTimeout(first.timer);
        this.pending.delete(first.context.requestId);
        first.reject(new Error(`DjGoo hosted relay: ${String(response.code || "unknown error")}`));
      }
      return;
    }
    const encrypted = response.envelope;
    const requestId = String(encrypted?.request_id || "");
    const request = this.pending.get(requestId);
    if (response.type !== "relay_response" || !request) return;
    this.pending.delete(requestId);
    window.clearTimeout(request.timer);
    try {
      request.resolve(await decodeEncryptedResult(encrypted, request.context));
    } catch (error) {
      request.reject(error instanceof Error ? error : new Error(String(error)));
    }
  }

  async exchange(action: string, payload: Record<string, unknown>) {
    const context = prepareExchange(this.roomId, this.hostPublicKey, action, payload);
    const socket = await this.open();
    return await new Promise<any>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(context.requestId);
        reject(new Error("DjGoo hosted relay request timed out"));
      }, 20000);
      this.pending.set(context.requestId, { context, resolve, reject, timer });
      try {
        socket.send(JSON.stringify({ type: "relay_request", envelope: context.envelope }));
      } catch (error) {
        window.clearTimeout(timer);
        this.pending.delete(context.requestId);
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }
}

const relaySessions = new Map<string, RelaySocketSession>();
type PendingDirectRequest = {
  resolve: (value: any) => void;
  reject: (error: Error) => void;
  timer: number;
};

class WebRTCControlSession {
  private peer: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private opening: Promise<void> | null = null;
  private retryTimer = 0;
  private pending = new Map<string, PendingDirectRequest>();
  private lastRevision = 0;

  constructor(private credential: WebCredential) {}

  get connected() {
    return this.channel?.readyState === "open";
  }

  async open(): Promise<void> {
    if (this.connected) return;
    if (this.opening) return this.opening;
    this.opening = this.negotiate().finally(() => {
      this.opening = null;
    });
    return this.opening;
  }

  async command(intent: string, values: Record<string, unknown>) {
    await this.open();
    return await this.request("command", {
      command: {
        ...values,
        intent,
        command_id: crypto.randomUUID(),
        created_at: Date.now() / 1000,
        confidence: 1,
        device_id: this.credential.device_id,
        guild_id: this.credential.guild_id,
      },
    });
  }

  async state() {
    await this.open();
    const result = await this.request("reconcile", { last_revision: this.lastRevision });
    this.rememberRevision(result);
    return result;
  }

  private async negotiate() {
    this.closePeer();
    const peer = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
    const channel = peer.createDataChannel("djgoo-control", { ordered: true });
    this.peer = peer;
    this.channel = channel;
    channel.onmessage = event => this.handleMessage(event);
    channel.onclose = () => this.scheduleReconnect();
    channel.onerror = () => this.scheduleReconnect();
    peer.onconnectionstatechange = () => {
      if (["failed", "closed", "disconnected"].includes(peer.connectionState)) this.scheduleReconnect();
    };
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await waitForIceGathering(peer, 2500);
    const sessionId = crypto.randomUUID();
    const answer = await exchangeCredential(this.credential, "webrtc/signal", {
      type: "offer",
      session_id: sessionId,
      device_token: this.credential.device_token,
      device_id: this.credential.device_id,
      guild_id: this.credential.guild_id,
      offer: peer.localDescription && { type: peer.localDescription.type, sdp: peer.localDescription.sdp },
    });
    const description = answer?.answer as RTCSessionDescriptionInit | undefined;
    if (!description?.sdp) throw new Error("DjGoo Host did not return a direct connection answer");
    await peer.setRemoteDescription(description);
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("Direct connection timed out")), 8000);
      channel.onopen = () => {
        window.clearTimeout(timer);
        resolve();
      };
      if (channel.readyState === "open") {
        window.clearTimeout(timer);
        resolve();
      }
    });
  }

  private request(type: string, payload: Record<string, unknown>) {
    if (!this.connected || !this.channel) throw new Error("Direct connection is not open");
    const requestId = crypto.randomUUID();
    return new Promise<any>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error("Direct connection request timed out"));
      }, 8000);
      this.pending.set(requestId, { resolve, reject, timer });
      this.channel?.send(JSON.stringify({ type, request_id: requestId, ...payload }));
    });
  }

  private handleMessage(event: MessageEvent) {
    let message: Record<string, any>;
    try {
      message = JSON.parse(String(event.data || "{}"));
    } catch {
      return;
    }
    if (message.type === "state" && message.state) {
      this.rememberRevision(message.state);
      return;
    }
    if (message.type !== "response") return;
    const request = this.pending.get(String(message.request_id || ""));
    if (!request) return;
    window.clearTimeout(request.timer);
    this.pending.delete(String(message.request_id || ""));
    if (message.ok) {
      this.rememberRevision(message.result);
      request.resolve(message.result);
    } else {
      request.reject(new Error(String(message.error || "Direct connection request failed")));
    }
  }

  private rememberRevision(value: any) {
    const revision = Number(value?.revision || 0);
    if (Number.isFinite(revision) && revision > this.lastRevision) this.lastRevision = revision;
  }

  private scheduleReconnect() {
    this.closePeer();
    window.clearTimeout(this.retryTimer);
    this.retryTimer = window.setTimeout(() => {
      void this.open().catch(() => undefined);
    }, 1500 + Math.floor(Math.random() * 2500));
  }

  private closePeer() {
    for (const request of this.pending.values()) {
      window.clearTimeout(request.timer);
      request.reject(new Error("Direct connection closed"));
    }
    this.pending.clear();
    try { this.channel?.close(); } catch { /* no-op */ }
    try { this.peer?.close(); } catch { /* no-op */ }
    this.channel = null;
    this.peer = null;
  }
}

const webRtcSessions = new Map<string, WebRTCControlSession>();

function relaySession(routeUrl: string, roomId: string, hostPublicKey: string) {
  const key = `${routeUrl}|${roomId}|${hostPublicKey}`;
  let session = relaySessions.get(key);
  if (!session) {
    session = new RelaySocketSession(routeUrl, roomId, hostPublicKey);
    relaySessions.set(key, session);
  }
  return session;
}

function directSession(credential: WebCredential) {
  const key = `${credential.room_id}|${credential.device_id}|${credential.host_fingerprint}`;
  let session = webRtcSessions.get(key);
  if (!session) {
    session = new WebRTCControlSession(credential);
    webRtcSessions.set(key, session);
  }
  return session;
}

function waitForIceGathering(peer: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise(resolve => {
    const timer = window.setTimeout(done, timeoutMs);
    function done() {
      window.clearTimeout(timer);
      peer.removeEventListener("icegatheringstatechange", changed);
      resolve();
    }
    function changed() {
      if (peer.iceGatheringState === "complete") done();
    }
    peer.addEventListener("icegatheringstatechange", changed);
  });
}

async function exchangeRelay(routeUrl: string, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  return relaySession(routeUrl, roomId, hostPublicKey).exchange(action, payload);
}

async function exchangeRoute(route: WebRoute, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  if (route.transport === "relay") return exchangeRelay(route.endpoint, roomId, hostPublicKey, action, payload);
  return exchangeDiscord(route.endpoint, roomId, hostPublicKey, action, payload);
}

async function exchangeCredential(credential: WebCredential, action: string, payload: Record<string, unknown>) {
  const routes = routesFromCredential(credential);
  if (!routes.length) throw new Error("This DjGoo web session has no usable secure route. Run /djgoo web again.");
  let lastError: Error | null = null;
  for (const route of routes) {
    try {
      return await exchangeRoute(route, credential.room_id, credential.host_public_key, action, payload);
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw lastError || new Error("DjGoo could not reach the Host");
}

export async function pairWeb(invite: string, deviceName: string): Promise<{ credential: WebCredential; guildName: string }> {
  const { endpoints, guild_name } = parseInvite(invite);
  let lastError: Error | null = null;
  for (const endpoint of endpoints) {
    try {
      const route = { transport: endpoint.transport as BrowserTransport, endpoint: endpoint.endpoint };
      const result = await exchangeRoute(route, endpoint.room_id, endpoint.host_public_key, "pair", { code: endpoint.code, device_name: deviceName });
      if (result.device_type !== "web") throw new Error("Host returned the wrong device type");
      const routes = endpoints
        .filter(item => item.room_id === endpoint.room_id && item.host_public_key === endpoint.host_public_key)
        .map(item => ({ transport: item.transport as BrowserTransport, endpoint: item.endpoint }));
      return {
        credential: {
          transport: route.transport,
          routes,
          webhook_url: routes.find(item => item.transport === "discord")?.endpoint,
          relay_url: routes.find(item => item.transport === "relay")?.endpoint,
          room_id: endpoint.room_id,
          host_public_key: endpoint.host_public_key,
          host_fingerprint: endpoint.security,
          ...result,
        },
        guildName: guild_name,
      };
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw lastError || new Error("DjGoo could not pair through any secure route");
}

export async function remoteState(c: WebCredential) {
  try {
    return await directSession(c).state();
  } catch {
    void directSession(c).open().catch(() => undefined);
    return await exchangeCredential(c, "web/state", { device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
  }
}

export async function remoteCommand(c: WebCredential, intent: string, values: Record<string, unknown> = {}) {
  try {
    return await directSession(c).command(intent, values);
  } catch {
    void directSession(c).open().catch(() => undefined);
    return await exchangeCredential(c, "command", { ...values, intent, command_id: crypto.randomUUID(), created_at: Date.now() / 1000, confidence: 1, device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
  }
}
