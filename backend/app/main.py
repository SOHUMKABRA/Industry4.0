import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401  (register tables)
from app.api import asset_types, assets, audit, auth, devices, factories, health
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("twin")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.check_production_safety()
    # Phase 1 creates tables directly; Alembic migrations arrive before the
    # first production deployment (see IMPLEMENTATION_ROADMAP.md).
    Base.metadata.create_all(engine)
    if settings.seed_demo:
        from app.seed.demo import seed_demo

        with SessionLocal() as db:
            if seed_demo(db):
                log.info("Seeded demo factory (login: %s)", "admin@demo.example.com")
    yield


app = FastAPI(title="Industrial Digital Twin Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

for r in (health, auth, factories, asset_types, assets, devices, audit):
    app.include_router(r.router, prefix="/api")
