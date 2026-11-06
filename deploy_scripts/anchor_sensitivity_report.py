# -*- coding: utf-8 -*-
"""锚点敏感性离线报告（只读，2026-11-06 Master 授权）。

读两期已有研究目录的 result.json 与 bars/*.csv，输出：
  ① 本期窗口锚价位移披露行（可直接接入周报头部）
  ② 多起点稳健性诊断表（窗口起点平移 0/-1/-2/-3/-4 交易日）

不改生产口径、不联网、不写账本/持仓/连续周状态、不跑生产研究。
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r'D:\Code\AH_analyse')
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.etf_research import anchor_sensitivity as a  # noqa: E402

DEFAULT_ROOT = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-research'
DEFAULT_PREV = DEFAULT_ROOT / 'rerank-20261105-1925'
DEFAULT_CURR = DEFAULT_ROOT / '20261106-152501-510377'


def _result(directory):
    return json.loads((directory / 'result.json').read_text(encoding='utf-8'))


def _row(result, code):
    return next(x for x in result['ranking'] if x['code'] == code)


def _bars(directory, code):
    path = directory / 'bars' / f'{code}-m5.csv'
    return pd.read_csv(path)


def build(prev_dir, curr_dir, code, sessions=63, shifts=(0, -1, -2, -3, -4)):
    prev, curr = _result(prev_dir), _result(curr_dir)
    pr, cr = _row(prev, code), _row(curr, code)
    prev_frame = _bars(prev_dir, code)
    prev_open = float(prev_frame['open'].iloc[
        prev_frame['time'].astype(str).str[:10] == pr['full_start'][:10]].iloc[0])
    curr_frame = _bars(curr_dir, code)
    curr_open = float(curr_frame['open'].iloc[
        curr_frame['time'].astype(str).str[:10] == cr['full_start'][:10]].iloc[0])
    # 首根开盘价：用窗口起点当天第一根 5 分钟 K（与 full_start 对齐）
    prev_anchor = a.anchor_of_first_open(prev_open, pr['full_start'])
    curr_anchor = a.anchor_of_first_open(curr_open, cr['full_start'])
    disclosure = a.disclosure_lines(prev_anchor, curr_anchor,
                                     prev['summary']['asof'], curr['summary']['asof'])
    diagnosis = a.diagnose(curr_frame, sessions=sessions, shifts=shifts)
    text = a.render(disclosure, diagnosis, code, cr.get('name', code),
                     prev['summary']['asof'], curr['summary']['asof'])
    return dict(text=text, prev_row=pr, curr_row=cr,
                prev_anchor=prev_anchor, curr_anchor=curr_anchor,
                disclosure=disclosure, diagnosis=diagnosis)


def main(argv=None):
    p = argparse.ArgumentParser(description='锚点敏感性离线诊断（只读）')
    p.add_argument('--prev', default=str(DEFAULT_PREV))
    p.add_argument('--curr', default=str(DEFAULT_CURR))
    p.add_argument('--code', default='sz159206')
    p.add_argument('--sessions', type=int, default=63)
    p.add_argument('--shifts', default='0,-1,-2,-3,-4')
    p.add_argument('--output', help='报告写入路径（可选）')
    args = p.parse_args(argv)
    shifts = tuple(int(x) for x in args.shifts.split(','))
    out = build(Path(args.prev), Path(args.curr), args.code, args.sessions, shifts)
    text = out['text']
    print(text)
    # 生产对照数字：本期/上期 63 日往返次数，明确标注生产口径与诊断口径不同
    print()
    print(f"生产口径对照（仅参考，不与诊断绝对值混用）：上期63日往返 "
          f"{out['prev_row']['full_cycles']:g} 次 / 净差价 {out['prev_row']['full_cycle_net']:,.2f} 元；"
          f"本期 {out['curr_row']['full_cycles']:g} 次 / 净差价 {out['curr_row']['full_cycle_net']:,.2f} 元。")
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    return text


if __name__ == '__main__':
    main()
