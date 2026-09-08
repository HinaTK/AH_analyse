"""Small optional client for HiThink Financial-API free capabilities."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


DEFAULT_BASE_URL = "https://fuyao.aicubes.cn"


def _thscode(code: str) -> str:
    raw = str(code).split(".")[0].zfill(6)
    return f"{raw}.SH" if raw.startswith(("5", "6", "9")) else f"{raw}.SZ"


def resolve_api_key(explicit: Optional[str] = None) -> str:
    if explicit is not None:
        return explicit.strip()
    value = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    if value:
        return value
    configured = os.environ.get("HITHINK_FINANCE_API_KEY_FILE", "").strip()
    paths = [Path(configured)] if configured else []
    paths.append(Path.home() / ".hithink-finance" / "api_key")
    paths.append(Path(r"C:\Users\Administrator\Downloads\hithink_key.txt"))
    for path in paths:
        try:
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            continue
    return ""


class HithinkClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL, timeout: float = 12.0):
        self.api_key = resolve_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.get(
            f"{self.base_url}{path}", params=params,
            headers={"X-api-key": self.api_key, "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Financial-API code={payload.get('code')}: {payload.get('message', '')}")
        return payload.get("data") or {}

    def probe(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"available": False, "reason": "missing_api_key", "capabilities": {}}
        capabilities: Dict[str, bool] = {}
        errors: Dict[str, str] = {}
        probes = {
            "snapshot": ("/api/a-share/prices/snapshot", {"thscodes": "600519.SH"}),
            "valuations": ("/api/a-share/valuations/snapshot", {"thscodes": "600519.SH"}),
            "dragon_tiger": ("/api/a-share/special-data/dragon-tiger-list", {"board_type": "org"}),
        }
        for name, (path, params) in probes.items():
            try:
                self._get(path, params)
                capabilities[name] = True
            except Exception as exc:
                capabilities[name] = False
                errors[name] = str(exc)
        return {"available": any(capabilities.values()), "capabilities": capabilities, "errors": errors}

    def market_snapshot(self, *, limit: int = 6000) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        items: List[Dict[str, Any]] = []
        offset = 0
        page_size = min(1000, max(1, limit))
        while len(items) < limit:
            data = self._get("/api/a-share/prices/snapshot", {"limit": page_size, "offset": offset})
            page = data.get("item") or []
            timestamp = data.get("timestamp")
            items.extend(dict(item, observed_at=item.get("observed_at") or timestamp) for item in page)
            if len(page) < page_size:
                break
            offset += page_size
        return [self._normalize_snapshot(item) for item in items[:limit]]

    def valuations(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        tokens = [_thscode(code) for code in codes]
        result: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(tokens), 100):
            data = self._get("/api/a-share/valuations/snapshot", {"thscodes": ",".join(tokens[start:start + 100])})
            for item in data.get("item") or []:
                code = str(item.get("thscode") or "").split(".")[0]
                result[code] = item
        return result

    def ticker_names(self) -> Dict[str, str]:
        """Return the complete A-share code-to-name map from official metadata."""
        result: Dict[str, str] = {}
        offset = 0
        page_size = 1000
        while True:
            data = self._get(
                "/api/meta/tickers/list",
                {
                    "exchange": "SH,SZ,BJ",
                    "asset_type": "a-share",
                    "limit": page_size,
                    "offset": offset,
                },
            )
            page = data.get("item") or data.get("stock_items") or []
            for item in page:
                code = str(item.get("ticker") or item.get("thscode") or "").split(".")[0].zfill(6)
                if len(code) == 6 and item.get("name"):
                    result[code] = str(item["name"])
            if len(page) < page_size:
                break
            offset += page_size
        return result

    def auction_metrics(self, codes: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch market-cap metadata exposed by the free auction endpoint."""
        tokens = [_thscode(code) for code in codes]
        result: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(tokens), 100):
            data = self._get(
                "/api/a-share/auction/snapshot",
                {"thscodes": ",".join(tokens[start : start + 100]), "stage": "final"},
            )
            for item in data.get("item") or data.get("stock_items") or []:
                code = str(item.get("ticker") or item.get("thscode") or "").split(".")[0].zfill(6)
                result[code] = item
        return result

    def industry_catalog(self) -> List[Dict[str, Any]]:
        data = self._get("/api/a-share-index/catalog/ths-index-list", {"tag": "industry"})
        return list(data.get("item") or [])

    def index_constituents(self, thscode: str) -> List[Dict[str, Any]]:
        data = self._get("/api/a-share-index/constituents/ths-stock-list", {"thscode": thscode})
        return list(data.get("item") or [])

    def focus_universe(self, keywords: Iterable[str]) -> Dict[str, List[Dict[str, str]]]:
        """Resolve configured themes to current THS industry constituents."""
        catalogs = self.industry_catalog()
        result: Dict[str, List[Dict[str, str]]] = {}
        for keyword in keywords:
            text = str(keyword).strip()
            matches = [item for item in catalogs if text and text in str(item.get("name") or "")]
            members: Dict[str, Dict[str, str]] = {}
            for industry in matches[:5]:
                for item in self.index_constituents(str(industry.get("thscode") or "")):
                    code = str(item.get("ticker") or item.get("thscode") or "").split(".")[0].zfill(6)
                    if len(code) == 6:
                        members[code] = {"code": code, "name": str(item.get("name") or code)}
            if members:
                result[text] = list(members.values())
        return result

    def enrich_snapshot(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge names, current valuation and market-cap fields into price rows."""
        result = [dict(row) for row in rows]
        codes = [str(row.get("code") or "").zfill(6) for row in result]
        names = self.ticker_names()
        valuations = self.valuations(codes)
        try:
            auctions = self.auction_metrics(codes)
        except Exception:
            auctions = {}
        for row in result:
            code = str(row.get("code") or "").zfill(6)
            valuation = valuations.get(code) or {}
            auction = auctions.get(code) or {}
            row["name"] = names.get(code) or auction.get("name") or row.get("name") or code
            row["pe"] = valuation.get("pe_ttm")
            row["pb"] = valuation.get("pb_mrq")
            row["market_cap"] = auction.get("float_market_cap")
            row["turnover_pct"] = auction.get("auction_turnover_pct")
        return result

    def historical(self, code: str, *, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
        """Fetch one A-share daily series; the upstream endpoint is single-symbol."""
        if not self.enabled:
            return []
        data = self._get(
            "/api/a-share/prices/historical",
            {"thscode": _thscode(code), "interval": "1d", "start": int(start_ms), "end": int(end_ms), "adjust": "forward"},
        )
        return [
            {
                **item,
                "date": item.get("date_ms"),
                "open": item.get("open_price"),
                "high": item.get("high_price"),
                "low": item.get("low_price"),
                "close": item.get("close_price"),
                "volume": item.get("volume"),
                "amount": item.get("turnover"),
            }
            for item in data.get("item") or []
        ]

    def dragon_tiger(self, *, board_type: str = "all", date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return the latest available龙虎榜 rows without assuming today's date."""
        if not self.enabled:
            return []
        data = self._get(
            "/api/a-share/special-data/dragon-tiger-list",
            {"board_type": board_type, "date": date},
        )
        return list(data.get("stock_items") or data.get("item") or [])

    @staticmethod
    def _normalize_snapshot(item: Dict[str, Any]) -> Dict[str, Any]:
        def first_present(*keys: str) -> Any:
            for key in keys:
                if item.get(key) is not None:
                    return item[key]
            return None

        code = str(item.get("thscode") or item.get("code") or "").split(".")[0]
        return {
            **item,
            "code": code.zfill(6),
            "name": item.get("name") or item.get("security_name") or code,
            "price": first_present("latest", "last_price", "price", "close"),
            "change_pct": first_present("change_pct", "price_change_ratio_pct", "pct_change"),
            "amount": first_present("amount", "turnover", "turnover_amount"),
            "volume": item.get("volume"),
            "observed_at": first_present("observed_at", "timestamp", "time"),
        }
