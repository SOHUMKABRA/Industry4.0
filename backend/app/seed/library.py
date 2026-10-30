import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssetType
from app.schemas.assets import AssetTypeIn

LIBRARY_PATH = Path(__file__).with_name("standard_types.json")


def install_standard_library(db: Session, org_id: str) -> int:
    """Copy the standard asset-type templates into an organization.

    Types are owned by the org afterwards and fully editable; the platform
    code never refers to these keys.
    """
    existing = set(db.scalars(select(AssetType.key).where(AssetType.org_id == org_id)))
    added = 0
    for raw in json.loads(LIBRARY_PATH.read_text()):
        spec = AssetTypeIn.model_validate(raw)
        if spec.key in existing:
            continue
        db.add(AssetType(org_id=org_id, **spec.model_dump(mode="json")))
        added += 1
    return added
