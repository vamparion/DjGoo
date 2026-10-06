import type { ControlState } from "./types";

type Playback = ControlState["playback"];

export function playbackPosition(playback: Playback, now = Date.now()) {
  const anchored = Number(playback.position_ms || 0);
  if (!playback.playing || !playback.measured_at) return anchored;
  return anchored + Math.max(0, now - playback.measured_at * 1000);
}

export function reconcilePlaybackState(current: ControlState | null, next: ControlState, now = Date.now()): ControlState {
  const received = {
    ...next,
    playback: {
      ...next.playback,
      measured_at: now / 1000,
    },
  };
  if (!current) return received;
  const sameTrack = current.playback.title === next.playback.title
    && current.playback.artist === next.playback.artist
    && current.playback.duration_ms === next.playback.duration_ms;
  if (!sameTrack) return received;
  const displayed = playbackPosition(current.playback, now);
  return {
    ...received,
    playback: {
      ...received.playback,
      position_ms: displayed,
    },
  };
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
