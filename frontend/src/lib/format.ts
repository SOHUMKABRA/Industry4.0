export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function formatValue(v: unknown, unit = ""): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return `${Number.isInteger(v) ? v : +v.toFixed(3)}${unit ? ` ${unit}` : ""}`;
  return `${v}${unit ? ` ${unit}` : ""}`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString();

// Lengths are stored in metres; displayed in the factory's chosen unit.
const PER_M: Record<string, number> = { mm: 1000, cm: 100, m: 1, ft: 3.28084 };
export const fromMetres = (m: number, unit: string) => +(m * (PER_M[unit] ?? 1)).toFixed(3);
export const toMetres = (v: number, unit: string) => v / (PER_M[unit] ?? 1);
