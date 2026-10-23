# -*- coding: utf-8 -*-
"""市况右侧信号监控测试（market_phase_check 扩展部分）

右侧三信号（承诺口径）：地量 + ADX降破25 + 周线KDJ金叉(K<50)，齐了才推飞书。
纯逻辑与 I/O 分离：本文件只测纯函数，网络路径由脚本实跑验证。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import market_phase_check as mpc


# ---------- evaluate_phase_signals ----------

def test_all_three_signals_fire_triggers_alert():
    metrics = {
        "vol_ratio": 0.20,       # 地量：5日均额 < 1/3 峰值
        "adx": 22.0,             # ADX 已降到 25 下方
        "adx_prev": 31.0,        # 且是从上方降破（单边动能衰竭）
        "kdj_golden": True,      # 周线KDJ金叉
        "kdj_k": 44.0,           # K<50 底部区金叉
    }
    out = mpc.evaluate_phase_signals(metrics)
    assert out["dilVolume"] is True
    assert out["adx_break"] is True
    assert out["kdj_golden"] is True
    assert out["trigger"] is True


def test_no_signal_when_market_still_one_sided_down():
    metrics = {
        "vol_ratio": 0.36,       # 量能未到地量
        "adx": 44.0,             # 单边下跌仍强
        "adx_prev": 47.0,
        "kdj_golden": False,
        "kdj_k": 20.0,
    }
    out = mpc.evaluate_phase_signals(metrics)
    assert out["trigger"] is False
    assert out["dilVolume"] is False
    assert out["adx_break"] is False


def test_adx_below_25_but_never_crossed_is_not_break():
    # ADX 一直低于 25（本来就在震荡）不算"降破"事件
    metrics = {"vol_ratio": 0.2, "adx": 17.0, "adx_prev": 18.0,
               "kdj_golden": False, "kdj_k": 30.0}
    out = mpc.evaluate_phase_signals(metrics)
    assert out["adx_break"] is False
    assert out["trigger"] is False


def test_kdj_cross_with_k_above_50_not_bottom_signal():
    # 高位金叉不是抄底信号（书口径：50以下金叉进场）
    metrics = {"vol_ratio": 0.2, "adx": 22.0, "adx_prev": 30.0,
               "kdj_golden": True, "kdj_k": 65.0}
    out = mpc.evaluate_phase_signals(metrics)
    assert out["kdj_golden"] is False
    assert out["trigger"] is False


def test_two_of_three_signals_do_not_trigger():
    # 只齐两个不推（承诺是"信号齐了"=三条全中）；0.36 > 1/3，非地量
    metrics = {"vol_ratio": 0.36, "adx": 22.0, "adx_prev": 30.0,
               "kdj_golden": True, "kdj_k": 40.0}
    out = mpc.evaluate_phase_signals(metrics)
    assert out["dilVolume"] is False
    assert out["adx_break"] is True
    assert out["kdj_golden"] is True
    assert out["trigger"] is False


# ---------- weekly KDJ / adx_prev / dedup ----------

def _bars(closes):
    """按收盘方向构造真实形态的K线。

    下跌bar：收盘贴最低（RSV→0）；上涨bar：收盘贴最高（RSV→100）。
    固定对称 spread 会让 RSV 恒为 50，测不出超买超卖。
    """
    bars = []
    prev = closes[0]
    for c in closes:
        hi = max(prev, c) + 0.5
        lo = min(prev, c) - 0.5
        if c < prev:            # 下跌：收盘压到最低附近
            lo = c - 0.1
        else:                   # 上涨：收盘顶到最高附近
            hi = c + 0.1
        bars.append({"date": f"w{len(bars)+1}", "open": prev, "close": c,
                     "high": hi, "low": lo, "volume": 0, "amount": 0, "pct": 0})
        prev = c
    return bars


# 等速下跌：每周-3，RSV恒为0，K被D持续压制。
# 注意不能用减速下跌(如2→1.5→0.5)，跌幅收窄会让RSV回升、KDJ低位金叉——那是另一种真实场景。
DECLINE = [100, 97, 94, 91, 88, 85, 82, 79, 76, 73, 70, 67, 64, 61]


def test_weekly_kdj_decline_has_no_golden_cross():
    # 14周连续阴跌：K 深陷低位、被 D 压制，无金叉
    series = mpc.weekly_kdj(_bars(DECLINE))
    golden, k = mpc.kdj_golden_cross(series)
    assert golden is False
    assert k < 50  # 深跌后 K 处于低位


def test_weekly_kdj_reversal_bar_produces_golden_cross_under_50():
    # 9周急跌(K死叉压制) + 强反弹周：K 从 D 下方上穿且 K<50 → 底部金叉
    sharp_decline = [100, 96, 92, 88, 84, 80, 76, 72, 68]
    series = mpc.weekly_kdj(_bars(sharp_decline + [80]))
    golden, k = mpc.kdj_golden_cross(series)
    assert golden is True
    assert k < 50


def test_kdj_golden_cross_needs_prior_k_below_d():
    series = [(60, 55), (65, 58)]  # 一直在上方，不是"上穿"
    golden, _ = mpc.kdj_golden_cross(series)
    assert golden is False


def test_kdj_golden_cross_short_series_is_false():
    assert mpc.kdj_golden_cross([(50, 50)])[0] is False


def test_adx_with_prev_returns_consecutive_values():
    rows = _bars([100 - i * 0.8 for i in range(80)])  # 持续下跌
    cur, prev = mpc.adx_with_prev(rows)
    assert isinstance(cur, float) and isinstance(prev, float)
    assert prev == mpc.wilder_adx(rows[:-1])[0]  # 前值=去掉最后一根重算


def test_should_push_first_time_and_dedup_same_day():
    state = {}
    assert mpc.should_push(state, "1.000001", "2026-10-23") is True
    state = mpc.record_push(state, "1.000001", "2026-10-23")
    assert mpc.should_push(state, "1.000001", "2026-10-23") is False  # 同日不重复
    assert mpc.should_push(state, "1.000001", "2026-10-26") is True   # 新交易日恢复


# ---------- monitor_main ----------

def test_monitor_main_triggers_only_when_signals_align_and_dedups(monkeypatch, tmp_path, capsys):
    # 日K：140天单边下跌（ADX抬升）+ 39天横盘钝化（ADX恰好降破25），amount=1亿(量能为常数)
    daily_closes = [100 - 0.5 * i for i in range(140)]
    base = daily_closes[-1]
    daily_closes += [base + (0.3 if i % 2 else -0.3) for i in range(39)]
    daily = _bars(daily_closes)
    for i, b in enumerate(daily):
        b["amount"] = 5e9 if i < 140 else 1e9  # 横盘段量能缩到峰值1/5 → 地量
    # 周K：9周急跌后反弹 → 底部金叉
    weekly = _bars([100, 96, 92, 88, 84, 80, 76, 72, 68] + [80])

    def fake_fetch(secid, lmt=300, klt="101"):
        return weekly if klt == "102" else daily

    monkeypatch.setattr(mpc, "fetch_kline", fake_fetch)
    monkeypatch.setattr(mpc, "INSTRUMENTS", [("WEEKLY", "测试指数")])
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(mpc, "_state_path", lambda: str(state_file))

    mpc.monitor_main()

    out1 = capsys.readouterr().out
    assert "测试指数" in out1            # 信号齐 → 打印警报
    assert "地量" in out1

    mpc.monitor_main()                  # 同日第二次 → 去重，不重复打印
    out2 = capsys.readouterr().out
    assert out2 == ""


def test_monitor_main_silent_when_no_signal(monkeypatch, tmp_path, capsys):
    # 日K持续单边下跌：ADX高、无降破；周K无金叉 → 全程静默
    daily = _bars([100 - 0.4 * i for i in range(160)])
    for b in daily:
        b["amount"] = 1e8
    weekly = _bars([100 - 3 * i for i in range(12)])
    monkeypatch.setattr(mpc, "fetch_kline", lambda secid, lmt=300, klt="101": weekly if klt == "102" else daily)
    monkeypatch.setattr(mpc, "INSTRUMENTS", [("WEEKLY", "测试指数")])
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(mpc, "_state_path", lambda: str(state_file))

    mpc.monitor_main()
    assert capsys.readouterr().out == ""
    assert not state_file.exists()      # 无触发不写状态文件


def test_build_alert_empty_when_no_trigger():
    result = {"name": "上证指数", "close": 3600.0, "signals": {"trigger": False}}
    assert mpc.build_alert([result]) == ""


def test_build_alert_lists_triggered_instruments():
    rows = [
        {"name": "上证指数", "close": 3600.0, "date": "2026-10-23",
         "signals": {"trigger": False}},
        {"name": "沪深300", "close": 3980.0, "date": "2026-10-23",
         "signals": {"trigger": True, "dilVolume": True, "adx_break": True,
                     "kdj_golden": True, "kdj_k": 44.0}},
    ]
    text = mpc.build_alert(rows)
    assert "沪深300" in text
    assert "地量" in text and "ADX" in text and "周线金叉" in text
    assert "上证指数" not in text  # 未触发的标的不能进警报
