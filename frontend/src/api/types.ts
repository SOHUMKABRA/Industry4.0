// Mirrors backend/app/schemas. Keep in sync with API_DOCUMENTATION.md.

export type Role = "admin" | "engineer" | "operator" | "viewer";

export interface User { id: string; org_id: string; email: string; name: string; role: Role; must_change_password?: boolean }
export interface Org { id: string; name: string; slug: string }
export interface Me { user: User; organization: Org; permissions: string[] }
export interface TokenOut { access_token: string; token_type: string; me: Me }

export type LengthUnit = "mm" | "cm" | "m" | "ft";
export interface Factory {
  id: string; name: string; description: string; location: string; timezone: string;
  length_unit: LengthUnit; created_at: string; updated_at: string;
}
export type AreaKind = "production" | "storage" | "walkway" | "safety" | "utility" | "office";
export interface Bounds { x: number; z: number; width: number; depth: number }
export interface Area { id: string; floor_id: string; name: string; kind: AreaKind; bounds: Bounds }
export interface Floor {
  id: string; factory_id: string; name: string; level: number; elevation_m: number;
  width_m: number; depth_m: number; areas: Area[];
}
export interface FactoryStructure extends Factory { floors: Floor[] }
export interface CountBy { key: string; label: string; count: number }
export interface FactorySummary {
  factory_id: string; asset_count: number; device_count: number; devices_enabled: number;
  devices_untested: number; devices_test_failed: number; floors: number; areas: number;
  by_category: CountBy[]; by_area: CountBy[]; live_data_available: boolean;
}

export type PropType = "number" | "integer" | "string" | "boolean" | "enum";
export interface PropertyDef {
  key: string; label: string; type: PropType; unit: string; required: boolean;
  min: number | null; max: number | null; options: string[]; default: unknown; group: string; help: string;
}
export interface TelemetryDef {
  key: string; label: string; data_type: PropType; unit: string;
  min: number | null; max: number | null; warn_low: number | null; warn_high: number | null;
  alarm_low: number | null; alarm_high: number | null; options: string[]; expected_interval_s: number;
}
export interface ControlParam { key: string; label: string; type: string; unit: string; min: number | null; max: number | null; options: string[] }
export interface ControlDef {
  key: string; label: string; kind: "command" | "setpoint"; params: ControlParam[];
  requires_confirmation: boolean; min_role: "operator" | "engineer" | "admin";
  feedback_measurement: string | null; feedback_value: string | number | boolean | null;
  feedback_tolerance: number | null; requires_approval: boolean; timeout_s: number; description: string;
}
export type Shape = "box" | "cylinder" | "sphere" | "conveyor" | "robot_arm" | "tank" | "panel" | "sensor" | "line";
export interface VisualDef { shape: Shape; color: string; model_url: string | null; size: [number, number, number] }
export interface AssetType {
  id: string; key: string; name: string; category: string; description: string; icon: string;
  property_schema: PropertyDef[]; telemetry: TelemetryDef[]; controls: ControlDef[]; visual: VisualDef;
  version: number; asset_count: number; created_at: string; updated_at: string;
}
export type Lifecycle = "active" | "maintenance" | "decommissioned";
export interface Asset {
  id: string; factory_id: string; area_id: string | null; parent_id: string | null;
  asset_type_id: string; asset_type: { id: string; key: string; name: string; category: string; icon: string };
  code: string; name: string; description: string; manufacturer: string; model: string; serial_number: string;
  tags: string[]; properties: Record<string, unknown>; lifecycle_status: Lifecycle; version: number;
  created_at: string; updated_at: string;
}

export interface ConfigField {
  key: string; label: string; type: string; required: boolean; default: unknown;
  options: string[]; secret: boolean; help: string;
}
export interface Protocol {
  key: string; name: string; status: "available" | "planned"; description: string;
  config_schema: ConfigField[]; supports_discovery: boolean; supports_write: boolean;
}
export interface PointMapping { point: string; measurement: string; scale: number; offset: number }
export interface ControlMapping { control: string; point: string; value: unknown; param: string | null; scale: number }
export interface Device {
  id: string; factory_id: string; asset_id: string | null; name: string; protocol: string;
  connection_config: Record<string, unknown>; has_credentials: boolean; point_mappings: PointMapping[];
  control_mappings: ControlMapping[]; template_id: string | null; enabled: boolean; last_test_status: "unknown" | "ok" | "error"; last_test_message: string;
  last_test_at: string | null; created_at: string; updated_at: string;
}
export interface TestResult { ok: boolean; message: string; latency_ms: number | null }
export interface DiscoveredPoint { point: string; label: string; data_type: string; unit: string; suggested_measurement: string | null }
export interface AuditEntry {
  id: string; at: string; user_email: string; action: string; entity_type: string;
  entity_id: string | null; summary: string; details: Record<string, unknown>;
}

// ---------- Phase 2: scenes, models, live, dashboards ----------
export type Vec3 = [number, number, number];
export type ObjectKind = "asset" | "wall" | "door" | "window" | "pillar" | "zone" | "walkway" | "safety_zone" | "workstation" | "storage" | "label" | "box";
export interface SceneObject {
  id: string; kind: ObjectKind; asset_id: string | null; name: string; shape: string;
  position: Vec3; rotation: Vec3; scale: Vec3; size: Vec3; color: string; opacity: number;
  model_id: string | null; floor_id: string | null; group_id: string | null;
  locked: boolean; hidden: boolean; sort: number; props: Record<string, unknown>;
}
export interface SceneInfo { id: string; factory_id: string; name: string; version: number; updated_by: string; updated_at: string }
export interface SceneWithObjects { scene: SceneInfo; objects: SceneObject[] }
export interface SceneVersion { id: string; version: number; message: string; created_by: string; created_at: string; object_count: number }
export interface ModelFile { id: string; filename: string; format: string; size_bytes: number; uploaded_by: string; created_at: string }
export interface HistoryPoint { t: number; avg: number | null; min: number | null; max: number | null; last: unknown; count: number; source: string }
export interface HistoryOut { asset_id: string; measurement: string; from: number; to: number; points: HistoryPoint[] }
export type WidgetType = "value" | "gauge" | "trend" | "state" | "kpis" | "alarms" | "devices";
export interface Widget { id: string; type: WidgetType; title: string; size: "s" | "m" | "l" | "w"; asset_id: string | null; measurement: string | null; minutes: number }
export interface Dashboard { id: string; factory_id: string; name: string; widgets: Widget[]; created_by: string; updated_at: string }

// ---------- Phase 3/5: templates, control, alerts, users ----------
export interface DeviceTemplate {
  id: string; key: string; name: string; protocol: string; description: string; asset_type_key: string | null;
  connection_config: Record<string, unknown>; point_mappings: PointMapping[]; control_mappings: ControlMapping[]; builtin: boolean;
}
export type CommandStatus = "REQUESTED" | "VALIDATING" | "PENDING_APPROVAL" | "APPROVED" | "SENT" | "ACKNOWLEDGED" | "COMPLETED" | "REJECTED" | "FAILED" | "TIMED_OUT" | "CANCELLED";
export interface Check { name: string; ok: boolean; detail: string }
export interface Command {
  id: string; org_id: string; factory_id: string; asset_id: string; device_id: string | null; control_key: string; control_label: string;
  params: Record<string, unknown>; status: CommandStatus; simulated: boolean; verified: boolean; reason: string;
  requested_by: string; requested_at: string; approved_by: string | null; approved_at: string | null; sent_at: string | null;
  acked_at: string | null; finished_at: string | null; result_message: string; checks: Check[];
  events: { status: CommandStatus; at: string; detail: string }[];
}
export interface ValidationResult { ok: boolean; checks: Check[]; simulated: boolean; requires_approval: boolean }
export interface Interlock {
  id: string; asset_id: string; control_key: string; source_asset_id: string; source_code: string | null;
  measurement: string; operator: string; value: string; message: string; enabled: boolean;
}
export interface Alert {
  id: string; org_id: string; factory_id: string; asset_id: string | null; device_id: string | null; kind: "limit" | "state" | "comm" | "command" | "automation";
  measurement: string | null; severity: "warning" | "alarm"; active: boolean; message: string; value_num: number | null; value_text: string | null;
  threshold: number | null; source: string; raised_at: string; updated_at: string; cleared_at: string | null;
  acked: boolean; acked_by: string | null; acked_at: string | null;
}
export interface UserAdmin { id: string; email: string; name: string; role: Role; is_active: boolean; must_change_password: boolean }
export interface DeviceDiagnostics {
  active: boolean; reason?: string; online?: boolean; connected?: boolean; protocol?: string; samples?: number; errors?: number;
  last_error?: string; poll_ms?: number | null; last_seen?: number | null; adapter?: Record<string, unknown>;
}

// ---------- Phase 6 ----------
export interface CondItem { asset_id: string; measurement: string; operator: string; value: string }
export interface Rule {
  id: string; factory_id: string; name: string; description: string; enabled: boolean;
  trigger: { type: "condition" | "schedule"; every_minutes?: number | null; daily_at?: string | null; days: number[] };
  conditions: { match: "all" | "any"; for_s: number; items: CondItem[] };
  actions: { type: "alert" | "notify" | "command" | "delay"; severity?: string; message?: string; channel_id?: string | null;
    asset_id?: string | null; control?: string | null; params?: Record<string, unknown>; seconds?: number }[];
  cooldown_s: number; created_by: string; version: number; last_fired_at: string | null; warnings?: string[];
}
export interface Execution {
  id: string; rule_id: string; started_at: string; finished_at: string | null; status: string; dry_run: boolean; trigger_detail: string;
  steps: { type: string; status: string; detail: string; at?: string; command_id?: string }[];
}
export interface Channel {
  id: string; name: string; type: "webhook" | "email"; enabled: boolean; alerts: boolean; min_severity: "warning" | "alarm";
  notify_clear: boolean; config: Record<string, unknown>; has_secret: boolean;
}
export interface Delivery { id: string; at: string; event: string; subject: string; status: string; attempts: number; detail: string }
export interface ScenarioStep { at_s: number; device_id: string; action: "set" | "offline" | "restore"; point?: string | null; value?: unknown; duration_s: number }
export interface Scenario { id: string; factory_id: string; name: string; description: string; steps: ScenarioStep[]; created_by: string }
export interface ScenarioRun { scenario_id: string; name: string; started_by: string; started_at: number; duration_s: number; elapsed_s: number; done: boolean; log: string[] }
