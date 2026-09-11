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
    nested = {key for row in data for key, value in row.items() if isinstance(value, (dict, list))}
    data = [{**row, **{key: json.dumps(row.get(key), ensure_ascii=False, default=str) for key in nested},
             "_json_fields": json.dumps(sorted(nested))} for row in data]
    if data:
        temporary = parquet.with_suffix(".parquet.tmp")
        pl.DataFrame(data, infer_schema_length=None).write_parquet(temporary)
        temporary.replace(parquet)
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


def load_last_snapshot(root: Path, max_age_seconds: float | None = None) -> list[Dict[str, Any]]:
    """Load the newest persisted snapshot.

    Without a freshness window every row stays an explicit stale last-good
    snapshot.  When max_age_seconds is set and the parquet mtime is still
    inside that window, the same file can be reused as a live disk cache.
    """
    import time

    import polars as pl  # type: ignore

    target = Path(root) / "data" / "market_store"
    snapshots = sorted(target.glob("a_share_spot_*.parquet"), reverse=True)
    if not snapshots:
        return []
    parquet = snapshots[0]
    rows = pl.read_parquet(parquet).to_dicts()
    for row in rows:
        for key in json.loads(row.pop("_json_fields", "[]") or "[]"):
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
    # Never relabel synthetic quotes as live just because the file is new.
    rows = [row for row in rows if not any(
        "mock" in str(row.get(key) or "").lower()
        for key in ("source", "original_source", "quote_source")
    ) and not row.get("is_mock")]
    age_seconds = max(0.0, time.time() - parquet.stat().st_mtime)
    fresh_file = max_age_seconds is not None and 0 <= time.time() - parquet.stat().st_mtime <= float(max_age_seconds)
    stale_batch = any(row.get("stale") or row.get("source") == "last_good_snapshot" for row in rows)
    stale = not fresh_file or stale_batch
    return [dict(row, stale=stale,
                 original_source=row.get("original_source") or row.get("source") or "unknown",
                 cache_age_seconds=age_seconds,
                 source="last_good_snapshot" if stale else "disk_cache") for row in rows]
