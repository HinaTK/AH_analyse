# -*- coding: utf-8 -*-
"""上涨侧持仓管理·只读样例报告（2026-11-07）。

只读 confirmed-*.json / holdings.json / regime-cache.json，不写账本、不改参数、
不联网、不生成买卖建议。用于让 Master 看到新口径在真实账本上的输出。

口径（Master 2026-11-07 拍板）：不定份额底仓，按格子——只要不是明确退出该 ETF，
就保留两格。份额登记脚本 set_core_qty.py 已不参与生产判据。
"""
import json
import os
import sys
from decimal import Decimal as D
from pathlib import Path

REPO = Path(r'D:\Code\AH_analyse')
ROOT = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-account'
os.environ['HERMES_HOME'] = str(REPO / '.cache' / 'grid-home')
sys.path.insert(0, str(REPO))

import holdings as H
import upside_guard as ug
import confirmed_runtime as rt


def main():
    holdings = H.load_holdings_from_root(ROOT)
    cache_path = ROOT / 'regime-cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    spot = {}
    for code, entry in cache.items():
        if isinstance(entry, dict) and entry.get('close'):
            try:
                spot[code] = D(str(entry['close']))
            except (ArithmeticError, ValueError):
                pass
    # 关键：直接消费生产 plan() 的 ticket，不另算一套，保证样例与 09:20 建议同源。
    ticket = rt.plan(ROOT, spot=spot or None)
    states = ticket['states']
    reviews = ticket.get('upside_reviews') or []
    review_by_code = {r['code']: r for r in reviews}
    lines = ['【上涨侧持仓管理·只读样例】',
             f'账本根（副本链）：{ROOT}',
             '数据来源：confirmed-*.json / holdings.json / regime-cache.json 已保存收盘价（非实时）',
             '口径（Master 2026-11-07 拍板）：不定份额底仓，按格子；非明确退出该 ETF 者一律保留两格',
             '只读层：不自动上移基准、不自动抬高既有买价、不自动追涨、不自动换仓',
             '提醒直接取自生产 plan() 的 ticket，与 09:20 建议 / 15:20 收盘报告同源',
             '',
             '| 代码 | 名称 | 是否活跃 | 当前库存 | 未平格数 | 保留下限 | 已完成T轮 | 最近卖出价 | 已保存收盘价 | 触发复核 |',
             '|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    for code, state in states.items():
        name = holdings.get(code, {}).get('name', '')
        last = ug.last_sell_price(state)
        active = H.is_active(code, holdings)
        lines.append(
            f"| {code} | {name} | {'是' if active else '否（明确退出，不受两格约束）'} "
            f"| {state['qty']:,} | {len(state.get('open_grid_positions') or [])} "
            f"| {ug.CORE_GRIDS} 格 | {len(state.get('t_records') or [])} "
            f"| {last if last else '无'} | {spot[code] if code in spot else '未取得'} "
            f"| {'是' if code in review_by_code else '否'} |")
    lines += ['', '## 生产 ticket 中的提醒', '']
    if reviews:
        lines.extend('📌 ' + r['text'] for r in reviews)
    else:
        lines.append('当前活跃标的均未触发低库存复核（判据：未平格数 ≤2 且已完成至少 1 轮做T）。')
    lines += ['', '## 保留两格保护状态', '',
              '判据：未平格数 ≤ 2 且该 ETF 非明确退出 → 不生成卖出建议。']
    for code, state in states.items():
        grids = len(state.get('open_grid_positions') or [])
        if ug.is_explicit_exit(holdings, code):
            lines.append(f"{code}：明确退出该 ETF → 不受两格约束，允许卖光")
        elif ug.sell_blocked_by_grid_floor(state, holdings, code):
            lines.append(f"{code}：未平 {grids} 格已到保留下限 → 本次不生成卖出建议")
        else:
            lines.append(f"{code}：未平 {grids} 格，距保留下限还可卖 {grids - ug.CORE_GRIDS} 格")
    lines += ['', '## 生产建议原文（render(ticket) 截取，验证口径已进入输出）', '',
              '```text', rt.render(ticket), '```', '',
              '口径来源：Master 2026-11-07 拍板「不定份额底仓，按格子；只要不是明确退出该 ETF，就保留两格」。'
              '无需登记任何份额数值；set_core_qty.py 已不再参与生产判据。']
    return '\n'.join(lines)


if __name__ == '__main__':
    print(main())
