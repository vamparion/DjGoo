// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TouchTrackHandle } from "./components/TouchTrackHandle";
import { TOUCH_TRACK_DROP, TOUCH_TRACK_MOVE, type TouchTrackDropDetail } from "./trackDrag";

function pointerEvent(type: string, x: number, y: number) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    pointerType: { value: "touch" },
    pointerId: { value: 7 },
    clientX: { value: x },
    clientY: { value: y },
  });
  return event;
}

describe("TouchTrackHandle", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    HTMLElement.prototype.setPointerCapture = vi.fn();
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it("turns a touch hold over the Queue tab into an append drop", async () => {
    const queueTarget = document.createElement("button");
    queueTarget.dataset.touchQueueTarget = "";
    document.body.appendChild(queueTarget);
    document.elementFromPoint = vi.fn(() => queueTarget);
    const moves = vi.fn();
    let dropped: TouchTrackDropDetail | null = null;
    window.addEventListener(TOUCH_TRACK_MOVE, moves);
    window.addEventListener(TOUCH_TRACK_DROP, (event) => { dropped = (event as CustomEvent<TouchTrackDropDetail>).detail; }, { once: true });

    await act(async () => root.render(<TouchTrackHandle track={{ id: "song", title: "Song", artist: "Artist", uri: "https://example.test/song" }} queueLength={3} />));
    const handle = container.querySelector("button")!;
    await act(async () => {
      handle.dispatchEvent(pointerEvent("pointerdown", 10, 10));
      vi.advanceTimersByTime(220);
    });
    await act(async () => { handle.dispatchEvent(pointerEvent("pointerup", 25, 30)); });

    expect(moves).toHaveBeenCalledOnce();
    expect(dropped).toMatchObject({ index: 3, track: { id: "song", title: "Song" } });
    queueTarget.remove();
  });
});
