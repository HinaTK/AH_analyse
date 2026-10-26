# -*- coding: utf-8 -*-
"""Grid account summary: per-ETF + totals, Decimal-exact, cash-flow cross-check.

Reads the confirmed-* sub-ledger files in a grid-account directory and
computes, without float arithmetic:

- per ETF: trade counts, buy/sell amounts, buy/sell fees, holding/sellable
  qty, max grid, ledger net_invested, T-round stats
- cash-flow net investment: buy_amount + buy_fees - sell_amount + sell_fees
  (buying costs amount+fee; selling recovers amount-fee)
- a cross-check flag: cash-flow figure must equal the ledger net_invested;
  a mismatch means the ledger or the trades are inconsistent and MUST be
  reported, never papered over
- A-share trading-day count over the report window (weekends + statutory
  holidays excluded; makeup Saturday workdays like 2026-10-10 are NOT
  trading days for the exchange)

All money values are returned as strings of 2-decimal Decimal text so the
summary can be compared verbatim against the ledger.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# A股2026法定休市日（中秋9/25，国庆10/1-10/7）。调休补班的周六（如10-10）不开市，
# 因此补班日不需要额外集合——按 weekday<5 且非休市日即可。
A_SHARE_HOLIDAYS_2026 = frozenset(
    date(2026, 9, 25),
    *(),
) if False else frozenset(
    {
        date(2026, 9, 25),   # 中秋节（9/26-9/27为周末，一并休市）
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
        date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
        date(2026, 10, 7),   # 国庆节
    }
)

EXCHANGE_PREFIX = {"sh": "5", "sz": "1"}


def load_account(path: Path) -> dict[str, Any]:
    """Load one confirmed-<code>.json sub-ledger."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    code = str(d.get("code", ""))
    # normalize display code with exchange prefix (sh589720 / sz159363)
    if code.isdigit() and len(code) == 6:
        prefix = "sh" if code.startswith("5") else "sz"
        d["code"] = f"{prefix}{code}"
    return d


def _is_subledger(acc: dict[str, Any]) -> bool:
    """Only per-ETF confirmed-*.json files are sub-ledgers; skip alert/config files."""
    return bool(acc.get("trades")) or "qty" in acc


def count_trading_days(start: str, end: str) -> int:
    """Count A-share trading days in [start, end], ISO date strings."""
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    holidays = A_SHARE_HOLIDAYS_2026
    n = 0
    d = d0
    while d <= d1:
        if d.weekday() < 5 and d not in holidays:
            n += 1
        d += timedelta(days=1)
    return n


def _fmt(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01")))


def _summarize_one(acc: dict[str, Any]) -> dict[str, Any]:
    code = str(acc["code"])
    buy_amt = sell_amt = Decimal("0")
    buy_fees = sell_fees = Decimal("0")
    n_buy = n_sell = 0
    dates: set[date] = set()
    amount_ok = True
    fee_ok = True
    for t in acc.get("trades", []):
        amt = Decimal(str(t["amount"]))
        fee = Decimal(str(t["fee"]))
        # consistency: amount == qty*price (2dp); fee == max(amount*万1, 1元)
        qp = (Decimal(str(t["qty"])) * Decimal(str(t["price"]))).quantize(Decimal("0.01"))
        if qp != amt:
            amount_ok = False
        expect_fee = max((amt * Decimal("0.0001")).quantize(Decimal("0.01")), Decimal("1.00"))
        if fee != expect_fee:
            fee_ok = False
        if t["side"] == "buy":
            buy_amt += amt
            buy_fees += fee
            n_buy += 1
        else:
            sell_amt += amt
            sell_fees += fee
            n_sell += 1
        ds = t.get("date")
        if ds:
            dates.add(date.fromisoformat(ds))
    # correct cash-flow formula (2026-10-22 bug fix):
    # outflow = buy amount + buy fee; inflow = sell amount - sell fee
    cash_net = buy_amt + buy_fees - sell_amt + sell_fees
    ledger_ni = Decimal(str(acc.get("net_invested", "0")))

    t_records = acc.get("t_records", [])
    t_gross = sum((Decimal(str(r["gross"])) for r in t_records), Decimal("0"))
    t_fees = sum((Decimal(str(r["fees"])) for r in t_records), Decimal("0"))
    t_net = sum((Decimal(str(r["net"])) for r in t_records), Decimal("0"))

    return {
        "code": code,
        "name": acc.get("name", ""),
        "n_trades": n_buy + n_sell,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "buy_amount": _fmt(buy_amt),
        "sell_amount": _fmt(sell_amt),
        "buy_fees": _fmt(buy_fees),
        "sell_fees": _fmt(sell_fees),
        "cash_net": _fmt(cash_net),
        "net_invested": _fmt(ledger_ni),
        "cashflow_matches_ledger": cash_net == ledger_ni,
        "amount_consistent": amount_ok,
        "fee_consistent": fee_ok,
        "qty": int(acc.get("qty", 0)),
        "sellable_qty": int(acc.get("sellable_qty", 0)),
        "max_grid": acc.get("max_grid", ""),
        "t_rounds": len(t_records),
        "t_gross": _fmt(t_gross),
        "t_fees": _fmt(t_fees),
        "t_net": _fmt(t_net),
        "trade_dates": sorted(d.isoformat() for d in dates),
    }


def _daily_stats(accs: list) -> dict[str, Any]:
    """Per-day completed T rounds + trade counts, from trades and t_records.

    A round lands on the SELL trade's date (round completes when the sell
    fills). A rebuy without a same-day matching sell is a half-cycle and
    never counts. Null dates are ignored entirely.
    """
    daily: dict[str, dict[str, Any]] = {}

    def _bucket(day: str) -> dict[str, Any]:
        if day not in daily:
            daily[day] = {"rounds": 0, "t_net": Decimal("0"),
                          "n_buys": 0, "n_sells": 0,
                          "buy_amount": Decimal("0"), "sell_amount": Decimal("0")}
        return daily[day]

    for acc in accs:
        trades = acc.get("trades", [])
        for t in trades:
            day = t.get("date")
            if not day:
                continue
            bucket = _bucket(day)
            if t["side"] == "buy":
                bucket["n_buys"] += 1
                bucket["buy_amount"] += Decimal(str(t["amount"]))
            else:
                bucket["n_sells"] += 1
                bucket["sell_amount"] += Decimal(str(t["amount"]))
        trade_by_id = {t["id"]: t for t in trades}
        for rec in acc.get("t_records", []):
            sell = trade_by_id.get(rec.get("sell_id"))
            if not sell or not sell.get("date"):
                continue
            bucket = _bucket(sell["date"])
            bucket["rounds"] += 1
            bucket["t_net"] += Decimal(str(rec["net"]))
    out: dict[str, dict[str, Any]] = {}
    for day, bucket in sorted(daily.items()):
        out[day] = {
            "rounds": bucket["rounds"],
            "t_net": _fmt(bucket["t_net"]),
            "n_buys": bucket["n_buys"],
            "n_sells": bucket["n_sells"],
            "buy_amount": _fmt(bucket["buy_amount"]),
            "sell_amount": _fmt(bucket["sell_amount"]),
        }
    return out


def summarize_account(home: Path) -> dict[str, Any]:
    """Summarize every confirmed-*.json sub-ledger under `home`."""
    home = Path(home)
    files = sorted(home.glob("confirmed-*.json"))
    if not files:
        raise FileNotFoundError(f"no confirmed-*.json sub-ledgers under {home}")
    etfs: dict[str, Any] = {}
    accs: list = []
    totals = {
        "n_trades": 0, "n_buy": 0, "n_sell": 0,
        "qty": 0, "sellable_qty": 0, "t_rounds": 0,
    }
    agg = {k: Decimal("0") for k in (
        "buy_amount", "sell_amount", "buy_fees", "sell_fees",
        "net_invested", "t_gross", "t_fees", "t_net")}
    all_dates: set[date] = set()
    for f in files:
        acc = load_account(f)
        if not _is_subledger(acc):
            continue
        accs.append(acc)
        one = _summarize_one(acc)
        etfs[one["code"]] = one
        totals["n_trades"] += one["n_trades"]
        totals["n_buy"] += one["n_buy"]
        totals["n_sell"] += one["n_sell"]
        totals["qty"] += one["qty"]
        totals["sellable_qty"] += one["sellable_qty"]
        totals["t_rounds"] += one["t_rounds"]
        for k in agg:
            agg[k] += Decimal(one[k])
        all_dates.update(date.fromisoformat(x) for x in one["trade_dates"])
    for k, v in agg.items():
        totals[k] = _fmt(v)
    totals["cashflow_all_match"] = all(e["cashflow_matches_ledger"] for e in etfs.values())
    totals["amount_all_consistent"] = all(e["amount_consistent"] for e in etfs.values())
    totals["fee_all_consistent"] = all(e["fee_consistent"] for e in etfs.values())
    window = None
    if all_dates:
        start = min(all_dates).isoformat()
        end = max(all_dates).isoformat()
        window = {"start": start, "end": end,
                  "trading_days": count_trading_days(start, end)}
    totals["window"] = window
    totals["trading_days"] = window["trading_days"] if window else 0
    return {"etfs": etfs, "totals": totals, "daily": _daily_stats(accs)}


def account_total_pnl(summary: dict, last_prices: dict) -> dict:
    """Total account P&L — market value minus net invested, EXACTLY ONCE.

    Regression: 2026-10-22 the reported total was pnl + t_net, double-counting
    realized T profit (sell inflow already reduces net_invested). This function
    computes and documents the only correct formula and refuses to add t_net.

    last_prices: {code: Decimal price}
    """
    from decimal import Decimal

    per: dict = {}
    tot_mv = Decimal("0")
    tot_ni = Decimal("0")
    for code, e in summary["etfs"].items():
        px = Decimal(str(last_prices[code]))
        mv = (px * Decimal(e["qty"])).quantize(Decimal("0.01"))
        ni = Decimal(e["net_invested"])
        per[code] = {
            "name": e["name"],
            "qty": e["qty"],
            "last_price": str(px),
            "market_value": _fmt(mv),
            "net_invested": e["net_invested"],
            "pnl": _fmt(mv - ni),
            "pnl_pct": _fmt((mv - ni) / ni * 100),
        }
        tot_mv += mv
        tot_ni += ni
    total = tot_mv - tot_ni
    return {
        "etfs": per,
        "market_value_total": _fmt(tot_mv),
        "net_invested_total": _fmt(tot_ni),
        "total_pnl": _fmt(total),
        "total_pnl_pct": _fmt(total / tot_ni * 100),
        "t_net_reported_separately": _fmt(sum(
            (Decimal(e["t_net"]) for e in summary["etfs"].values()), Decimal("0"))),
        "t_net_added": False,
        "note": ("total = market_value - net_invested; t_net is already "
                 "reflected via sell inflow; never add again"),
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Grid account summary")
    ap.add_argument("home", nargs="?",
                    default="D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account")
    args = ap.parse_args()
    s = summarize_account(Path(args.home))
    print(json.dumps(s, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
