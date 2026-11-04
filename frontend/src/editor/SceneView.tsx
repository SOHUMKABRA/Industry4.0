import { Edges, Grid, Html, Instance, Instances, OrbitControls, OrthographicCamera, PerspectiveCamera, TransformControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { create } from "zustand";
import { FactoryStructure, SceneObject, Vec3 } from "../api/types";
import { telemetry } from "../live/telemetryStore";
import { SceneContext, SceneCtx, SceneItem, SelectionOutline } from "./objects";
import { GizmoMode, useEditor } from "./store";

// ---------- performance metrics (written from the render loop at 2 Hz) ----------
export const usePerf = create<{ fps: number; frameMs: number; calls: number; triangles: number; geometries: number; textures: number }>(() => ({
  fps: 0, frameMs: 0, calls: 0, triangles: 0, geometries: 0, textures: 0,
}));

function PerfProbe() {
  const gl = useThree((s) => s.gl);
  const acc = useRef({ frames: 0, start: performance.now(), work: 0 });
  useFrame(() => {
    const t0 = performance.now();
    const a = acc.current;
    a.frames++;
    const elapsed = t0 - a.start;
    if (elapsed >= 500) {
      const info = gl.info;
      usePerf.setState({
        fps: Math.round((a.frames * 1000) / elapsed), frameMs: +(a.work / Math.max(a.frames, 1)).toFixed(2),
        calls: info.render.calls, triangles: info.render.triangles, geometries: info.memory.geometries, textures: info.memory.textures,
      });
      a.frames = 0; a.start = t0; a.work = 0;
    }
    a.work += performance.now() - t0;
  });
  // Idle (on-demand) scenes render 0 fps; refresh the numbers anyway.
  useEffect(() => {
    const t = setInterval(() => { if (performance.now() - acc.current.start > 1000) usePerf.setState({ fps: 0 }); }, 1000);
    return () => clearInterval(t);
  }, []);
  return null;
}

// ---------- floor & areas from factory structure ----------
const AREA_COLORS: Record<string, string> = {
  production: "#38bdf8", storage: "#a78bfa", walkway: "#94a3b8", safety: "#f59e0b", utility: "#22c55e", office: "#f472b6",
};

const Floors = memo(function Floors({ structure, labels }: { structure?: FactoryStructure; labels: boolean }) {
  const floors = structure?.floors ?? [];
  return (
    <>
      {floors.map((f) => (
        <group key={f.id} position={[0, f.elevation_m, 0]}>
          <mesh position={[f.width_m / 2, -0.03, f.depth_m / 2]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow raycast={() => null}>
            <planeGeometry args={[f.width_m, f.depth_m]} />
            <meshStandardMaterial color="#4b5563" roughness={0.95} />
          </mesh>
          {f.areas.map((a) => (
            <group key={a.id} position={[a.bounds.x + a.bounds.width / 2, -0.02, a.bounds.z + a.bounds.depth / 2]}>
              <mesh rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
                <planeGeometry args={[a.bounds.width - 0.2, a.bounds.depth - 0.2]} />
                <meshBasicMaterial color={AREA_COLORS[a.kind] ?? "#94a3b8"} transparent opacity={0.07} depthWrite={false} />
                <Edges color={AREA_COLORS[a.kind] ?? "#94a3b8"} />
              </mesh>
              {labels && (
                <Html position={[-a.bounds.width / 2 + 0.6, 0.05, -a.bounds.depth / 2 + 0.6]} zIndexRange={[5, 0]} style={{ pointerEvents: "none" }}>
                  <div className="area-label">{a.name}</div>
                </Html>
              )}
            </group>
          ))}
        </group>
      ))}
    </>
  );
});

// ---------- instanced static primitives ----------
const INSTANCEABLE_KINDS = new Set(["wall", "door", "window", "pillar", "workstation", "storage", "box"]);
export const isInstanced = (o: SceneObject) =>
  INSTANCEABLE_KINDS.has(o.kind) && !o.model_id && o.opacity >= 1 && (o.shape === "box" || o.shape === "cylinder");

const tmpV = new THREE.Vector3();
const tmpE = new THREE.Euler();
function centerOf(o: SceneObject): Vec3 {
  tmpV.set(0, (o.size[1] * o.scale[1]) / 2, 0).applyEuler(tmpE.set(o.rotation[0], o.rotation[1], o.rotation[2]));
  return [o.position[0] + tmpV.x, o.position[1] + tmpV.y, o.position[2] + tmpV.z];
}

const InstancedLayer = memo(function InstancedLayer({ objs, shape, onPick }: {
  objs: SceneObject[]; shape: "box" | "cylinder"; onPick: (e: { shiftKey: boolean; delta: number }, id: string) => void;
}) {
  if (!objs.length) return null;
  // Remount when the count grows past capacity.
  const cap = Math.max(64, 2 ** Math.ceil(Math.log2(objs.length)));
  return (
    <Instances key={cap} limit={cap} range={objs.length}>
      {shape === "box" ? <boxGeometry args={[1, 1, 1]} /> : <cylinderGeometry args={[0.5, 0.5, 1, 20]} />}
      <meshStandardMaterial roughness={0.7} metalness={0.1} />
      {objs.map((o) => (
        <Instance key={o.id} position={centerOf(o)} rotation={o.rotation}
          scale={[o.size[0] * o.scale[0], o.size[1] * o.scale[1], o.size[2] * o.scale[2]]} color={o.color}
          onClick={(e) => { e.stopPropagation(); onPick({ shiftKey: e.shiftKey || e.ctrlKey || e.metaKey, delta: e.delta }, o.id); }} />
      ))}
    </Instances>
  );
});

/** For large selections: a single box around everything instead of one outline per object. */
function SelectionBounds({ objs }: { objs: SceneObject[] }) {
  const box = useMemo(() => {
    const b = new THREE.Box3();
    for (const o of objs) {
      const half = new THREE.Vector3((o.size[0] * o.scale[0]) / 2, 0, (o.size[2] * o.scale[2]) / 2);
      b.expandByPoint(new THREE.Vector3(o.position[0] - half.x, o.position[1], o.position[2] - half.z));
      b.expandByPoint(new THREE.Vector3(o.position[0] + half.x, o.position[1] + o.size[1] * o.scale[1], o.position[2] + half.z));
    }
    return b;
  }, [objs]);
  const size = box.getSize(new THREE.Vector3());
  const c = box.getCenter(new THREE.Vector3());
  return (
    <mesh position={c} raycast={() => null}>
      <boxGeometry args={[size.x + 0.2, size.y + 0.2, size.z + 0.2]} />
      <meshBasicMaterial color="#38bdf8" transparent opacity={0.05} depthWrite={false} />
      <Edges color="#38bdf8" />
    </mesh>
  );
}

// ---------- transform gizmo (editor only) ----------
function Gizmo({ mode, snap, grid, view, onActive }: { mode: GizmoMode; snap: boolean; grid: number; view: "3d" | "2d"; onActive: () => void }) {
  const selected = useEditor((s) => s.selected);
  const primary = useEditor((s) => (s.selected.length ? s.objects[s.selected[0]] : undefined));
  const anyLocked = useEditor((s) => s.selected.some((id) => s.objects[id]?.locked));
  const [proxy, setProxy] = useState<THREE.Group | null>(null);
  const dragging = useRef(false);
  const invalidate = useThree((s) => s.invalidate);

  useLayoutEffect(() => {
    if (!proxy || !primary || dragging.current) return;
    proxy.position.set(...primary.position);
    proxy.rotation.set(...primary.rotation);
    proxy.scale.set(...primary.scale);
    proxy.updateMatrixWorld();
    invalidate();
  }, [proxy, primary, invalidate]);

  const onChange = useCallback(() => {
    const s = useEditor.getState();
    if (!proxy || !s.transforming || !dragging.current) return;
    const base = s.transforming[s.selected[0]];
    if (!base) return;
    const dp = [proxy.position.x - base.position[0], proxy.position.y - base.position[1], proxy.position.z - base.position[2]];
    const dr = [proxy.rotation.x - base.rotation[0], proxy.rotation.y - base.rotation[1], proxy.rotation.z - base.rotation[2]];
    const ratio = [proxy.scale.x / base.scale[0], proxy.scale.y / base.scale[1], proxy.scale.z / base.scale[2]];
    const changes: Record<string, Partial<SceneObject>> = {};
    for (const [id, b] of Object.entries(s.transforming)) {
      changes[id] = {
        position: [b.position[0] + dp[0], Math.max(-50, b.position[1] + dp[1]), b.position[2] + dp[2]],
        rotation: [b.rotation[0] + dr[0], b.rotation[1] + dr[1], b.rotation[2] + dr[2]],
        scale: [Math.max(0.01, b.scale[0] * ratio[0]), Math.max(0.01, b.scale[1] * ratio[1]), Math.max(0.01, b.scale[2] * ratio[2])],
      };
    }
    s.transformLive(changes);
  }, [proxy]);

  const show = selected.length > 0 && primary && !anyLocked;
  return (
    <>
      <group ref={setProxy} />
      {show && proxy && (
        <TransformControls
          object={proxy} mode={mode} size={0.8}
          translationSnap={snap ? grid : null} rotationSnap={snap ? Math.PI / 12 : null} scaleSnap={snap ? 0.1 : null}
          showY={view === "3d" || mode === "scale" ? true : false}
          showX={mode === "rotate" && view === "2d" ? false : true}
          showZ={mode === "rotate" && view === "2d" ? false : true}
          onMouseDown={() => { dragging.current = true; useEditor.getState().beginTransform(); onActive(); }}
          onMouseUp={() => {
            dragging.current = false;
            const label = mode === "translate" ? "Move" : mode === "rotate" ? "Rotate" : "Scale";
            useEditor.getState().endTransform(label);
            onActive();
          }}
          onObjectChange={onChange}
        />
      )}
    </>
  );
}

// ---------- camera framing & drop raycasting ----------
export interface SceneViewHandle {
  /** Project a client (screen) point onto the floor plane. */
  floorPoint(clientX: number, clientY: number): [number, number] | null;
  frame(): void;
}

const Bridge = forwardRef<SceneViewHandle, { center: [number, number]; extent: number; view: "3d" | "2d" }>(function Bridge({ center, extent, view }, ref) {
  const { camera, gl, controls, invalidate } = useThree() as unknown as {
    camera: THREE.Camera & { zoom: number; updateProjectionMatrix(): void }; gl: THREE.WebGLRenderer;
    controls: { target: THREE.Vector3; update(): void } | null; invalidate(): void;
  };
  const frame = useCallback(() => {
    const [cx, cz] = center;
    if (view === "3d") camera.position.set(cx - extent * 0.35, extent * 0.55, cz + extent * 0.75);
    else {
      camera.position.set(cx, 200, cz);
      camera.zoom = Math.max(2, Math.min(gl.domElement.clientWidth, gl.domElement.clientHeight) / (extent * 1.05));
      camera.updateProjectionMatrix();
    }
    if (controls) { controls.target.set(cx, 0, cz); controls.update(); }
    invalidate();
  }, [camera, controls, center, extent, view, gl, invalidate]);
  // Re-frame only when the camera itself changes (view switch / first mount), never on ordinary re-renders,
  // so the user's camera position survives edits.
  const frameRef = useRef(frame);
  frameRef.current = frame;
  useEffect(() => { frameRef.current(); }, [camera, controls, view]);
  useImperativeHandle(ref, () => ({
    frame,
    floorPoint(x, y) {
      const rect = gl.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, camera);
      const hit = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3());
      return hit ? [hit.x, hit.z] : null;
    },
  }), [frame, gl, camera]);
  return null;
});

/** Redraw on telemetry updates and once a second so staleness changes show. */
function LiveInvalidator({ live }: { live: boolean }) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    if (!live) return;
    const off = telemetry.subscribeAll(() => invalidate());
    const t = setInterval(() => invalidate(), 1000);
    return () => { off(); clearInterval(t); };
  }, [live, invalidate]);
  return null;
}

// ---------- main view ----------
export interface SceneViewProps {
  objects: Record<string, SceneObject>;
  order: string[];
  selected: string[];
  structure?: FactoryStructure;
  ctx: SceneCtx;
  editable: boolean;
  mode?: GizmoMode;
  snap?: boolean;
  grid?: number;
  perf?: boolean;
  onSelect: (ids: string[], additive: boolean) => void;
  onDropItem?: (data: string, at: [number, number]) => void;
}

export const SceneView = forwardRef<SceneViewHandle, SceneViewProps>(function SceneView(p, ref) {
  const { objects, order, selected, structure, ctx, editable } = p;
  const bridge = useRef<SceneViewHandle>(null);
  useImperativeHandle(ref, () => ({
    floorPoint: (x, y) => bridge.current?.floorPoint(x, y) ?? null,
    frame: () => bridge.current?.frame(),
  }));
  const down = useRef<[number, number]>([0, 0]);
  const gizmoAt = useRef(0);

  const floor = structure?.floors[0];
  const W = floor?.width_m ?? 50, D = floor?.depth_m ?? 30;
  const center = useMemo<[number, number]>(() => [W / 2, D / 2], [W, D]);
  const extent = Math.max(W, D);

  const onPick = useCallback((e: { shiftKey: boolean; delta: number }, id: string) => {
    if (e.delta > 4) return; // it was an orbit drag, not a click
    p.onSelect([id], e.shiftKey);
  }, [p.onSelect]); // eslint-disable-line react-hooks/exhaustive-deps

  const { instBoxes, instCyl, items } = useMemo(() => {
    const instBoxes: SceneObject[] = [], instCyl: SceneObject[] = [], items: SceneObject[] = [];
    for (const id of order) {
      const o = objects[id];
      if (!o || o.hidden) continue;
      if (isInstanced(o)) (o.shape === "box" ? instBoxes : instCyl).push(o);
      else items.push(o);
    }
    return { instBoxes, instCyl, items };
  }, [objects, order]);

  return (
    <div className="scene-wrap"
      onPointerDown={(e) => { down.current = [e.clientX, e.clientY]; }}
      onDragOver={(e) => { if (p.onDropItem) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } }}
      onDrop={(e) => {
        if (!p.onDropItem) return;
        e.preventDefault();
        const data = e.dataTransfer.getData("application/x-twin");
        const at = bridge.current?.floorPoint(e.clientX, e.clientY);
        if (data && at) p.onDropItem(data, at);
      }}>
      <Canvas frameloop="demand" dpr={[1, 2]} gl={{ antialias: true, powerPreference: "high-performance" }}
        onPointerMissed={(e) => {
          if (Date.now() - gizmoAt.current < 300) return;
          const [x, y] = down.current;
          if (Math.hypot(e.clientX - x, e.clientY - y) > 4) return;
          if (!e.shiftKey) p.onSelect([], false);
        }}>
        <color attach="background" args={["#0e1218"]} />
        {ctx.view === "3d" ? (
          <PerspectiveCamera makeDefault fov={45} near={0.1} far={2000} position={[0, 40, 60]} />
        ) : (
          <OrthographicCamera makeDefault near={0.1} far={1000} up={[0, 0, -1]} position={[center[0], 200, center[1]]} zoom={10} />
        )}
        <OrbitControls key={ctx.view} makeDefault target={[center[0], 0, center[1]]} enableRotate={ctx.view === "3d"} screenSpacePanning={ctx.view === "2d"}
          maxPolarAngle={Math.PI / 2 - 0.02} enableDamping={false} />
        <Bridge ref={bridge} center={center} extent={extent} view={ctx.view} />
        <hemisphereLight args={["#dbeafe", "#1f2937", 0.9]} />
        <directionalLight position={[W * 0.3, 60, D * 0.2]} intensity={1.4} />
        <ambientLight intensity={0.25} />
        <Floors structure={structure} labels={ctx.labels && ctx.view === "2d"} />
        <Grid position={[0, -0.015, 0]} args={[400, 400]} cellSize={editable ? (p.grid ?? 1) : 1} sectionSize={5}
          cellColor="#2a323d" sectionColor="#3a4554" fadeDistance={extent * 3} infiniteGrid followCamera={false} />
        <SceneContext.Provider value={ctx}>
          <InstancedLayer objs={instBoxes} shape="box" onPick={onPick} />
          <InstancedLayer objs={instCyl} shape="cylinder" onPick={onPick} />
          {items.map((o) => <SceneItem key={o.id} o={o} onPick={onPick} />)}
        </SceneContext.Provider>
        {selected.length <= 64
          ? selected.map((id) => objects[id] && <SelectionOutline key={id} o={objects[id]} color={objects[id].locked ? "#f59e0b" : "#38bdf8"} />)
          : <SelectionBounds objs={selected.map((id) => objects[id]).filter(Boolean)} />}
        {editable && <Gizmo mode={p.mode ?? "translate"} snap={!!p.snap} grid={p.grid ?? 0.5} view={ctx.view} onActive={() => { gizmoAt.current = Date.now(); }} />}
        <LiveInvalidator live={ctx.live} />
        {p.perf && <PerfProbe />}
      </Canvas>
    </div>
  );
});

export function PerfHud({ objects, latency }: { objects: number; latency: number | null }) {
  const perf = usePerf();
  return (
    <div className="perf-hud" aria-label="Performance">
      <div><span>FPS</span>{perf.fps || "idle"}</div>
      <div><span>JS/frame</span>{perf.frameMs} ms</div>
      <div><span>Draw calls</span>{perf.calls}</div>
      <div><span>Triangles</span>{perf.triangles.toLocaleString()}</div>
      <div><span>Objects</span>{objects.toLocaleString()}</div>
      <div><span>Geometries</span>{perf.geometries}</div>
      <div><span>WS latency</span>{latency !== null ? `${latency} ms` : "—"}</div>
    </div>
  );
}
