from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Literal

import pandas as pd


Mode = Literal["premium", "prices"]


@dataclass
class Trade:
    direction: str  # buy_ah or sell_ah
    entry_date: str
    entry_index: int
    entry_premium_pct: float
    entry_equity: float

    exit_date: Optional[str] = None
    exit_index: Optional[int] = None
    exit_premium_pct: Optional[float] = None
    pnl_pct: Optional[float] = None
    holding_days: Optional[int] = None

    def close(self, exit_date: str, exit_index: int, exit_premium: float, exit_equity: float) -> None:
        self.exit_date = exit_date
        self.exit_index = exit_index
        self.exit_premium_pct = exit_premium
        self.holding_days = exit_index - self.entry_index
        self.pnl_pct = (exit_equity / self.entry_equity - 1.0) * 100.0

    def to_dict(self) -> Dict:
        return {
            "direction": self.direction,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "entry_premium_pct": self.entry_premium_pct,
            "exit_premium_pct": self.exit_premium_pct,
            "pnl_pct": self.pnl_pct,
            "holding_days": self.holding_days,
        }


def _run_backtest_core(
    df: pd.DataFrame,
    lookback: int,
    entry_z: float,
    exit_z: float,
    round_trip_cost_pct: float,
    mode: Mode,
) -> Dict:
    if df is None or df.empty:
        return {"metrics": {"trades": 0}, "equity_curve": [], "trades": []}

    if "date" not in df.columns or "premium_pct" not in df.columns:
        raise ValueError("df must contain date and premium_pct")

    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date").reset_index(drop=True)

    premium = pd.to_numeric(data["premium_pct"], errors="coerce")
    mean = premium.rolling(window=lookback).mean()
    std = premium.rolling(window=lookback).std()
    z = (premium - mean) / std

    equity = 1.0
    equity_curve: List[Dict] = []

    pos = 0  # 0 flat, 1 buy_ah, -1 sell_ah
    current_trade: Optional[Trade] = None
    trades: List[Trade] = []

    half_cost = (round_trip_cost_pct / 100.0) / 2.0

    def apply_cost() -> None:
        nonlocal equity
        equity *= (1.0 - half_cost)

    for i in range(len(data)):
        dt = data.loc[i, "date"]
        dt_str = dt.strftime("%Y-%m-%d")

        zi = z.iloc[i]

        # Settle yesterday's position first. Missing z only blocks new trades,
        # not already-observable returns on a still-held position.
        day_ret = 0.0
        if pos != 0 and i > 0:
            if mode == "premium":
                prev_p = premium.iloc[i - 1]
                curr_p = premium.iloc[i]
                if pd.notna(prev_p) and pd.notna(curr_p):
                    day_ret = (pos * float(curr_p - prev_p)) / 100.0
            else:
                a_ret = float(data.loc[i, "a_ret"]) if not pd.isna(data.loc[i, "a_ret"]) else 0.0
                h_ret = float(data.loc[i, "h_ret"]) if not pd.isna(data.loc[i, "h_ret"]) else 0.0
                day_ret = (a_ret - h_ret) if pos == 1 else (-a_ret + h_ret)

        equity *= (1.0 + day_ret)

        if pd.isna(zi):
            equity_curve.append({"date": dt_str, "equity": equity})
            continue

        zi_f = float(zi)

        # Exit
        if pos != 0 and abs(zi_f) <= exit_z:
            apply_cost()
            if current_trade is not None:
                current_trade.close(
                    exit_date=dt_str,
                    exit_index=i,
                    exit_premium=float(premium.iloc[i]),
                    exit_equity=equity,
                )
                trades.append(current_trade)

            pos = 0
            current_trade = None

        # Entry. Record equity before the entry cost so round-trip fees
        # are included in trade pnl.
        if pos == 0:
            if zi_f <= -entry_z:
                pos = 1
                entry_equity = equity
                apply_cost()
                current_trade = Trade(
                    direction="buy_ah",
                    entry_date=dt_str,
                    entry_index=i,
                    entry_premium_pct=float(premium.iloc[i]),
                    entry_equity=entry_equity,
                )
            elif zi_f >= entry_z:
                pos = -1
                entry_equity = equity
                apply_cost()
                current_trade = Trade(
                    direction="sell_ah",
                    entry_date=dt_str,
                    entry_index=i,
                    entry_premium_pct=float(premium.iloc[i]),
                    entry_equity=entry_equity,
                )

        equity_curve.append({"date": dt_str, "equity": equity})

    # Force close any open trade at the end.
    if pos != 0 and current_trade is not None:
        apply_cost()
        last_i = len(data) - 1
        last_dt = data.loc[last_i, "date"].strftime("%Y-%m-%d")
        current_trade.close(
            exit_date=last_dt,
            exit_index=last_i,
            exit_premium=float(premium.iloc[last_i]),
            exit_equity=equity,
        )
        trades.append(current_trade)

    metrics = {
        "trades": len(trades),
        "total_return_pct": (equity - 1.0) * 100.0,
        "win_rate": (sum(1 for t in trades if (t.pnl_pct or 0) > 0) / len(trades)) if trades else 0.0,
    }

    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": [t.to_dict() for t in trades],
        "parameters": {
            "lookback": lookback,
            "entry_z": entry_z,
            "exit_z": exit_z,
            "round_trip_cost_pct": round_trip_cost_pct,
            "mode": mode,
        },
    }


def run_backtest_from_price_dfs(
    a_df: pd.DataFrame,
    h_df: pd.DataFrame,
    hkd_cny: float,
    lookback: int,
    entry_z: float,
    exit_z: float,
    round_trip_cost_pct: float,
) -> Dict:
    """Backtest pair trade using A/H close prices."""
    if a_df is None or h_df is None or a_df.empty or h_df.empty:
        return {"metrics": {"trades": 0}, "equity_curve": [], "trades": []}

    for col in ("date", "close"):
        if col not in a_df.columns or col not in h_df.columns:
            raise ValueError("a_df and h_df must contain date and close")

    aa = a_df[["date", "close"]].copy().rename(columns={"close": "a_close"})
    hh = h_df[["date", "close"]].copy().rename(columns={"close": "h_close"})
    aa["date"] = pd.to_datetime(aa["date"])
    hh["date"] = pd.to_datetime(hh["date"])

    data = pd.merge(aa, hh, on="date", how="inner").sort_values("date").reset_index(drop=True)
    if data.empty:
        return {"metrics": {"trades": 0}, "equity_curve": [], "trades": []}

    data["premium_pct"] = (data["a_close"] / (data["h_close"] * float(hkd_cny)) - 1.0) * 100.0
    data["a_ret"] = data["a_close"].pct_change()
    data["h_ret"] = data["h_close"].pct_change()

    return _run_backtest_core(
        df=data[["date", "premium_pct", "a_ret", "h_ret"]],
        lookback=lookback,
        entry_z=entry_z,
        exit_z=exit_z,
        round_trip_cost_pct=round_trip_cost_pct,
        mode="prices",
    )


def run_backtest_from_premium_df(
    df: pd.DataFrame,
    lookback: int,
    entry_z: float,
    exit_z: float,
    round_trip_cost_pct: float,
) -> Dict:
    """Backtest pair trading using premium mean reversion (proxy PnL)."""
    return _run_backtest_core(
        df=df[["date", "premium_pct"]].copy(),
        lookback=lookback,
        entry_z=entry_z,
        exit_z=exit_z,
        round_trip_cost_pct=round_trip_cost_pct,
        mode="premium",
    )
