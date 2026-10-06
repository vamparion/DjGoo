import { describe, expect, it } from "vitest";
import { clearDraggedTrack, draggedTrackFallback, rememberDraggedTrack } from "./trackDrag";
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
