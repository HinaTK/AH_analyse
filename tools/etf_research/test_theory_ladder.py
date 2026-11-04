# -*- coding: utf-8 -*-
"""理论口径阶梯模型的刻度回归测试。

《投资理论框架》§4（2026-11-01 等比定稿）：10万账户、3万底仓、
每格 3000、格距 3% 等比——跌到 -45.6%（第20格）触及"留1万现金"线，
跌到 -51.9%（第24格买不起）现金打光。
本测试用合成单调下跌日线钉死这两个刻度：模型改了口径测试必须红。
"""
import sys
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tools.theory_ladder import simulate_ladder


def _monotonic_drop(days, start, end):
    """从 start 等比滑到 end 的合成日线（收盘=开高低）。"""
    bars = []
    for i in range(days):
        price = start * (end / start) ** (i / (days - 1))
        bars.append({'date': '2022-01-{:02d}'.format(i + 1) if i < 28
                     else '2022-02-{:02d}'.format(i - 27), 'close': round(price, 4)})
    return bars


def test_theory_cash_floor_scale_at_minus_45_6():
    """单调跌 60%：第20格（-45.6%）是现金首次降到约1万的格。

    理论算术：网格现金 70,000 − 20×3,000 = 10,000。模型按整百份买入，
    每格实际花费略低于 3,000（尾差），所以第20格后现金略高于 10,000——
    刻度验证的是"第20格是 1 万线所在的格"，不是分毫不差。
    """
    bars = _monotonic_drop(120, 1.0, 0.4)
    r = simulate_ladder(bars, gap=0.03, lot_budget=3000)
    curve = r['curve']
    hit = next(c for c in curve if c['open_levels'] >= 20)
    assert D('10000') <= D(hit['cash']) <= D('12000'), '第20格后现金应落在1万-1.2万（整百份尾差内）'
    before = [c for c in curve if c['date'] < hit['date']]
    assert all(D(c['cash']) > D('12000') for c in before), '第20格之前现金必须高于该区间'


def test_theory_cash_exhausted_scale_at_minus_51_9():
    """单调跌 60%：最深只买到第23格（第24格 = -51.9% 买不起），现金打光。"""
    bars = _monotonic_drop(120, 1.0, 0.4)
    r = simulate_ladder(bars, gap=0.03, lot_budget=3000)
    assert r['deepest_k'] == 23, '现金在第23格后不足以买第24格'
    assert D(r['min_cash']) < D('3000'), '终点现金必须不够再买一格（现金打光）'
    # 价格刻度：第24格线 = 0.97^24 ≈ 0.4811 → -51.89%
    line24 = D('1') * (D('1') - D('0.03')) ** 24
    assert abs(line24 - D('0.4811')) < D('0.001')


def test_round_trips_counted_and_cash_recycles():
    """跌破两格再涨回：两格都卖出，往返=2，卖出释放的现金可再买。"""
    bars = [{'date': '2022-01-0{}'.format(i + 1), 'close': p} for i, p in enumerate(
        [1.0, 0.97, 0.94, 0.97, 1.0, 1.03])]
    r = simulate_ladder(bars, gap=0.03, lot_budget=3000)
    assert r['cycles'] == 2
    assert D(r['realized']) > 0
    assert r['open_levels'] == 0


def test_core_position_never_sold():
    """底仓永不卖：上涨段往返=0，权益涨幅 ≈ 底仓占比 × 价格涨幅。"""
    bars = [{'date': '2022-01-0{}'.format(i + 1), 'close': p}
            for i, p in enumerate([1.0, 1.1, 1.2, 1.3])]
    r = simulate_ladder(bars, gap=0.03, lot_budget=3000)
    assert r['cycles'] == 0
    assert r['core_qty'] > 0
    # 底仓 30% × 涨 30% ≈ 账户 +9%（整百份与费用的尾差内）
    end_equity = D(r['end_equity'])
    assert D('108000') < end_equity < D('110000')
