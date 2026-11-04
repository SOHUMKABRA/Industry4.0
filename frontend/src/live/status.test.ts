import { beforeEach, describe, expect, it } from "vitest";
import { AssetType, TelemetryDef } from "../api/types";
import { assetLive, freshness, severity } from "./status";
import { telemetry } from "./telemetryStore";

const def = (p: Partial<TelemetryDef>): TelemetryDef => ({
  key: "temp", label: "T", data_type: "number", unit: "°C", min: null, max: null, warn_low: null, warn_high: 70,
  alarm_low: null, alarm_high: 80, options: [], expected_interval_s: 5, ...p,
});
const type = { telemetry: [def({}), def({ key: "state", data_type: "enum", warn_high: null, alarm_high: null })] } as unknown as AssetType;
const now = 1_000_000;

beforeEach(() => telemetry.clear());

describe("telemetry store", () => {
  it("never lets an older sample overwrite a newer one", () => {
    telemetry.apply([["a", "temp", 50, now, "good", "simulated"]]);
    telemetry.apply([["a", "temp", 99, now - 1000, "good", "simulated"]]);
    expect(telemetry.get("a", "temp")?.v).toBe(50);
  });
});

describe("status rules", () => {
  it("classifies limits", () => {
    expect(severity(def({}), 65)).toBe("ok");
    expect(severity(def({}), 72)).toBe("warn");
    expect(severity(def({}), 80)).toBe("alarm");
    expect(severity(def({ warn_low: 4, alarm_low: 3 }), 2.5)).toBe("alarm");
  });

  it("marks values stale after 3x the expected interval", () => {
    expect(freshness({ v: 1, ts: now - 14_000, q: "good", src: "live" }, def({}), now)).toBe("fresh");
    expect(freshness({ v: 1, ts: now - 16_000, q: "good", src: "live" }, def({}), now)).toBe("stale");
    expect(freshness(undefined, def({}), now)).toBe("none");
  });

  it("never reports 'running' from stale data", () => {
    telemetry.apply([["a", "state", "running", now - 60_000, "good", "simulated"], ["a", "temp", 50, now - 60_000, "good", "simulated"]]);
    expect(assetLive({ id: "a" }, type, now).condition).toBe("stale");
    telemetry.apply([["a", "state", "running", now, "good", "simulated"], ["a", "temp", 50, now, "good", "simulated"]]);
    expect(assetLive({ id: "a" }, type, now).condition).toBe("running");
  });

  it("prioritises fault states, then alarms", () => {
    telemetry.apply([["a", "state", "running", now, "good", "simulated"], ["a", "temp", 85, now, "good", "simulated"]]);
    expect(assetLive({ id: "a" }, type, now).condition).toBe("alarm");
    telemetry.apply([["a", "state", "fault", now + 1, "good", "simulated"]]);
    expect(assetLive({ id: "a" }, type, now + 1).condition).toBe("fault");
    expect(assetLive({ id: "nothing" }, type, now).condition).toBe("nodata");
  });
});
