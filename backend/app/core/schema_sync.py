"""Additive schema migration.

`create_all` creates missing tables but never alters existing ones. This adds
columns that exist in the models but not in the database (ALTER TABLE ... ADD
COLUMN), so upgrades keep existing data. It never drops or rewrites columns;
destructive changes need a hand-written migration.
"""

import json
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.db import Base

log = logging.getLogger("twin.schema")


def _default_sql(col) -> str | None:
    d = col.default
    if d is None:
        return None
    arg = d.arg
    if callable(arg):
        try:
            arg = arg(None)
        except TypeError:
            arg = arg()
    if isinstance(arg, bool):
        return "1" if arg else "0"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, (list, dict)):
        return "'" + json.dumps(arg).replace("'", "''") + "'"
    if isinstance(arg, str):
        return "'" + arg.replace("'", "''") + "'"
    return None


def sync_columns(engine: Engine) -> list[str]:
    added: list[str] = []
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = _default_sql(col)
                stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'
                if default is not None:
                    stmt += f" DEFAULT {default}"
                conn.execute(text(stmt))
                added.append(f"{table.name}.{col.name}")
    for a in added:
        log.info("schema: added column %s", a)
    return added
