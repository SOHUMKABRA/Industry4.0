from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm
from app.models import Device, Factory, SimulationScenario, User
from app.services import audit
from app.simulation import ScenarioRunner, SimulationError, apply_step

router = APIRouter(prefix="/simulation", tags=["simulation"])
Writer = Annotated[User, Depends(require(Perm.FACTORY_WRITE))]


class Step(BaseModel):
    at_s: float = Field(default=0, ge=0, le=3600)
    device_id: str
    action: Literal["set", "offline", "restore"]
    point: str | None = None
    value: Any = None
    duration_s: float = Field(default=60, ge=1, le=3600)


class ScenarioIn(BaseModel):
    factory_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    steps: list[Step] = Field(min_length=1, max_length=50)


def _runner(request: Request) -> ScenarioRunner:
    r = getattr(request.app.state, "scenarios", None)
    if r is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Simulation runner is not available")
    return r


def _check_devices(db, user, factory_id: str, steps: list[Step]) -> None:
    for s in steps:
        d = get_owned(db, Device, s.device_id, user, "Device")
        if d.factory_id != factory_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{d.name} is in another factory")
        if d.protocol != "simulated":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{d.name} is a field device ({d.protocol}); scenarios only act on simulated devices")
        if s.action == "set" and not s.point:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A 'set' step needs a point")


def _out(s: SimulationScenario) -> dict[str, Any]:
    return {"id": s.id, "factory_id": s.factory_id, "name": s.name, "description": s.description, "steps": s.steps, "created_by": s.created_by}


@router.get("/scenarios")
def list_scenarios(factory_id: str, user: CurrentUser, db: DB):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    return [_out(s) for s in db.scalars(select(SimulationScenario).where(SimulationScenario.factory_id == f.id).order_by(SimulationScenario.name))]


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioIn, user: Writer, db: DB):
    get_owned(db, Factory, body.factory_id, user, "Factory")
    _check_devices(db, user, body.factory_id, body.steps)
    s = SimulationScenario(org_id=user.org_id, factory_id=body.factory_id, name=body.name, description=body.description,
                           steps=[x.model_dump(mode="json") for x in body.steps], created_by=user.email)
    db.add(s)
    db.flush()
    audit.record(db, user, "scenario.create", "scenario", s.id, f"Created simulation scenario '{s.name}'")
    db.commit()
    return _out(s)


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: ScenarioIn, user: Writer, db: DB):
    s = get_owned(db, SimulationScenario, scenario_id, user, "Scenario")
    _check_devices(db, user, s.factory_id, body.steps)
    s.name, s.description, s.steps = body.name, body.description, [x.model_dump(mode="json") for x in body.steps]
    audit.record(db, user, "scenario.update", "scenario", s.id, f"Updated simulation scenario '{s.name}'")
    db.commit()
    return _out(s)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, user: Writer, db: DB):
    s = get_owned(db, SimulationScenario, scenario_id, user, "Scenario")
    audit.record(db, user, "scenario.delete", "scenario", s.id, f"Deleted simulation scenario '{s.name}'")
    db.delete(s)
    db.commit()
    return Response(status_code=204)


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str, request: Request, user: Writer, db: DB):
    s = get_owned(db, SimulationScenario, scenario_id, user, "Scenario")
    try:
        run = _runner(request).start({**_out(s), "org_id": s.org_id}, user.email)
    except SimulationError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    audit.record(db, user, "scenario.run", "scenario", s.id, f"Started simulation scenario '{s.name}'")
    db.commit()
    return run.as_dict()


@router.post("/stop")
def stop(factory_id: str, request: Request, user: Writer, db: DB):
    get_owned(db, Factory, factory_id, user, "Factory")
    run = _runner(request).stop(factory_id)
    return run.as_dict() if run else {"done": True}


@router.get("/status")
def run_status(factory_id: str, request: Request, user: CurrentUser, db: DB):
    get_owned(db, Factory, factory_id, user, "Factory")
    run = _runner(request).runs.get(factory_id)
    return run.as_dict() if run else None


class InjectIn(BaseModel):
    device_id: str
    action: Literal["set", "offline", "restore"]
    point: str | None = None
    value: Any = None
    duration_s: float = Field(default=60, ge=1, le=3600)


@router.post("/inject")
def inject(body: InjectIn, request: Request, user: Writer, db: DB):
    d = get_owned(db, Device, body.device_id, user, "Device")
    _check_devices(db, user, d.factory_id, [Step(**body.model_dump())])
    try:
        msg = apply_step(_runner(request).runtime, user.org_id, body.model_dump())
    except SimulationError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    audit.record(db, user, "simulation.inject", "device", d.id, f"Simulation: {msg}")
    db.commit()
    return {"ok": True, "message": msg}
