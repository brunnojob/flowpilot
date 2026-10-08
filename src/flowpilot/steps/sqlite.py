"""``sqlite`` — run SQL against a SQLite database file."""

from __future__ import annotations

import sqlite3
from typing import Any

from flowpilot.context import StepContext
from flowpilot.errors import StepConfigError
from flowpilot.registry import step


@step("sqlite")
def sqlite(
    ctx: StepContext,
    database: str,
    query: str,
    params: list[Any] | dict[str, Any] | None = None,
    many: list[Any] | None = None,
    script: bool = False,
) -> dict[str, Any]:
    """Execute ``query`` and return rows (as dicts), ``rowcount`` and ``lastrowid``.

    Use ``params`` for a single statement, ``many`` for ``executemany`` and
    ``script: true`` to run several statements (e.g. ``CREATE TABLE`` + index).
    """
    path = ctx.resolve_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            if script:
                conn.executescript(query)
                return {"rows": [], "rowcount": -1, "lastrowid": None}
            if many is not None:
                cur = conn.executemany(query, many)
            else:
                cur = conn.execute(query, params or ())
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            return {"rows": rows, "rowcount": cur.rowcount, "lastrowid": cur.lastrowid}
    except sqlite3.Error as exc:
        raise StepConfigError(f"sqlite: {exc}") from exc
    finally:
        conn.close()
