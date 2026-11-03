# -*- coding: utf-8 -*-
"""Shared, read-only grid efficiency and ETF rotation review helpers."""
import os
import sys

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
_IS_312 = sys.version_info[:2] == (3, 12) and 'Programs' in sys.executable

if __name__ == '__main__' and not _IS_312:
    import subprocess
    sys.stdout.flush(); sys.stderr.flush()
    sys.exit(subprocess.call([SYSTEM_PY, os.path.abspath(__file__)] + sys.argv[1:]))

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

GAP = 0.02
OBSERVATION_DAYS = 20
NO_CYCLE_DAYS = 10
MAX_CYCLES_20D = 1


def _successful_actions(book: dict, code: str):
    for item in book.get("history", []):
        if item.get("result") != "成功":
            continue
        for action in item.get("actions", []):
            if action.get("code") == code:
                yield item["date"], action


def completed_cycles(book: dict, code: str, since: date | None = None) -> list[dict]:
    """Pair confirmed buys and sells by explicit lot; never count alerts/orders."""
    buys = {}
    rows = []
    for day, action in _successful_actions(book, code):
        lot = action.get("lot")
        if not lot:
            continue
        key = (code, lot)
        if action.get("side") == "buy":
            buys[key] = (day, action)
        elif action.get("side") == "sell" and key in buys:
            buy_day, buy = buys.pop(key)
            sell_day = date.fromisoformat(day)
            if since is not None and sell_day < since:
                continue
            rows.append({
                "lot": lot,
                "buy_date": buy_day,
                "sell_date": day,
                "qty": int(action["qty"]),
                "buy_price": float(buy["price"]),
                "sell_price": float(action["price"]),
            })
    return rows


def count_grid_crossings(closes: list[float], gap: float = GAP) -> int:
    """Count how many times price moved >= gap from the last crossing level.

    Unlike max/min range, this captures repeated oscillation: a price that
    goes 1.00 -> 1.03 -> 1.00 -> 1.03 produces 4 crossings, while a price
    that goes 1.00 -> 1.04 -> 1.00 produces only 2. The first is genuinely
    grid-friendly; the second is a single spike.
    """
    if len(closes) < 2:
        return 0
    crossings = 0
    level = closes[0]
    for p in closes[1:]:
        if p >= level * (1 + gap):
            crossings += 1
            level = p
        elif p <= level / (1 + gap):
            crossings += 1
            level = p
    return crossings


def recent_trend_ratio(closes: list[float], lookback: int = 10) -> float | None:
    """Fraction of recent closes above the 20-day MA. >0.5 = uptrend."""
    if len(closes) < lookback + 5:
        return None
    ma20 = sum(closes[-20:]) / 20
    recent = closes[-lookback:]
    above = sum(1 for p in recent if p > ma20)
    return round(above / len(recent), 3)


def assess_low_efficiency(cycles: list[dict], bars: list[dict], day: date, gap: float = GAP) -> dict:
    """Assess the current ETF using completed cycles and trailing price behaviour."""
    ordered = sorted(bars, key=lambda x: x["date"])
    if not ordered or ordered[-1]["date"] != day.isoformat() or len(ordered) < OBSERVATION_DAYS:
        return {"state": "DATA_INSUFFICIENT", "executable": False,
                "reason": "不足20个已确认收盘交易日"}
    window = ordered[-OBSERVATION_DAYS:]
    closes = [float(x["close"]) for x in window]
    if any(x <= 0 for x in closes):
        return {"state": "DATA_INSUFFICIENT", "executable": False,
                "reason": "收盘数据无效"}
    start = date.fromisoformat(window[0]["date"])
    recent_cycles = [x for x in cycles if date.fromisoformat(x["sell_date"]) >= start]
    last_ten_start = date.fromisoformat(ordered[-NO_CYCLE_DAYS]["date"])
    recent_ten = [x for x in recent_cycles if date.fromisoformat(x["sell_date"]) >= last_ten_start]
    crossings = count_grid_crossings(closes, gap)
    trend_ratio = recent_trend_ratio(closes)
    low = len(recent_ten) == 0 or len(recent_cycles) <= MAX_CYCLES_20D
    if not low:
        state = "ACTIVE"
        reason = "最近20个交易日完成往返次数尚可"
    elif crossings <= 1:
        state = "LOW_EFFICIENCY"
        reason = (f"20日网格穿越仅{crossings}次，价格基本未覆盖2%间距；"
                  "不是成交提醒或触价次数，是真实波动不足")
    elif len(recent_ten) == 0:
        state = "LOW_EFFICIENCY"
        reason = (f"最近{NO_CYCLE_DAYS}个交易日无完成往返；"
                  f"20日网格穿越{crossings}次，需区分趋势与低波动")
    else:
        state = "LOW_EFFICIENCY"
        trend_desc = "偏上行" if (trend_ratio or 0) > 0.6 else "偏下行" if (trend_ratio or 0) < 0.4 else "震荡"
        reason = (f"最近20日仅{len(recent_cycles)}次完成往返；"
                  f"20日网格穿越{crossings}次，近期{trend_desc}，先观察，不自动切换")
    return {"state": state, "executable": False, "cycles_20d": len(recent_cycles),
            "cycles_10d": len(recent_ten), "crossings": crossings,
            "trend_ratio": trend_ratio, "reason": reason}


def update_consecutive_signal(path: Path, comparison: dict, asof: date) -> dict:
    """Require the same peer to lead in two weekly observations before review."""
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    leader = comparison.get("leader")
    previous_date = old.get("asof")
    if leader and old.get("asof") == asof.isoformat():
        consecutive = int(old.get("consecutive_weeks", 0)) if old.get("leader") == leader else 1
    elif (leader and old.get("leader") == leader and old.get("consecutive_weeks", 0) > 0
          and previous_date and 0 < (asof - date.fromisoformat(previous_date)).days <= 11):
        consecutive = int(old["consecutive_weeks"]) + 1
    elif leader:
        consecutive = 1
    else:
        consecutive = 0
    result = dict(comparison)
    result.update({"asof": asof.isoformat(), "leader": leader,
                   "consecutive_weeks": consecutive,
                   "switch_review_due": bool(leader and consecutive >= 2),
                   "previous_asof": previous_date})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def simulate_daily_grid(closes: list[float], gap: float = GAP, n_slots: int = 4,
                        slot_budget: float = 5000.0) -> dict:
    """Multi-slot grid simulation using daily closes.

    Uses current close for both signal and execution (optimistic proxy —
    assumes we can observe and trade at the same close). Enforces T+1
    settlement and multiple parallel slots, unlike the single-state
    count_close_proxy_cycles. Absolute numbers are optimistic; relative
    ranking across candidates is the meaningful output.
    """
    if len(closes) < 2:
        return {"cycles": 0, "cycle_net": 0.0}

    slots = []
    for k in range(n_slots):
        if k < n_slots // 2:
            qty = max(0, int(slot_budget / (closes[0] * 100)) * 100)
            slots.append({"qty": qty, "cost": qty * closes[0],
                          "target": closes[0] * (1 + gap) ** (k + 1),
                          "bought_day": 0, "initial": True})
        else:
            slots.append({"qty": 0, "cost": 0.0,
                          "target": closes[0] / (1 + gap) ** (k - n_slots // 2 + 1),
                          "bought_day": -1, "initial": True})

    cycles = 0
    cycle_pnl = 0.0

    for i in range(1, len(closes)):
        close = closes[i]

        for s in slots:
            if s["qty"] > 0 and close >= s["target"] and i > s["bought_day"]:
                proceeds = s["qty"] * close
                profit = proceeds - s["cost"]
                if not s["initial"]:
                    cycles += 1
                    cycle_pnl += profit
                s["qty"] = 0
                s["cost"] = 0.0
                s["target"] = close / (1 + gap)
                s["bought_day"] = i
                s["initial"] = False

        for s in slots:
            if s["qty"] == 0 and close <= s["target"]:
                qty = max(0, int(slot_budget / (close * 100)) * 100)
                if qty > 0:
                    s["qty"] = qty
                    s["cost"] = qty * close
                    s["target"] = close * (1 + gap)
                    s["bought_day"] = i
                    s["initial"] = False

    return {"cycles": cycles, "cycle_net": round(cycle_pnl, 2)}


def compare_close_proxy(all_bars: dict, baseline: str, candidates: list[str], day: date) -> dict:
    """Same trailing 63 common sessions. Uses multi-slot daily-grid simulation."""
    if baseline not in all_bars:
        raise ValueError("缺少基准ETF日线")
    base = all_bars[baseline]
    if not base or base[-1]["date"] != day.isoformat():
        raise ValueError("基准ETF不是当日已确认收盘数据")
    dates = [x["date"] for x in base[-63:]]
    if len(dates) != 63:
        raise ValueError("基准ETF不足63个交易日")
    start = dates[0]
    selected = {}
    for code in [baseline, *candidates]:
        bars = all_bars.get(code, [])
        keyed = {x["date"]: x for x in bars}
        if any(d not in keyed for d in dates):
            continue
        result = simulate_daily_grid([keyed[d]["close"] for d in dates])
        selected[code] = result["cycles"]
        selected[f"{code}_net"] = result["cycle_net"]
    if baseline not in selected:
        raise ValueError("基准ETF可比窗口缺失")
    leaders = [(code, n) for code, n in selected.items()
               if not code.endswith("_net") and code != baseline and n > selected[baseline]]
    leaders.sort(key=lambda x: (-x[1], x[0]))
    return {"baseline_code": baseline, "baseline": selected[baseline],
            "baseline_net": selected.get(f"{baseline}_net"),
            "leader": leaders[0][0] if leaders else None,
            "leader_cycles": leaders[0][1] if leaders else None,
            "leader_net": selected.get(f"{leaders[0][0]}_net") if leaders else None,
            "window_sessions": 63, "window_start": start, "window_end": day.isoformat(),
            "compared": {code: selected[code] for code in selected if not code.endswith("_net")},
            "compared_net": {code: selected[f"{code}_net"] for code in selected if not code.endswith("_net")},
            "method": "同一63日收盘价多槽位网格模拟（含T+1、4槽并行、每格5000元）；"
                      "非5分钟成交回测或真实成交；绝对数字偏乐观，相对排序可信"}
