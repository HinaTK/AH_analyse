"""Daily-bar features used by the evidence-based stock screener."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import pandas as pd


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def calculate_features(bars: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate auditable trend, price-volume and risk features."""
    frame = pd.DataFrame(list(bars))
    required = {"high", "low", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return {"history_days": 0, "quality_flags": ["ohlcv_missing"]}
    for column in required | {"open"}:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required)).reset_index(drop=True)
    if "date" in frame.columns:
        frame = frame.sort_values("date").reset_index(drop=True)
    days = len(frame)
    if not days:
        return {"history_days": 0, "quality_flags": ["ohlcv_invalid"]}

    close = frame["close"]
    volume = frame["volume"]
    previous_close = close.shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous_close).abs(), (frame["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    ma5 = close.rolling(5).mean().iloc[-1] if days >= 5 else None
    ma20 = close.rolling(20).mean().iloc[-1] if days >= 20 else None
    ma60 = close.rolling(60).mean().iloc[-1] if days >= 60 else None
    atr = true_range.rolling(14).mean().iloc[-1] if days >= 14 else None
    high20 = frame["high"].tail(20).max() if days >= 20 else None
    low20 = frame["low"].tail(20).min() if days >= 20 else None
    volume20 = volume.tail(20).mean() if days >= 20 else None
    returns = close.pct_change().dropna()
    delta = close.diff()
    average_gain = delta.clip(lower=0).rolling(14).mean()
    average_loss = -delta.clip(upper=0).rolling(14).mean()
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + relative_strength))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_series = ema12 - ema26
    macd_signal = macd_series.ewm(span=9, adjust=False).mean()
    volatility = returns.tail(20).std() * (252 ** 0.5) * 100 if len(returns) >= 20 else None
    rolling_peak = close.cummax()
    drawdown = (close / rolling_peak - 1.0) * 100

    def period_return(period: int) -> Optional[float]:
        if days <= period or close.iloc[-period - 1] <= 0:
            return None
        return round((close.iloc[-1] / close.iloc[-period - 1] - 1.0) * 100, 3)

    quality_flags = []
    if days < 60:
        quality_flags.append("history_lt_60")
    if days < 120:
        quality_flags.append("history_lt_120")
    latest = float(close.iloc[-1])
    return {
        "history_days": days,
        "ma5": _number(ma5),
        "ma20": _number(ma20),
        "ma60": _number(ma60),
        "above_ma20": bool(ma20 is not None and latest > float(ma20)),
        "above_ma60": bool(ma60 is not None and latest > float(ma60)),
        "bullish_alignment": bool(ma5 is not None and ma20 is not None and ma60 is not None and ma5 > ma20 > ma60),
        "return_20d_pct": period_return(20),
        "return_60d_pct": period_return(60),
        "return_120d_pct": period_return(120),
        "volume_ratio_20d": round(float(volume.iloc[-1] / volume20), 3) if volume20 and volume20 > 0 else None,
        "high_20d": _number(high20),
        "low_20d": _number(low20),
        "new_high_20d": bool(high20 is not None and latest >= float(high20) * 0.995),
        "atr": round(float(atr), 4) if atr is not None and pd.notna(atr) else None,
        "volatility_20d_pct": round(float(volatility), 3) if volatility is not None and pd.notna(volatility) else None,
        "max_drawdown_pct": round(float(drawdown.min()), 3),
        "rsi_14": round(float(rsi.iloc[-1]), 3) if pd.notna(rsi.iloc[-1]) else (100.0 if average_loss.iloc[-1] == 0 else None),
        "macd": round(float(macd_series.iloc[-1]), 4),
        "macd_signal": round(float(macd_signal.iloc[-1]), 4),
        "support": round(float(max(x for x in (low20, ma20, ma60) if x is not None)), 3),
        "resistance": round(float(high20), 3) if high20 is not None else None,
        "quality_flags": quality_flags,
    }
