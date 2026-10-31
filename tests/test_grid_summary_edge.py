# -*- coding: utf-8 -*-
"""Edge cases for grid_summary: commission minimums vs ledger-stored fees."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grid_summary import summarize_account  # noqa: E402


def _write(tmp_path, code, trades, net_invested, qty, sellable_qty=0):
    import json
    d = {"code": code, "name": f"ETF{code}", "trades": trades,
         "qty": qty, "sellable_qty": sellable_qty, "max_grid": "A",
         "net_invested": net_invested, "t_net": "0.00", "t_records": []}
    p = tmp_path / f"confirmed-{code}.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def test_ledger_fees_used_as_source_of_truth(tmp_path):
    """We must use the fees stored in the trade records, not re-derive them.

    The ledger fee is the authoritative estimate (万一免五, min 1元);
    the summary cross-checks amounts and stored fees, never substitutes.
    """
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "8000.00", "fee": "1.00", "date": "2026-09-23"},
        {"id": "T-2", "side": "sell", "qty": 10000, "price": "0.824",
         "amount": "8240.00", "fee": "1.00", "date": "2026-09-24"},
    ]
    # script-computed: (8000+1) - (8240-1) = -238.00 (sell exceeds buys: net cash returned)
    _write(tmp_path, "589720", trades, net_invested="-238.00", qty=0, sellable_qty=0)
    s = summarize_account(tmp_path)
    etf = s["etfs"]["sh589720"]
    assert etf["cash_net"] == "-238.00"
    assert etf["cashflow_matches_ledger"] is True


def test_amount_fee_consistency_check(tmp_path):
    """amount must equal qty*price; fee must obey 万一免五 minimum 1 yuan."""
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "8000.00", "fee": "1.00", "date": "2026-09-23"},
    ]
    _write(tmp_path, "159363", trades, net_invested="8001.00", qty=10000)
    s = summarize_account(tmp_path)
    etf = s["etfs"]["sz159363"]
    assert etf["amount_consistent"] is True
    assert etf["fee_consistent"] is True


def test_inconsistent_amount_flagged(tmp_path):
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "9999.00", "fee": "1.00", "date": "2026-09-23"},
    ]
    _write(tmp_path, "159363", trades, net_invested="10000.00", qty=10000)
    s = summarize_account(tmp_path)
    assert s["etfs"]["sz159363"]["amount_consistent"] is False


def test_fee_below_minimum_flagged(tmp_path):
    trades = [
        {"id": "T-1", "side": "buy", "qty": 10000, "price": "0.800",
         "amount": "8000.00", "fee": "0.50", "date": "2026-09-23"},
    ]
    _write(tmp_path, "159363", trades, net_invested="8000.50", qty=10000)
    s = summarize_account(tmp_path)
    assert s["etfs"]["sz159363"]["fee_consistent"] is False
