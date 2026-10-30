import { PropertyDef } from "../api/types";
import { Field } from "./ui";

/** Client-side mirror of backend property validation, for instant feedback.
 *  The server remains the authority. */
export function validateValue(d: Pick<PropertyDef, "type" | "required" | "min" | "max" | "options">, v: unknown): string | null {
  if (v === undefined || v === null || v === "") return d.required ? "Required" : null;
  if (d.type === "number" || d.type === "integer") {
    if (typeof v !== "number" || Number.isNaN(v)) return "Must be a number";
    if (d.type === "integer" && !Number.isInteger(v)) return "Must be a whole number";
    if (d.min !== null && d.min !== undefined && v < d.min) return `Must be ≥ ${d.min}`;
    if (d.max !== null && d.max !== undefined && v > d.max) return `Must be ≤ ${d.max}`;
  }
  if (d.type === "enum" && !d.options.includes(String(v))) return "Choose a value";
  return null;
}

export function validateAll(schema: PropertyDef[], values: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const d of schema) {
    const e = validateValue(d, values[d.key]);
    if (e) out[d.key] = e;
  }
  return out;
}

export function defaultsFor(schema: PropertyDef[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const d of schema) if (d.default !== null && d.default !== undefined) out[d.key] = d.default;
  return out;
}

function PropInput({ def, value, onChange, invalid, disabled }: {
  def: PropertyDef; value: unknown; onChange: (v: unknown) => void; invalid: boolean; disabled?: boolean;
}) {
  const id = `prop-${def.key}`;
  const cls = `input${invalid ? " invalid" : ""}`;
  switch (def.type) {
    case "boolean":
      return (
        <label className="check" style={{ height: 32 }}>
          <input id={id} type="checkbox" checked={value === true} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          {value === true ? "Yes" : "No"}
        </label>
      );
    case "enum":
      return (
        <select id={id} className={`select ${cls}`} value={String(value ?? "")} disabled={disabled}
          onChange={(e) => onChange(e.target.value || null)}>
          <option value="">{def.required ? "Select…" : "—"}</option>
          {def.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case "number":
    case "integer":
      return (
        <div className="input-unit">
          <input id={id} className={cls} type="number" inputMode="decimal" disabled={disabled}
            step={def.type === "integer" ? 1 : "any"} min={def.min ?? undefined} max={def.max ?? undefined}
            value={value === null || value === undefined ? "" : String(value)}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
          {def.unit && <span className="unit">{def.unit}</span>}
        </div>
      );
    default:
      return <input id={id} className={cls} value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
  }
}

/** Renders an editable form for any asset type's property_schema. */
export function DynamicForm({ schema, values, onChange, errors = {}, disabled }: {
  schema: PropertyDef[]; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void;
  errors?: Record<string, string>; disabled?: boolean;
}) {
  if (!schema.length) return <p className="faint small" style={{ margin: 0 }}>This asset type defines no custom properties.</p>;
  const groups = [...new Set(schema.map((d) => d.group || "General"))];
  return (
    <div className="stack">
      {groups.map((g) => (
        <div key={g}>
          {groups.length > 1 && <div className="section-title">{g}</div>}
          <div className="grid-2">
            {schema.filter((d) => (d.group || "General") === g).map((d) => {
              const rangeHelp = d.min !== null || d.max !== null
                ? `Range ${d.min ?? "−∞"} – ${d.max ?? "∞"}${d.unit ? ` ${d.unit}` : ""}` : "";
              return (
                <Field key={d.key} label={d.label} required={d.required} htmlFor={`prop-${d.key}`}
                  error={errors[d.key]} help={d.help || rangeHelp}>
                  <PropInput def={d} value={values[d.key]} invalid={!!errors[d.key]} disabled={disabled}
                    onChange={(v) => onChange({ ...values, [d.key]: v })} />
                </Field>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
