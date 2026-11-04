import { describe, expect, it } from "vitest";
import { framesAt, lastAtOrBefore } from "./PlaybackBar";

describe("playback lookup", () => {
  const ts = [1000, 2000, 3000, 4000];
  it("finds the last sample at or before t", () => {
    expect(lastAtOrBefore(ts, 500)).toBe(-1);
    expect(lastAtOrBefore(ts, 1000)).toBe(0);
    expect(lastAtOrBefore(ts, 2999)).toBe(1);
    expect(lastAtOrBefore(ts, 9999)).toBe(3);
  });
  it("emits replay frames and leaves gaps empty instead of inventing values", () => {
    const series = [{ a: "a1", m: "state", t: ts, v: ["running", "running", "stopped", "stopped"] }, { a: "a2", m: "temp", t: [1000], v: [20] }];
    const f = framesAt(series, 3500, 5000);
    expect(f).toContainEqual(["a1", "state", "stopped", 3000, "good", "playback"]);
    expect(f).toContainEqual(["a2", "temp", 20, 1000, "good", "playback"]);
    expect(framesAt(series, 9000, 1000).map((x) => x[0])).toEqual([]); // older than the max age → nothing shown
  });
});
