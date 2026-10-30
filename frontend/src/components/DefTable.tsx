import { Icon } from "./Icon";

export type Col<T> = {
  key: keyof T & string;
  label: string;
  kind: "text" | "num" | "select" | "bool" | "list" | "any";
  options?: string[];
  width?: number;
  placeholder?: string;
  title?: string;
};

type Row = Record<string, unknown>;

function cellValue(kind: Col<Row>["kind"], v: unknown): string {
  if (v === null || v === undefined) return "";
  if (kind === "list") return (v as string[]).join(", ");
  return String(v);
}

function parse(kind: Col<Row>["kind"], raw: string): unknown {
  if (kind === "num") return raw === "" ? null : Number(raw);
  if (kind === "list") return raw.split(",").map((s) => s.trim()).filter(Boolean);
  if (kind === "any") {
    if (raw === "") return null;
    if (raw === "true" || raw === "false") return raw === "true";
    const n = Number(raw);
    return Number.isFinite(n) && raw.trim() !== "" ? n : raw;
  }
  return raw;
}

/** Spreadsheet-like editor for a list of definitions (properties, telemetry, controls). */
export function DefTable<T extends object>({ rows, cols, onChange, blank, disabled, addLabel }: {
  rows: T[]; cols: Col<T>[]; onChange: (rows: T[]) => void; blank: () => T; disabled?: boolean; addLabel: string;
}) {
  const update = (i: number, k: string, v: unknown) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  return (
    <div className="scroll">
      <table className="table def-table">
        <thead>
          <tr>{cols.map((c) => <th key={c.key} style={{ width: c.width }} title={c.title}>{c.label}</th>)}{!disabled && <th style={{ width: 84 }} />}</tr>
        </thead>
        <tbody>
          {(rows as unknown as Row[]).map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c.key}>
                  {c.kind === "bool" ? (
                    <input type="checkbox" checked={!!r[c.key]} disabled={disabled} aria-label={c.label}
                      onChange={(e) => update(i, c.key, e.target.checked)} style={{ accentColor: "var(--accent)" }} />
                  ) : c.kind === "select" ? (
                    <select className="select" value={String(r[c.key] ?? "")} disabled={disabled} aria-label={c.label}
                      onChange={(e) => update(i, c.key, e.target.value || null)}>
                      {c.options!.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
                    </select>
                  ) : (
                    <input className={`input${c.key === "key" ? " mono" : ""}`} value={cellValue(c.kind, r[c.key])} placeholder={c.placeholder}
                      type={c.kind === "num" ? "number" : "text"} step="any" disabled={disabled} aria-label={c.label}
                      onChange={(e) => update(i, c.key, parse(c.kind, e.target.value))} />
                  )}
                </td>
              ))}
              {!disabled && (
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn sm ghost" onClick={() => move(i, -1)} aria-label="Move up" disabled={i === 0}>↑</button>
                  <button className="btn sm ghost danger" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label="Remove"><Icon name="x" size={13} /></button>
                </td>
              )}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={cols.length + 1} className="faint">None defined.</td></tr>}
        </tbody>
      </table>
      {!disabled && <button className="btn sm" style={{ margin: "8px 6px" }} onClick={() => onChange([...rows, blank()])}><Icon name="plus" size={13} />{addLabel}</button>}
    </div>
  );
}
