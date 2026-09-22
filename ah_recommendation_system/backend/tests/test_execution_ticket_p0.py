"""P0: pre-market conditional tickets, RR gate, size, open-confirm session."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ah_recommendation_system.backend.stock_recommend.candidate_pool import Candidate


def _candidate(**overrides) -> Candidate:
    payload = dict(
        code="600001",
        name="合格票",
        price=10.0,
        composite=0.8,
        quality_grade="A",
        support=9.0,
        resistance=13.0,
        atr=0.2,
        valid_dimensions={"trend", "price_volume", "value", "relative_strength", "capital"},
        factor_scores={"trend": 0.85, "relative_strength": 0.7},
        evidence=[
            {"factor": "trend", "statement": "趋势向上", "supports": True},
            {"factor": "price_volume", "statement": "量价确认", "supports": True},
            {"factor": "value", "statement": "估值可比", "supports": True},
            {"factor": "relative_strength", "statement": "相对转强", "supports": True},
            {"factor": "capital", "statement": "资金净流入", "supports": True},
        ],
    )
    payload.update(overrides)
    return Candidate(**payload)


def _premarket_report(**overrides):
    report = {
        "schema_version": "decision-report-v2",
        "type": "stock_recommend_pre_market",
        "as_of": "2026-09-22",
        "run": {
            "run_id": "r1",
            "session": "pre_market",
            "status": "passed",
            "trade_date": "2026-09-22",
        },
        "coverage": {
            "mode": "full_market",
            "source": "previous_close",
            "quote_basis": "previous_close",
        },
        "quality_gate": {"passed": True, "blocking_reasons": []},
        "market": {"label": "防守", "regime": "defense", "status": "降级观察"},
        "picks": [
            {
                "code": "600001",
                "name": "合格票",
                "action": "CONDITIONAL_BUY",
                "reference_price": 10.0,
                "buy_zone": "9.00-10.00",
                "stop_loss": "8.75",
                "target": "13.00",
                "reward_risk": 2.4,
                "position_pct_min": 0.05,
                "position_pct_max": 0.08,
                "account_cap_pct": 0.30,
                "position_text": "单票5%-8%，账户总仓≤30%",
                "execution_status": "awaiting_open_confirmation",
                "trigger": "板块不转弱且价格站稳前一交易日收盘，成交额不低于20日均值",
                "invalidation": "收盘跌破观察止损位，或板块与个股相对强度同时转弱",
            }
        ],
        "etf_picks": [],
        "directions": {
            "current_attack": [],
            "medium_term": [],
            "avoid_or_exit": [],
        },
    }
    report.update(overrides)
    return report


class TestPremarketConditionalTicket(unittest.TestCase):
    def test_premarket_formal_pick_is_conditional_buy_never_buy(self):
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        result = select_by_rules([_candidate()], top_n_pick=1)
        pick = result["picks"][0]
        self.assertEqual(pick["action"], "CONDITIONAL_BUY")
        self.assertEqual(pick["execution_status"], "awaiting_open_confirmation")
        self.assertIn("开盘确认前不得成交", pick["fill_constraint"])

    def test_reward_risk_below_1_5_is_not_a_buy_ticket(self):
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        # Entry 23.8, target 24.45, stop 22.24 → RR ~0.42
        weak = _candidate(
            code="002241",
            name="歌尔股份",
            price=23.8,
            support=23.16,
            resistance=24.45,
            atr=0.736,
        )
        result = select_by_rules([weak], top_n_pick=3)
        self.assertEqual(result["picks"], [])
        self.assertTrue(
            any("reward_risk" in str(reason) for reason in weak.rejection_reasons)
        )

    def test_defense_ticket_caps_single_name_at_5_to_8_percent(self):
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        result = select_by_rules(
            [_candidate()],
            top_n_pick=2,
            market_regime={"regime": "defense", "status": "available"},
        )
        pick = result["picks"][0]
        self.assertEqual(pick["action"], "CONDITIONAL_BUY")
        self.assertEqual(pick["position_pct_min"], 0.05)
        self.assertEqual(pick["position_pct_max"], 0.08)
        self.assertEqual(pick["account_cap_pct"], 0.30)

    def test_offense_ticket_caps_single_name_at_10_percent(self):
        from ah_recommendation_system.backend.stock_recommend.rule_selector import select_by_rules

        result = select_by_rules(
            [_candidate()],
            top_n_pick=1,
            market_regime={"regime": "offense", "status": "available"},
        )
        pick = result["picks"][0]
        self.assertEqual(pick["position_pct_max"], 0.10)
        self.assertLessEqual(pick["position_pct_max"], 0.10)


class TestOpenConfirm(unittest.TestCase):
    def test_open_confirm_promotes_only_when_price_volume_hold(self):
        from ah_recommendation_system.backend.stock_recommend.open_confirm import confirm_open_picks

        picks = _premarket_report()["picks"]
        confirmed = confirm_open_picks(
            picks,
            quotes={
                "600001": {
                    "price": 9.80,
                    "previous_close": 10.0,
                    "amount": 220_000_000,
                    "amount_20d": 200_000_000,
                    "sector_change_pct": 0.4,
                }
            },
        )
        self.assertEqual(confirmed[0]["action"], "BUY")
        self.assertEqual(confirmed[0]["execution_status"], "open_confirmed")

    def test_gap_up_out_of_zone_cancels_without_replacement(self):
        from ah_recommendation_system.backend.stock_recommend.open_confirm import confirm_open_picks

        confirmed = confirm_open_picks(
            _premarket_report()["picks"],
            quotes={
                "600001": {
                    "price": 10.50,
                    "previous_close": 10.0,
                    "amount": 300_000_000,
                    "amount_20d": 200_000_000,
                    "sector_change_pct": 1.0,
                }
            },
        )
        self.assertEqual(confirmed[0]["action"], "CANCEL")
        self.assertIn("gap_up", confirmed[0]["cancel_reason"])

    def test_low_turnover_cancels(self):
        from ah_recommendation_system.backend.stock_recommend.open_confirm import confirm_open_picks

        confirmed = confirm_open_picks(
            _premarket_report()["picks"],
            quotes={
                "600001": {
                    "price": 9.80,
                    "previous_close": 10.0,
                    "amount": 80_000_000,
                    "amount_20d": 200_000_000,
                    "sector_change_pct": 0.2,
                }
            },
        )
        self.assertEqual(confirmed[0]["action"], "CANCEL")
        self.assertIn("volume", confirmed[0]["cancel_reason"])

    def test_open_confirm_session_can_push_after_pre_market(self):
        from ah_recommendation_system.backend.stock_recommend.run import _deliver_report

        pre = _premarket_report()
        confirm = {
            "schema_version": "decision-report-v2",
            "type": "stock_recommend_open_confirm",
            "as_of": "2026-09-22",
            "run": {
                "run_id": "r2",
                "session": "open_confirm",
                "status": "passed",
                "trade_date": "2026-09-22",
            },
            "coverage": {
                "mode": "full_market",
                "source": "live_open",
                "quote_basis": "intraday",
                "fresh_data_available": True,
            },
            "quality_gate": {"passed": True, "blocking_reasons": []},
            "picks": [{"code": "600001", "name": "合格票", "action": "BUY", "rationale": "开盘确认通过", "evidence": [{"statement": "量价确认"}]}],
            "etf_picks": [],
            "market": {"regime": "defense", "status": "降级观察"},
            "directions": {
                "current_attack": [],
                "medium_term": [],
                "early_positioning": [],
                "avoid_or_exit": [],
            },
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "ah_recommendation_system.backend.stock_recommend.run.push_to_feishu",
            return_value={"ok": True, "reason": "sent"},
        ) as push:
            ledger = Path(tmp) / "delivery.json"
            first = _deliver_report(pre, ledger_path=ledger)
            second = _deliver_report(confirm, ledger_path=ledger)

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(push.call_count, 2)

    def test_open_confirm_job_loads_today_premarket_and_does_not_replace_it(self):
        from ah_recommendation_system.backend.stock_recommend.run import run_open_confirm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            latest = root / "latest.json"
            latest.write_text(json.dumps(_premarket_report()), encoding="utf-8")
            quotes = {
                "600001": {
                    "price": 9.80,
                    "previous_close": 10.0,
                    "amount": 220_000_000,
                    "amount_20d": 200_000_000,
                    "sector_change_pct": 0.3,
                }
            }
            with patch(
                "ah_recommendation_system.backend.stock_recommend.run._backend_root",
                return_value=root,
            ), patch(
                "ah_recommendation_system.backend.stock_recommend.run._lookup_open_quotes",
                return_value=quotes,
            ), patch(
                "ah_recommendation_system.backend.stock_recommend.run._deliver_report",
                return_value={"ok": True},
            ), patch(
                "ah_recommendation_system.backend.stock_recommend.run.push_to_wechat",
                return_value=None,
            ):
                result = run_open_confirm(
                    push=False,
                    report_path=latest,
                    expected_as_of="2026-09-22",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["review"]["picks"][0]["action"], "BUY")
            saved_pre = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(saved_pre["type"], "stock_recommend_pre_market")
            confirm_path = root / "latest_open_confirm.json"
            self.assertTrue(confirm_path.exists())


class TestConditionalCardCopy(unittest.TestCase):
    def test_premarket_card_prints_conditional_ticket_not_market_buy(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        rendered = json.dumps(build_card(_premarket_report()), ensure_ascii=False)
        self.assertIn("CONDITIONAL_BUY", rendered)
        self.assertIn("开盘确认前不得成交", rendered)
        self.assertIn("条件买入", rendered)
        self.assertIn("9.00-10.00", rendered)
        self.assertIn("仓位", rendered)
        self.assertNotIn("市价买入", rendered)

    def test_open_confirm_card_prints_buy_or_cancel(self):
        from ah_recommendation_system.backend.stock_recommend.feishu_pusher import build_card

        report = {
            "schema_version": "decision-report-v2",
            "type": "stock_recommend_open_confirm",
            "as_of": "2026-09-22",
            "run": {"session": "open_confirm", "status": "passed", "trade_date": "2026-09-22"},
            "quality_gate": {"passed": True},
            "picks": [
                {
                    "code": "600001",
                    "name": "合格票",
                    "action": "BUY",
                    "buy_zone": "9.00-10.00",
                    "stop_loss": "8.75",
                    "position_text": "单票5%-8%，账户总仓≤30%",
                }
            ],
            "coverage": {"source": "live_open"},
            "market": {"regime": "defense", "status": "降级观察"},
            "directions": {},
        }
        rendered = json.dumps(build_card(report), ensure_ascii=False)
        self.assertIn("可下单", rendered)
        self.assertIn("合格票", rendered)

    def test_scheduler_open_confirm_mode_calls_confirm_job(self):
        from ah_recommendation_system.backend.scheduler.daily_job import main

        with patch("sys.argv", ["daily_job.py", "--mode", "open_confirm", "--push"]), patch(
            "ah_recommendation_system.backend.scheduler.daily_job.run_open_confirm",
            return_value={"ok": True, "push": {"ok": True}},
        ) as confirm:
            exit_code = main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(confirm.call_args.kwargs["push"])


if __name__ == "__main__":
    unittest.main()
