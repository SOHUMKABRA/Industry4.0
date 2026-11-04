"""Production HTTP concerns: security headers, serving the built UI, metrics."""

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss: blob:; "
    "worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(("/api/docs", "/api/redoc", "/docs", "/redoc")):
            h.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return resp


def mount_ui(app: FastAPI, dist: Path) -> bool:
    """Serve the built single-page app from the same origin as the API."""
    index = dist / "index.html"
    if not index.exists():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (root / path).resolve()
        if path and f.is_file() and root in f.parents:
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(f, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True


def metrics_text(app: FastAPI) -> PlainTextResponse:
    rt = getattr(app.state, "telemetry", None)
    lines = [f"twin_up 1", f"twin_uptime_seconds {time.time() - app.state.started:.0f}"]
    if rt:
        online = sum(1 for c in rt.devices.values() if rt.device_online(c))
        lines += [
            f"twin_devices_active {len(rt.devices)}", f"twin_devices_online {online}",
            f"twin_ws_subscribers {len(rt.hub.subscribers)}", f"twin_latest_values {len(rt.latest)}",
            f"twin_alerts_active {len(rt.alerts.active)}", f"twin_history_buffer {len(rt._buffer)}",
        ] + [f"twin_telemetry_{k}_total {v}" for k, v in rt.stats.items()]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
