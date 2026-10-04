import type { ControlState } from "./types";

type Playback = ControlState["playback"];

export function playbackPosition(playback: Playback, now = Date.now()) {
  const anchored = Number(playback.position_ms || 0);
  if (!playback.playing || !playback.measured_at) return anchored;
  return anchored + Math.max(0, now - playback.measured_at * 1000);
}

export function optimisticallyTogglePlayback(state: ControlState, now = Date.now()): ControlState {
  const playing = !state.playback.playing;
  return {
    ...state,
    playback: {
      ...state.playback,
      position_ms: playbackPosition(state.playback, now),
      measured_at: now / 1000,
      playing,
      state: playing ? "playing" : "paused",
    },
  };
}
