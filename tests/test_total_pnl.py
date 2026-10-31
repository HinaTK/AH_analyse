# -*- coding: utf-8 -*-
"""Account total P&L must be market_value - net_invested, exactly once.

Regression test for the 2026-10-22 double-count error: the assistant
reported total = pnl + t_net = -7,750.60, double-counting realized T
profit already reflected in net_invested via sell cash inflow.
"""
import sys
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grid_summary import account_total_pnl  # noqa: E402


def _mini_summary():
    """Minimal summary dict, same shape as summarize_account() totals."""
    return {
        "etfs": {
            "sh589720": {"qty": 10000, "net_invested": "9980.03",
                        "t_net": "19.98", "name": "DEMO"},
        },
        "totals": {"qty": 10000, "net_invested": "9980.03",
                   "t_net": "19.98"},
    }


def test_total_pnl_is_market_value_minus_net_invested():
    s = _mini_summary()
    # market value at 0.950: 9500.00; total = 9500 - 9980.03 = -480.03
    r = account_total_pnl(s, {"sh589720": D("0.950")})
    assert r["total_pnl"] == "-480.03"
    assert r["total_pnl_pct"] == "-4.81"  # -480.03/9980.03*100 = -4.809%


def test_total_pnl_does_not_double_count_t_net():
    """The bug: reporting pnl + t_net. Result must equal plain pnl."""
    s = _mini_summary()
    r = account_total_pnl(s, {"sh589720": D("0.950")})
    # the wrong figure -7,750-style addition would give -460.05; forbid it
    assert D(r["total_pnl"]) == D("9500.00") - D("9980.03")
    assert "t_net_added" in r and r["t_net_added"] is False
    # documented guidance field
    assert r["note"] == ("total = market_value - net_invested; "
                         "t_net is already reflected via sell inflow; never add again")


def test_per_etf_pnl_included():
    s = _mini_summary()
    r = account_total_pnl(s, {"sh589720": D("0.950")})
    assert r["etfs"]["sh589720"]["market_value"] == "9500.00"
    assert r["etfs"]["sh589720"]["pnl"] == "-480.03"
