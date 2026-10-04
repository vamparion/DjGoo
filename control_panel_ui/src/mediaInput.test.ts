import { describe, expect, it } from "vitest";
import { normalizeMediaInput } from "./mediaInput";

describe("normalizeMediaInput", () => {
  it("extracts the destination from a Markdown playlist link", () => {
    expect(normalizeMediaInput(
      "[playlist](https://www.youtube.com/playlist?list=PLGQK9yb_7IySSAYo_tJYjIXEmLTvm4W1e)",
    )).toBe("https://www.youtube.com/playlist?list=PLGQK9yb_7IySSAYo_tJYjIXEmLTvm4W1e");
  });

  it("extracts links with a Markdown title", () => {
    expect(normalizeMediaInput(
      '[playlist](https://www.youtube.com/playlist?list=PL123 "YouTube playlist")',
    )).toBe("https://www.youtube.com/playlist?list=PL123");
  });

  it("leaves normal searches intact", () => {
    expect(normalizeMediaInput("  artist and song  ")).toBe("artist and song");
  });
});
