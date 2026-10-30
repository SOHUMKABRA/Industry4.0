import { ReactNode, useEffect } from "react";
import { Icon } from "./Icon";

export function Modal({ title, onClose, children, footer, wide }: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn ghost icon right" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title, message, confirmLabel = "Delete", onConfirm, onClose, busy }: {
  title: string; message: ReactNode; confirmLabel?: string; onConfirm: () => void; onClose: () => void; busy?: boolean;
}) {
  return (
    <Modal title={title} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn danger solid" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
    </>}>
      <p className="muted" style={{ margin: 0 }}>{message}</p>
    </Modal>
  );
}

export function Field({ label, required, help, error, children, htmlFor }: {
  label: ReactNode; required?: boolean; help?: ReactNode; error?: string; children: ReactNode; htmlFor?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}{required && <span className="req">*</span>}</label>
      {children}
      {error ? <span className="err">{error}</span> : help ? <span className="help">{help}</span> : null}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading"><div className="spinner" />{label}</div>;
}

export function ErrorNote({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="notice bad" role="alert">
      <span>{error.message}</span>
      {onRetry && <button className="btn sm right" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <div style={{ marginBottom: action ? 14 : 0 }}>{children}</div>}
      {action}
    </div>
  );
}

export type Tone = "ok" | "warn" | "bad" | "sim" | "info" | "neutral";
export function Pill({ tone = "neutral", children, dot = true }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return <span className={`pill ${tone}`}>{dot && <span className="dot" />}{children}</span>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { key: T; label: ReactNode }[]; value: T; onChange: (k: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === value} className={t.key === value ? "active" : ""}
          onClick={() => onChange(t.key)}>{t.label}</button>
      ))}
    </div>
  );
}
