import type { Track } from "./types";

let activeTrack: Track | null = null;

export function rememberDraggedTrack(track: Track) {
  activeTrack = track;
}

export function draggedTrackFallback() {
  return activeTrack;
}

export function clearDraggedTrack() {
  activeTrack = null;
}
