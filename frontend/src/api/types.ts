// Mirrors backend/app/schemas. Keep in sync with API_DOCUMENTATION.md.

export type Role = "admin" | "engineer" | "operator" | "viewer";

export interface User { id: string; org_id: string; email: string; name: string; role: Role }
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
  feedback_measurement: string | null; description: string;
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
export interface Device {
  id: string; factory_id: string; asset_id: string | null; name: string; protocol: string;
  connection_config: Record<string, unknown>; has_credentials: boolean; point_mappings: PointMapping[];
  enabled: boolean; last_test_status: "unknown" | "ok" | "error"; last_test_message: string;
  last_test_at: string | null; created_at: string; updated_at: string;
}
export interface TestResult { ok: boolean; message: string; latency_ms: number | null }
export interface DiscoveredPoint { point: string; label: string; data_type: string; unit: string; suggested_measurement: string | null }
export interface AuditEntry {
  id: string; at: string; user_email: string; action: string; entity_type: string;
  entity_id: string | null; summary: string; details: Record<string, unknown>;
}
