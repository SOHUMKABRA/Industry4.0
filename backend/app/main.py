import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (register tables)
from pathlib import Path

from fastapi import Request
from fastapi.middleware.gzip import GZipMiddleware

from app.adapters.registry import load_plugins
from app.api import (
    alerts, analytics, asset_types, assets, audit, auth, automations, control, devices, factories, health, live, models3d,
    notifications, scenes, simulation, users,
)
from app.automation.engine import AutomationEngine
from app.notify.service import Notifier
from app.simulation import ScenarioRunner
from app.control.engine import ControlEngine
from app.core.schema_sync import sync_columns
from app.core.web import SecurityHeaders, metrics_text, mount_ui
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.telemetry.runtime import TelemetryRuntime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("twin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.check_production_safety()
    # Phase 1 creates tables directly; Alembic migrations arrive before the
    # first production deployment (see IMPLEMENTATION_ROADMAP.md).
    Base.metadata.create_all(engine)
    sync_columns(engine)
    plugins = load_plugins()
    if plugins:
        log.info("Loaded adapter plugins: %s", ", ".join(plugins))
    if settings.seed_demo:
        from app.seed.demo import seed_demo

        with SessionLocal() as db:
            if seed_demo(db):
                log.info("Seeded demo factory (login: %s)", "admin@demo.example.com")
            from app.seed.demo_layout import ensure_demo_extras

            added = ensure_demo_extras(db)
            from app.seed.demo_field import ensure_field_devices

            added += ensure_field_devices(db)
            from app.seed.demo_phase6 import ensure_phase6_demo

            added += ensure_phase6_demo(db)
            if added:
                log.info("Demo content added: %s", ", ".join(added))
    notifier = Notifier(SessionLocal)
    await notifier.start()
    app.state.notifier = notifier
    runtime = None
    if settings.telemetry_enabled:
        runtime = TelemetryRuntime(SessionLocal, settings.telemetry_poll_s, settings.telemetry_retention_hours)
        runtime.alert_listeners.append(notifier.on_alert)
        await runtime.start()
    app.state.telemetry = runtime
    control_engine = ControlEngine(runtime, SessionLocal)
    control_engine.bind_loop(asyncio.get_running_loop())
    stuck = control_engine.recover()
    if stuck:
        log.warning("%d command(s) interrupted by restart marked FAILED (state unknown)", stuck)
    app.state.control = control_engine
    app.state.scenarios = ScenarioRunner(runtime)
    automation = AutomationEngine(runtime, control_engine, notifier, SessionLocal)
    if runtime:
        await automation.start()
    app.state.automation = automation
    yield
    await automation.stop()
    if runtime:
        await runtime.stop()
    await notifier.stop()


app = FastAPI(title="Industrial Digital Twin Platform", version="1.1.0", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.state.started = __import__("time").time()
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(SecurityHeaders)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

for r in (health, auth, users, factories, asset_types, assets, devices, audit, scenes, models3d, live, control, alerts,
          analytics, automations, notifications, simulation):
    app.include_router(r.router, prefix="/api")


@app.get("/api/metrics", include_in_schema=False)
def metrics(request: Request):
    """Prometheus metrics; only served to local scrapers."""
    if request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
        from fastapi import HTTPException

        raise HTTPException(404)
    return metrics_text(app)


# The built UI is served by the same process in production (single origin, no CORS).
UI_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if mount_ui(app, UI_DIST):
    log.info("Serving UI from %s", UI_DIST)
