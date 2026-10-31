# -*- coding: utf-8 -*-
"""TDD for daily T-rounds stats: per-day completed rounds, net, and activity.

2026-10-26 incident: assistant hand-assembled a "daily report" claiming 3
rounds/+349.20 for the day, counting a rebuy (half-cycle) as a full round.
The ledger truth: 2 completed rounds/+233.60. Per-day stats must come from
the module, never hand-assembled in chat.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

from grid_summary import summarize_account  # noqa: E402


def _write(tmp_path, code, trades, t_records, **fields):
    d = {
        "code": code, "name": f"ETF{code}", "trades": trades,
        "qty": fields.pop("qty"), "sellable_qty": fields.pop("sellable_qty"),
        "max_grid": fields.pop("max_grid"), "net_invested": fields.pop("net_invested"),
        "t_net": fields.pop("t_net", "0.00"), "t_records": t_records,
    }
    d.update(fields)
    p = tmp_path / f"confirmed-{code}.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def test_daily_rounds_counts_only_completed_rounds(tmp_path):
    """Rebuy without a same-day sell is a half-cycle, not a round."""
    trades = [
        {"id": "T-1", "side": "buy", "qty": 9800, "price": "0.809",
         "amount": "7928.20", "fee": "1.00", "date": "2026-10-21"},
        {"id": "T-2", "side": "sell", "qty": 9800, "price": "0.821",
         "amount": "8045.80", "fee": "1.00", "date": "2026-10-26"},
        {"id": "T-3", "side": "buy", "qty": 9800, "price": "0.809",
         "amount": "7928.20", "fee": "1.00", "date": "2026-10-26"},  # rebuy, no sell
    ]
    t_records = [
        {"lot": "E", "buy_id": "T-1", "sell_id": "T-2", "qty": 9800,
         "buy_price": "0.809", "sell_price": "0.821", "gross": "117.60",
         "fees": "2.00", "net": "115.60"},
    ]
    _write(tmp_path, "589720", trades, t_records, qty=9800, sellable_qty=9800,
           max_grid="E", net_invested="7929.20", t_net="115.60")
    s = summarize_account(tmp_path)
    daily = s["daily"]
    assert daily["2026-10-26"]["rounds"] == 1
    assert daily["2026-10-26"]["t_net"] == "115.60"
    assert daily["2026-10-21"]["rounds"] == 0


def test_daily_rounds_matches_2026_10_26_incident(tmp_path):
    """Two completed rounds on the day (E via 023->030, F via 032->033)."""
    trades = [
        {"id": "589720-023", "side": "buy", "qty": 9800, "price": "0.809",
         "amount": "7928.20", "fee": "1.00", "date": "2026-10-21"},
        {"id": "589720-030", "side": "sell", "qty": 9800, "price": "0.821",
         "amount": "8045.80", "fee": "1.00", "date": "2026-10-26"},
        {"id": "589720-031", "side": "buy", "qty": 9800, "price": "0.809",
         "amount": "7928.20", "fee": "1.00", "date": "2026-10-26"},
        {"id": "589720-032", "side": "buy", "qty": 10000, "price": "0.797",
         "amount": "7970.00", "fee": "1.00", "date": "2026-10-26"},
        {"id": "589720-033", "side": "sell", "qty": 10000, "price": "0.809",
         "amount": "8090.00", "fee": "1.00", "date": "2026-10-26"},
    ]
    t_records = [
        {"lot": "E", "buy_id": "589720-023", "sell_id": "589720-030", "qty": 9800,
         "buy_price": "0.809", "sell_price": "0.821", "gross": "117.60",
         "fees": "2.00", "net": "115.60"},
        {"lot": "F", "buy_id": "589720-032", "sell_id": "589720-033", "qty": 10000,
         "buy_price": "0.797", "sell_price": "0.809", "gross": "120.00",
         "fees": "2.00", "net": "118.00"},
    ]
    _write(tmp_path, "589720", trades, t_records, qty=19600, sellable_qty=19600,
           max_grid="E", net_invested="15900.40", t_net="233.60")
    s = summarize_account(tmp_path)
    daily = s["daily"]
    assert daily["2026-10-26"]["rounds"] == 2
    assert daily["2026-10-26"]["t_net"] == "233.60"
    assert daily["2026-10-26"]["n_buys"] == 2
    assert daily["2026-10-26"]["n_sells"] == 2
    # 10-21 only has a buy, no completed round
    assert daily["2026-10-21"]["rounds"] == 0
    assert daily["2026-10-21"]["n_buys"] == 1


def test_null_dates_are_ignored_in_daily(tmp_path):
    trades = [
        {"id": "T-1", "side": "buy", "qty": 9400, "price": "0.846",
         "amount": "7952.40", "fee": "1.00", "date": None},
        {"id": "T-2", "side": "sell", "qty": 9400, "price": "0.863",
         "amount": "8112.20", "fee": "1.00", "date": None},
    ]
    t_records = [
        {"lot": "C", "buy_id": "T-1", "sell_id": "T-2", "qty": 9400,
         "buy_price": "0.846", "sell_price": "0.863", "gross": "159.80",
         "fees": "2.00", "net": "157.80"},
    ]
    _write(tmp_path, "159992", trades, t_records, qty=0, sellable_qty=0,
           max_grid=None, net_invested="-157.80", t_net="157.80")
    s = summarize_account(tmp_path)
    # null-date rounds must not land on any day key
    assert all(v["rounds"] == 0 for v in s["daily"].values())
