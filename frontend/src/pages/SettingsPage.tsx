import { FormEvent, Fragment, useState } from "react";
import { api } from "../api/client";
import { Role, UserAdmin } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { ErrorNote, Field, Loading, Modal, Pill, Tabs } from "../components/ui";
import { titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";
import { NotificationsSettings } from "./NotificationsSettings";

const ROLES: Role[] = ["viewer", "operator", "engineer", "admin"];
const ROLE_HELP: Record<Role, string> = {
  viewer: "Read-only access",
  operator: "Read, test connections, issue commands, acknowledge alerts",
  engineer: "Configure everything, approve commands",
  admin: "Everything, plus user management",
};

export function ChangePassword({ onDone }: { onDone?: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ current: "", next: "", again: "" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (f.next !== f.again) { setErr("The new passwords don't match"); return; }
    try {
      await api.post("/auth/change-password", { current_password: f.current, new_password: f.next });
      toast("ok", "Password changed");
      setF({ current: "", next: "", again: "" });
      setErr(null);
      onDone?.();
    } catch (ex) { setErr((ex as Error).message); }
  };
  return (
    <form className="stack" onSubmit={submit} style={{ maxWidth: 420 }}>
      <Field label="Current password" required><input className="input" type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} required /></Field>
      <Field label="New password" required help="At least 8 characters"><input className="input" type="password" autoComplete="new-password" minLength={8} value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} required /></Field>
      <Field label="Repeat new password" required><input className="input" type="password" autoComplete="new-password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} required /></Field>
      {err && <div className="notice bad">{err}</div>}
      <div><button className="btn primary" type="submit">Change password</button></div>
    </form>
  );
}

function Users() {
  const { me } = useAuth();
  const toast = useToast();
  const users = useApi(() => api.get<UserAdmin[]>("/users"), []);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", role: "operator" as Role });
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null);

  const patch = async (u: UserAdmin, body: Partial<UserAdmin>) => {
    try { await api.patch(`/users/${u.id}`, body); await users.reload(); toast("ok", `${u.email} updated`); } catch (e) { toast("bad", (e as Error).message); }
  };
  const create = async () => {
    try {
      const r = await api.post<{ user: UserAdmin; temporary_password: string }>("/users", form);
      setAdding(false);
      setSecret({ email: r.user.email, password: r.temporary_password });
      setForm({ email: "", name: "", role: "operator" });
      await users.reload();
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const reset = async (u: UserAdmin) => {
    try { const r = await api.post<{ temporary_password: string }>(`/users/${u.id}/reset-password`); setSecret({ email: u.email, password: r.temporary_password }); await users.reload(); }
    catch (e) { toast("bad", (e as Error).message); }
  };

  if (users.error) return <ErrorNote error={users.error} />;
  if (!users.data) return <Loading />;
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}><span className="muted small">{users.data.length} users</span><button className="btn primary right" onClick={() => setAdding(true)}>Add user</button></div>
      <table className="table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
        <tbody>
          {users.data.map((u) => (
            <tr key={u.id}>
              <td>{u.name}{u.id === me?.user.id && <span className="faint small"> (you)</span>}</td>
              <td className="muted">{u.email}</td>
              <td>
                <select className="select" style={{ width: 130 }} value={u.role} onChange={(e) => patch(u, { role: e.target.value as Role })} aria-label="Role">
                  {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
                </select>
              </td>
              <td>{u.is_active ? (u.must_change_password ? <Pill tone="warn">Must set password</Pill> : <Pill tone="ok">Active</Pill>) : <Pill tone="neutral">Deactivated</Pill>}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <button className="btn sm ghost" onClick={() => reset(u)}>Reset password</button>
                {u.id !== me?.user.id && <button className="btn sm ghost" onClick={() => patch(u, { is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Reactivate"}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="kv small" style={{ marginTop: 14 }}>{ROLES.map((r) => <Fragment key={r}><dt>{titleCase(r)}</dt><dd>{ROLE_HELP[r]}</dd></Fragment>)}</dl>
      {adding && (
        <Modal title="Add user" onClose={() => setAdding(false)} footer={<>
          <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
          <button className="btn primary" disabled={!form.email || !form.name} onClick={create}>Create</button>
        </>}>
          <div className="stack">
            <Field label="Name" required><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
            <Field label="Email" required><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Role" help={ROLE_HELP[form.role]}>
              <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</select>
            </Field>
            <p className="faint small" style={{ margin: 0 }}>A temporary password is generated. The user must change it at first sign-in.</p>
          </div>
        </Modal>
      )}
      {secret && (
        <Modal title="Temporary password" onClose={() => setSecret(null)} footer={<button className="btn primary" onClick={() => setSecret(null)}>Done</button>}>
          <div className="stack">
            <p className="muted" style={{ margin: 0 }}>Give this to <strong>{secret.email}</strong> through a secure channel. It is shown only once.</p>
            <div className="secret mono">{secret.password}</div>
          </div>
        </Modal>
      )}
    </>
  );
}

export function SettingsPage() {
  const { me, can } = useAuth();
  const [tab, setTab] = useState<"account" | "users" | "notifications">(can("user.manage") ? "users" : "account");
  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><div className="sub">{me?.organization.name}</div></div></div>
      <section className="panel">
        <Tabs value={tab} onChange={setTab} tabs={[...(can("user.manage") ? [{ key: "users" as const, label: "Users & roles" }] : []),
          { key: "notifications", label: "Notifications" }, { key: "account", label: "My account" }]} />
        <div className="panel-body">
          {tab === "users" ? <Users /> : tab === "notifications" ? <NotificationsSettings /> : (
            <div className="stack">
              <dl className="kv"><dt>Name</dt><dd>{me?.user.name}</dd><dt>Email</dt><dd>{me?.user.email}</dd><dt>Role</dt><dd>{titleCase(me?.user.role ?? "")}</dd></dl>
              <div className="section-title">Change password</div>
              <ChangePassword />
            </div>
          )}
        </div>
      </section>
    </>
  );
}
