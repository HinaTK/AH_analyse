"""Conservative A-share forward fills, separate from recommendation returns.

Inputs must be complete exchange sessions and unadjusted prices, including the
exchange previous close (not blindly a shifted adjusted close). Costs are
explicit assumptions; defaults are illustrative, not a broker tariff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ExecutionCosts:
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    sell_tax: float = 0.0005
    slippage: float = 0.001
    minimum_fee: float = 5.0

    def __post_init__(self) -> None:
        if any(not isfinite(float(x)) or float(x) < 0 or float(x) > .1 for x in (self.buy_fee, self.sell_fee, self.sell_tax, self.slippage)):
            raise ValueError("fees and slippage must be finite values in [0, .1]")
        if not isfinite(float(self.minimum_fee)) or self.minimum_fee < 0:
            raise ValueError("minimum_fee must be finite and non-negative")


def _limit(code: str, row: pd.Series) -> float:
    code = str(code).split(".")[0]
    if code.startswith(("300", "301", "688", "689")):
        return .20
    if code.startswith(("8", "43", "92")):
        return .30
    if str(row.get("name", "")).upper().startswith(("ST", "*ST")) or row.get("is_st", False) == True:
        return .05
    return .10


def _finite(row: Any, names: tuple[str, ...]) -> bool:
    try:
        return all(isfinite(float(row[name])) for name in names)
    except (KeyError, TypeError, ValueError):
        return False


def _fee(value: float, rate: float, minimum: float) -> float:
    return max(minimum, value * rate) if value else 0.0


def _prepare(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty or "date" not in data:
        raise ValueError("price_data_missing")
    result = data.copy()
    dates = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("invalid_or_duplicate_dates")
    result["date"] = dates
    return result.set_index("date").sort_index()


def _limit_price(code: str, row: pd.Series, side: str) -> float:
    field = "limit_up" if side == "buy" else "limit_down"
    if _finite(row, (field,)) and float(row[field]) > 0:
        return float(row[field])
    rate = _limit(code, row)
    multiplier = Decimal("1") + Decimal(str(rate)) * (1 if side == "buy" else -1)
    return float((Decimal(str(row["prev_close"])) * multiplier).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def _blocked_reason(row: pd.Series, code: str, side: str) -> str | None:
    price_field = "open" if side == "buy" else "close"
    if not _finite(row, (price_field, "volume", "prev_close")):
        return "data_missing"
    if float(row[price_field]) <= 0 or float(row["prev_close"]) <= 0:
        return "data_missing"
    if float(row["volume"]) <= 0:
        return "suspended"
    if row.get("no_price_limit", False) == True:
        return None
    limit = _limit_price(code, row, side)
    price = float(row[price_field])
    if side == "buy" and price >= limit - 1e-8:
        return "limit_up"
    if side == "sell" and price <= limit + 1e-8:
        return "limit_down"
    return None


def simulate_forward_trade(*, bars: pd.DataFrame, benchmark: pd.DataFrame, code: str,
                           signal_date: str, horizon: int = 5,
                           costs: ExecutionCosts | None = None,
                           quantity: int = 1000) -> dict[str, Any]:
    """Buy next session open, sell H sessions later at close, subject to rules.

    Benchmark dates define sessions; missing individual bars cannot shift entry
    or shorten holding periods. Unfilled entry is cancelled; suspended/limited
    exits wait, never force-liquidate. Benchmark return uses the same dates and
    open/close convention. This fixed-horizon test does not simulate WATCH
    triggers, target/stop orders or a capital-constrained portfolio.
    """
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be at least one session")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity % 100:
        raise ValueError("quantity must be a positive multiple of 100 shares")
    costs = costs or ExecutionCosts()
    if str(code).startswith(("688", "689")) and quantity < 200:
        raise ValueError("STAR opening order requires at least 200 shares")
    for data in (bars, benchmark):
        if data is not None and ("mock" in str(data.attrs.get("source", "")).lower()
                                 or data.attrs.get("adjustment") not in {None, "none"}):
            return {"status": "unavailable", "reason": "non_execution_price_provenance"}
    try:
        frame, bench = _prepare(bars), _prepare(benchmark)
    except ValueError as exc:
        return {"status": "unavailable", "reason": str(exc)}
    signal = pd.Timestamp(signal_date)
    sessions = bench.index[bench.index > signal]
    if not len(sessions):
        return {"status": "pending", "reason": "entry_session_unavailable"}
    entry_date = sessions[0]
    if entry_date not in frame.index:
        return {"status": "unfilled", "reason": "entry_data_missing"}
    entry = frame.loc[entry_date]
    reason = _blocked_reason(entry, code, "buy")
    if reason:
        return {"status": "unfilled", "reason": "entry_" + reason}
    if len(sessions) <= horizon:
        return {"status": "pending", "reason": "horizon_unmatured"}
    for delay, exit_date in enumerate(sessions[horizon:]):
        if exit_date not in frame.index:
            return {"status": "unavailable", "reason": "exit_data_missing"}
        exit_row = frame.loc[exit_date]
        reason = _blocked_reason(exit_row, code, "sell")
        if reason == "data_missing":
            return {"status": "unavailable", "reason": "exit_data_missing"}
        if reason is None:
            break
    else:
        return {"status": "pending", "reason": "exit_unavailable"}

    benchmark_entry, benchmark_exit = bench.loc[entry_date], bench.loc[exit_date]
    if (not _finite(benchmark_entry, ("open",)) or not _finite(benchmark_exit, ("close",))
            or float(benchmark_entry["open"]) <= 0 or float(benchmark_exit["close"]) <= 0):
        return {"status": "unavailable", "reason": "benchmark_data_missing"}
    entry_price = float(entry["open"]) * (1 + costs.slippage)
    exit_price = float(exit_row["close"]) * (1 - costs.slippage)
    buy_value, sell_value = entry_price * quantity, exit_price * quantity
    entry_fee = _fee(buy_value, costs.buy_fee, costs.minimum_fee)
    exit_fee = _fee(sell_value, costs.sell_fee, costs.minimum_fee) + sell_value * costs.sell_tax
    net_return = ((sell_value - exit_fee) / (buy_value + entry_fee) - 1) * 100
    benchmark_return = (float(benchmark_exit["close"]) / float(benchmark_entry["open"]) - 1) * 100
    marks, benchmark_marks = {}, {}
    holding_sessions = sessions[(sessions >= entry_date) & (sessions <= exit_date)]
    previous_close = None
    for date in holding_sessions:
        if date not in frame.index or not _finite(frame.loc[date], ("close", "prev_close")):
            return {"status": "unavailable", "reason": "holding_mark_missing"}
        row = frame.loc[date]
        if previous_close is not None and abs(float(row["prev_close"]) - previous_close) > .011:
            return {"status": "unavailable", "reason": "corporate_action_requires_total_return_accounting"}
        previous_close = float(row["close"])
        if previous_close <= 0 or not _finite(bench.loc[date], ("close",)) or float(bench.loc[date]["close"]) <= 0:
            return {"status": "unavailable", "reason": "holding_mark_invalid"}
        key = date.strftime("%Y-%m-%d")
        marks[key] = previous_close * quantity / (buy_value + entry_fee)
        benchmark_marks[key] = float(bench.loc[date]["close"]) / float(benchmark_entry["open"])
    marks[exit_date.strftime("%Y-%m-%d")] = (sell_value - exit_fee) / (buy_value + entry_fee)
    return {
        "status": "filled", "methodology": "next_open_fixed_horizon_v1",
        "entry_date": entry_date.strftime("%Y-%m-%d"), "exit_date": exit_date.strftime("%Y-%m-%d"),
        "exit_delay_sessions": delay, "entry_price": entry_price, "exit_price": exit_price,
        "quantity": quantity, "entry_cost": entry_fee, "exit_cost": exit_fee,
        "net_return_pct": net_return, "benchmark_return_pct": benchmark_return,
        "excess_return_pct": net_return - benchmark_return,
        "daily_equity": marks, "daily_benchmark": benchmark_marks,
        "invested_amount": buy_value + entry_fee, "exit_amount": sell_value - exit_fee,
        "cost_assumptions": asdict(costs),
    }
