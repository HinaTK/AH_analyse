"""Weekly reporting only: call research once, no second simulation/model."""
from pathlib import Path
from datetime import date, timedelta
import json
from . import research, pair_review
from .engine import dump
STATE_VERSION=research.VERSION+'-rotation-streak-v1'
DEFAULT_STATE=Path('D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account/rotation')/f'{STATE_VERSION}.json'

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
    return dict(state=state,pair_review=pairs,holdings=result['holdings'],report=report,research=result)

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
    result=run_weekly(**args);print(result['report']);return result['report']
if __name__=='__main__':main()
