"""周五轮换 TOP2 的不同大题材约束（2026-11-06 Master 授权）。

规则：TOP2 = 排名前两个**不同大题材**而非前两只 ETF。
- 为两个基准持仓（BASE）各找一个可替换做网格的代表，两个候选不得同题材。
- 先剔除两个持仓已占题材（保守口径：无法确定哪个保留，两个题材都排除）。
- 每题材只取一只代表（按 63 日往返次数 → 净差价 → 代码排序）。
- 与当前持仓并排给出 63 日 / 近 20 日往返次数与领先差额。

题材来源：官方 taxonomy（verified=True）优先；未核验时用名称粗分兜底，
并显式标注 name（非官方分类，不能累计 priority）。本模块只出观察报告，
不自动换仓、不生成买卖建议、不读写账本。
"""
try:
    from . import pair_review, research
except ImportError:  # 独立加载（tests 用 importlib.spec_from_file_location）
    import sys
    from pathlib import Path as _Path
    _root = str(_Path(__file__).resolve().parents[2])
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from tools.etf_research import pair_review, research

# 名称粗分：大题材 -> 关键词。按「大题材」而非细分主题聚类，
# 因为 Master 关心的是两个网格标的不能落在同一产业簇（如创新药各细分、
# 卫星/航空航天/军工/国防同属军工航天）。顺序敏感：先匹配到的优先。
MAJOR_THEME_RULES = (
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
    """名称 → 大题材；无法归类时返回 None（按代码单独成组，不静默合并）。"""
    text = str(name or '')
    for theme, keywords in MAJOR_THEME_RULES:
        if any(k in text for k in keywords):
            return theme
    return None


def theme_of(code, name, taxonomy):
    """返回 (题材键, 来源)。来源 ∈ {official, name, unknown}。

    官方 taxonomy 只在 verified_entry 通过时采信；名称粗分一律标注 name，
    绝不冒充官方分类（pair_review.classify 的口径：unknown 不能累计 priority）。
    """
    entry = pair_review.taxonomy_entry((taxonomy or {}).get('assets', (taxonomy or {}).get('entries', {})), code)
    if pair_review.verified_entry(entry):
        official = entry.get('theme', entry.get('theme_id'))
        if official:
            mapped = major_theme(official) or major_theme(entry.get('index_name', ''))
            return f'official:{mapped or official}', 'official'
    coarse = major_theme(name)
    if coarse:
        return f'name:{coarse}', 'name'
    return f'unknown:{code}', 'unknown'


def _holding_aliases():
    aliases = set()
    for code in research.HOLDINGS:
        aliases.update((code, code[-6:], 'sh' + code[-6:], 'sz' + code[-6:]))
    return aliases


def select_top2(result, taxonomy=None, admitted=None):
    """只读选取：返回 candidates / blocked / shortfall / executable。

    2026-11-06 Master 整改：候选须同时满足领先门槛与可建仓榜同口径，
    被拦原因逐条写进 blocked；无合格候选时不凑数（shortfall=True、candidates 为空）。
    admitted 为可选代码集合（来自 entry_rank.rank_entries 的 rows）：传入时只从
    该集合取候选，排除被双规则刷掉的标的；None 时保持原行为，兼容测试与离线调用。
    """
    aliases = _holding_aliases()
    holdings = result.get('holdings') or {}
    holding_names = set()
    for code in research.BASE:
        h = holdings.get(code) or {}
        name = h.get('name', '')
        # 名称粗分 + 官方分类都纳入，避免 taxonomy 已核的名称与粗分口径不一致时漏剔除。
        coarse = major_theme(name)
        if coarse:
            holding_names.add(coarse)
        theme, _ = theme_of(code, name, taxonomy)
        holding_names.add(theme.split(':', 1)[1] if ':' in theme else theme)

    def num(row, key):
        value = row.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    ranked = [r for r in (result.get('ranking') or [])
              if r.get('has_all_four_windows') and r.get('code') not in aliases
              and num(r, 'full_cycles') is not None and num(r, 'recent20_cycles') is not None]
    ranked.sort(key=lambda r: (-num(r, 'full_cycles'), -(num(r, 'full_cycle_net') or 0), r['code']))

    baseline = holdings.get(research.BASE[0]) or {}
    base_full, base_recent = num(baseline, 'full_cycles'), num(baseline, 'recent20_cycles')

    candidates, blocked, used = [], [], set()
    for row in ranked:
        theme, source = theme_of(row['code'], row.get('name', ''), taxonomy)
        short = theme.split(':', 1)[1] if ':' in theme else theme
        # 2026-11-06 Master 整改：两道门槛，被拦原因逐条写进 blocked。
        # ① 与可建仓榜同口径：只从本期双规则入选集合取候选（排除被刷掉的标的）。
        if admitted is not None and row['code'] not in admitted:
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason='未入选本期可建仓榜（时点建仓判定/近20日≥2/四窗口齐全双规则过滤），不进入观察候选'))
            continue
        # ② 领先对照基准持仓：63日往返须严格大于、近20日往返不得低于
        #    （与 engine.rotation_top10 的领先口径一致）。基准数据不可用时该维度不比较。
        full, recent = num(row, 'full_cycles'), num(row, 'recent20_cycles')
        if base_full is not None and (full is None or full <= base_full):
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason='63日往返未领先对照持仓'))
            continue
        if base_recent is not None and (recent is None or recent < base_recent):
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason='近20日往返落后对照持仓'))
            continue
        if short in used:
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason=f'与已选 TOP2 同题材（{short}），每题材只取一只代表'))
            continue
        if short in holding_names:
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason=f'与现有持仓题材相同（{short}），按保守口径剔除'))
            continue
        if source == 'unknown':
            # 与 pair_review 一致：官方 taxonomy 待核不能累计 priority，也不占 TOP2 正式名额。
            blocked.append(dict(code=row['code'], name=row.get('name', ''), theme=short,
                                reason='题材未识别，不占 TOP2 正式名额（需补官方 taxonomy 或大题材规则）'))
            continue
        if source != 'official':
            blocked_note = '官方taxonomy待核，仅名称粗分，不能累计priority' if source == 'name' else '题材未识别，单独成组'
        else:
            blocked_note = '官方已核题材'
        candidates.append(dict(
            code=row['code'], name=row.get('name', ''), theme=short, theme_source=source,
            theme_note=blocked_note,
            full_cycles=num(row, 'full_cycles'), full_cycle_net=num(row, 'full_cycle_net'),
            recent20_cycles=num(row, 'recent20_cycles'),
            baseline_code=research.BASE[0], baseline_full_cycles=base_full,
            baseline_recent20_cycles=base_recent,
            full_cycle_delta=None if base_full is None else num(row, 'full_cycles') - base_full,
            recent20_delta=None if base_recent is None else num(row, 'recent20_cycles') - base_recent,
            max_corr_to_base=num(row, 'max_corr_to_base'),
        ))
        used.add(short)
        if len(candidates) == 2:
            break
    return dict(candidates=candidates, blocked=blocked, shortfall=len(candidates) < 2,
                executable=False, holding_themes=sorted(holding_names),
                taxonomy_rule='官方 taxonomy 优先；名称粗分标注待核，不能累计 priority')


TOP2_TITLE = '【TOP2 观察候选·不同大题材（只报告，不自动换仓）】'


def report_lines(top2):
    """周报区块：观察候选对比表 + 表后解释（数字逐格取自 select_top2）。

    2026-11-06 Master 整改：本区块仅与对照基准比较往返次数，不构成替换建议。
    标题/表头/行首不得出现「替换候选」「持仓→候选」或持仓连候选的箭头。
    """
    # 模块顶部已按「包内导入 / 独立加载」两种方式备好 pair_review，
    # 统一复用，避免在 spec_from_file_location 独立加载时相对导入失败。
    _table = pair_review._table
    lines = [TOP2_TITLE,
             '约束：两个观察候选不得同题材；先剔除两个持仓已占题材；每题材只取一只代表。']
    rows = []
    for c in top2['candidates']:
        def fmt(v):
            return '不可用' if v is None else f'{v:g}'
        rows.append([
            f"{c['code']} {c['name']}",
            c['theme'], c['theme_source'], fmt(c['full_cycles']),
            fmt(c['baseline_full_cycles']), fmt(c['full_cycle_delta']),
            fmt(c['recent20_cycles']), fmt(c['baseline_recent20_cycles']),
            fmt(c['recent20_delta']), c['theme_note'],
        ])
    if rows:
        lines.extend(_table(
            ['观察标的', '大题材', '题材来源', '63日往返', '持仓往返', '领先差额',
             '近20往返', '持仓近20', '近期差额', '备注'], rows))
    else:
        lines.append('无同时满足领先条件与建仓规则的候选（不凑数，不用落后或同题材标的替代）。')
    if top2['shortfall']:
        lines.append('可用大题材不足两个，按实际数量呈现，不用同题材标的凑数。')
    baseline = (top2['candidates'][0]['baseline_code'] if top2['candidates']
                else research.BASE[0])
    lines.append(f'对照基准 {baseline} 仅用于比较往返次数，不是待替换标的。')
    lines.append('表后说明：中期与近期差额分别看 63 日 / 近 20 日完整模拟往返；'
                 '同窗模拟非真实成交，领先不等于可执行。')
    lines.append(f"与保留持仓的最大相关性见综合排名；"
                 f"已剔除持仓题材 {('、'.join(top2['holding_themes']) or '无')}。")
    lines.append('数据覆盖降级时不推进连续周状态、不触发复核门槛；'
                 '名称粗分待核不计入优先资格；本区块只报告，不授权换仓、不生成买卖建议。')
    lines.append('本区块不生成替换建议，仅与对照基准比较往返次数。')
    return lines


def digest_lines(top2):
    """飞书精简摘要必须带 TOP2（2026-10-24 教训：定时推送的是 summarize）。"""
    lines = [TOP2_TITLE]
    for c in top2['candidates']:
        lines.append(
            f"{c['code']} {c['name']}｜{c['theme']}（{c['theme_source']}）｜"
            f"63日往返{c['full_cycles']:g}次｜近20日{c['recent20_cycles']:g}次｜仅观察")
    if top2['shortfall']:
        lines.append('可用大题材不足两个，不凑数。')
    # 与 report_lines 同口径：本区块不生成替换建议；合并进末行，保持精简摘要行数上限。
    lines.append('两个观察候选不同题材；只报告不自动换仓；本区块不生成替换建议。')
    return lines
