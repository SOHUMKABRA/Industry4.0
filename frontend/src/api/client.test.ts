import { describe, expect, it } from "vitest";
import { fromMetres, toMetres } from "../lib/format";
import { ApiError, qs } from "./client";

describe("ApiError", () => {
  it("describes FastAPI validation errors and extracts field errors", () => {
    const e = new ApiError(422, [{ loc: ["body", "code"], msg: "too short" }]);
    expect(e.message).toBe("code: too short");
    expect(e.fieldErrors).toEqual({ code: "too short" });
  });
  it("handles structured property errors", () => {
    const e = new ApiError(422, { message: "Invalid properties", fields: { power: "must be ≥ 0" } });
    expect(e.fieldErrors).toEqual({ power: "must be ≥ 0" });
    expect(e.message).toContain("Invalid properties");
  });
  it("passes plain strings through", () => {
    expect(new ApiError(409, "Asset ID 'X' is already in use").message).toBe("Asset ID 'X' is already in use");
  });
});

describe("helpers", () => {
  it("builds query strings without empty values", () => {
    expect(qs({ a: "1", b: "", c: undefined, d: 0 })).toBe("?a=1&d=0");
    expect(qs({})).toBe("");
  });
  it("round-trips length units via metres", () => {
    expect(fromMetres(1.5, "mm")).toBe(1500);
    expect(toMetres(1500, "mm")).toBe(1.5);
    expect(toMetres(fromMetres(10, "ft"), "ft")).toBeCloseTo(10, 3);
  });
});
