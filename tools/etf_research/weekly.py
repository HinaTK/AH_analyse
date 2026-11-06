"""Weekly reporting only: call research once, no second simulation/model."""
from pathlib import Path
from datetime import date, timedelta
import json
from . import research, pair_review, rotation_top2
from .entry_rank import rank_entries, render_markdown
from .engine import dump
from .pair_review import _table as _md_table
STATE_VERSION=research.VERSION+'-rotation-streak-v1'
DEFAULT_STATE=pair_review.ROTATION_DIR/f'{STATE_VERSION}.json'  # 跟随 HERMES_HOME，见 pair_review.ROTATION_DIR
# 榜单区块唯一标题：周报/摘要/测试三方共用，禁止任何一方手写。
# 2026-10-24 教训：测试手写子串与实现表头不一致，误判功能缺失。
ENTRY_BLOCK_TITLE='【可建仓候选·双规则过滤（五线全破暂停买入+近20日往返<2出榜，持仓豁免）】'

def entry_rank_block(result, output, top_n=20, digest_n=3):
    """生成双规则榜单的两个渲染面：(完整周报行, 飞书精简摘要行)。

    规则（2026-10-23 起，2026-10-26 语义校准）：五线全破暂停买入 + 候选近20日往返<2 出榜，
    持仓豁免保留。所有数字来自 rank_entries 的 rows——周报表格由
    entry_rank.render_markdown 原样渲染，摘要行也由本函数从 rows
    逐格生成，聊天层/推送层禁止改写任何数字（表格交付铁律）。
    失败不再静默（2026-10-24 整改）：返回带 ⚠️ 的可见行。
    """
    if not output:
        warn = '⚠️ 本次研究无 output_path，榜单未生成——请检查研究目录配置。'
        return [ENTRY_BLOCK_TITLE, warn], [ENTRY_BLOCK_TITLE, warn]
    try:
        report = rank_entries(Path(output))
    except Exception as exc:
        warn = f'⚠️ 榜单生成失败：{exc}——完整榜单缺失，请检查研究目录 bars/result.json。'
        return [ENTRY_BLOCK_TITLE, warn], [ENTRY_BLOCK_TITLE, warn]
    rows = report['rows']
    excluded = report['excluded']
    head = (f"asof {report['asof']} 入选 {len(rows)} 只；排除：时点暂停买入{excluded.get('timing', 0)}、"
            f"近20日不足{excluded.get('recent20', 0)}、四窗口不全{excluded.get('incomplete', 0)}")
    if not rows:
        tail = '；无入选标的（候选全部被双规则过滤或无完整四窗口数据）。'
        return [ENTRY_BLOCK_TITLE, head + tail], [ENTRY_BLOCK_TITLE, head + tail]
    # 完整周报：表格数字逐格来自 render_markdown，禁止任何第二渲染器
    table = render_markdown(report, top_n=top_n)
    report_lines = [ENTRY_BLOCK_TITLE, head, '', table]
    # 飞书精简摘要：每行数字同样逐格取自 rows，且必须与表格同源——
    # 2026-11-06 起表格按题材限额，摘要必须走同一 cap_per_theme。
    from .entry_rank import cap_per_theme
    shown = cap_per_theme(rows)['rows']
    digest = [ENTRY_BLOCK_TITLE, head]
    for row in shown[:digest_n]:
        digest.append(
            f"{row['rank']}. {row['code']} {row['name']}｜{row['label']}｜"
            f"63日往返{row['full_cycles']:.0f}次｜净差价{row['full_cycle_net']:,.2f}元｜"
            f"近20日{row['recent20_cycles']:.0f}次")
    if len(shown) > digest_n:
        digest.append(f"……共{len(shown)}只入选，完整表见 weekly-report.txt 与 entry-ranking.csv")
    return report_lines, digest

def _first_open(res):
    """从只读 result 里取「完整窗口首根开盘价」；取不到返回 None（不编造数字）。"""
    if not isinstance(res, dict):
        return None
    summary = res.get('summary') or {}
    for key in ('window_first_open', 'first_open', 'anchor_first_open'):
        value = summary.get(key, res.get(key))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
    return None


def _fit_width(line, width=120):
    """按中文分号把长披露行折成 ≤width 的多行，不丢信息、不改写数字。"""
    if len(line) <= width:
        return [line]
    segments = str(line).split('；')
    out, buf = [], ''
    for index, seg in enumerate(segments):
        piece = seg + ('；' if index < len(segments) - 1 else '')
        if buf and len(buf) + len(piece) > width:
            out.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        out.append(buf)
    final = []
    for part in out:
        while len(part) > width:
            final.append(part[:width]); part = part[width:]
        if part:
            final.append(part)
    return final


def _anchor_disclosure_lines(result, prev_result):
    """只读锚价位移披露：两期窗口首根开盘价 → anchor_sensitivity.disclosure_lines。

    数据只取自本次与上一期 result；不联网、不跑研究/回测、不改生产排名数字。
    无上一期或无法计算时输出「略过」文案，不报错、不编造数字。
    """
    skip = ['锚价位移披露：本期无可比上期基准，略过']
    if not isinstance(prev_result, dict):
        return skip
    prev_open, curr_open = _first_open(prev_result), _first_open(result)
    prev_asof = (prev_result.get('summary') or {}).get('asof')
    curr_asof = (result.get('summary') or {}).get('asof')
    if not (prev_open and curr_open and prev_asof and curr_asof):
        return skip
    try:
        from . import anchor_sensitivity as anchor
        lines = anchor.disclosure_lines(
            anchor.anchor_of_first_open(prev_open, prev_asof),
            anchor.anchor_of_first_open(curr_open, curr_asof),
            prev_asof, curr_asof)
    except Exception:
        return skip
    return [fitted for line in lines for fitted in _fit_width(line)]


def _admitted_codes(result):
    """本期可建仓榜入选代码集合；无 output 或榜单生成失败时返回 None 保持兼容。

    TOP2 与可建仓榜同口径（时点建仓判定/近20日≥2/四窗口齐全双规则）：
    只把 entry_rank.rank_entries 的入选代码交给 select_top2，避免推出被刷掉的标的。
    """
    output=(result.get('summary') or {}).get('output_path')
    if not output:return None
    try:
        return {x['code'] for x in rank_entries(Path(output))['rows']}
    except Exception:
        return None


def summarize(result, pairs=None, entry_digest=None):
    """Compact push digest; the full weekly report stays in weekly-report.txt."""
    s=result['summary']
    degraded=bool(s.get('data_failed_runs',s.get('failed_runs',0)) or s.get('fetch_errors',0))
    def number(v):return '不可用' if v is None else str(int(v))
    def money(v):return '不可用' if v is None else f'{v:,.2f}'
    lines=['【每周ETF轮换研究·精简】',
           f"{s.get('asof','未知')}：资格池{s.get('attempted_assets','未知')}只，共同窗口{s.get('window_start','未知')}→{s.get('window_end','未知')}；成功{number(s.get('successful_runs'))}/失败{number(s.get('failed_runs'))}。",
           '数据覆盖降级：连续周状态不推进，不触发复核门槛。' if degraded else '数据覆盖完整：连续周状态正常推进。']
    state=((pairs or {}).get('state') or {}).get('pairs') or {}
    due=[(k,v) for k,v in state.items() if v.get('review_due')]
    leaders=[(k,v) for k,v in state.items() if v.get('candidate')]
    lines.extend(f"🔔 人工复核触发：{k.replace('/',' ')} → {v['candidate']}（连续{v['consecutive_weeks']}周）。" for k,v in due)
    if not due:lines.append('轮换复核：未触发' + ('（pair状态不可用）。' if not state else '（无连续2周priority领先）。'))
    if leaders:lines.append('priority领先：'+'；'.join(f"{v['candidate']} 领先 {k.split('/')[0]}（{k.split('/')[1]}，连续{v['consecutive_weeks']}周）" for k,v in leaders))
    lines.append('【三持仓·只展示】')
    for c in research.HOLDINGS:
        x=result['holdings'].get(c) or {}
        lines.append(f"{c}：往返{number(x.get('full_cycles'))}次；净差价{money(x.get('full_cycle_net'))}元")
    if entry_digest is not None:lines.extend(entry_digest)
    top2=result.get('top2_rotation')
    if top2 is not None:lines.extend(rotation_top2.digest_lines(top2))
    items=[];seen=set()
    for x in [result.get('leader'),*(result.get('rotation_top10') or [])]:
        if x and x.get('code') not in seen:seen.add(x.get('code'));items.append(x)
    if items:lines.append('【往返前列】'+'；'.join(f"{x['code']} {number(x.get('full_cycles'))}次/{money(x.get('full_cycle_net'))}元" for x in items[:3]))
    out=s.get('output_path')
    if out:lines.append(f"完整报告：{out}/weekly-report.txt（轮换复核状态、可建仓候选、往返前10、观察候选、免责声明）。")
    return '\n'.join(lines)


def run_weekly(state_path=DEFAULT_STATE,research_runner=None,pair_state_path=None,taxonomy=None,
               taxonomy_path=None,name_exclusions=pair_review.DEFAULT_NAME_EXCLUSIONS,prev_result=None,**kwargs):
    if taxonomy_path:
        if taxonomy is not None:raise ValueError('use taxonomy or taxonomy_path, not both')
        taxonomy=json.loads(Path(taxonomy_path).read_text(encoding='utf-8'))
    result=(research_runner or research.run_research)(**kwargs)
    # An explicitly custom legacy path keeps test/validation outputs isolated too.
    pair_path=pair_state_path or (pair_review.DEFAULT_STATE if Path(state_path)==DEFAULT_STATE else Path(state_path).with_name('pair-review-v1.json'))
    pairs=pair_review.run_pair_review(result,state_path=pair_path,taxonomy=taxonomy,name_exclusions=name_exclusions)
    # 2026-11-06 Master 授权：TOP2 必须是两个不同大题材，且剔除两个持仓已占题材。
    # 只在周报与飞书摘要呈现，不改动 research 排名本身、不触碰账本与任务状态。
    result['top2_rotation']=rotation_top2.select_top2(result,taxonomy=taxonomy,admitted=_admitted_codes(result))
    s=result['summary'];day=date.fromisoformat(s['asof']);week=day-timedelta(days=day.weekday())
    leader=result['leader']['code'] if result['leader'] else None
    path=Path(state_path);old={}
    production_scope=bool(s.get('production_scope',False) and s['full_pool'] and not s['offline'])
    if production_scope and path.exists():old=json.loads(path.read_text(encoding='utf-8'))
    if old.get('version')!=STATE_VERSION:old={}
    import hashlib
    coverage=hashlib.sha256('|'.join(sorted(x['code'] for x in result['ranking'] if x.get('has_all_four_windows'))).encode()).hexdigest()
    if old.get('coverage_signature') not in (None,coverage):old={}
    count=1 if leader else 0
    if leader and old.get('leader')==leader:
        if old.get('week')==week.isoformat():count=old['consecutive_weeks']
        elif old.get('week')==(week-timedelta(days=7)).isoformat():count=old['consecutive_weeks']+1
    state=dict(version=STATE_VERSION,coverage_signature=coverage,week=week.isoformat(),asof=day.isoformat(),leader=leader,consecutive_weeks=count,review_due=count>=2,executable=False)
    # Offline/smoke reports never contaminate production consecutive-week state.
    degraded=bool(s.get('data_failed_runs',s.get('failed_runs',0)) or s.get('fetch_errors',0))
    if degraded or not production_scope:state['review_due']=False
    if production_scope and not degraded:
        if old.get('week') and old['week']>week.isoformat():raise ValueError('cannot rewind weekly state')
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(dump(state),encoding='utf-8');temp.replace(path)
        if json.loads(path.read_text(encoding='utf-8'))!=state:raise ValueError('state readback failed')
    # 2026-11-06 Master 整改：开头口径压缩为 1~2 行紧凑头部（保留 provenance：
    # asof/共同窗口起止、资格池只数、成功失败模拟次数、模型资格排除数、覆盖降级结论）；
    # 删除无决策价值的 legacy reference 三行；双轨周检表格区块不再进正文，
    # 改为一行轮换复核状态（run_pair_review 调用与连续周状态机推进逻辑保持不变）。
    lines=['【每周ETF轮换研究·只报告，不自动换仓】',
           f"数据截止{s['asof']}｜共同窗口 {s['window_start']}→{s['window_end']}｜资格池{s['attempted_assets']}只｜"
           f"成功{s['successful_runs']}次/失败{s['failed_runs']}次｜最低佣金1元、T+1、滑点0.05%。",
           f"模型资格排除{s.get('model_excluded_runs',0)}个窗口；"
           + ('数据覆盖降级：连续周状态不推进、不触发复核门槛。' if degraded else '数据覆盖完整：连续周状态正常推进。')]
    pair_state=((pairs or {}).get('state') or {}).get('pairs') or {}
    due=[(k,v) for k,v in pair_state.items() if v.get('review_due')]
    if due:
        first=due[0];extra=f"等{len(due)}条" if len(due)>1 else ''
        lines.append(f"轮换复核：触发（{first[0].replace('/',' ')} 候选{first[1]['candidate']} "
                     f"连续{first[1]['consecutive_weeks']}周{extra}），仅人工复核、不授权换仓。")
    elif degraded:
        lines.append('轮换复核：未触发（数据覆盖降级，连续周状态不推进）。')
    else:
        lines.append('轮换复核：未触发（无连续2周领先候选）。')
    # 只读锚价位移披露：紧凑头部之后、数据区之前；无上一期时输出「略过」文案。
    lines.extend(_anchor_disclosure_lines(result, prev_result))
    def money(v):return '不可用' if v is None else f'{v:,.2f}'
    def number(v):return '不可用' if v is None else str(int(v))
    lines.append(f"完整四窗口可排名{s.get('rankable_rows','未知')}只；其余占位失败行不算成功。")
    lines.append('【当前三持仓·全部展示，不参与领先者】')
    # 2026-10-30 表格化：数字逐格取自 holdings dict，不另设渲染口径。
    lines.extend(_md_table(
        ['持仓', '往返次数', '净差价元'],
        [[f"{c} {result['holdings'][c].get('name','')}", number(x.get('full_cycles')), money(x.get('full_cycle_net'))]
         for c in research.HOLDINGS for x in [result['holdings'][c]]]))
    output=s.get('output_path')
    # 2026-10-23 起：周报必须带上过两道建仓规则（五线全破禁入 + 近20日<2 出榜）的榜单。
    # 2026-10-24 起：榜单同时进飞书精简摘要（定时任务推送的是 summarize，不带即整改未落地）。
    entry_report_lines, entry_digest = entry_rank_block(result, output)
    lines.extend(entry_report_lines)
    lines.append('【轮换往返前10·同一套5分钟模拟】')
    lines.append('说明：本表未按题材去重，不作 TOP2 观察候选遴选依据；不同大题材观察候选见下方 TOP2 区块。')
    top10=result.get('rotation_top10') or result.get('rotation_ranking',[])[:10]
    lines.extend(_md_table(
        ['代码', '名称', '往返次数', '净差价元'],
        [[x['code'], x.get('name',''), number(x.get('full_cycles')), money(x.get('full_cycle_net'))] for x in top10]))
    lines.extend(rotation_top2.report_lines(result['top2_rotation']))
    lines.append(f"数据/模拟错误记录{len(result['errors'])}条；详见研究目录errors.json。")
    if not production_scope:lines.append('仅验证：非生产范围（离线、小规模、自定义资格池、非63交易日或历史时点），不宣称最新生产全池，不读取或更新生产连续周状态，不触发生产复核门槛。')
    lines.append('独立10万元模拟账户，不是共同资金账户；当根成交量参与限制有前视偏差，非真实成交。禁止自动买入、撤单、改账本。')
    report='\n'.join(lines)
    output=s.get('output_path')
    if output:(Path(output)/'weekly-report.txt').write_text(report,encoding='utf-8')
    return dict(state=state,pair_review=pairs,holdings=result['holdings'],report=report,summary=summarize(result,pairs,entry_digest),research=result)

def main(argv=None,now=None):
    import argparse
    from .engine import DEFAULT_INPUT
    p=argparse.ArgumentParser(description='周度研究中文报告')
    p.add_argument('--input-path',default=str(DEFAULT_INPUT));p.add_argument('--output-path');p.add_argument('--bars-dir');p.add_argument('--asof');p.add_argument('--sessions',type=int,default=63);p.add_argument('--offline',action='store_true');p.add_argument('--limit',type=int);p.add_argument('--workers',type=int,default=8);p.add_argument('--state-path',default=str(DEFAULT_STATE))
    p.add_argument('--pair-state-path');p.add_argument('--taxonomy-path');p.add_argument('--include-hong-kong',action='store_true',help='关闭周报pair temporary name-based港股过滤，不改研究资格池')
    args=vars(p.parse_args(argv))
    args['name_exclusions']=() if args.pop('include_hong_kong') else pair_review.DEFAULT_NAME_EXCLUSIONS
    if args['asof'] is None and not args['offline']:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .calendar import is_session
        now=now or datetime.now(ZoneInfo('Asia/Shanghai'))
        if not is_session(now.date()) or now.hour*60+now.minute<15*60+15:
            text='周度研究：休市或收盘未确认，不生成报告、不更新状态。';print(text);return text
    result=run_weekly(**args)
    # 2026-10-30 起：cron（no_agent）吃本函数 stdout，用户要求周检推送完整报告、
    # 禁止缩略——完整周报含紧凑口径头部、轮换复核状态、双规则完整榜单、往返前10、TOP2 观察候选。
    text=result.get('report') or result['summary']
    print(text);return text
if __name__=='__main__':main()
