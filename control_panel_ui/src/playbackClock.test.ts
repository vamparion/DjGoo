import { describe, expect, it } from "vitest";
import { optimisticallyTogglePlayback, playbackPosition, reconcilePlaybackState } from "./playbackClock";
import type { ControlState } from "./types";

function state(playing: boolean): ControlState {
  return {
    playback: {
      title: "With You",
      track_id: "track-1",
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

  it("resumes from the frozen position without counting paused time", () => {
    const paused = optimisticallyTogglePlayback(state(true), 105_000);
    const resumed = optimisticallyTogglePlayback(paused, 120_000);

    expect(resumed.playback.playing).toBe(true);
    expect(resumed.playback.position_ms).toBe(15_000);
    expect(playbackPosition(resumed.playback, 123_000)).toBe(18_000);
  });

  it("does not let a polling snapshot pull the same playing track backward", () => {
    const current = state(true);
    const next = state(true);
    next.playback.position_ms = 13_000;
    next.playback.measured_at = 105;

    const reconciled = reconcilePlaybackState(current, next, 105_000);

    expect(playbackPosition(reconciled.playback, 105_000)).toBe(15_000);
    expect(playbackPosition(reconciled.playback, 106_000)).toBe(16_000);
  });

  it("does not let a resume snapshot jump the same track forward", () => {
    const paused = state(false);
    const resumed = state(true);
    resumed.playback.position_ms = 18_000;
    resumed.playback.measured_at = 105;

    const reconciled = reconcilePlaybackState(paused, resumed, 105_000);

    expect(playbackPosition(reconciled.playback, 105_000)).toBe(10_000);
    expect(playbackPosition(reconciled.playback, 106_000)).toBe(11_000);
  });

  it("accepts a new track even when its position is behind", () => {
    const next = state(true);
    next.playback.track_id = "track-2";
    next.playback.title = "Next track";
    next.playback.position_ms = 0;
    next.playback.measured_at = 105;

    const reconciled = reconcilePlaybackState(state(true), next, 105_000);
    expect(reconciled.playback.position_ms).toBe(0);
    expect(reconciled.playback.measured_at).toBe(105);
  });

  it("anchors host snapshots to browser receipt time instead of the host clock", () => {
    const next = state(true);
    next.playback.position_ms = 42_000;
    next.playback.measured_at = 1;

    const reconciled = reconcilePlaybackState(null, next, 200_000);

    expect(playbackPosition(reconciled.playback, 201_000)).toBe(43_000);
  });

  it("resets when a new instance of the same song starts", () => {
    const next = state(true);
    next.playback.track_id = "track-2";
    next.playback.position_ms = 2_000;
    next.playback.measured_at = 105;

    const reconciled = reconcilePlaybackState(state(true), next, 105_000);

    expect(playbackPosition(reconciled.playback, 105_000)).toBe(2_000);
  });

  it("never displays elapsed time beyond the track duration", () => {
    const playback = state(true).playback;
    playback.position_ms = 250_000;
    playback.duration_ms = 255_000;
    playback.measured_at = 100;

    expect(playbackPosition(playback, 120_000)).toBe(255_000);
  });
});
