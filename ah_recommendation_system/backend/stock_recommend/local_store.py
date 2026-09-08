"""Parquet snapshots with a DuckDB catalog for reproducible screening."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


def persist_snapshot(rows: Iterable[Dict[str, Any]], root: Path, *, as_of: str) -> Dict[str, str]:
    """Persist a normalized market snapshot and expose it through DuckDB.

    The imports are lazy so existing AH-only commands remain usable before the
    new optional data dependencies are installed.
    """
    import duckdb  # type: ignore
    import polars as pl  # type: ignore

    target = root / "data" / "market_store"
    target.mkdir(parents=True, exist_ok=True)
    parquet = target / f"a_share_spot_{as_of.replace('-', '')}.parquet"
    database = target / "market.duckdb"
    data = list(rows)
    if data:
        pl.DataFrame(data).write_parquet(parquet)
    else:
        pl.DataFrame({"code": [], "name": []}).write_parquet(parquet)
    con = duckdb.connect(str(database))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS snapshot_catalog "
            "(as_of VARCHAR PRIMARY KEY, parquet_path VARCHAR, rows BIGINT, created_at TIMESTAMP)"
        )
        con.execute(
            "INSERT OR REPLACE INTO snapshot_catalog VALUES (?, ?, ?, ?)",
            [as_of, str(parquet), len(data), datetime.now()],
        )
        con.execute(
            f"CREATE OR REPLACE VIEW latest_a_share_spot AS SELECT * FROM read_parquet('{parquet.as_posix()}')"
        )
    finally:
        con.close()
    return {"parquet_path": str(parquet), "database_path": str(database)}


def load_last_snapshot(root: Path) -> list[Dict[str, Any]]:
    """Load the newest persisted snapshot as explicitly stale fallback data."""
    import polars as pl  # type: ignore

    target = Path(root) / "data" / "market_store"
    snapshots = sorted(target.glob("a_share_spot_*.parquet"), reverse=True)
    if not snapshots:
        return []
    rows = pl.read_parquet(snapshots[0]).to_dicts()
    return [dict(row, stale=True, source="last_good_snapshot") for row in rows]
