const TOKEN_KEY = "twin.token";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(ApiError.describe(detail, status));
    this.status = status;
    this.detail = detail;
  }

  /** Field-level errors from 422 responses, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const d = this.detail as { fields?: Record<string, string> } | undefined;
    if (d && typeof d === "object" && d.fields) return d.fields;
    if (Array.isArray(this.detail)) {
      const out: Record<string, string> = {};
      for (const e of this.detail as { loc?: unknown[]; msg?: string }[]) {
        const key = e.loc?.slice(1).join(".");
        if (key) out[key] = e.msg ?? "invalid";
      }
      return out;
    }
    return {};
  }

  static describe(detail: unknown, status: number): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".") || "request"}: ${e.msg}`)
        .join("; ");
    }
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; assets?: string[]; fields?: Record<string, string> };
      const extra = d.assets?.join("; ") ?? (d.fields ? Object.entries(d.fields).map(([k, v]) => `${k} ${v}`).join("; ") : "");
      return [d.message, extra].filter(Boolean).join(": ");
    }
    return `Request failed (${status})`;
  }
}

export const tokenStore = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (t: string | null) => {
    try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
  },
};

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
export const onUnauthorized = (fn: Listener) => {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
};

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your network connection.");
  }
  if (res.status === 401 && token) unauthorizedListeners.forEach((fn) => fn());
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b: unknown) => request<T>("PATCH", p, b),
  del: (p: string) => request<void>("DELETE", p),
};

export function qs(params: Record<string, string | number | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}
