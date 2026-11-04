import { describe, expect, it } from "vitest";
import { statusLabel, statusTone, TERMINAL } from "./ControlPanel";

describe("command status presentation", () => {
  it("never shows an unverified completion as plain success", () => {
    expect(statusLabel({ status: "COMPLETED", verified: true })).toBe("Completed · verified");
    expect(statusTone({ status: "COMPLETED", verified: true })).toBe("ok");
    expect(statusLabel({ status: "COMPLETED", verified: false })).toBe("Completed · not verified");
    expect(statusTone({ status: "COMPLETED", verified: false })).toBe("warn");
  });
  it("flags timeouts as unverified equipment state", () => {
    expect(statusLabel({ status: "TIMED_OUT", verified: false })).toMatch(/unverified/);
    expect(statusTone({ status: "FAILED", verified: false })).toBe("bad");
    expect(statusLabel({ status: "PENDING_APPROVAL", verified: false })).toBe("Awaiting approval");
  });
  it("knows which states are final", () => {
    expect([...TERMINAL].sort()).toEqual(["CANCELLED", "COMPLETED", "FAILED", "REJECTED", "TIMED_OUT"]);
  });
});
