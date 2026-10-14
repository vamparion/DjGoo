// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ControlState } from "./types";

const state: ControlState = {
  playback: { title: "Preview", artist: "DjGoo", station: "", source: "", remaining: "", queue_count: 1 },
  queue: [{ id: "queue-1", title: "Queued song", artist: "Artist" }],
  playlists: [],
  stations: [],
  active_station: null,
  health: {},
  logs: {},
  timeline: [],
  history: [],
  gaming: {
    settings: {
      ranked_mode: false,
      per_user_queue_limit: 10,
      round_robin: false,
      vote_thresholds: {},
      explicit_policy: "allow",
      volume_normalization: true,
      normalization_target: -14,
      crossfade_enabled: false,
      crossfade_seconds: 0,
      preload_enabled: true,
      media_keys_enabled: true,
    },
    profiles: [],
  },
};

vi.mock("./api", () => ({
  createProfile: vi.fn(),
  getState: vi.fn(async () => state),
  isDirectTransportHealthy: vi.fn(() => true),
  isRemoteSession: vi.fn(() => false),
  reconnectRemote: vi.fn(),
  resetDjGoo: vi.fn(),
  savedProfile: vi.fn(() => ({ id: "host", token: "token", username: "Host", role: "host" })),
  sendCommand: vi.fn(),
  stateRefreshIntervalMs: vi.fn(() => 60_000),
  subscribeConnection: vi.fn(() => () => undefined),
  subscribeState: vi.fn(() => () => undefined),
}));

vi.mock("./components/CommandBar", () => ({ CommandBar: () => <div>Command bar</div> }));
vi.mock("./components/HealthPanel", () => ({ HealthPanel: () => <div>Health panel</div> }));
vi.mock("./components/HistoryPanel", () => ({ HistoryPanel: () => <div>History page</div> }));
vi.mock("./components/LivePanel", () => ({ LivePanel: () => <div>Live page</div> }));
vi.mock("./components/LogsPanel", () => ({ LogsPanel: () => <div>Logs page</div> }));
vi.mock("./components/PersistentFooter", () => ({ PersistentFooter: () => <div>Player footer</div> }));
vi.mock("./components/PlaylistPanel", () => ({ PlaylistPanel: () => <div>Playlists panel</div> }));
vi.mock("./components/QueuePanel", () => ({ QueuePanel: () => <div>Queue panel</div> }));
vi.mock("./components/SearchPanel", () => ({ SearchPanel: () => <div>Find page</div> }));
vi.mock("./components/StationPanel", () => ({ StationPanel: () => <div>Radio page</div> }));
vi.mock("./components/GuestPanel", () => ({ GuestPanel: () => <div>Players page</div> }));
vi.mock("./components/Onboarding", () => ({ Onboarding: () => <div>Onboarding</div> }));
vi.mock("./components/GamingSettings", () => ({ GamingSettings: () => <div>Settings page</div> }));

import { App } from "./App";

describe("mobile navigation", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    window.scrollTo = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => { root.render(<App />); });
  });

  afterEach(async () => {
    await act(async () => { root.unmount(); });
    container.remove();
  });

  it("keeps primary pages, the queue, and every secondary page reachable", async () => {
    const buttons = () => Array.from(container.querySelectorAll("button"));
    const click = async (label: string) => {
      const button = buttons().find(item => item.textContent?.trim() === label);
      expect(button, `${label} button`).toBeTruthy();
      await act(async () => { button!.click(); });
    };

    const mobileNav = container.querySelector('[aria-label="DjGoo mobile navigation"]');
    expect(mobileNav?.textContent).toContain("Live");
    expect(mobileNav?.textContent).toContain("Find");
    expect(mobileNav?.textContent).toContain("Queue");
    expect(mobileNav?.textContent).toContain("Lists");
    expect(mobileNav?.textContent).toContain("More");

    await click("Find");
    expect(container.textContent).toContain("Find page");

    await click("More");
    for (const page of ["History", "Radio", "Players", "Settings", "Logs", "Playlists"]) {
      expect(buttons().some(button => button.textContent?.trim() === page), `${page} menu entry`).toBe(true);
    }

    await click("History");
    expect(container.textContent).toContain("History page");

    const queueButton = mobileNav?.querySelectorAll("button")[2] as HTMLButtonElement;
    await act(async () => { queueButton.click(); });
    expect(container.textContent).toContain("Queue panel");
  });
});
