import { create } from "zustand";
import { SceneObject, Vec3 } from "../api/types";

/** A reversible edit: snapshots of touched objects before and after (null = absent). */
interface Cmd {
  label: string;
  before: Record<string, SceneObject | null>;
  after: Record<string, SceneObject | null>;
  // Set when objects were added/removed, so undo restores their original position in the list.
  orderBefore?: string[];
  orderAfter?: string[];
}

export type GizmoMode = "translate" | "rotate" | "scale";
export type ViewMode = "3d" | "2d";
const MAX_HISTORY = 200;

export const uuid = () =>
  (crypto as Crypto & { randomUUID?: () => string }).randomUUID?.() ??
  "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });

export interface EditorState {
  sceneId: string | null;
  factoryId: string | null;
  version: number;
  objects: Record<string, SceneObject>;
  order: string[];
  selected: string[];
  past: Cmd[];
  future: Cmd[];
  dirty: boolean;
  mode: GizmoMode;
  view: ViewMode;
  snap: boolean;
  grid: number;
  labels: boolean;
  live: boolean;
  transforming: Record<string, SceneObject> | null;

  load(factoryId: string, sceneId: string, version: number, objects: SceneObject[]): void;
  markSaved(version: number, objects: SceneObject[]): void;
  set(p: Partial<EditorState>): void;
  commit(label: string, changes: Record<string, SceneObject | null>): void;
  undo(): void;
  redo(): void;
  select(ids: string[], additive?: boolean): void;
  add(objs: SceneObject[], label?: string): void;
  update(ids: string[], patch: (o: SceneObject) => Partial<SceneObject>, label: string): void;
  remove(ids: string[]): void;
  duplicate(ids: string[]): void;
  group(ids: string[]): void;
  ungroup(ids: string[]): void;
  align(ids: string[], axis: 0 | 2, how: "min" | "center" | "max"): void;
  distribute(ids: string[], axis: 0 | 2): void;
  beginTransform(): void;
  transformLive(changes: Record<string, Partial<SceneObject>>): void;
  endTransform(label: string): void;
}

const clone = (o: SceneObject): SceneObject => ({ ...o, position: [...o.position] as Vec3, rotation: [...o.rotation] as Vec3, scale: [...o.scale] as Vec3, size: [...o.size] as Vec3, props: { ...o.props } });

function applyChanges(s: EditorState, changes: Record<string, SceneObject | null>, orderOverride?: string[]) {
  const objects = { ...s.objects };
  let order = s.order;
  for (const [id, o] of Object.entries(changes)) {
    if (o === null) {
      delete objects[id];
      order = order.filter((x) => x !== id);
    } else {
      if (!objects[id]) order = [...order, id];
      objects[id] = o;
    }
  }
  if (orderOverride) order = orderOverride.filter((id) => objects[id]);
  return { objects, order, selected: s.selected.filter((id) => objects[id]) };
}

/** Selecting any member of a group selects the whole group. */
function expandGroups(s: EditorState, ids: string[]): string[] {
  const groups = new Set(ids.map((id) => s.objects[id]?.group_id).filter(Boolean));
  if (!groups.size) return ids;
  return [...new Set([...ids, ...s.order.filter((id) => groups.has(s.objects[id].group_id))])];
}

export const useEditor = create<EditorState>((set, get) => ({
  sceneId: null, factoryId: null, version: 0, objects: {}, order: [], selected: [], past: [], future: [],
  dirty: false, mode: "translate", view: "3d", snap: true, grid: 0.5, labels: true, live: true, transforming: null,

  load(factoryId, sceneId, version, objects) {
    const sorted = [...objects].sort((a, b) => a.sort - b.sort);
    set({
      factoryId, sceneId, version, objects: Object.fromEntries(sorted.map((o) => [o.id, o])), order: sorted.map((o) => o.id),
      selected: [], past: [], future: [], dirty: false, transforming: null,
    });
  },
  markSaved(version, objects) {
    get().load(get().factoryId!, get().sceneId!, version, objects);
  },
  set: (p) => set(p),

  commit(label, changes) {
    const s = get();
    const before: Cmd["before"] = {};
    for (const id of Object.keys(changes)) before[id] = s.objects[id] ? s.objects[id] : null;
    const next = applyChanges(s, changes);
    const structural = Object.entries(changes).some(([id, o]) => (o === null) !== (before[id] === null));
    const cmd: Cmd = { label, before, after: changes, ...(structural ? { orderBefore: s.order, orderAfter: next.order } : {}) };
    set({ ...next, past: [...s.past, cmd].slice(-MAX_HISTORY), future: [], dirty: true });
  },
  undo() {
    const s = get();
    const cmd = s.past[s.past.length - 1];
    if (!cmd) return;
    set({ ...applyChanges(s, cmd.before, cmd.orderBefore), past: s.past.slice(0, -1), future: [cmd, ...s.future], dirty: true });
  },
  redo() {
    const s = get();
    const cmd = s.future[0];
    if (!cmd) return;
    set({ ...applyChanges(s, cmd.after, cmd.orderAfter), past: [...s.past, cmd], future: s.future.slice(1), dirty: true });
  },
  select(ids, additive) {
    const s = get();
    const expanded = expandGroups(s, ids);
    if (!additive) return set({ selected: expanded });
    const cur = new Set(s.selected);
    const allIn = expanded.every((id) => cur.has(id));
    expanded.forEach((id) => (allIn ? cur.delete(id) : cur.add(id)));
    set({ selected: [...cur] });
  },
  add(objs, label = "Add") {
    const s = get();
    const base = s.order.length;
    get().commit(label, Object.fromEntries(objs.map((o, i) => [o.id, { ...o, sort: base + i }])));
    set({ selected: objs.map((o) => o.id) });
  },
  update(ids, patch, label) {
    const s = get();
    const changes: Record<string, SceneObject> = {};
    for (const id of ids) if (s.objects[id]) changes[id] = { ...clone(s.objects[id]), ...patch(s.objects[id]) };
    if (Object.keys(changes).length) get().commit(label, changes);
  },
  remove(ids) {
    const s = get();
    const removable = ids.filter((id) => s.objects[id] && !s.objects[id].locked);
    if (!removable.length) return;
    get().commit(`Delete ${removable.length}`, Object.fromEntries(removable.map((id) => [id, null])));
    set({ selected: get().selected.filter((id) => !removable.includes(id)) });
  },
  duplicate(ids) {
    const s = get();
    const groupMap = new Map<string, string>();
    // Asset objects represent one physical asset and can't be cloned visually.
    const copies = ids.map((id) => s.objects[id]).filter((o) => o && o.kind !== "asset").map((o) => {
      const g = o.group_id ? (groupMap.get(o.group_id) ?? groupMap.set(o.group_id, uuid()).get(o.group_id)!) : null;
      const c = clone(o);
      return { ...c, id: uuid(), name: `${o.name} copy`, locked: false, group_id: g, position: [o.position[0] + 1, o.position[1], o.position[2] + 1] as Vec3 };
    });
    if (copies.length) get().add(copies, `Duplicate ${copies.length}`);
  },
  group(ids) {
    if (ids.length < 2) return;
    const g = uuid();
    get().update(ids, () => ({ group_id: g }), "Group");
  },
  ungroup(ids) {
    get().update(ids, () => ({ group_id: null }), "Ungroup");
  },
  align(ids, axis, how) {
    const s = get();
    const objs = ids.map((id) => s.objects[id]).filter((o) => o && !o.locked);
    if (objs.length < 2) return;
    const half = (o: SceneObject) => (o.size[axis] * o.scale[axis]) / 2;
    const target =
      how === "min" ? Math.min(...objs.map((o) => o.position[axis] - half(o)))
      : how === "max" ? Math.max(...objs.map((o) => o.position[axis] + half(o)))
      : objs.reduce((a, o) => a + o.position[axis], 0) / objs.length;
    get().update(objs.map((o) => o.id), (o) => {
      const p = [...o.position] as Vec3;
      p[axis] = how === "min" ? target + half(o) : how === "max" ? target - half(o) : target;
      return { position: p };
    }, `Align ${how}`);
  },
  distribute(ids, axis) {
    const s = get();
    const objs = ids.map((id) => s.objects[id]).filter((o) => o && !o.locked).sort((a, b) => a.position[axis] - b.position[axis]);
    if (objs.length < 3) return;
    const first = objs[0].position[axis], last = objs[objs.length - 1].position[axis];
    const step = (last - first) / (objs.length - 1);
    const idx = new Map(objs.map((o, i) => [o.id, i]));
    get().update(objs.map((o) => o.id), (o) => {
      const p = [...o.position] as Vec3;
      p[axis] = first + step * idx.get(o.id)!;
      return { position: p };
    }, "Distribute");
  },
  beginTransform() {
    const s = get();
    set({ transforming: Object.fromEntries(s.selected.filter((id) => s.objects[id]).map((id) => [id, s.objects[id]])) });
  },
  transformLive(changes) {
    const s = get();
    const objects = { ...s.objects };
    for (const [id, p] of Object.entries(changes)) if (objects[id]) objects[id] = { ...objects[id], ...p };
    set({ objects });
  },
  endTransform(label) {
    const s = get();
    if (!s.transforming) return;
    const before = s.transforming;
    const after: Record<string, SceneObject> = {};
    let changed = false;
    for (const id of Object.keys(before)) {
      after[id] = s.objects[id];
      if (JSON.stringify(before[id]) !== JSON.stringify(after[id])) changed = true;
    }
    set({ transforming: null });
    if (!changed) return;
    set({ past: [...s.past, { label, before, after }].slice(-MAX_HISTORY), future: [], dirty: true });
  },
}));

export const selectionOf = (s: EditorState) => s.selected.map((id) => s.objects[id]).filter(Boolean);
