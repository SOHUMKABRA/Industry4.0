import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { onAlert, useAlerts } from "../live/liveMeta";

/** Top-bar bell: count of unacknowledged alerts; toasts new alarms. */
export function AlertBell() {
  const active = useAlerts((s) => s.active);
  const toast = useToast();
  useEffect(() => onAlert((a, isNew) => {
    if (isNew) toast(a.severity === "alarm" ? "bad" : "info", `${a.severity === "alarm" ? "ALARM" : "Warning"}: ${a.message}`);
  }), [toast]);
  const list = Object.values(active);
  const unacked = list.filter((a) => !a.acked);
  const alarm = unacked.some((a) => a.severity === "alarm");
  return (
    <Link to="/alerts" className={`bell${unacked.length ? (alarm ? " alarm" : " warn") : ""}`} title={`${unacked.length} unacknowledged of ${list.length} active alerts`} aria-label="Alerts">
      <Icon name="alert" size={17} />
      {unacked.length > 0 && <span className="bell-count">{unacked.length}</span>}
    </Link>
  );
}
