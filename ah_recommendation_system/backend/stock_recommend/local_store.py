"""Parquet snapshots with a DuckDB catalog for reproducible screening."""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Mapping


def quote_date_from_value(value: Any) -> str | None:
    """Extract an explicit quote date; time-only strings remain unknown."""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        except ValueError:
            return None
    try:
        numeric = float(text)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        if numeric > 1_000_000_000:
            return datetime.fromtimestamp(numeric).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return None


def persist_snapshot(
    rows: Iterable[Dict[str, Any]],
    root: Path,
    *,
    as_of: str,
    min_rows: int = 0,
) -> Dict[str, str]:
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
    if min_rows and len(data) < max(1, int(min_rows)):
        return {
            "parquet_path": str(parquet),
            "database_path": str(database),
            "skipped": "below_min_rows",
            "row_count": str(len(data)),
        }
    if parquet.exists() and len(data) < 1000:
        try:
            existing_rows = int(pl.read_parquet(parquet).height)
        except Exception:
            existing_rows = 0
        if existing_rows >= 1000 and existing_rows > len(data):
            return {"parquet_path": str(parquet), "database_path": str(database), "skipped": "thin_overwrite"}
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



def load_previous_close_snapshot(
    root: Path,
    *,
    as_of: str | None = None,
    min_rows: int = 1000,
    include_as_of: bool = False,
    min_mtime: datetime | None = None,
) -> list[Dict[str, Any]]:
    """Load the newest complete previous-close snapshot, skipping thin intraday overwrites."""
    import polars as pl  # type: ignore

    target = Path(root) / "data" / "market_store"
    cutoff = str(as_of or "").replace("-", "")
    candidates = []
    for parquet in target.glob("a_share_spot_*.parquet"):
        stamp = parquet.stem.replace("a_share_spot_", "")
        if cutoff and ((stamp > cutoff) if include_as_of else (stamp >= cutoff)):
            continue
        if min_mtime is not None and datetime.fromtimestamp(parquet.stat().st_mtime) < min_mtime:
            continue
        candidates.append((stamp, parquet))
    for _, parquet in sorted(candidates, reverse=True):
        rows = pl.read_parquet(parquet).to_dicts()
        for row in rows:
            for key in json.loads(row.pop("_json_fields", "[]") or "[]"):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
        rows = [
            row for row in rows
            if not any("mock" in str(row.get(key) or "").lower() for key in ("source", "original_source", "quote_source"))
            and not row.get("is_mock")
        ]
        if len(rows) < max(1, int(min_rows)):
            continue
        # A file's mtime proves when it was written, not which trading session
        # its quotes represent. Every row must carry the same explicit quote
        # date; a file label or a turnover threshold is not a quote date.
        row_dates = [
            quote_date_from_value(row.get("price_as_of") or row.get("quote_date") or row.get("price_date"))
            for row in rows
        ]
        quote_dates = {item for item in row_dates if item}
        if len(quote_dates) != 1 or any(item != next(iter(quote_dates)) for item in row_dates):
            continue
        original = str(rows[0].get("original_source") or rows[0].get("source") or "unknown")
        verified_date = next(iter(quote_dates), None)
        return [
            dict(
                row,
                stale=False,
                original_source=row.get("original_source") or original,
                source="previous_close",
                quote_basis="previous_close",
                price_as_of=quote_date_from_value(row.get("price_as_of") or row.get("quote_date") or row.get("price_date")) or verified_date,
            )
            for row in rows
        ]
    return []


def persist_ranking_panel(rows: Iterable[Dict[str, Any]], root: Path, *, as_of: str) -> Dict[str, str]:
    """Persist the daily full-tradable feature panel for walk-forward training."""
    import polars as pl  # type: ignore

    target = Path(root) / "data" / "stock_recommend" / "panels"
    target.mkdir(parents=True, exist_ok=True)
    parquet = target / f"ranking_panel_{as_of.replace('-', '')}.parquet"
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
    return {"parquet_path": str(parquet), "rows": len(data)}

def _industry_universe_dir(root: Path) -> Path:
    return Path(root) / "data" / "stock_recommend"


def persist_industry_universe(
    universe: Mapping[str, Iterable[Mapping[str, Any]]],
    root: Path,
    *,
    as_of: str,
) -> Dict[str, str]:
    """Persist a full-market industry catalog for previous-close and live replay."""
    target = _industry_universe_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    stamp = str(as_of or "").replace("-", "") or datetime.now().strftime("%Y%m%d")
    payload = {
        "as_of": as_of,
        "industries": {
            str(industry): [
                {"code": str(item.get("code") or "").zfill(6), "name": str(item.get("name") or item.get("code") or "")}
                for item in (members or [])
                if len(str((item or {}).get("code") or "").zfill(6)) == 6
                and str((item or {}).get("code") or "").zfill(6).isdigit()
            ]
            for industry, members in (universe or {}).items()
            if str(industry or "").strip()
        },
    }
    path = target / f"industry_universe_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    latest = target / "industry_universe_latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"path": str(path), "latest_path": str(latest), "industry_count": str(len(payload["industries"]))}


def load_industry_universe(root: Path, *, as_of: str | None = None) -> Dict[str, list[Dict[str, str]]]:
    """Load the newest industry catalog not newer than as_of, falling back to latest."""
    target = _industry_universe_dir(root)
    cutoff = str(as_of or "").replace("-", "")
    candidates = []
    for path in target.glob("industry_universe_*.json"):
        if path.name == "industry_universe_latest.json":
            continue
        stamp = path.stem.replace("industry_universe_", "")
        if cutoff and stamp > cutoff:
            continue
        candidates.append((stamp, path))
    ordered = [path for _, path in sorted(candidates, reverse=True)]
    latest = target / "industry_universe_latest.json"
    if latest.exists() and not cutoff:
        ordered.append(latest)
    elif latest.exists():
        try:
            preview = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            preview = {}
        stamp = str((preview or {}).get("as_of") or "").replace("-", "")
        if stamp and stamp <= cutoff:
            ordered.append(latest)
    for path in ordered:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        industries = payload.get("industries") if isinstance(payload, dict) else payload
        if isinstance(industries, dict) and industries:
            return {
                str(industry): [
                    {"code": str(item.get("code") or "").zfill(6), "name": str(item.get("name") or item.get("code") or "")}
                    for item in (members or [])
                    if len(str((item or {}).get("code") or "").zfill(6)) == 6
                    and str((item or {}).get("code") or "").zfill(6).isdigit()
                ]
                for industry, members in industries.items()
            }
    return {}
