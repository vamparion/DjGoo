// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { clearDraggedTrack, draggedTrackFallback, rememberDraggedTrack, touchQueueIndex } from "./trackDrag";
import type { Track } from "./types";

describe("hosted drag fallback", () => {
  it("keeps the complete track while browser transfer data is unavailable", () => {
    const track = { id: "one", title: "Song", artist: "Artist", uri: "https://example.test/song" } as Track;

    rememberDraggedTrack(track);

    expect(draggedTrackFallback()).toEqual(track);
    clearDraggedTrack();
    expect(draggedTrackFallback()).toBeNull();
  });
});

describe("touchQueueIndex", () => {
  it("maps queue rows, the end target, and the Queue tab", () => {
    document.body.innerHTML = '<div data-touch-queue-index="2"><span id="row"></span></div><div data-touch-queue-index="end" id="end"></div><button data-touch-queue-target id="tab"></button>';
    expect(touchQueueIndex(document.querySelector("#row"), 5)).toBe(2);
    expect(touchQueueIndex(document.querySelector("#end"), 5)).toBe(5);
    expect(touchQueueIndex(document.querySelector("#tab"), 5)).toBe(5);
    expect(touchQueueIndex(document.body, 5)).toBeNull();
  });
});
