import { beforeEach, describe, expect, it } from "vitest";
import { SceneObject } from "../api/types";
import { useEditor } from "./store";

const obj = (id: string, p: Partial<SceneObject> = {}): SceneObject => ({
  id, kind: "box", asset_id: null, name: id, shape: "box", position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1],
  size: [1, 1, 1], color: "#000000", opacity: 1, model_id: null, floor_id: null, group_id: null, locked: false, hidden: false, sort: 0, props: {}, ...p,
});
const S = () => useEditor.getState();

beforeEach(() => {
  S().load("f", "s", 3, [obj("a", { position: [0, 0, 0] }), obj("b", { position: [10, 0, 0], size: [2, 1, 1] }), obj("c", { position: [4, 0, 5] })]);
});

describe("editor store", () => {
  it("undoes and redoes updates, adds and removals", () => {
    S().update(["a"], () => ({ position: [5, 0, 5] }), "Move");
    S().add([obj("d")]);
    S().remove(["b"]);
    expect(S().order).toEqual(["a", "c", "d"]);
    expect(S().dirty).toBe(true);
    S().undo(); S().undo(); S().undo();
    expect(S().order).toEqual(["a", "b", "c"]);
    expect(S().objects.a.position).toEqual([0, 0, 0]);
    S().redo();
    expect(S().objects.a.position).toEqual([5, 0, 5]);
    S().update(["c"], () => ({ name: "x" }), "Rename");
    expect(S().future).toHaveLength(0); // new edit clears redo
  });

  it("records a drag as a single history step", () => {
    S().select(["a", "c"]);
    S().beginTransform();
    for (let i = 1; i <= 10; i++) S().transformLive({ a: { position: [i, 0, 0] }, c: { position: [4 + i, 0, 5] } });
    S().endTransform("Move");
    expect(S().past).toHaveLength(1);
    S().undo();
    expect(S().objects.a.position).toEqual([0, 0, 0]);
    expect(S().objects.c.position).toEqual([4, 0, 5]);
  });

  it("selects whole groups and ungroups", () => {
    S().group(["a", "b"]);
    S().select(["a"]);
    expect(new Set(S().selected)).toEqual(new Set(["a", "b"]));
    S().ungroup(["a", "b"]);
    S().select(["a"]);
    expect(S().selected).toEqual(["a"]);
  });

  it("aligns using object extents", () => {
    S().align(["a", "b"], 0, "min");
    // a spans -0.5..0.5, b (width 2) moves so its left edge is at -0.5
    expect(S().objects.b.position[0]).toBe(0.5);
    S().distribute(["a", "b", "c"], 2);
  });

  it("protects locked objects and never duplicates assets", () => {
    S().update(["a"], () => ({ locked: true }), "Lock");
    S().remove(["a", "c"]);
    expect(S().objects.a).toBeDefined();
    expect(S().objects.c).toBeUndefined();
    S().add([obj("m", { kind: "asset", asset_id: "asset-1" })]);
    const before = S().order.length;
    S().duplicate(["m", "b"]);
    expect(S().order.length).toBe(before + 1);
    expect(Object.values(S().objects).filter((o) => o.asset_id === "asset-1")).toHaveLength(1);
  });
});
