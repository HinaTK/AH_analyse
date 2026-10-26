"""Weekly reporting only: call research once, no second simulation/model."""
from pathlib import Path
from datetime import date, timedelta
import json
from . import research, pair_review
from .entry_rank import rank_entries, render_markdown
from .engine import dump
STATE_VERSION=research.VERSION+'-rotation-streak-v1'
DEFAULT_STATE=Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/rotation')/f'{STATE_VERSION}.json'
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
    # 飞书精简摘要：每行数字同样逐格取自 rows
    digest = [ENTRY_BLOCK_TITLE, head]
    for row in rows[:digest_n]:
        digest.append(
            f"{row['rank']}. {row['code']} {row['name']}｜{row['label']}｜"
            f"63日往返{row['full_cycles']:.0f}次｜净差价{row['full_cycle_net']:,.2f}元｜"
            f"近20日{row['recent20_cycles']:.0f}次")
    if len(rows) > digest_n:
        digest.append(f"……共{len(rows)}只入选，完整表见 weekly-report.txt 与 entry-ranking.csv")
    return report_lines, digest

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
    items=[];seen=set()
    for x in [result.get('leader'),*(result.get('rotation_top10') or [])]:
        if x and x.get('code') not in seen:seen.add(x.get('code'));items.append(x)
    if items:lines.append('【往返前列】'+'；'.join(f"{x['code']} {number(x.get('full_cycles'))}次/{money(x.get('full_cycle_net'))}元" for x in items[:3]))
    out=s.get('output_path')
    if out:lines.append(f"完整报告：{out}/weekly-report.txt（双轨周检明细、往返前10、综合排名、免责声明）。")
    return '\n'.join(lines)


def run_weekly(state_path=DEFAULT_STATE,research_runner=None,pair_state_path=None,taxonomy=None,
               taxonomy_path=None,name_exclusions=pair_review.DEFAULT_NAME_EXCLUSIONS,**kwargs):
    if taxonomy_path:
        if taxonomy is not None:raise ValueError('use taxonomy or taxonomy_path, not both')
        taxonomy=json.loads(Path(taxonomy_path).read_text(encoding='utf-8'))
    result=(research_runner or research.run_research)(**kwargs)
    # An explicitly custom legacy path keeps test/validation outputs isolated too.
    pair_path=pair_state_path or (pair_review.DEFAULT_STATE if Path(state_path)==DEFAULT_STATE else Path(state_path).with_name('pair-review-v1.json'))
    pairs=pair_review.run_pair_review(result,state_path=pair_path,taxonomy=taxonomy,name_exclusions=name_exclusions)
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
    lines=['【每周ETF轮换研究·只报告，不自动换仓】',f"历史资格快照池：{s['attempted_assets']}只；共同5分钟窗口 {s['window_start']}→{s['window_end']}。",f"成功模拟{s['successful_runs']}次，失败{s['failed_runs']}次；最低佣金1元、T+1、滑点0.05%。"]
    if s.get('model_excluded_runs',0):lines.append(f"模型资格排除{s['model_excluded_runs']}个窗口；只在相同完整合格覆盖签名下累计连续周。")
    if degraded:lines.append('数据覆盖降级：存在失败候选，不推进连续周状态，不触发复核门槛。')
    if leader:lines.append(f"legacy reference（旧全局参考，非逐持仓建议）：{leader}，完成往返{result['leader']['full_cycles']}次（仅次数领先589720）。")
    else:lines.append('legacy reference：旧全局参考无领先者，不代表逐持仓双轨结论。')
    lines.append(f"legacy reference兼容计数{count}周（不作为逐持仓复核证据）。")
    lines.extend(pair_review.report_lines(pairs))
    def money(v):return '不可用' if v is None else f'{v:,.2f}'
    def number(v):return '不可用' if v is None else str(int(v))
    lines.append(f"完整四窗口可排名{s.get('rankable_rows','未知')}只；其余占位失败行不算成功。")
    lines.append('【当前三持仓·全部展示，不参与领先者】')
    for c in research.HOLDINGS:
        x=result['holdings'][c];lines.append(f"{c}：往返{number(x.get('full_cycles'))}次；净差价{money(x.get('full_cycle_net'))}元")
    output=s.get('output_path')
    # 2026-10-23 起：周报必须带上过两道建仓规则（五线全破禁入 + 近20日<2 出榜）的榜单。
    # 2026-10-24 起：榜单同时进飞书精简摘要（定时任务推送的是 summarize，不带即整改未落地）。
    entry_report_lines, entry_digest = entry_rank_block(result, output)
    lines.extend(entry_report_lines)
    lines.append('【轮换往返前10·同一套5分钟模拟】')
    top10=result.get('rotation_top10') or result.get('rotation_ranking',[])[:10]
    for x in top10:lines.append(f"{x['code']} {x.get('name','')}：{number(x.get('full_cycles'))}次；净差价{money(x.get('full_cycle_net'))}元")
    lines.append('【综合研究排名·第三ETF互补视图】')
    for x in result['ranking'][:10]:
        score='不可用' if x.get('score') is None else f"{x['score']:.3f}"
        lines.append(f"{x['code']} {x.get('name','')}：score={score}；资格={x.get('qualification')}")
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
    text=result.get('summary') or summarize(result['research'],result['pair_review'])
    print(text);return text
if __name__=='__main__':main()
