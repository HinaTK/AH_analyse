"""Unadjusted execution prices; intentionally independent of mock price mode."""
from __future__ import annotations

from threading import RLock

import pandas as pd


_SESSION_LOCK = RLock()


class ExecutionDataProvider:
    """BaoStock OHLCV/preclose provider with an explicitly identified benchmark.

    No adjusted-price or synthetic fallback is allowed for execution checks.
    Missing provider coverage is an unavailable verification, not a fill.
    """

    benchmark_code = "sh.000300"

    def __init__(self, api=None):
        self.api = api

    def get_stock_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        symbol = str(code).split(".")[0]
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("expected six-digit A-share code")
        if symbol.startswith(("8", "43", "92")):
            raise ValueError("BaoStock BSE execution coverage unavailable")
        exchange = "sh" if symbol.startswith("6") else "sz"
        return self._query(f"{exchange}.{symbol}", start, end, stock=True)

    def get_benchmark_bars(self, start: str, end: str) -> pd.DataFrame:
        return self._query(self.benchmark_code, start, end, stock=False)

    def get_signal_bars(self, code: str, start: str, end: str) -> pd.DataFrame:
        """Forward-adjusted history for relative returns only, never fills."""
        if len(code) != 6 or not code.isdigit() or code.startswith(("8", "43", "92")):
            raise ValueError("signal_provider_unsupported_symbol")
        return self._query(("sh." if code.startswith("6") else "sz.") + code, start, end,
                           stock=True, adjustment="2")

    def _query(self, code: str, start: str, end: str, *, stock: bool, adjustment: str = "3") -> pd.DataFrame:
        api = self.api
        if api is None:
            import baostock as api
        fields = "date,open,high,low,close,preclose,volume"
        if stock:
            fields += ",tradestatus,isST"
        with _SESSION_LOCK:
            login = api.login()
            if str(login.error_code) != "0":
                raise RuntimeError("execution_provider_login_failed")
            try:
                result = api.query_history_k_data_plus(
                    code, fields, start_date=pd.Timestamp(start).strftime("%Y-%m-%d"),
                    end_date=pd.Timestamp(end).strftime("%Y-%m-%d"), frequency="d", adjustflag=adjustment,
                )
                if str(result.error_code) != "0":
                    raise RuntimeError(f"execution_provider_query_failed:{result.error_code}")
                rows = []
                while result.next():
                    rows.append(result.get_row_data())
                if str(result.error_code) != "0":
                    raise RuntimeError("execution_provider_incomplete_response")
                frame = pd.DataFrame(rows, columns=result.fields).rename(columns={"preclose": "prev_close"})
            finally:
                api.logout()
        for field in ("open", "high", "low", "close", "prev_close", "volume"):
            if field in frame:
                frame[field] = pd.to_numeric(frame[field], errors="coerce")
        if "tradestatus" in frame:
            frame.loc[frame["tradestatus"].astype(str) == "0", "volume"] = 0
        if "isST" in frame:
            frame["is_st"] = frame["isST"].astype(str) == "1"
        frame.attrs.update(source="baostock", adjustment="none" if adjustment == "3" else "forward", symbol=code)
        return frame
