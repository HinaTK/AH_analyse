# -*- coding: utf-8 -*-
"""登记「参与底仓」份额到 holdings.json（2026-11-07 上涨侧持仓管理）。

只改 holdings.json 的 core_qty 字段，不碰 confirmed-*.json 账本，不生成买卖建议。
写入前备份、写入后读回核验；非法值直接拒绝且不落盘。

默认只写 the agent harness 副本链账本根；生产链需 Master 明确授权后用 --root 指定。
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(r'D:\Code\AH_analyse')
DEFAULT_ROOT = REPO / '.cache' / 'grid-home' / 'cache' / 'grid-account'


def register(root, code, qty, now=None):
    root = Path(root)
    path = root / 'holdings.json'
    if not path.exists():
        raise ValueError(f'未找到 holdings.json：{path}')
    if type(qty) is not int or qty < 0:
        raise ValueError('参与底仓必须为非负整数份额')
    original = path.read_text(encoding='utf-8')
    data = json.loads(original)
    holdings = data.get('holdings', data)
    if code not in holdings:
        raise ValueError(f'holdings.json 未枚举该标的：{code}')
    state_path = root / f'confirmed-{code[-6:]}.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if qty > int(state['qty']):
            raise ValueError(f'参与底仓 {qty:,} 份超过当前库存 {int(state["qty"]):,} 份')
    holdings[code]['core_qty'] = qty
    stamp = (now or datetime.now(timezone(timedelta(hours=8)))).strftime('%Y%m%d-%H%M%S')
    backup = path.with_name(f'holdings.json.bak-{stamp}-pre-core-qty')
    shutil.copy2(path, backup)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)
    written = json.loads(path.read_text(encoding='utf-8')).get('holdings', {})
    if int(written[code].get('core_qty', -1)) != qty:
        raise ValueError('读回核验失败：登记值未生效')
    return dict(code=code, core_qty=qty, backup=str(backup), verified=True)


def main(argv=None):
    p = argparse.ArgumentParser(description='登记参与底仓份额（只写 holdings.json）')
    p.add_argument('--code', required=True)
    p.add_argument('--qty', required=True, type=int)
    p.add_argument('--root', default=str(DEFAULT_ROOT))
    args = p.parse_args(argv)
    try:
        result = register(args.root, args.code, args.qty)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'登记失败：{exc}')
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
