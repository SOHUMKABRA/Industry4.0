"""Online backup of the platform database + uploaded models (keeps the newest N).

SQLite: uses the online backup API (safe while the platform is running).
PostgreSQL: use pg_dump instead (see DEPLOYMENT.md).
"""

import os
import sqlite3
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("TWIN_DB", ROOT / "backend" / "data" / "twin.db"))
MODELS = Path(os.environ.get("MODEL_STORAGE_DIR", ROOT / "backend" / "data" / "models"))
OUT = Path(os.environ.get("BACKUP_DIR", ROOT / "backups"))
KEEP = int(os.environ.get("BACKUP_KEEP", "14"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    snap = OUT / f"twin-{stamp}.db"
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(snap)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    archive = OUT / f"twin-{stamp}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(snap, arcname="twin.db")
        if MODELS.exists():
            tar.add(MODELS, arcname="models")
    snap.unlink()
    for old in sorted(OUT.glob("twin-*.tar.gz"))[:-KEEP]:
        old.unlink()
    print(f"backup written: {archive} ({archive.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
