# -*- coding: utf-8 -*-
"""每日 ETF 轻量快照（2026-11-06 Master 授权，只读观察任务，TDD 落地）。

设计（来自 10:1x 只读评估）：不每天全量重跑 321 只 × 63 日 × 4 窗口的 5 分钟
回测（1284 次模拟、105MB、窗口滑动使名次差无解释力、coverage_signature 天天变
会清零连续周计数）。改为：收盘后只读最近一期周频 result.json / entry-ranking.csv，
沿用其 rank/score/cycles/net/theme 并标 source_asof，日频不得重算；只对观察池取
当日日K，刷新 close / 振幅 / 量比 / regime20 / net20 / er20 六个轻量观测量，
落盘 append-only 的 jsonl；带窗口对齐与 delta_reason 归因，换窗当日不把名次差
当趋势。

只读边界（违反即算失败）：
- 只处理 the agent harness 副本根 .cache/grid-home（HERMES_HOME 由 run_and_push
  设定为该副本根）；脚本内不出现、不读取、不对比 Hermes 生产根路径。
- 绝不写 confirmed-*.json / holdings.json / regime-cache.json / rotation 连续周
  状态 / weekly-report.txt / 任何 rerank-* 目录；唯一落点是
  cache/grid-research/daily-snapshots/YYYY-MM-DD.jsonl。
- 不改 research / engine / grid_model / weekly / entry_rank 的模拟与排名逻辑，
  不读写交易参数，不改账本与任务状态。
- 输出只有观察数据与变化提示，不含任何买卖/操作建议词。

字段口径：
- 周频字段（存在才写，缺失写 null 并记 data_gap，禁止编造数字）：
  rank_research（result.json ranking 序位）、rank_entry（entry-ranking.csv rank）、
  score / full_cycles / full_cycle_net / recent20_cycles / has_all_four_windows /
  recent20_start（result.json ranking 列）、major_theme（名称粗分）、
  window_start / window_end / degraded / latest_claim（result.json summary），
  coverage_signature（与 weekly.py 同算法的完整四窗口代码集合签名）、
  window_anchor_price（周频产物无此列 → null + data_gap，不臆造）。
- 日频观测（全部由当日日K现算，数据不足写 null + data_gap）：
  close（最新收盘）、amplitude_pct = (high-low)/open*100、
  volume_ratio = 当日量 / 前20日量中位数、net20_pct = 近20交易日收盘涨跌幅、
  er20 = Kaufman 效率系数（净位移 / 路径长度，21 根收盘）、
  regime20 = er20 >= ER_TREND_TH 记「趋势」否则「震荡」（er20 不可用则 null）。
- 归因字段：window_shifted / delta_reason / delta_rank。
  delta_reason ∈ {price, coverage_change, window_shift, theme_cap, initial}。
  仅当 window_start / window_end 与上一交易日快照相同且 coverage_signature
  相同（或明确「window_start 相同、window_end 仅新增 1 个交易日、签名不变」）
  时才计算 delta_rank；否则 window_shifted=true、delta_rank=null。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 规格 point 3：一行一标的的 28 个字段。
FIELDS = (
    'asof', 'code', 'name', 'major_theme', 'source_asof',
    'rank_research', 'rank_entry', 'score', 'full_cycles', 'full_cycle_net',
    'recent20_cycles', 'has_all_four_windows', 'degraded', 'latest_claim',
    'window_start', 'window_end', 'recent20_start', 'coverage_signature',
    'window_anchor_price', 'window_shifted', 'delta_reason', 'delta_rank',
    'close', 'amplitude_pct', 'volume_ratio', 'regime20', 'net20_pct', 'er20',
)
WEEKLY_KEYS = (
    'name', 'major_theme', 'source_asof', 'rank_research', 'rank_entry',
    'score', 'full_cycles', 'full_cycle_net', 'recent20_cycles',
    'has_all_four_windows', 'degraded', 'latest_claim', 'window_start',
    'window_end', 'recent20_start', 'coverage_signature', 'window_anchor_price',
)
DAILY_KEYS = ('close', 'amplitude_pct', 'volume_ratio', 'regime20', 'net20_pct', 'er20')
DELTA_REASONS = ('price', 'coverage_change', 'window_shift', 'theme_cap', 'initial')
RANK_SIGNIFICANT = 20     # |delta_rank| >= 20 且未换窗才视为显著名次变化
ER_TREND_TH = 0.4         # er20 效率系数判「趋势/震荡」阈值
MIN_HISTORY = 21          # 近20日指标需 21 根收盘
VOLUME_BASE = 20          # 量比基线窗口

SYSTEM_PY = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'

# 展示用大题材粗分（与 tools/etf_research/rotation_top2.py MAJOR_THEME_RULES 同口径；
# 只在本地做观察分类，不 import 研究模块、不触碰排名逻辑、不写账本）。顺序敏感。
_MAJOR_THEME_RULES = (
    ('军工航天', ('卫星', '航天', '航空', '军工', '国防', '兵器', '装备')),
    ('医药创新药', ('创新药', '医药', '医疗', '生物', '疫苗', '中药', '恒生医疗')),
    ('人工智能机器人', ('人工智能', '机器人', '智能', 'AI')),
    ('半导体芯片', ('芯片', '半导体', '集成电路', '科创芯片')),
    ('通信电子', ('通信', '电子', '消费电子', '5G', '云计算', '大数据', '计算机', '软件')),
    ('新能源', ('新能源', '光伏', '锂电', '电池', '风电', '储能')),
    ('资源能源', ('煤炭', '石油', '有色', '稀土', '化工', '钢铁', '黄金', '资源', '能源')),
    ('金融地产', ('证券', '券商', '银行', '保险', '金融科技', '房地产', '地产')),
    ('消费', ('消费', '白酒', '食品', '饮料', '家电', '养殖', '农业', '旅游')),
    ('文化传媒', ('传媒', '影视', '游戏', '文化', '动漫', '出版', '娱乐')),
    ('基建公用', ('基建', '建筑', '建材', '电力', '公用', '水务', '环保', '交通')),
    ('宽基指数', ('沪深300', '中证500', '中证1000', '上证50', '科创100', '科创50',
                  '创业板', 'A500', '深证100', '中证100', '成长ETF', '价值ETF')),
)


def major_theme(name):
    """名称 → 大题材；无法归类返回 None（不臆造分类 → null + data_gap）。"""
    text = str(name or '')
    for theme, keywords in _MAJOR_THEME_RULES:
        if any(k in text for k in keywords):
            return theme
    return None


def daily_snapshot_path(root, asof):
    """唯一落点：root/cache/grid-research/daily-snapshots/YYYY-MM-DD.jsonl。"""
    return Path(root) / 'cache' / 'grid-research' / 'daily-snapshots' / f'{asof}.jsonl'


def _research_root(root):
    return Path(root) / 'cache' / 'grid-research'


def _latest_research_dir(root):
    """cache/grid-research 下 mtime 最新、且含 result.json 的目录；排除 daily-snapshots 自身。

    绝不写进 rerank-* 目录；daily-snapshots 既按名字排除，也因不含 result.json
    不会入选（volatility_expansion_watch.py 的观察池依赖最新目录的 entry-ranking.csv）。
    """
    base = _research_root(root)
    if not base.exists():
        return None
    candidates = [d for d in base.iterdir()
                  if d.is_dir() and d.name != 'daily-snapshots'
                  and (d / 'result.json').exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.stat().st_mtime)


def _coverage_signature(ranking):
    """与 weekly.py:106 同算法：完整四窗口代码排序后的 sha256。"""
    codes = sorted(str(x['code']) for x in ranking if x.get('has_all_four_windows'))
    return hashlib.sha256('|'.join(codes).encode()).hexdigest()


def _num(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_weekly(research_dir):
    """只读加载最近一期周频研究：summary + ranking + entry-ranking。

    research_dir 为 None / 文件缺失时返回空壳（所有周频字段 → null + data_gap），
    绝不臆造数字。返回 {summary 级字段..., rows: {code: {周频逐标的字段}}}。
    """
    weekly = dict(source_asof=None, window_start=None, window_end=None,
                  degraded=None, latest_claim=None, coverage_signature=None,
                  window_anchor_price=None, rows={})
    if research_dir is None:
        return weekly
    rd = Path(research_dir)
    result = {}
    rp = rd / 'result.json'
    if rp.exists():
        try:
            result = json.loads(rp.read_text(encoding='utf-8')) or {}
        except (ValueError, OSError):
            result = {}
    summary = result.get('summary') or {}
    ranking = result.get('ranking') or []
    if not summary and (rd / 'summary.json').exists():
        try:
            summary = json.loads((rd / 'summary.json').read_text(encoding='utf-8')) or {}
        except (ValueError, OSError):
            summary = {}

    weekly['source_asof'] = summary.get('asof')
    weekly['window_start'] = summary.get('window_start')
    weekly['window_end'] = summary.get('window_end')
    weekly['latest_claim'] = summary.get('latest_claim')
    failed = summary.get('data_failed_runs', summary.get('failed_runs', 0)) or 0
    weekly['degraded'] = bool(failed or (summary.get('fetch_errors', 0) or 0))
    weekly['coverage_signature'] = (summary.get('coverage_signature')
                                    or (_coverage_signature(ranking) if ranking else None))
    weekly['window_anchor_price'] = summary.get('window_anchor_price')

    # entry-ranking.csv：rank_entry 与名称（不新增标的池）。
    entry = {}
    ep = rd / 'entry-ranking.csv'
    if ep.exists():
        try:
            with ep.open(encoding='utf-8-sig') as fh:
                for r in csv.DictReader(fh):
                    code = (r.get('code') or '').strip()
                    if not code:
                        continue
                    entry[code] = dict(rank_entry=_num(r.get('rank')),
                                       name=r.get('name') or code)
        except (OSError, ValueError):
            pass

    for i, row in enumerate(ranking):
        code = (row.get('code') or '').strip()
        if not code:
            continue
        e = entry.get(code, {})
        name = row.get('name') or e.get('name') or code
        weekly['rows'][code] = dict(
            name=name, major_theme=major_theme(name),
            rank_research=i + 1, rank_entry=e.get('rank_entry'),
            score=_num(row.get('score')),
            full_cycles=_num(row.get('full_cycles')),
            full_cycle_net=_num(row.get('full_cycle_net')),
            recent20_cycles=_num(row.get('recent20_cycles')),
            has_all_four_windows=bool(row.get('has_all_four_windows')),
            recent20_start=row.get('recent20_start'),
        )
    return weekly


def _universe(root, research_dir=None):
    """观察池 = 最新一期 entry-ranking.csv 全量行；不新增标的池。"""
    rd = research_dir or _latest_research_dir(root)
    if rd is None:
        return []
    ep = Path(rd) / 'entry-ranking.csv'
    if not ep.exists():
        return []
    codes = []
    try:
        with ep.open(encoding='utf-8-sig') as fh:
            for r in csv.DictReader(fh):
                code = (r.get('code') or '').strip()
                if code:
                    codes.append((code, r.get('name') or code))
    except (OSError, ValueError):
        return []
    return codes


def to_secid(code):
    """观察池代码 → 腾讯 secid：5/6 开头归上交所(1.)，其余归深交所(0.)。

    兼容纯 6 位、sh/sz 前缀、已规范化的 1./0. 前缀三种格式。
    """
    text = str(code).strip().lower()
    if '.' in text and text.split('.', 1)[0] in ('0', '1'):
        return text
    digits = text[2:] if text[:2] in ('sh', 'sz') else text
    if not digits.isdigit() or len(digits) != 6:
        raise ValueError(f'无法识别的标的代码：{code}')
    return ('1.' if digits[0] in ('5', '6') else '0.') + digits


def _get_kline_fetcher():
    """延迟导入，避免无关 job / 离线夹具多加载一次重模块。"""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from tools.market_phase_check import fetch_tencent_kline
    return fetch_tencent_kline


def _fetch_daily(secid, lmt=40):
    """生产取数：腾讯日K（klt=101，end 留空，2026-11-04 口径）。"""
    rows = _get_kline_fetcher()(to_secid(secid), lmt=lmt, klt='101')
    return [dict(date=r.get('date'), open=_num(r.get('open')),
                 high=_num(r.get('high')), low=_num(r.get('low')),
                 close=_num(r.get('close')), volume=_num(r.get('volume')) or 0)
            for r in (rows or [])]


def _amplitude(row):
    """日振幅 % = (high-low)/open。缺项/非法返回 None。"""
    o, hi, lo = _num(row.get('open')), _num(row.get('high')), _num(row.get('low'))
    if o is None or hi is None or lo is None or o <= 0 or hi < lo:
        return None
    return round((hi - lo) / o * 100.0, 4)


def _daily_metrics(bars):
    """由当日日K现算 6 个轻量观测量；数据不足写 None（→ data_gap），不臆造。"""
    out = {k: None for k in DAILY_KEYS}
    rows = [b for b in (bars or []) if isinstance(b, dict)]
    if not rows:
        return out
    last = rows[-1]
    out['close'] = _num(last.get('close'))
    out['amplitude_pct'] = _amplitude(last)

    # 量比 = 当日量 / 前 20 日量中位数
    idx = len(rows) - 1
    if idx >= VOLUME_BASE:
        try:
            current = _num(rows[idx].get('volume')) or 0
            base = [(_num(r.get('volume')) or 0) for r in rows[idx - VOLUME_BASE:idx]]
            med = statistics.median(base)
            if current > 0 and med > 0:
                out['volume_ratio'] = round(current / med, 4)
        except (TypeError, ValueError, statistics.StatisticsError):
            pass

    closes = [_num(r.get('close')) for r in rows]
    if len(closes) >= MIN_HISTORY and all(c is not None for c in closes[-MIN_HISTORY:]):
        window = closes[-MIN_HISTORY:]
        c0, c1 = window[0], window[-1]
        if c0 and c0 > 0:
            out['net20_pct'] = round((c1 / c0 - 1.0) * 100.0, 4)
        path = sum(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
        if path > 0:
            er = round(abs(c1 - c0) / path, 4)
            out['er20'] = er
            out['regime20'] = '趋势' if er >= ER_TREND_TH else '震荡'
    return out


def _one_session_added(prev_end, cur_end):
    """window_end 是否仅新增 1 个交易日（1 天，或跨周末的 2~3 天）。"""
    try:
        d0 = date.fromisoformat(str(prev_end))
        d1 = date.fromisoformat(str(cur_end))
    except (TypeError, ValueError):
        return False
    return 1 <= (d1 - d0).days <= 3


def _window_decision(weekly_row, prev):
    """返回 (window_shifted, delta_reason)。换窗当日不得把名次差当趋势。"""
    if not prev:
        return False, 'initial'
    cs = weekly_row.get('window_start')
    ce = weekly_row.get('window_end')
    cc = weekly_row.get('coverage_signature')
    ps = prev.get('window_start')
    pe = prev.get('window_end')
    pc = prev.get('coverage_signature')
    same_cov = cc is not None and cc == pc
    if cs == ps and ce == pe and same_cov:
        return False, 'price'
    # 明确「仅新增 1 个交易日且 coverage_signature 不变」也算对齐
    if cs == ps and same_cov and _one_session_added(pe, ce):
        return False, 'price'
    if not same_cov:
        return True, 'coverage_change'
    return True, 'window_shift'


def evaluate(code, weekly_row, daily, prev=None, asof=None, theme_changed=False):
    """构造一行快照（28 字段 + data_gap）。纯函数，不落盘、不触网。"""
    row = {k: None for k in FIELDS}
    row['asof'] = asof or date.today().isoformat()
    row['code'] = code
    weekly_row = dict(weekly_row or {})
    daily = dict(daily or {})
    for k in WEEKLY_KEYS:
        row[k] = weekly_row.get(k)
    for k in DAILY_KEYS:
        row[k] = daily.get(k)

    shifted, reason = _window_decision(row, prev)
    if reason == 'price' and (theme_changed or
                              (prev and prev.get('major_theme') != row.get('major_theme'))):
        reason = 'theme_cap'
    row['window_shifted'] = shifted
    row['delta_reason'] = reason
    if reason in ('price', 'theme_cap') and prev:
        pr, cr = prev.get('rank_research'), row.get('rank_research')
        if isinstance(pr, (int, float)) and isinstance(cr, (int, float)):
            row['delta_rank'] = int(pr - cr)  # 正=名次前移
        else:
            row['delta_rank'] = None
    else:
        row['delta_rank'] = None

    # 缺失写 null 并记 data_gap（归因字段不参与；不臆造数字）。
    row['data_gap'] = sorted(k for k in (WEEKLY_KEYS + DAILY_KEYS)
                             if row.get(k) is None)
    return row


def _theme_distribution_changed(rows, prev_rows):
    from collections import Counter
    if not prev_rows:
        return False
    cur = Counter(r.get('major_theme') for r in rows)
    prev = Counter(r.get('major_theme') for r in prev_rows)
    return cur != prev


def render(rows, failures=None, prev_rows=None, compare=False):
    """简短中文观察文本；无显著变化且无取数失败时返回空串（wrapper 静默）。

    禁止任何买卖/操作建议词；含固定免责声明；取数失败必须披露有限样本观察池。
    """
    rows = list(rows or [])
    failures = list(failures or [])
    first_run = bool(rows) and all(r.get('delta_reason') == 'initial' for r in rows)
    big = [r for r in rows if r.get('delta_rank') is not None
           and abs(r['delta_rank']) >= RANK_SIGNIFICANT and not r.get('window_shifted')]
    theme_change = _theme_distribution_changed(rows, prev_rows)
    if not (failures or first_run or big or theme_change or (compare and rows and prev_rows)):
        return ''

    asof = rows[0].get('asof') if rows else '—'
    source = rows[0].get('source_asof') if rows else None
    lines = ['【每日ETF轻量快照·仅观察】',
             f'快照日 {asof}｜观察池 {len(rows)} 只'
             f'｜周频来源 source_asof {source or "不可用"}']
    if first_run:
        lines.append('首次落盘：仅记录当日观察量，未与上一交易日对齐，不呈现名次趋势。')
    if big:
        for r in big[:5]:
            lines.append(f'{r.get("code")}｜名次变动 {r["delta_rank"]:+d}'
                         f'（窗口对齐、未换窗；题材归因 {r.get("delta_reason")}）')
    if theme_change:
        lines.append('题材分布较上一交易日发生变化（题材限额口径，仅观察）。')
    if compare and rows and prev_rows:
        lines.append(f'窗口对齐对比：已对齐 {sum(1 for r in rows if not r.get("window_shifted"))} 只、'
                     f'换窗 {sum(1 for r in rows if r.get("window_shifted"))} 只。')
    if failures:
        lines.append(f'⚠️ 取数失败 {len(failures)} 只｜有限样本观察池：'
                     '未覆盖失败标的，不得据此断言全池无变化。')
    lines.append('说明：名次/评分/往返/净额/题材沿用最近一期周频研究并标 source_asof，'
                 '日频不重算；收盘价/振幅/量比/近20日涨跌幅/效率系数/市况为当日日K观察量。')
    lines.append('仅观察，不构成操作依据；不改动持仓、账本与任务状态。')
    return '\n'.join(lines)


def _load_previous_snapshot(root, asof):
    """只读上一交易日快照（文件名 < asof 的最新一份），返回 {code: row}。"""
    base = daily_snapshot_path(root, asof).parent
    if not base.exists():
        return {}
    candidates = [p for p in base.glob('????-??-??.jsonl') if p.stem < str(asof)]
    if not candidates:
        return {}
    latest = max(candidates, key=lambda p: p.stem)
    rows = {}
    try:
        for line in latest.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get('code'):
                rows[r['code']] = r
    except OSError:
        return {}
    return rows


def _append_snapshot(root, asof, rows):
    """append-only 写入 daily-snapshots/YYYY-MM-DD.jsonl，一行一标的。"""
    path = daily_snapshot_path(root, asof)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    return path


def _resolve_root(account_root=None):
    """只认传入副本根 / HERMES_HOME / 仓库内 .cache/grid-home；不引用生产根。"""
    if account_root:
        return Path(account_root)
    env = os.environ.get('HERMES_HOME')
    if env:
        return Path(env)
    return REPO / '.cache' / 'grid-home'


def _weekly_for(weekly, code, name=None):
    """把周频 summary + 逐标的列合成 evaluate 需要的扁平 weekly_row。"""
    per = weekly.get('rows', {}).get(code, {})
    disp = per.get('name') or name or code
    return dict(
        code=code, name=disp,
        major_theme=per.get('major_theme') or major_theme(disp),
        source_asof=weekly.get('source_asof'),
        rank_research=per.get('rank_research'), rank_entry=per.get('rank_entry'),
        score=per.get('score'), full_cycles=per.get('full_cycles'),
        full_cycle_net=per.get('full_cycle_net'),
        recent20_cycles=per.get('recent20_cycles'),
        has_all_four_windows=per.get('has_all_four_windows'),
        degraded=weekly.get('degraded'), latest_claim=weekly.get('latest_claim'),
        window_start=weekly.get('window_start'), window_end=weekly.get('window_end'),
        recent20_start=per.get('recent20_start'),
        coverage_signature=weekly.get('coverage_signature'),
        window_anchor_price=weekly.get('window_anchor_price'),
    )


def run(fixture_path=None, account_root=None, fetch=None, limit=None,
        compare=False, asof=None):
    """只读执行：fixture 注入优先（离线测试）；否则读周频研究 + 当日日K。

    返回待 wrapper 处理的文本（push=off 时只记录不推送）；快照 append-only 落盘。
    """
    root = _resolve_root(account_root)
    asof = asof or date.today().isoformat()
    research_dir = _latest_research_dir(root)
    weekly = _load_weekly(research_dir)
    prev_by_code = _load_previous_snapshot(root, asof)
    prev_flat = list(prev_by_code.values())

    if fixture_path is not None:
        data = json.loads(Path(fixture_path).read_text(encoding='utf-8'))
        pairs = [(code, code, rows) for code, rows in data.items()]
        if limit:
            pairs = pairs[:limit]
        failures = []
    else:
        universe = _universe(root, research_dir=research_dir)
        if limit:
            universe = universe[:limit]
        fetch = fetch or _fetch_daily
        pairs, failures = [], []
        for code, name in universe:
            try:
                pairs.append((code, name, fetch(code)))
            except Exception:
                failures.append(code)  # 单只失败不影响其余，但必须披露缺口

    rows = []
    for code, name, bars in pairs:
        wrow = _weekly_for(weekly, code, name)
        daily = _daily_metrics(bars)
        prev = prev_by_code.get(code)
        theme_changed = bool(prev and prev.get('major_theme') != wrow.get('major_theme'))
        rows.append(evaluate(code, wrow, daily, prev=prev, asof=asof,
                             theme_changed=theme_changed))
    _append_snapshot(root, asof, rows)
    return render(rows, failures=failures, prev_rows=prev_flat, compare=compare)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='每日 ETF 轻量快照（只读观察）')
    p.add_argument('--fixture-path', help='离线夹具 JSON：{code: [日线行]}')
    p.add_argument('--account-root', help='副本账本根（只读周频研究；唯一写入 daily-snapshots）')
    p.add_argument('--limit', type=int, help='限制观察池数量（生产调试用）')
    p.add_argument('--compare', action='store_true', help='附带窗口对齐对比摘要')
    args = p.parse_args(argv)
    text = run(fixture_path=args.fixture_path, account_root=args.account_root,
               limit=args.limit, compare=args.compare)
    if text:
        print(text)
    return text


if __name__ == '__main__':
    main()
