import { GripVertical } from "lucide-react";
import { useRef, useState, type PointerEvent } from "react";
import { TOUCH_TRACK_DROP, TOUCH_TRACK_MOVE, touchQueueIndex, type TouchTrackDropDetail, type TouchTrackMoveDetail } from "../trackDrag";
import type { Track } from "../types";

type Props = { track: Track; queueLength: number };

export function TouchTrackHandle({ track, queueLength }: Props) {
  const timer = useRef(0);
  const active = useRef(false);
  const position = useRef({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);

  function finish(event: PointerEvent<HTMLButtonElement>, drop: boolean) {
    window.clearTimeout(timer.current);
    if (active.current && drop) {
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const index = touchQueueIndex(target, queueLength);
      if (index !== null) {
        window.dispatchEvent(new CustomEvent<TouchTrackDropDetail>(TOUCH_TRACK_DROP, { detail: { index, track } }));
      }
    }
    active.current = false;
    setDragging(false);
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* pointer capture may already be gone */ }
  }

  return (
    <button
      className={`mobile-track-grip ${dragging ? "dragging" : ""}`}
      type="button"
      title="Hold and drag to Queue"
      aria-label={`Drag ${track.title} to queue`}
      onPointerDown={(event) => {
        if (event.pointerType === "mouse") return;
        position.current = { x: event.clientX, y: event.clientY };
        event.currentTarget.setPointerCapture(event.pointerId);
        timer.current = window.setTimeout(() => {
          active.current = true;
          setDragging(true);
          window.dispatchEvent(new CustomEvent<TouchTrackMoveDetail>(TOUCH_TRACK_MOVE, { detail: { ...position.current, track } }));
        }, 220);
      }}
      onPointerMove={(event) => {
        position.current = { x: event.clientX, y: event.clientY };
        if (!active.current) return;
        event.preventDefault();
        window.dispatchEvent(new CustomEvent<TouchTrackMoveDetail>(TOUCH_TRACK_MOVE, { detail: { x: event.clientX, y: event.clientY, track } }));
      }}
      onPointerUp={(event) => finish(event, true)}
      onPointerCancel={(event) => finish(event, false)}
    >
      <GripVertical size={18} />
    </button>
  );
}
