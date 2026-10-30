import { FormEvent, useState } from "react";
import { useAuth } from "./AuthContext";
import { Field } from "../components/ui";

export function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", organization_name: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(form.email, form.password);
      else await register(form);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="panel login-card stack" onSubmit={submit}>
        <div className="row" style={{ gap: 12, marginBottom: 4 }}>
          <img src="/favicon.svg" width={34} height={34} alt="" />
          <div>
            <h1>{mode === "login" ? "Sign in" : "Create your organization"}</h1>
            <div className="muted small">Industrial Digital Twin Platform</div>
          </div>
        </div>
        {mode === "register" && (
          <>
            <Field label="Organization" required htmlFor="org">
              <input id="org" className="input" value={form.organization_name} onChange={set("organization_name")} required minLength={2} />
            </Field>
            <Field label="Your name" required htmlFor="name">
              <input id="name" className="input" value={form.name} onChange={set("name")} required />
            </Field>
          </>
        )}
        <Field label="Email" required htmlFor="email">
          <input id="email" className="input" type="email" autoComplete="username" value={form.email} onChange={set("email")} required autoFocus />
        </Field>
        <Field label="Password" required htmlFor="pw" help={mode === "register" ? "At least 8 characters" : undefined}>
          <input id="pw" className="input" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={form.password} onChange={set("password")} required minLength={mode === "register" ? 8 : 1} />
        </Field>
        {error && <div className="notice bad" role="alert">{error}</div>}
        <button className="btn primary" type="submit" disabled={busy} style={{ height: 36 }}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
        <button type="button" className="btn ghost" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
          {mode === "login" ? "New here? Create an organization" : "Have an account? Sign in"}
        </button>
        {mode === "login" && import.meta.env.DEV && (
          <div className="notice small">
            <span>Demo: <code>admin@demo.example.com</code> / <code>demo1234</code> (also engineer@, operator@, viewer@)</span>
          </div>
        )}
      </form>
    </div>
  );
}
