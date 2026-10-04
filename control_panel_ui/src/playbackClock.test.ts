import { describe, expect, it } from "vitest";
import { optimisticallyTogglePlayback, playbackPosition } from "./playbackClock";
import type { ControlState } from "./types";

function state(playing: boolean): ControlState {
  return {
    playback: {
      title: "With You",
      artist: "LINKIN PARK",
      station: "",
      source: "PLAYBACK",
      remaining: "",
      queue_count: 0,
      requester: "",
      state: playing ? "playing" : "paused",
      position_ms: 10_000,
      duration_ms: 180_000,
      playing,
      measured_at: 100,
      volume: 90,
    },
  } as ControlState;
}

describe("playback clock", () => {
  it("advances only while playback is playing", () => {
    expect(playbackPosition(state(true).playback, 105_000)).toBe(15_000);
    expect(playbackPosition(state(false).playback, 105_000)).toBe(10_000);
  });

  it("freezes at the extrapolated position immediately when paused", () => {
    const paused = optimisticallyTogglePlayback(state(true), 105_000);
    expect(paused.playback.playing).toBe(false);
    expect(paused.playback.state).toBe("paused");
    expect(paused.playback.position_ms).toBe(15_000);
    expect(playbackPosition(paused.playback, 120_000)).toBe(15_000);
  });
});
