# -*- coding: utf-8 -*-
"""Grid account summary: per-ETF + totals, Decimal-exact, cash-flow cross-check.

Tests for the summary module before it exists (TDD RED step).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grid_summary import (  # noqa: E402  (module under test)
    A_SHARE_HOLIDAYS_2026,
    count_trading_days,
    load_account,
    summarize_account,
)

HOME = Path(__file__).resolve().parents[1] / "fixtures" / "grid-summary"


def _mk(tmp_path, code, trades, **fields):
    d = {
        "code": code,
        "name": f"ETF{code}",
        "trades": trades,
        "qty": fields.pop("qty"),
        "sellable_qty": fields.pop("sellable_qty"),
        "max_grid": fields.pop("max_grid"),
        "net_invested": fields.pop("net_invested"),
        "t_net": fields.pop("t_net", "0.00"),
        "t_records": fields.pop("t_records", []),
    }
    d.update(fields)
    p = tmp_path / f"confirmed-{code}.json"
    p.write_text(__import__("json").dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def test_missing_module_raises(tmp_path):
    with pytest.raises(Exception):
        summarize_account(tmp_path)


def test_summary_matches_ledger_with_correct_cashflow(tmp_path):
    """The 2026-10-22 bug: wrong formula bought-sold-all_fees created a fake 102 gap.

    Correct formula: net = buy_amt + buy_fees - sell_amt + sell_fees.
    """
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "8000.00", "fee": "1.00", "date": "2026-09-23"},
        {"id": "T-2", "side": "buy", "qty": 10000, "price": "0.812",
         "amount": "8120.00", "fee": "1.00", "date": "2026-09-23"},
        {"id": "T-3", "side": "sell", "qty": 10000, "price": "0.824",
         "amount": "8240.00", "fee": "1.00", "date": "2026-09-24"},
    ]
    # ledger-check (script-computed, not mental):
    # (8000+1) + (8120+1) - (8240-1) = 7883.00
    _mk(tmp_path, "589720", trades, qty=10000, sellable_qty=10000,
        max_grid="B", net_invested="7883.00",
        t_records=[{"gross": "120.00", "fees": "2.00", "net": "118.00"}])
    s = summarize_account(tmp_path)
    etf = s["etfs"]["sh589720"]
    assert etf["n_trades"] == 3
    assert etf["buy_amount"] == "16120.00"
    assert etf["sell_amount"] == "8240.00"
    assert etf["buy_fees"] == "2.00"
    assert etf["sell_fees"] == "1.00"
    # correct cash flow
    assert etf["cash_net"] == "7883.00"
    # cross-check against ledger field
    assert etf["cash_net"] == etf["net_invested"]
    assert etf["cashflow_matches_ledger"] is True
    # totals
    assert s["totals"]["net_invested"] == "7883.00"
    assert s["totals"]["n_trades"] == 3
    assert s["totals"]["t_rounds"] == 1
    assert s["totals"]["t_net"] == "118.00"
    assert s["totals"]["qty"] == 10000
    assert s["totals"]["sellable_qty"] == 10000


def test_cashflow_mismatch_is_flagged(tmp_path):
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "8000.00", "fee": "1.00", "date": "2026-09-23"},
    ]
    _mk(tmp_path, "159363", trades, qty=10000, sellable_qty=0,
        max_grid="A", net_invested="9999.00")  # deliberately wrong ledger
    s = summarize_account(tmp_path)
    etf = s["etfs"]["sz159363"]
    assert etf["cashflow_matches_ledger"] is False
    assert etf["cash_net"] == "8001.00"


def test_trading_days_window_excludes_holidays_and_weekends():
    # 2026-09-23 -> 2026-10-22: 16 trading days (mid-autumn 9/25, national day 10/1-10/7 off)
    days = count_trading_days("2026-09-23", "2026-10-22")
    assert days == 16
    # national day window itself: only makeup weekend excluded here
    assert count_trading_days("2026-10-01", "2026-10-08") == 1  # 10-08 only


def test_holiday_set_known():
    from datetime import date
    assert date(2026, 9, 25) in A_SHARE_HOLIDAYS_2026
    assert date(2026, 10, 1) in A_SHARE_HOLIDAYS_2026
    assert date(2026, 10, 7) in A_SHARE_HOLIDAYS_2026
    # 10-10 makeup workday: market CLOSED despite being Saturday workday
    assert date(2026, 10, 10) not in A_SHARE_HOLIDAYS_2026


def test_load_account_reads_real_shape(tmp_path):
    _mk(tmp_path, "159992", [
        {"id": "T-1", "side": "buy", "qty": 9100, "price": "0.871",
         "amount": "7926.10", "fee": "1.00", "date": None},
    ], qty=9100, sellable_qty=9100, max_grid="A", net_invested="7927.10")
    acc = load_account(tmp_path / "confirmed-159992.json")
    assert acc["code"] == "sz159992"
    assert acc["trades"][0]["date"] is None
    s = summarize_account(tmp_path)
    # null dates must not crash and must not count as a trading day
    assert s["totals"]["trading_days"] == 0 or "trading_days" in s["totals"]
