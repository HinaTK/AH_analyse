"""Pair research only: consumes the one simulation, never orders or ledger state."""
from .research import BASE, HOLDINGS

TRACKS = ('same_class', 'cross_theme')


def taxonomy_entry(entries, code):
    if code in entries:return entries[code]
    # Explicit identifier alias only; never derive category from ETF names.
    if len(code) == 8 and code[:2] in ('sh', 'sz') and code[2:].isascii() and code[2:].isdigit():
        return entries.get(code[2:], {})
    if len(code) == 6 and code.isascii() and code.isdigit():
        aliases = [entries[prefix + code] for prefix in ('sh', 'sz') if prefix + code in entries]
        return aliases[0] if len(aliases) == 1 else {}
    return {}


def verified_entry(entry):
    from urllib.parse import urlsplit
    if not isinstance(entry, dict) or entry.get('verified') is not True:
        return False
    sources = entry.get('sources')
    if not isinstance(sources, list) or not sources:
        return False
    for source in sources:
        if not isinstance(source, str) or any(c.isspace() or ord(c) < 32 for c in source):
            return False
        try:
            url = urlsplit(source)
            if url.scheme not in ('http', 'https') or not url.hostname:
                return False
            url.port  # Reject malformed or out-of-range ports.
        except ValueError:
            return False
    return True


def classify(holding, candidate, taxonomy):
    entries = (taxonomy or {}).get('assets', (taxonomy or {}).get('entries', {}))
    if not isinstance(entries, dict):
        entries = {}
    a, b = taxonomy_entry(entries, holding), taxonomy_entry(entries, candidate)
    if not all(verified_entry(x) for x in (a, b)):
        return 'unknown'
    a = dict(a, theme_id=a.get('theme', a.get('theme_id')))
    b = dict(b, theme_id=b.get('theme', b.get('theme_id')))
    if a.get('index_id') and a.get('index_id') == b.get('index_id'):
        return 'same_index'
    # Exact verified official index names can bridge missing IDs, not conflicting IDs.
    if not (a.get('index_id') and b.get('index_id')) and a.get('index_name') and a.get('index_name') == b.get('index_name'):
        return 'same_index'
    if not a.get('theme_id') or not b.get('theme_id'):
        return 'unknown'
    return 'same_theme' if a['theme_id'] == b['theme_id'] else 'cross_theme'


DEFAULT_NAME_EXCLUSIONS = ('港股', '恒生', 'H股')


def evaluate(result, taxonomy=None, name_exclusions=DEFAULT_NAME_EXCLUSIONS):
    output = {'holdings': {}, 'name_exclusions': list(name_exclusions)}
    holding_aliases = {alias for code in HOLDINGS for alias in (code, code[-6:], 'sh' + code[-6:], 'sz' + code[-6:])}
    candidates = [x for x in result['ranking'] if x.get('has_all_four_windows') and x['code'] not in holding_aliases
                  and not any(token.casefold() in x.get('name', '').casefold() for token in name_exclusions)]
    for holding in BASE:
        baseline = result['holdings'].get(holding, {})
        retained = next(c for c in BASE if c != holding)
        groups = {t: {'priority': None, 'observe': []} for t in TRACKS}
        unknown = []
        for x in sorted(candidates, key=lambda r: (0 if classify(holding, r['code'], taxonomy) == 'same_index' else 1,
                                                    -(r.get('full_cycles') or 0), -(r.get('full_cycle_net_per_avg_cost_pct') or 0), r['code'])):
            fields = ('full_cycles', 'full_cycle_net_per_avg_cost_pct', 'recent20_cycles', 'recent20_cycle_net_per_avg_cost_pct')
            import math
            if not baseline.get('has_all_four_windows'):
                continue
            if any(not isinstance(r.get(k), (int, float)) or not math.isfinite(r[k])
                   for r in (x, baseline) for k in fields):
                continue
            if not all(x[k] > baseline[k] for k in fields[:2]):
                continue
            classification = classify(holding, x['code'], taxonomy)
            priority = all(x[k] >= baseline[k] for k in fields[2:])
            candidate = dict(x, classification=classification, status='priority' if priority else 'observe',
                             reason='中期往返与成本效率严格领先，近期两指标均不低于持仓' if priority else '中期两指标领先，但近期至少一指标落后',
                             retained_holding=retained, retained_correlation=x.get('corr_' + retained))
            if classification == 'unknown':
                candidate.update(status='observe', reason=candidate['reason'] + '；官方taxonomy待核，不能累计priority')
                unknown.append(candidate)
                continue
            track = 'same_class' if classification in ('same_index', 'same_theme') else 'cross_theme'
            if priority and groups[track]['priority'] is None:
                groups[track]['priority'] = candidate
            elif len(groups[track]['observe']) < 3:
                if priority:
                    candidate.update(status='observe', reason=candidate['reason'] + '；本线已有priority leader，仅观察')
                groups[track]['observe'].append(candidate)
        output['holdings'][holding] = dict(baseline=baseline, tracks=groups, unknown=unknown)
    return output


from pathlib import Path
from datetime import date, timedelta
import hashlib
import json
import os
import tempfile

STATE_VERSION = 'pair-review-v1'
DEFAULT_STATE = Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/rotation') / (STATE_VERSION + '.json')


DEFAULT_TAXONOMY = Path(__file__).with_name('taxonomy.json')


def run_pair_review(result, state_path=DEFAULT_STATE, taxonomy=None, name_exclusions=DEFAULT_NAME_EXCLUSIONS):
    if taxonomy is None and DEFAULT_TAXONOMY.exists():
        taxonomy = json.loads(DEFAULT_TAXONOMY.read_text(encoding='utf-8'))
    output = evaluate(result, taxonomy, name_exclusions)
    s = result['summary']
    day = date.fromisoformat(s['asof'])
    week = (day - timedelta(days=day.weekday())).isoformat()
    path = Path(state_path) if state_path is not None else None
    production = bool(path is not None and s.get('production_scope') and s.get('full_pool') and not s.get('offline'))
    degraded = bool(s.get('data_failed_runs', s.get('failed_runs', 0)) or s.get('fetch_errors', 0))
    fingerprint = hashlib.sha256(json.dumps(dict(
        method=STATE_VERSION, research=s.get('version'), taxonomy=taxonomy or {},
        filters=list(name_exclusions), coverage=sorted(x['code'] for x in result['ranking'] if x.get('has_all_four_windows')),
    ), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old = {}
    if production and path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
    if old.get('version') != STATE_VERSION:
        old = {}
    if old.get('week', '') > week:
        raise ValueError('cannot rewind pair weekly state')
    if old.get('fingerprint') != fingerprint:
        old = {}
    pairs = {}
    for holding, data in output['holdings'].items():
        for track, group in data['tracks'].items():
            key = holding + '/' + track
            candidate = group['priority']['code'] if group['priority'] else None
            previous = old.get('pairs', {}).get(key, {})
            count = 1 if candidate else 0
            if candidate and previous.get('candidate') == candidate:
                if old.get('week') == week:
                    count = previous['consecutive_weeks']
                elif old.get('week') == (date.fromisoformat(week) - timedelta(days=7)).isoformat():
                    count = previous['consecutive_weeks'] + 1
            if degraded:
                count = previous.get('consecutive_weeks', 0) if candidate and previous.get('candidate') == candidate else 0
            pairs[key] = dict(holding=holding, track=track, candidate=candidate,
                              consecutive_weeks=count, review_due=count >= 2 and production and not degraded,
                              executable=False)
    state = dict(version=STATE_VERSION, fingerprint=fingerprint, week=week, asof=s['asof'], pairs=pairs)
    if production and not degraded:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            if json.loads(path.read_text(encoding='utf-8')) != state:
                raise ValueError('pair state readback failed')
        finally:
            if os.path.exists(temp):os.unlink(temp)
    entries = (taxonomy or {}).get('assets', (taxonomy or {}).get('entries', {}))
    if not isinstance(entries, dict):
        entries = {}
    verified = {c for c, v in entries.items() if verified_entry(v)}
    universe = {x['code'] for x in result['ranking']} | set(result['holdings'])
    matched = {c for c in universe if verified_entry(taxonomy_entry(entries, c))}
    output['taxonomy_coverage'] = dict(verified_assets=len(verified), universe_verified=len(matched),
                                       unknown_assets=len(universe - matched))
    output.update(state=state, production_scope=production, degraded=degraded)
    return output


def _table(header, rows):
    """Markdown 表格（飞书可渲染）；header 为列名列表，rows 为每行单元格列表。"""
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---' for _ in header) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(c) for c in row) + ' |')
    return lines


def report_lines(output):
    lines = ['【逐持仓双轨周检】', '159992 exit-only：仅退出管理，不建立替换线。',
             'temporary name-based有限过滤：' + (' / '.join(output['name_exclusions']) or '关闭') + '；未改变生产资格池，不代表官方港股暴露分类。']
    coverage = output['taxonomy_coverage']
    lines.append(f"taxonomy已核{coverage['verified_assets']}只；本次池内已核{coverage['universe_verified']}只，未知待核{coverage['unknown_assets']}只（有限官方分类覆盖）。")
    lines.append('cross_theme仅按官方细分theme划线；细分分类不等于无重叠，科创板创新药与创新药仍可能有共同产业暴露，不代表组合互补。')
    lines.append('前后半窗展示稳定性；期末槽包括未退出持仓，不等同未闭合循环数；未闭合天数及占用/库存浮盈亏仅风险观察，不加波动或趋势硬否决。')
    # 2026-10-30 用户反馈“没有一点可读性”：双轨周检改 Markdown 表格渲染，
    # 数字逐格取自同一 dict 字段（表格交付铁律），禁止 300 字符机器长行。
    def fmt(v):return '不可用' if v is None else f'{v:g}'
    def pct(v):return '不可用' if v is None else f'{v:.2f}'
    def money(v):return '不可用' if v is None else f'{v:,.0f}'
    def half(cycles, efficiency):
        if cycles is None:return '不可用'
        return f'{fmt(cycles)}次/{pct(efficiency)}%'
    header = ['标的', '轨道', '身份', '中期往返', '成本效率%', '近20往返', '近20效率%',
              '净差价元', '前半', '后半', '未闭最长', '平均占用元', '库存浮亏元', '备注']
    def table_row(x, track, identity):
        early = half(x.get('early_cycles'), x.get('early_cycle_net_per_avg_cost_pct'))
        late = half(x.get('late_cycles'), x.get('late_cycle_net_per_avg_cost_pct'))
        corr = '不可用' if x.get('retained_correlation') is None else pct(x['retained_correlation'])
        # 备注列只放短标签：完整 reason 原文仍在 result 数据里，避免行宽爆炸。
        tags = []
        if 'taxonomy待核' in x.get('reason', ''):
            tags.append('待核')
        if x.get('retained_correlation') is not None and abs(x['retained_correlation']) >= .8:
            tags.append('高重叠')
        if '近期至少一指标落后' in x.get('reason', ''):
            tags.append('近期回落')
        if '已有priority leader' in x.get('reason', ''):
            tags.append('第二优先')
        return [f"{x['code']} {x.get('name','')}", track, identity,
                fmt(x.get('full_cycles')), pct(x.get('full_cycle_net_per_avg_cost_pct')),
                fmt(x.get('recent20_cycles')), pct(x.get('recent20_cycle_net_per_avg_cost_pct')),
                money(x.get('full_cycle_net')), early, late,
                fmt(x.get('full_max_unclosed_cycle_days')), money(x.get('full_avg_cost')),
                money(x.get('full_inventory_pnl')), corr + ('｜' + '｜'.join(tags) if tags else '')]
    def baseline_row(data):
        b = data['baseline']
        early = half(b.get('early_cycles'), b.get('early_cycle_net_per_avg_cost_pct'))
        late = half(b.get('late_cycles'), b.get('late_cycle_net_per_avg_cost_pct'))
        return [f"{b.get('code', '')} {b.get('name','')}", '基线', '持仓',
                fmt(b.get('full_cycles')), pct(b.get('full_cycle_net_per_avg_cost_pct')),
                fmt(b.get('recent20_cycles')), pct(b.get('recent20_cycle_net_per_avg_cost_pct')),
                money(b.get('full_cycle_net')), early, late,
                fmt(b.get('full_max_unclosed_cycle_days')), money(b.get('full_avg_cost')),
                money(b.get('full_inventory_pnl')), '期末占用' + money(b.get('full_end_cost')) + '元/槽' + fmt(b.get('full_end_slots'))]
    for holding, data in output['holdings'].items():
        lines.append(f"持仓{holding}（基线+替换候选，同一张表）")
        rows = [baseline_row(data)]
        track_names = {'same_class': '同类', 'cross_theme': '跨主题'}
        for track, group in data['tracks'].items():
            label = track_names.get(track, track)
            if group['priority']:
                rows.append(table_row(group['priority'], label, 'priority'))
            for x in group['observe']:
                rows.append(table_row(x, label, 'observe'))
        for x in data['unknown']:
            rows.append(table_row(x, '待核', 'observe'))
        lines.extend(_table(header, rows))
        lines.append('图例：轨道=同类/跨主题/待核；高重叠=abs corr≥0.8，仅提示不否决，不代表组合互补；待核=官方taxonomy未核不能累计priority；近期回落=近20日至少一指标落后。')
        signals = []
        for track, group in data['tracks'].items():
            signal = output['state']['pairs'][holding + '/' + track]
            if signal['review_due']:
                signals.append(f"{track_names.get(track, track)}触发 HUMAN_ROTATION_REVIEW {signal['candidate']}（连续{signal['consecutive_weeks']}周，仅人工复核，不授权换仓）")
            elif signal['candidate']:
                signals.append(f"{track_names.get(track, track)}候选{signal['candidate']}领先{signal['consecutive_weeks']}周，未达2周门槛")
            else:
                signals.append(f"{track_names.get(track, track)}无priority")
        lines.append('复核状态：' + '；'.join(signals) + '。')
    return lines
