# -*- coding: utf-8 -*-
"""上涨侧持仓管理（2026-11-07 Master 要求落地到脚本）。

用户原则（2026-09-22 定、2026-11-07 确认）：
- 单边上涨里网格会过早卖光；保留一定参与底仓，卖出网格不得动它。
- 库存低时提前做上移基准「人工复核」提醒；不自动追涨、不自动抬高既有买价、
  不自动上移基准、不自动换仓。

本模块是**只读层**：只根据已确认账本状态生成提醒与保护说明，不写账本、
不改任何网格参数、不生成买卖建议。所有数字来自 confirmed-*.json 与调用方传入的
已核实现价；现价缺失时明确披露，不编造偏离。

参与底仓登记在 holdings.json 每只标的的可选字段 core_qty（份额，非负整数）。
未登记（缺省）→ 0，行为与改动前完全一致（向后兼容）。
"""
from decimal import Decimal as D

# 2026-11-07 Master 拍板：不定份额底仓，按格子——只要不是明确退出该 ETF，
# 就保留两格。低库存复核阈值与之下限同源（不再是我拍的经验值）。
CORE_GRIDS = 2
LOW_INVENTORY_GRIDS = CORE_GRIDS
CORE_QTY_FIELD = 'core_qty'  # 兼容旧字段读取；份额登记已不再是拦截判据
REVIEW_TITLE = '上移基准人工复核'
DISCLAIMER = '只提醒人工复核；不自动上移基准、不自动抬高既有买价、不自动追涨、不自动换仓'


def core_qty(holdings, code):
    """读取参与底仓份额；未登记或非法值按 0 处理（不静默放大保护范围）。"""
    entry = (holdings or {}).get(code) or {}
    raw = entry.get(CORE_QTY_FIELD, 0)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def is_explicit_exit(holdings, code):
    """明确退出该 ETF = 迁移退出（active=false）。此情形允许卖光，不受保留两格约束。"""
    entry = (holdings or {}).get(code) or {}
    return entry.get('active') is False


def sell_blocked_by_grid_floor(state, holdings, code):
    """2026-11-07 Master 口径：未平格数 ≤2 且非明确退出 → 不再生成卖出建议。

    按格子而非份额；每次卖出只减一格，故「剩两格」即触发下限。
    """
    if is_explicit_exit(holdings, code):
        return False
    return len(state.get('open_grid_positions') or []) <= CORE_GRIDS


def grid_floor_text(code, name, state, holdings):
    return (f"{code} {name} 保留两格：当前未平 "
            f"{len(state.get('open_grid_positions') or [])} 格，已到保留下限 {CORE_GRIDS} 格，"
            f"本次不生成卖出建议（卖出网格不得动参与底仓；只保护，不生成买卖建议）")


# 旧份额判据保留为兼容读取，但生产拦截已改用 sell_blocked_by_grid_floor。
def sell_blocked_by_core(state, holdings, code, sell_qty):
    """[已废弃，仅兼容] 份额口径：卖出后剩余 < 登记参与底仓 → 拦。"""
    core = core_qty(holdings, code)
    if core <= 0:
        return False
    return state['qty'] - int(sell_qty) < core


def core_protected_text(code, name, state, holdings, sell_qty):
    core = core_qty(holdings, code)
    return (f"{code} {name} 参与底仓保护：当前库存 {state['qty']:,} 份，"
            f"登记参与底仓 {core:,} 份；卖出 {int(sell_qty):,} 份后剩 "
            f"{state['qty'] - int(sell_qty):,} 份将低于底仓，本次不生成卖出建议"
            f"（卖出网格不得动参与底仓；只保护，不生成买卖建议）")


def is_low_inventory(state):
    """低库存：未平网格 ≤2 格，且已完成过至少一次往返（排除从未建仓的空仓）。"""
    open_grids = len(state.get('open_grid_positions') or [])
    sold_rounds = len(state.get('t_records') or [])
    return open_grids <= LOW_INVENTORY_GRIDS and sold_rounds >= 1


def last_sell_price(state):
    """最近一笔卖出成交价；无卖出记录返回 None（不编造）。"""
    for trade in reversed(state.get('trades') or []):
        if trade.get('side') == 'sell':
            return trade.get('price')
    return None


def review(state, code, name, holdings, spot=None):
    """生成一条只读的「上移基准人工复核」提醒；库存未偏低返回 None。

    spot 必须是调用方已核实的现价（Decimal/数值/字符串）；None 时披露「现价未核实」，
    不输出任何偏离百分比。
    """
    if not is_low_inventory(state):
        return None
    open_grids = len(state.get('open_grid_positions') or [])
    sold_rounds = len(state.get('t_records') or [])
    last_px = last_sell_price(state)
    core = core_qty(holdings, code)
    parts = [f"{code} {name} {REVIEW_TITLE}：当前库存 {state['qty']:,} 份"
             f"（未平 {open_grids} 格，保留两格下限 {CORE_GRIDS} 格），"
             f"已卖 {sold_rounds} 轮做T，最近卖出价 {last_px if last_px is not None else '无卖出记录'}"]
    if spot is None:
        parts.append('已核实收盘价未取得，偏离不报')
    else:
        try:
            spot_d = D(str(spot))
            last_d = D(str(last_px)) if last_px is not None else None
            if last_d is None or last_d <= 0 or spot_d <= 0:
                parts.append('已核实收盘价或最近卖出价无效，偏离不报')
            else:
                deviation = (spot_d / last_d - 1) * 100
                parts.append(f"已核实收盘价（非实时行情）{spot_d} 对最近卖出价偏离 {deviation:+.1f}%")
        except (ArithmeticError, ValueError, TypeError):
            parts.append('已核实收盘价未取得，偏离不报')
    parts.append(DISCLAIMER)
    text = '；'.join(parts)
    return dict(code=code, name=name, qty=state['qty'], open_grids=open_grids,
                sold_rounds=sold_rounds, last_sell_price=last_px,
                core_qty=core, spot=None if spot is None else str(spot), text=text)


def render_lines(reviews):
    """统一渲染用的行；不与其他状态图标（✅/⛔）混用。"""
    return ['📌 ' + r['text'] for r in reviews or []]


def eod_review_text(review_item):
    """收盘报告字段：只放提醒正文，供 render_eod 输出。"""
    return review_item['text'] if review_item else None
