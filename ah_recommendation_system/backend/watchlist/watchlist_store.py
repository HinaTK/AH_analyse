from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ah_recommendation_system.backend.data.ah_stock_list import (
    get_ah_pairs,
    get_stock_name,
)


_A_CODE_RE = re.compile(r"\d{6}\.(SH|SZ)$", re.IGNORECASE)


def _normalize_symbol_code(code: str) -> str:
    value = (code or "").strip().upper()
    if not value:
        return ""

    if _A_CODE_RE.match(value):
        return value

    match = re.search(r"(\d{6})", value)
    if not match:
        return ""

    digits = match.group(1)
    market = "SH" if digits.startswith("6") else "SZ"
    return f"{digits}.{market}"


class WatchlistStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = root_dir or (
            Path(__file__).resolve().parents[1] / "data" / "watchlist"
        )
        self._file_path = self._root_dir / "watchlist.json"

    def add_symbol(self, a_code: str) -> None:
        normalized = _normalize_symbol_code(a_code)
        snapshot = self._build_symbol_snapshot(normalized)
        if not snapshot:
            return

        payload = self._read_payload()
        symbols = payload["symbols"]
        if any(symbol["a_code"] == normalized for symbol in symbols):
            return

        symbols.append(snapshot)
        self._write_payload(payload)

    def remove_symbol(self, a_code: str) -> None:
        normalized = _normalize_symbol_code(a_code)
        if not normalized:
            return

        payload = self._read_payload()
        symbols = payload["symbols"]
        updated_symbols = [
            symbol for symbol in symbols if symbol["a_code"] != normalized
        ]
        if updated_symbols == symbols:
            return

        payload["symbols"] = updated_symbols
        self._write_payload(payload)

    def list_symbols(self) -> List[Dict[str, str]]:
        return [symbol.copy() for symbol in self._read_payload()["symbols"]]

    def _read_payload(self) -> Dict[str, List[Dict[str, str]]]:
        if not self._file_path.exists():
            return {"symbols": []}

        try:
            raw_payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError("Failed to read watchlist payload") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid watchlist payload") from exc

        if not isinstance(raw_payload, dict):
            raise ValueError("Watchlist payload must be an object")

        raw_symbols = raw_payload.get("symbols")
        if not isinstance(raw_symbols, list):
            raise ValueError("Watchlist symbols must be a list")

        symbols = [self._coerce_symbol_entry(entry) for entry in raw_symbols]
        payload = {"symbols": symbols}
        if any(isinstance(entry, str) for entry in raw_symbols):
            self._write_payload(payload)

        return payload

    def _write_payload(self, payload: Dict[str, List[Dict[str, str]]]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_path.write_text(
            json.dumps(
                {"symbols": payload.get("symbols", [])}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

    def _coerce_symbol_entry(self, entry: Any) -> Dict[str, str]:
        if isinstance(entry, str):
            normalized = _normalize_symbol_code(entry)
            if not normalized:
                raise ValueError("Watchlist symbol entry is invalid")
            return self._build_legacy_snapshot(normalized)

        if not isinstance(entry, dict):
            raise ValueError("Watchlist symbol entry must be a string or object")

        snapshot = self._build_complete_snapshot(
            entry.get("a_code", ""),
            entry.get("h_code", ""),
            entry.get("name", ""),
        )
        if not snapshot:
            raise ValueError("Watchlist symbol entry has invalid fields")

        return snapshot

    def _build_symbol_snapshot(self, a_code: str) -> Dict[str, str] | None:
        if not a_code:
            return None

        h_code = get_ah_pairs().get(a_code)
        if not h_code:
            return None

        return self._build_complete_snapshot(a_code, h_code, get_stock_name(a_code))

    def _build_legacy_snapshot(self, a_code: str) -> Dict[str, str]:
        snapshot = self._build_complete_snapshot(
            a_code,
            get_ah_pairs().get(a_code, ""),
            get_stock_name(a_code),
        )
        if not snapshot:
            raise ValueError("Legacy watchlist entry cannot be migrated")

        return snapshot

    def _build_complete_snapshot(
        self, a_code: Any, h_code: Any, name: Any
    ) -> Dict[str, str] | None:
        normalized_a_code = _normalize_symbol_code(str(a_code))
        normalized_h_code = h_code.strip() if isinstance(h_code, str) else ""
        normalized_name = name.strip() if isinstance(name, str) else ""
        if not normalized_a_code or not normalized_h_code or not normalized_name:
            return None

        return {
            "a_code": normalized_a_code,
            "h_code": normalized_h_code,
            "name": normalized_name,
        }
