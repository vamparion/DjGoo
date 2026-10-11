import type { Track } from "./types";

export const TOUCH_TRACK_MOVE = "djgoo-touch-track-move";
export const TOUCH_TRACK_DROP = "djgoo-touch-track-drop";

export type TouchTrackMoveDetail = { x: number; y: number; track: Track };
export type TouchTrackDropDetail = { index: number; track: Track };

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

export function touchQueueIndex(target: Element | null, queueLength: number) {
  const indexed = target?.closest<HTMLElement>("[data-touch-queue-index]");
  if (indexed) {
    const value = indexed.dataset.touchQueueIndex;
    if (value === "end") return queueLength;
    const parsed = Number(value);
    if (Number.isInteger(parsed)) return Math.max(0, Math.min(queueLength, parsed));
  }
  return target?.closest("[data-touch-queue-target]") ? queueLength : null;
}
