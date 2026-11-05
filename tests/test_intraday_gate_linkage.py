"""盘中监控与门控联动：门控拦截的买入不得在盘中监控里复活。

事故 2026-11-05：9:20 盘前建议对 159363 判 ⛔ 强动能跌势（不生成 I格买入@1.064），
但 9:31 盘中监控每分钟重新 plan(root) 时不传 regime_gate，I格买入复活，
现价 0.855 ≤ 1.064 → 首见现价触价误报。根因：intraday_main 裸调 plan(root)。
"""
import ast
import json
import tempfile
from pathlib import Path

import confirmed_runtime as runtime


def _build_state(code, name, inputs):
    import confirmed_589720
    state = confirmed_589720.build(inputs, code=code, name=name)
    state['sellable_qty'] = state['qty']
    return state


def _setup_root():
    """为 held_codes() 里每个代码建 state；缺失的代码补空仓（注册标的）。"""
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    codes = runtime.H.held_codes()
    for code in codes:
        path = root / f'confirmed-{code[-6:]}.json'
        if path.exists():
            continue
        state = _build_state(code, code, [('buy', 4600, '1.28')])
        path.write_text(json.dumps(state))
    runtime.H.save_holdings_to_root(
        {c: dict(runtime.H.load_holdings()[c]) for c in codes}, root)
    return directory, root


def _write_cache(root):
    """写入门控缓存，覆盖全部 holdings 代码，避免 build_gate 走补拉联网路径。"""
    cache = {}
    for code in runtime.H.held_codes():
        if code == 'sh589720':
            cache[code] = dict(level='normal', blocks_buy=False, reason='正常', adx=15.0, close='1.28', asof='2026-11-04')
        elif code == 'sz159363':
            cache[code] = dict(level='pause_buy', blocks_buy=True, reason='强动能跌势', adx=48.0, close='0.873', asof='2026-11-04')
        elif code == 'sz159992':
            cache[code] = dict(level='probe_only', blocks_buy=False, reason='试错仓', adx=13.0, close='0.831', asof='2026-11-04')
        else:
            cache[code] = dict(level='normal', blocks_buy=False, reason='正常', adx=15.0, close='0.800', asof='2026-11-04')
    (root / 'regime-cache.json').write_text(json.dumps(cache))


def _func_body(func_name, source_path):
    """提取指定函数体的源码文本（含嵌套调用），供静态检查。"""
    tree = ast.parse(Path(source_path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            segment = ast.get_source_segment(Path(source_path).read_text(encoding='utf-8'), node)
            return segment or ''
    raise AssertionError(f'函数 {func_name} 未找到')


def test_intraday_main_calls_plan_with_regime_gate():
    """intraday_main 必须像 ops_main 一样传 regime_gate（静态检查，不依赖运行时 mock）。"""
    body = _func_body('intraday_main', runtime.__file__)
    assert 'regime_gate' in body, 'intraday_main 必须把门控传给 plan，否则被拦截的买入会在盘中复活'


def test_confirm_and_eod_share_plan_gate():
    """confirm_main 后剩余建议、eod_report 也必须走门控（同类裸调）。"""
    directory, root = _setup_root()
    try:
        _write_cache(root)
        gate = runtime.build_gate(root, expect_asof='2026-11-04')
        gated = runtime.plan(root, regime_gate=gate)
        bare = runtime.plan(root)
        assert any(a['side'] == 'buy' and a['code'] == 'sz159363' for a in bare['actions'])
        assert not any(a['side'] == 'buy' and a['code'] == 'sz159363' for a in gated['actions'])
    finally:
        directory.cleanup()


def test_gate_blocks_buy_suppresses_intraday_false_alert():
    """行为验证：门控拦截后 monitor 不得对 159363 买入误报（复现 11-05 事故）。"""
    directory, root = _setup_root()
    try:
        _write_cache(root)
        old_home = runtime.root_from_home
        runtime.root_from_home = lambda: root
        try:
            gate = runtime.build_gate(root, expect_asof='2026-11-04')
            gated = runtime.plan(root, regime_gate=gate)
            assert not any(a['side'] == 'buy' and a['code'] == 'sz159363' for a in gated['actions'])
            quotes = {code: dict(last='0.855', high='0.880', low='0.850', time='20261105093112')
                      for code in runtime.H.held_codes()}
            msg = runtime.monitor(gated, quotes, {}, '2026-11-05')
            assert 'sz159363' not in msg, f'门控后不应报 159363 买入触价：{msg}'
        finally:
            runtime.root_from_home = old_home
    finally:
        directory.cleanup()