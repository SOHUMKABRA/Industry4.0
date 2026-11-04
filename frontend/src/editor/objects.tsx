import { Edges, Html } from "@react-three/drei";
import { useFrame, useLoader } from "@react-three/fiber";
import { createContext, memo, Suspense, useContext, useMemo, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { tokenStore } from "../api/client";
import { AssetType, ModelFile, SceneObject } from "../api/types";
import { assetLive, CONDITION_STYLE } from "../live/status";
import { clock } from "../live/clock";
import { telemetry } from "../live/telemetryStore";

export interface SceneCtx {
  typeOfAsset: (assetId: string) => AssetType | undefined;
  assetLabel: (assetId: string) => string;
  models: Record<string, ModelFile>;
  live: boolean;         // show live state (beacons, animation)
  animate: boolean;
  labels: boolean;
  view: "3d" | "2d";
}
export const SceneContext = createContext<SceneCtx>({
  typeOfAsset: () => undefined, assetLabel: () => "", models: {}, live: false, animate: true, labels: true, view: "3d",
});

const RUNNING = new Set(["running", "run", "loaded"]);
const num = (v: unknown) => (typeof v === "number" ? v : 0);

/** Throttled per-asset live read inside the render loop (no React state). */
function useAssetPulse(assetId: string | null, cb: (now: number) => void, hz = 4) {
  const last = useRef(0);
  useFrame(() => {
    if (!assetId) return;
    const wall = Date.now();
    if (wall - last.current < 1000 / hz) return;
    last.current = wall;
    cb(clock.now());
  });
}

/** Fresh "running" state only: animation never runs on stale or missing data. */
function isRunning(assetId: string, type: AssetType | undefined): boolean {
  const def = type?.telemetry.find((d) => d.key === "state");
  const tv = telemetry.get(assetId, "state");
  if (!tv) return false;
  const limit = Math.max(3 * (def?.expected_interval_s ?? 5), 6) * 1000;
  return clock.now() - tv.ts < limit && RUNNING.has(String(tv.v));
}

function Mat({ color, opacity = 1, emissive }: { color: string; opacity?: number; emissive?: string }) {
  return <meshStandardMaterial color={color} transparent={opacity < 1} opacity={opacity} depthWrite={opacity >= 1}
    roughness={0.65} metalness={0.15} emissive={emissive ?? "#000000"} />;
}

// ---------- primitive shapes (local coords: y=0 is the base) ----------
function BoxShape({ o }: { o: SceneObject }) {
  const [w, h, d] = o.size;
  return <mesh position={[0, h / 2, 0]}><boxGeometry args={[w, h, d]} /><Mat color={o.color} opacity={o.opacity} /></mesh>;
}

function VerticalCylinder({ o }: { o: SceneObject }) {
  const [w, h, d] = o.size;
  return <mesh position={[0, h / 2, 0]}><cylinderGeometry args={[Math.min(w, d) / 2, Math.min(w, d) / 2, h, 24]} /><Mat color={o.color} opacity={o.opacity} /></mesh>;
}

function SphereShape({ o }: { o: SceneObject }) {
  const [w, h, d] = o.size;
  const r = Math.min(w, h, d) / 2;
  return <mesh position={[0, r, 0]}><sphereGeometry args={[r, 24, 16]} /><Mat color={o.color} opacity={o.opacity} /></mesh>;
}

function FlatZone({ o, dashed }: { o: SceneObject; dashed?: boolean }) {
  const [w, , d] = o.size;
  return (
    <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[w, d]} />
      <meshBasicMaterial color={o.color} transparent opacity={o.opacity * (dashed ? 0.6 : 0.5)} depthWrite={false} />
      <Edges color={o.color} />
    </mesh>
  );
}

function LineFootprint({ o }: { o: SceneObject }) {
  const [w, , d] = o.size;
  return (
    <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[w, d]} />
      <meshBasicMaterial color={o.color} transparent opacity={0.08} depthWrite={false} />
      <Edges color={o.color} />
    </mesh>
  );
}

/** Horizontal machine (motor/pump/fan): body, base, fan that spins with live speed. */
function Machine({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const [w, h, d] = o.size;
  const fan = useRef<THREE.Group>(null);
  const speed = useRef(0);
  const type = o.asset_id ? ctx.typeOfAsset(o.asset_id) : undefined;
  useAssetPulse(ctx.live ? o.asset_id : null, () => {
    if (!o.asset_id || !isRunning(o.asset_id, type)) { speed.current = 0; return; }
    const rpm = num(telemetry.get(o.asset_id, "rpm")?.v) || 1200;
    speed.current = Math.min(rpm / 60, 25) * 0.35; // visual rev/s, slowed for readability
  });
  useFrame((state, dt) => {
    if (fan.current && speed.current > 0 && ctx.animate) {
      fan.current.rotation.z += speed.current * dt * Math.PI * 2;
      state.invalidate();
    }
  });
  const r = Math.min(w, h) * 0.42;
  return (
    <group>
      <mesh position={[0, 0.03, 0]}><boxGeometry args={[w, 0.06, d]} /><Mat color="#374151" /></mesh>
      <mesh position={[0, h * 0.55, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[r, r, d * 0.8, 24]} /><Mat color={o.color} opacity={o.opacity} />
      </mesh>
      <group ref={fan} position={[0, h * 0.55, -d * 0.42]}>
        {[0, 1, 2, 3].map((i) => (
          <mesh key={i} rotation={[0, 0, (i * Math.PI) / 2]} position={[0, 0, -0.01]}>
            <boxGeometry args={[r * 1.5, r * 0.25, 0.02]} /><Mat color="#e5e7eb" />
          </mesh>
        ))}
      </group>
      <mesh position={[0, h * 0.55, d * 0.48]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[r * 0.15, r * 0.15, d * 0.2, 12]} /><Mat color="#9ca3af" />
      </mesh>
    </group>
  );
}

/** Belt conveyor: legs, frame, belt; cleats move with live belt speed. */
function Conveyor({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const [len, h, wid] = o.size;
  const cleats = useRef<THREE.Group>(null);
  const speed = useRef(0);
  const type = o.asset_id ? ctx.typeOfAsset(o.asset_id) : undefined;
  useAssetPulse(ctx.live ? o.asset_id : null, () => {
    if (!o.asset_id || !isRunning(o.asset_id, type)) { speed.current = 0; return; }
    speed.current = num(telemetry.get(o.asset_id, "speed_mps")?.v) || 1;
  });
  const n = Math.max(4, Math.round(len / 0.8));
  const offset = useRef(0);
  useFrame((state, dt) => {
    if (!cleats.current || speed.current <= 0 || !ctx.animate) return;
    offset.current = (offset.current + speed.current * dt) % (len / n);
    cleats.current.children.forEach((c, i) => { c.position.x = -len / 2 + ((i * len) / n + offset.current) % len; });
    state.invalidate();
  });
  const legs = Math.max(2, Math.round(len / 2.5) + 1);
  return (
    <group>
      {Array.from({ length: legs }, (_, i) => {
        const x = -len / 2 + 0.1 + (i * (len - 0.2)) / (legs - 1);
        return [-1, 1].map((s) => (
          <mesh key={`${i}${s}`} position={[x, (h - 0.12) / 2, (s * wid) / 2.2]}><boxGeometry args={[0.06, h - 0.12, 0.06]} /><Mat color="#6b7280" /></mesh>
        ));
      })}
      <mesh position={[0, h - 0.07, 0]}><boxGeometry args={[len, 0.12, wid]} /><Mat color={o.color} opacity={o.opacity} /></mesh>
      <mesh position={[0, h + 0.005, 0]}><boxGeometry args={[len * 0.99, 0.02, wid * 0.86]} /><Mat color="#1f2937" /></mesh>
      <group ref={cleats}>
        {Array.from({ length: n }, (_, i) => (
          <mesh key={i} position={[-len / 2 + (i * len) / n, h + 0.03, 0]}><boxGeometry args={[0.05, 0.03, wid * 0.8]} /><Mat color="#9ca3af" /></mesh>
        ))}
      </group>
    </group>
  );
}

/** Six-axis robot: animates only while the controller reports "running". */
function RobotArm({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const [w, h] = o.size;
  const turret = useRef<THREE.Group>(null);
  const upper = useRef<THREE.Group>(null);
  const fore = useRef<THREE.Group>(null);
  const running = useRef(false);
  const t = useRef(0);
  const type = o.asset_id ? ctx.typeOfAsset(o.asset_id) : undefined;
  useAssetPulse(ctx.live ? o.asset_id : null, () => { running.current = !!o.asset_id && isRunning(o.asset_id, type); });
  useFrame((state, dt) => {
    if (!running.current || !ctx.animate || !turret.current) return;
    t.current += dt;
    turret.current.rotation.y = Math.sin(t.current * 0.9) * 1.1;
    upper.current!.rotation.z = -0.5 + Math.sin(t.current * 1.3) * 0.35;
    fore.current!.rotation.z = 1.1 + Math.sin(t.current * 1.7 + 1) * 0.4;
    state.invalidate();
  });
  const L = h * 0.42;
  return (
    <group>
      <mesh position={[0, h * 0.06, 0]}><cylinderGeometry args={[w * 0.35, w * 0.4, h * 0.12, 24]} /><Mat color="#374151" /></mesh>
      <group ref={turret} position={[0, h * 0.12, 0]}>
        <mesh position={[0, h * 0.08, 0]}><cylinderGeometry args={[w * 0.22, w * 0.25, h * 0.16, 20]} /><Mat color={o.color} /></mesh>
        <group ref={upper} position={[0, h * 0.18, 0]} rotation={[0, 0, -0.5]}>
          <mesh position={[0, L / 2, 0]}><boxGeometry args={[w * 0.14, L, w * 0.16]} /><Mat color={o.color} /></mesh>
          <group ref={fore} position={[0, L, 0]} rotation={[0, 0, 1.1]}>
            <mesh><sphereGeometry args={[w * 0.1, 16, 12]} /><Mat color="#374151" /></mesh>
            <mesh position={[0, L * 0.4, 0]}><boxGeometry args={[w * 0.1, L * 0.8, w * 0.12]} /><Mat color={o.color} /></mesh>
            <mesh position={[0, L * 0.85, 0]}><cylinderGeometry args={[w * 0.06, w * 0.04, L * 0.12, 12]} /><Mat color="#9ca3af" /></mesh>
          </group>
        </group>
      </group>
    </group>
  );
}

/** Tank shell with a liquid column that follows the live level. */
function Tank({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const [w, h, d] = o.size;
  const r = Math.min(w, d) / 2;
  const liquid = useRef<THREE.Mesh>(null);
  useAssetPulse(ctx.live ? o.asset_id : null, () => {
    const lv = o.asset_id ? telemetry.get(o.asset_id, "level_pct") : undefined;
    const fresh = lv && clock.now() - lv.ts < 30_000;
    const frac = fresh ? Math.max(0.01, Math.min(1, num(lv!.v) / 100)) : 0;
    if (liquid.current) {
      liquid.current.visible = !!fresh;
      liquid.current.scale.y = frac;
      liquid.current.position.y = (h * 0.92 * frac) / 2 + 0.02;
    }
  }, 2);
  return (
    <group>
      <mesh position={[0, h / 2, 0]}>
        <cylinderGeometry args={[r, r, h, 32, 1, true]} />
        <meshStandardMaterial color={o.color} transparent opacity={0.35} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <mesh position={[0, h, 0]}><cylinderGeometry args={[r, r, 0.04, 32]} /><Mat color={o.color} /></mesh>
      <mesh ref={liquid} position={[0, h * 0.3, 0]} visible={false}>
        <cylinderGeometry args={[r * 0.96, r * 0.96, h * 0.92, 32]} />
        <meshStandardMaterial color="#0ea5e9" transparent opacity={0.7} />
      </mesh>
    </group>
  );
}

function Panel({ o }: { o: SceneObject }) {
  const [w, h, d] = o.size;
  return (
    <group>
      <mesh position={[0, h / 2, 0]}><boxGeometry args={[w, h, d]} /><Mat color={o.color} opacity={o.opacity} /></mesh>
      <mesh position={[0, h / 2, d / 2 + 0.005]}><planeGeometry args={[w * 0.9, h * 0.92]} /><meshStandardMaterial color="#e5e7eb" roughness={0.5} /></mesh>
    </group>
  );
}

/** Field instrument on a stand; the head shows the live limit state. */
function Sensor({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const [w, h] = o.size;
  const stand = 1.2;
  const head = useRef<THREE.MeshStandardMaterial>(null);
  const type = o.asset_id ? ctx.typeOfAsset(o.asset_id) : undefined;
  useAssetPulse(ctx.live ? o.asset_id : null, (now) => {
    if (!head.current || !o.asset_id) return;
    const c = CONDITION_STYLE[assetLive({ id: o.asset_id }, type, now).condition].color;
    head.current.emissive.set(c);
    head.current.emissiveIntensity = 0.6;
  });
  return (
    <group>
      <mesh position={[0, stand / 2, 0]}><cylinderGeometry args={[0.025, 0.025, stand, 8]} /><Mat color="#6b7280" /></mesh>
      <mesh position={[0, stand + h / 2, 0]}>
        <boxGeometry args={[w, h, w]} />
        <meshStandardMaterial ref={head} color={o.color} />
      </mesh>
    </group>
  );
}

// ---------- uploaded models ----------
function authLoader<T extends THREE.Loader>(loader: T) {
  const token = tokenStore.get();
  if (token) loader.setRequestHeader({ Authorization: `Bearer ${token}` });
}

function fitTo(object: THREE.Object3D, size: [number, number, number]) {
  const box = new THREE.Box3().setFromObject(object);
  const dim = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const s = new THREE.Vector3(size[0] / (dim.x || 1), size[1] / (dim.y || 1), size[2] / (dim.z || 1));
  const wrap = new THREE.Group();
  object.position.set(-center.x, -box.min.y, -center.z);
  const inner = new THREE.Group();
  inner.add(object);
  inner.scale.copy(s);
  wrap.add(inner);
  return wrap;
}

function GltfModel({ url, o }: { url: string; o: SceneObject }) {
  const gltf = useLoader(GLTFLoader, url, authLoader);
  const obj = useMemo(() => fitTo(gltf.scene.clone(true), o.size), [gltf, o.size]);
  return <primitive object={obj} />;
}
function ObjModel({ url, o }: { url: string; o: SceneObject }) {
  const group = useLoader(OBJLoader, url, authLoader);
  const obj = useMemo(() => {
    const g = group.clone(true);
    g.traverse((c) => { if ((c as THREE.Mesh).isMesh) (c as THREE.Mesh).material = new THREE.MeshStandardMaterial({ color: o.color }); });
    return fitTo(g, o.size);
  }, [group, o.size, o.color]);
  return <primitive object={obj} />;
}
function StlModel({ url, o }: { url: string; o: SceneObject }) {
  const geom = useLoader(STLLoader, url, authLoader);
  const obj = useMemo(() => fitTo(new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color: o.color })), o.size), [geom, o.size, o.color]);
  return <primitive object={obj} />;
}

function ModelShape({ o, model }: { o: SceneObject; model: ModelFile }) {
  const url = `/api/models/${model.id}/file`;
  const Comp = model.format === "glb" ? GltfModel : model.format === "obj" ? ObjModel : StlModel;
  return (
    <Suspense fallback={<mesh position={[0, o.size[1] / 2, 0]}><boxGeometry args={o.size} /><meshBasicMaterial color={o.color} wireframe /></mesh>}>
      <Comp url={url} o={o} />
    </Suspense>
  );
}

// ---------- dispatcher ----------
function Body({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const model = o.model_id ? ctx.models[o.model_id] : undefined;
  if (model) return <ModelShape o={o} model={model} />;
  switch (o.kind) {
    case "walkway": return <FlatZone o={o} dashed />;
    case "zone": case "safety_zone": return <FlatZone o={o} />;
  }
  switch (o.shape) {
    case "conveyor": return <Conveyor o={o} />;
    case "robot_arm": return <RobotArm o={o} />;
    case "tank": return <Tank o={o} />;
    case "panel": return <Panel o={o} />;
    case "sensor": return <Sensor o={o} />;
    case "line": return <LineFootprint o={o} />;
    case "sphere": return <SphereShape o={o} />;
    case "cylinder": return o.kind === "asset" ? <Machine o={o} /> : <VerticalCylinder o={o} />;
    default: return <BoxShape o={o} />;
  }
}

export function objectHeight(o: SceneObject): number {
  if (o.shape === "sensor") return 1.2 + o.size[1];
  if (o.kind === "walkway" || o.kind === "zone" || o.kind === "safety_zone" || o.shape === "line") return 0.05;
  return o.size[1];
}

/** Status beacon above an asset: colour = derived live condition. */
function Beacon({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const mat = useRef<THREE.MeshBasicMaterial>(null);
  const type = o.asset_id ? ctx.typeOfAsset(o.asset_id) : undefined;
  useAssetPulse(o.asset_id, (now) => {
    if (!mat.current || !o.asset_id) return;
    mat.current.color.set(CONDITION_STYLE[assetLive({ id: o.asset_id }, type, now).condition].color);
  }, 3);
  if (o.shape === "line") return null;
  const y = (objectHeight(o) + 0.35) / Math.max(o.scale[1], 0.01);
  return (
    <mesh position={[0, y, 0]}>
      <sphereGeometry args={[0.16, 12, 8]} />
      <meshBasicMaterial ref={mat} color="#475569" />
    </mesh>
  );
}

function Label({ o }: { o: SceneObject }) {
  const ctx = useContext(SceneContext);
  const text = o.asset_id ? ctx.assetLabel(o.asset_id) : o.name;
  const y = (objectHeight(o) + (ctx.live ? 0.8 : 0.4)) / Math.max(o.scale[1], 0.01);
  return (
    <Html position={[0, y, 0]} center zIndexRange={[10, 0]} style={{ pointerEvents: "none" }}>
      <div className="scene-label">{text}</div>
    </Html>
  );
}

export const SceneItem = memo(function SceneItem({ o, onPick }: { o: SceneObject; onPick: (e: { shiftKey: boolean; delta: number }, id: string) => void }) {
  const ctx = useContext(SceneContext);
  if (o.hidden) return null;
  return (
    <group position={o.position} rotation={o.rotation} scale={o.scale}
      onClick={(e) => { e.stopPropagation(); onPick({ shiftKey: e.shiftKey || e.ctrlKey || e.metaKey, delta: e.delta }, o.id); }}>
      <Body o={o} />
      {ctx.live && o.kind === "asset" && <Beacon o={o} />}
      {ctx.labels && o.kind === "asset" && o.shape !== "line" && <Label o={o} />}
      {ctx.labels && o.shape === "line" && ctx.view === "2d" && <Label o={o} />}
    </group>
  );
});

/** Highlight for selected objects. */
export function SelectionOutline({ o, color = "#38bdf8" }: { o: SceneObject; color?: string }) {
  const h = Math.max(objectHeight(o), 0.05);
  const [w, , d] = o.size;
  return (
    <group position={o.position} rotation={o.rotation} scale={o.scale}>
      <mesh position={[0, h / 2, 0]} raycast={() => null}>
        <boxGeometry args={[w * 1.04 + 0.04, h * 1.04 + 0.04, d * 1.04 + 0.04]} />
        <meshBasicMaterial color={color} transparent opacity={0.08} depthWrite={false} />
        <Edges color={color} />
      </mesh>
    </group>
  );
}
