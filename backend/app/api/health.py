from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.deps import DB

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DB, request: Request):
    db.execute(text("SELECT 1"))
    rt = getattr(request.app.state, "telemetry", None)
    return {"status": "ok", "database": "ok", "telemetry": "running" if rt and rt.running else "off",
            "control": "ready" if getattr(request.app.state, "control", None) else "off", "version": request.app.version}
