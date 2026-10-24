import importlib
import json
import pandas as pd
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

def bars(days):
    rows=[]
    for day in days:
        for hour in pd.date_range('2000-01-01 09:35','2000-01-01 11:30',freq='5min').strftime('%H:%M:%S').tolist()+pd.date_range('2000-01-01 13:05','2000-01-01 15:00',freq='5min').strftime('%H:%M:%S').tolist():
            rows.append(dict(time=f'{day} {hour}',open=1.,high=1.,low=1.,close=1.,volume=1e8))
    return pd.DataFrame(rows)

def test_closed_common_window_rejects_stale_baselines():
    r=module()
    data={c:bars(['2026-10-08','2026-10-09']) for c in r.BASE}
    assert r.select_window(data,'2026-10-09',2)==['2026-10-08','2026-10-09']
    with pytest.raises(ValueError,match='stale'):
        r.select_window(data,'2026-10-12',2)
    with pytest.raises(ValueError,match='insufficient'):
        r.select_window(data,'2026-10-09',63)
    assert r.latest_session(datetime(2026,10,10,12,tzinfo=ZoneInfo('Asia/Shanghai')))=='2026-10-09'


def test_model_preserves_constraints_and_changes_only_fee():
    r=module()
    model=r.get_model()
    assert model.fee(5000)==1
    assert model.fee(20000)==2
    d=bars(['2026-10-08','2026-10-09'])
    result=model.simulate(d,trace=True)
    assert abs(result['identity_error'])<1e-6
    assert result['t0'] is False
    assert result['min_cash']>=50000
    assert all(e['qty']%100==0 for e in result['events'])
    d.volume=100
    with pytest.raises(ValueError,match='volume'):
        model.simulate(d)

def test_offline_research_runs_four_windows_and_accounts_for_errors(tmp_path,monkeypatch):
    r=module()
    inp=tmp_path/'synthetic-input';inp.mkdir();(inp/'bars').mkdir()
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in [*r.HOLDINGS,'sh510050','sh510100']]).to_csv(inp/'eligibility.csv',index=False)
    days=pd.bdate_range('2026-06-30',periods=63).strftime('%Y-%m-%d').tolist()
    for code in [*r.HOLDINGS,'sh510050']:
        frame=bars(days)
        frame.to_csv(inp/'bars'/f'{code}-m5.csv',index=False)
    out=tmp_path/'synthetic-output'
    result=r.run_research(input_path=inp,output_path=out,offline=True,asof=days[-1])
    assert result['summary']['universe_count']==5
    assert result['summary']['attempted_runs']==20
    assert result['summary']['successful_runs']+result['summary']['failed_runs']==20
    assert result['summary']['rankable_rows']==4
    assert result['summary']['failed_assets']==1
    assert result['summary']['successful_assets']==4
    alt=r.run_research(input_path=inp,bars_dir=inp/'bars',output_path=tmp_path/'synthetic-alt',offline=True,asof=days[-1])
    assert alt['summary']['successful_assets']==4
    assert len(result['ranking'])==5
    assert set(result['holdings'])==set(r.HOLDINGS)
    assert result['summary']['latest_claim'] is False
    assert len(result['rotation_top10'])<=10
    assert all(x.get('has_all_four_windows') for x in result['rotation_top10'])
    assert all(x['code'] not in r.HOLDINGS for x in result['rotation_top10'])
    import json
    text=(out/'summary.json').read_text(encoding='utf-8')
    json.loads(text,parse_constant=lambda x: pytest.fail('invalid JSON constant'))
    assert len((out/'progress.jsonl').read_text().splitlines())>=5
    assert result['summary']['production_pool'] is False
    assert result['summary']['production_scope'] is False
    engine=importlib.import_module('tools.etf_research.engine')
    reference=tmp_path/'production-input';reference.mkdir()
    monkeypatch.setattr(engine,'DEFAULT_INPUT',reference)
    monkeypatch.setattr(engine,'latest_session',lambda:days[-1])
    # Online branches exercise the real engine with local bars, never network.
    def local_fetch(code):
        return engine.validate(pd.read_csv(inp/'bars'/f'{code}-m5.csv'))
    monkeypatch.setattr(engine,'fetch_bars',local_fetch)
    def online(label,**kwargs):
        return r.run_research(input_path=inp,output_path=tmp_path/label,asof=days[-1],**kwargs)['summary']
    missing=online('missing-reference')
    assert missing['full_pool'] and not missing['production_pool']
    assert not missing['production_scope'] and not missing['latest_claim']
    (reference/'eligibility.csv').write_bytes((inp/'eligibility.csv').read_bytes())
    failed=online('data-failed')
    assert failed['production_pool'] and failed['production_scope']
    assert failed['data_failed_runs']>0 and not failed['latest_claim']
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in [*r.HOLDINGS,'sh510050']]).to_csv(inp/'eligibility.csv',index=False)
    custom=online('custom-pool')
    assert custom['full_pool'] and not custom['production_pool']
    assert not custom['production_scope'] and not custom['latest_claim']
    (reference/'eligibility.csv').write_bytes((inp/'eligibility.csv').read_bytes())
    current=online('production-current')
    assert current['production_scope'] and current['latest_claim']
    short=online('short-window',sessions=20)
    assert not short['production_scope'] and not short['latest_claim']
    smoke=online('smoke',limit=1)
    assert not smoke['production_scope'] and not smoke['latest_claim']
    monkeypatch.setattr(engine,'latest_session',lambda:'2026-10-09')
    historical=online('historical')
    assert not historical['production_scope'] and not historical['latest_claim']


def test_weekly_report_includes_entry_rank_gated_listing(tmp_path):
    """周报必须带上 entry_rank 新规则（五线全破禁入+近20日<2出榜）的榜单。

    用户 2026-10-23 要求定时任务用整改后的脚本：周报不能只给裸
    63 日往返榜，要给出过两道新规则的 entry-ranking 表。
    断言一律引用 weekly.ENTRY_BLOCK_TITLE 常量——2026-10-24 曾因
    手写断言子串与实现表头不一致误判功能缺失（榜单实际已生成）。
    """
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module()
    ranking=[
        dict(code='sh588010',name='零活跃候选',has_all_four_windows=True,full_cycles=37.0,full_cycle_net=5628.8,full_cycle_net_per_avg_cost_pct=18.5,recent20_cycles=0.0,recent20_cycle_net_per_avg_cost_pct=0.0),
        dict(code='sh589720',name='持仓活跃',has_all_four_windows=True,full_cycles=29.0,full_cycle_net=4028.4,full_cycle_net_per_avg_cost_pct=10.6,recent20_cycles=12.0,recent20_cycle_net_per_avg_cost_pct=3.9),
        dict(code='sz159363',name='持仓零活跃',has_all_four_windows=True,full_cycles=21.0,full_cycle_net=3408.7,full_cycle_net_per_avg_cost_pct=8.0,recent20_cycles=0.0,recent20_cycle_net_per_avg_cost_pct=0.0),
    ]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-23','full_pool':True,'offline':False,'production_scope':False,'window_start':'2026-07-21','window_end':'2026-10-23','successful_runs':1139,'failed_runs':145,'attempted_assets':321},'leader':None,'holdings':{c:{'full_cycles':10,'full_cycle_net':1000.0} for c in r.HOLDINGS},'ranking':ranking,'errors':[]}
    # bars 目录供 entry_rank 判定用
    bars_dir=tmp_path/'bars';bars_dir.mkdir()
    n=120
    dates=pd.bdate_range(end='2026-10-23',periods=n).strftime('%Y-%m-%d')
    for row in ranking:
        closes=[10*1.003**i for i in range(n)]
        lows=[c*0.99 for c in closes];lows[-1]=sum(closes[-20:])/20
        pd.DataFrame({'time':[f'{d} 10:00' for d in dates],'open':closes,'high':[c*1.01 for c in closes],'low':lows,'close':closes}).to_csv(bars_dir/f"{row['code']}-m5.csv",index=False)
    (tmp_path/'result.json').write_text(json.dumps(result),encoding='utf-8')
    def runner(**kwargs):
        return dict(result, summary=dict(result['summary'], output_path=str(tmp_path)))
    path=tmp_path/'state.json'
    out=weekly.run_weekly(state_path=path,research_runner=runner)
    report=out['report']
    # 周报里必须出现 entry_rank 产出的榜单区块（标题取共享常量，不手写）
    assert weekly.ENTRY_BLOCK_TITLE in report, '周报缺少 entry_rank 榜单区块'
    # 零活跃候选不得出现在榜单（新规则出榜），持仓必须出现
    entry_block=report.split(weekly.ENTRY_BLOCK_TITLE)[1].split('【')[0]
    assert 'sh588010' not in entry_block, '近20日0次的候选不得入周报榜单'
    assert 'sh589720' in entry_block, '持仓要出现在周报榜单里'
    assert 'sz159363' in entry_block, '持仓近20日0次也豁免保留'
    # 表格必须由 entry_rank.render_markdown 原样渲染（表格交付铁律）
    assert '| 名次 | 代码 | 名称 | 资格 | 63日往返 | 净差价 | 近20日往返 | 资金效率% |' in report
    assert '2,279.30' not in entry_block


def test_weekly_report_renders_top20_in_gated_listing(tmp_path):
    """周报榜单必须渲染前 20 行（2026-10-24 用户：以后给出前20）。

    原 top_n 默认 10；本测试用 25 只合成候选（全部近20日≥2 且非
    持仓）验证周报表格恰好渲染 20 行数据行，不多不少。
    """
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module()
    ranking=[dict(code=f'sz1599{i:02d}',name=f'候选{i}',has_all_four_windows=True,
                  full_cycles=float(50-i),full_cycle_net=1000.0-i,full_cycle_net_per_avg_cost_pct=5.0,
                  recent20_cycles=float(5+i),recent20_cycle_net_per_avg_cost_pct=0.5) for i in range(25)]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-23','full_pool':True,'offline':False,'production_scope':False,'window_start':'2026-07-21','window_end':'2026-10-23','successful_runs':1139,'failed_runs':145,'attempted_assets':321},'leader':None,'holdings':{c:{'full_cycles':10,'full_cycle_net':1000.0} for c in r.HOLDINGS},'ranking':ranking,'errors':[]}
    bars_dir=tmp_path/'bars';bars_dir.mkdir()
    n=120
    dates=pd.bdate_range(end='2026-10-23',periods=n).strftime('%Y-%m-%d')
    for row in ranking:
        closes=[10*1.003**i for i in range(n)]
        lows=[c*0.99 for c in closes];lows[-1]=sum(closes[-20:])/20
        pd.DataFrame({'time':[f'{d} 10:00' for d in dates],'open':closes,'high':[c*1.01 for c in closes],'low':lows,'close':closes}).to_csv(bars_dir/f"{row['code']}-m5.csv",index=False)
    (tmp_path/'result.json').write_text(json.dumps(result),encoding='utf-8')
    def runner(**kwargs):
        return dict(result, summary=dict(result['summary'], output_path=str(tmp_path)))
    out=weekly.run_weekly(state_path=tmp_path/'state.json',research_runner=runner)
    report=out['report']
    assert weekly.ENTRY_BLOCK_TITLE in report
    block=report.split(weekly.ENTRY_BLOCK_TITLE)[1].split('【')[0]
    data_rows=[ln for ln in block.splitlines() if ln.startswith('| ') and '名次' not in ln and '---' not in ln]
    assert len(data_rows)==20, f'周报榜单必须渲染前20行，实际 {len(data_rows)} 行'
    # 第 20 名在榜（sz159919, full=31），第 21 名不在（sz159920, full=30 不渲染）
    assert 'sz159919' in block
    assert 'sz159920' not in block


def test_weekly_report_flags_entry_rank_failure_instead_of_silent_gap(tmp_path):
    """榜单生成失败必须在周报里可见，禁止静默吞异常。

    2026-10-24 根因调查发现 entry_rank_lines 裸 except 把任何失败
    静默成"无区块"，调用方无从察觉。整改后失败必须显示 ⚠️。
    """
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module()
    result={'summary':{'version':r.VERSION,'asof':'2026-10-23','full_pool':True,'offline':False,'production_scope':False,'window_start':'2026-07-21','window_end':'2026-10-23','successful_runs':1139,'failed_runs':145,'attempted_assets':321},'leader':None,'holdings':{c:{'full_cycles':10,'full_cycle_net':1000.0} for c in r.HOLDINGS},'ranking':[],'errors':[]}
    # output 指向存在 result.json 但内容损坏的目录 -> rank_entries 必然抛错
    (tmp_path/'result.json').write_text('{corrupted',encoding='utf-8')
    def runner(**kwargs):
        return dict(result, summary=dict(result['summary'], output_path=str(tmp_path)))
    out=weekly.run_weekly(state_path=tmp_path/'state.json',research_runner=runner)
    assert weekly.ENTRY_BLOCK_TITLE in out['report'], '失败也要出现榜单区块标题'
    assert '⚠️' in out['report'], '失败必须在周报可见'
    assert '4,028.40' not in out['report'].split(weekly.ENTRY_BLOCK_TITLE)[1]


def test_weekly_summary_pushes_entry_rank_digest(tmp_path):
    """飞书推送（summarize 精简摘要）必须带双规则榜单摘要。

    定时任务 5d8180a8d025 推飞书的是 summarize() 而非全量周报；
    摘要不带榜单的话，用户周五收到的仍是旧口径，整改未落地。
    """
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module()
    ranking=[
        dict(code='sh588010',name='零活跃候选',has_all_four_windows=True,full_cycles=37.0,full_cycle_net=5628.8,full_cycle_net_per_avg_cost_pct=18.5,recent20_cycles=0.0,recent20_cycle_net_per_avg_cost_pct=0.0),
        dict(code='sh589720',name='持仓活跃',has_all_four_windows=True,full_cycles=29.0,full_cycle_net=4028.4,full_cycle_net_per_avg_cost_pct=10.6,recent20_cycles=12.0,recent20_cycle_net_per_avg_cost_pct=3.9),
        dict(code='sz159363',name='持仓零活跃',has_all_four_windows=True,full_cycles=21.0,full_cycle_net=3408.7,full_cycle_net_per_avg_cost_pct=8.0,recent20_cycles=0.0,recent20_cycle_net_per_avg_cost_pct=0.0),
    ]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-23','full_pool':True,'offline':False,'production_scope':False,'window_start':'2026-07-21','window_end':'2026-10-23','successful_runs':1139,'failed_runs':145,'attempted_assets':321},'leader':None,'holdings':{c:{'full_cycles':10,'full_cycle_net':1000.0} for c in r.HOLDINGS},'ranking':ranking,'errors':[]}
    bars_dir=tmp_path/'bars';bars_dir.mkdir()
    n=120
    dates=pd.bdate_range(end='2026-10-23',periods=n).strftime('%Y-%m-%d')
    for row in ranking:
        closes=[10*1.003**i for i in range(n)]
        lows=[c*0.99 for c in closes];lows[-1]=sum(closes[-20:])/20
        pd.DataFrame({'time':[f'{d} 10:00' for d in dates],'open':closes,'high':[c*1.01 for c in closes],'low':lows,'close':closes}).to_csv(bars_dir/f"{row['code']}-m5.csv",index=False)
    (tmp_path/'result.json').write_text(json.dumps(result),encoding='utf-8')
    def runner(**kwargs):
        return dict(result, summary=dict(result['summary'], output_path=str(tmp_path)))
    out=weekly.run_weekly(state_path=tmp_path/'state.json',research_runner=runner)
    text=out['summary']
    assert weekly.ENTRY_BLOCK_TITLE in text, '精简摘要缺少双规则榜单块'
    assert 'sh589720' in text and 'sz159363' in text, '摘要榜单必须含持仓'
    assert 'sh588010' not in text, '近20日0次的候选不得出现在摘要'
    assert len(text.splitlines())<=16, '摘要超出精简行数上限'


def test_weekly_single_call_versioned_streak_and_no_same_week_double_count(tmp_path):
    try: weekly=importlib.import_module('tools.etf_research.weekly')
    except ModuleNotFoundError: pytest.fail('weekly thin entry missing')
    r=module();calls=[]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-09','full_pool':True,'offline':False,'production_scope':True,'window_start':'2026-07-01','window_end':'2026-10-09','successful_runs':1284,'failed_runs':0,'attempted_assets':321},'leader':{'code':'sh510050','full_cycles':30},'holdings':{c:{'full_cycles':10} for c in r.HOLDINGS},'ranking':[],'errors':[]}
    def runner(**kwargs):calls.append(kwargs);return result
    path=tmp_path/'state.json';path.write_text('{"version":"old-daily","consecutive_weeks":50}')
    one=weekly.run_weekly(state_path=path,research_runner=runner)
    assert len(calls)==1 and one['state']['consecutive_weeks']==1
    assert set(r.HOLDINGS).issubset(set(one['holdings']))
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    result['summary']['asof']='2026-10-16'
    two=weekly.run_weekly(state_path=path,research_runner=runner)
    assert two['state']['review_due'] and two['state']['consecutive_weeks']==2
    assert two['state']['executable'] is False
    previous=path.read_text()
    # Validation cannot inherit a production streak, in either week.
    for offline,full_pool,scope in ((True,True,False),(False,False,False),(True,False,False),(False,True,False),(False,True,None)):
        for asof in ('2026-10-16','2026-10-23'):
            result['summary'].update(offline=offline,full_pool=full_pool,asof=asof)
            result['summary'].pop('production_scope',None)
            if scope is not None:result['summary']['production_scope']=scope
            validation=weekly.run_weekly(state_path=path,research_runner=runner)
            assert validation['state']['consecutive_weeks']==1
            assert validation['state']['review_due'] is False
            assert path.read_text()==previous
            assert '仅验证' in validation['report']
            assert '达到两周人工复核门槛。' not in validation['report']
    result['summary'].update(offline=False,full_pool=True,production_scope=True,asof='2026-10-23',failed_runs=4)
    degraded_two=weekly.run_weekly(state_path=path,research_runner=runner)
    assert degraded_two['state']['consecutive_weeks']>=2
    assert degraded_two['state']['review_due'] is False
    assert '达到两周人工复核门槛。' not in degraded_two['report']
    assert path.read_text()==previous
    result['summary']['failed_runs']=0
    result['summary']['asof']='2026-10-30'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    previous=path.read_text()
    result['summary']['failed_runs']=4;result['summary']['failed_assets']=1
    degraded=weekly.run_weekly(state_path=path,research_runner=runner)
    assert path.read_text()==previous
    assert not degraded['state']['review_due']
    assert '降级' in degraded['report']
    result['holdings'][r.BASE[0]]['full_cycle_net']=4038.9000000000005
    assert '4,038.90' in weekly.run_weekly(state_path=path,research_runner=runner)['report']

def test_window_does_not_skip_missing_baseline_session():
    r=module();days=['2026-10-08','2026-10-09','2026-10-13']
    with pytest.raises(ValueError,match='missing'):
        r.select_window({c:bars(days) for c in r.BASE},'2026-10-13',3)

def test_offline_intraday_gaps_are_rejected(tmp_path):
    r=module();inp=tmp_path/'synthetic-input';inp.mkdir();(inp/'bars').mkdir()
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in r.HOLDINGS]).to_csv(inp/'eligibility.csv',index=False)
    days=pd.bdate_range('2026-06-30',periods=63).strftime('%Y-%m-%d').tolist()
    for c in r.HOLDINGS:
        f=bars(days);f=f[f.time.str.endswith('15:00:00')];f.to_csv(inp/'bars'/f'{c}-m5.csv',index=False)
    with pytest.raises(ValueError,match='baseline simulation'):
        r.run_research(input_path=inp,output_path=tmp_path/'synthetic-output',offline=True,asof=days[-1])

def test_weekly_cli_weekend_guard():
    weekly=importlib.import_module('tools.etf_research.weekly')
    text=weekly.main([],now=datetime(2026,10,10,16,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert '休市' in text

def test_weekly_model_exclusions_allow_streak_only_on_same_coverage(tmp_path):
    weekly=importlib.import_module('tools.etf_research.weekly')
    r=module()
    result={'summary':{'version':r.VERSION,'asof':'2026-10-09','full_pool':True,'offline':False,'production_scope':True,'window_start':'2026-07-07','window_end':'2026-10-09','successful_runs':1185,'failed_runs':95,'data_failed_runs':0,'model_excluded_runs':95,'fetch_errors':0,'attempted_assets':321},'leader':{'code':'sh589120','full_cycles':38},'holdings':{c:{} for c in r.HOLDINGS},'ranking':[{'code':'sh589120','has_all_four_windows':True}],'errors':[]}
    def runner(**kwargs):return result
    path=tmp_path/'state.json'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1
    result['summary']['asof']='2026-10-16'
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['review_due'] is True
    result['summary']['asof']='2026-10-23';result['ranking'].append({'code':'sh510050','has_all_four_windows':True})
    assert weekly.run_weekly(state_path=path,research_runner=runner)['state']['consecutive_weeks']==1


def test_weekly_summary_compact_and_actionable():
    weekly=importlib.import_module('tools.etf_research.weekly');r=module()
    ranking=[dict(code=c,name=c,has_all_four_windows=True,holding=True) for c in r.HOLDINGS]
    ranking+= [dict(code='sh510050',name='50ETF',has_all_four_windows=True,holding=False,
                    full_cycles=5.0,full_cycle_net=123.4)]
    result={'summary':{'version':r.VERSION,'asof':'2026-10-09','window_start':'2026-07-07','window_end':'2026-10-09',
                       'attempted_assets':321,'successful_runs':1139,'failed_runs':145,'fetch_errors':0,
                       'data_failed_runs':52,'model_excluded_runs':93,'rankable_rows':253,
                       'output_path':'D:/tmp/grid-research/20261023-152537'},
            'leader':dict(code='sh588010',full_cycles=37.0),
            'holdings':{c:dict(code=c,name=c,full_cycles=29.0,full_cycle_net=4028.4) for c in r.HOLDINGS},
            'ranking':ranking,'errors':[1,2,3]}
    text=weekly.summarize(result)
    lines=text.splitlines()
    assert '每周ETF轮换研究' in text and '精简' in text
    assert 'sh589720' in text and '29' in text and '4,028.40' in text
    assert 'sh588010' in text and '37' in text
    assert '降级' in text and '不触发复核' in text
    assert '完整报告' in text and 'weekly-report.txt' in text
    assert '【逐持仓双轨周检】' not in text and 'legacy reference' not in text
    assert len(lines)<=16, f'summary too long: {len(lines)} lines'


def test_weekly_cli_prints_summary_only(monkeypatch,capfd):
    weekly=importlib.import_module('tools.etf_research.weekly')
    fake=dict(state={},pair_review={},holdings={},research={},
              report='逐持仓双轨周检'*50,summary='【每周ETF轮换研究·精简】一行摘要')
    monkeypatch.setattr(weekly,'run_weekly',lambda **kwargs:fake)
    text=weekly.main(['--offline'])
    out=capfd.readouterr().out
    assert text==fake['summary']
    assert '一行摘要' in out
    assert '双轨周检' not in out


def module():
    try:
        return importlib.import_module('tools.etf_research.research')
    except ModuleNotFoundError:
        raise AssertionError('versioned research entry is missing')

def test_universe_keeps_all_eligible_and_all_holdings(tmp_path):
    p=tmp_path/'eligibility.csv'
    pd.DataFrame([{'code':'sh510050','name':'ETF','eligible':True},{'code':'sz159992','name':'holding','eligible':False}]).to_csv(p,index=False)
    r=module()
    pool=r.load_universe(p)
    assert set(pool.code)=={'sh510050',*r.HOLDINGS}
    assert not pool.code.duplicated().any()


def test_lot_budget_scales_core_and_initial_lots():
    """RED->GREEN: simulate() must scale core_qty and initial lot qty with lot_budget."""
    r=module()
    model=r.get_model()
    d=bars(['2026-10-08','2026-10-09'])

    r5=model.simulate(d,trace=True)
    core5=[e for e in r5['events'] if e['slot']=='core'][0]
    init5=[e for e in r5['events'] if e.get('initial') and e['slot']!='core'][0]

    r6=model.simulate(d,lot_budget=6000,trace=True)
    core6=[e for e in r6['events'] if e['slot']=='core'][0]
    init6=[e for e in r6['events'] if e.get('initial') and e['slot']!='core'][0]

    assert core6['qty'] > core5['qty'], 'core qty must increase with lot_budget'
    assert init6['qty'] > init5['qty'], 'initial lot qty must increase with lot_budget'
    ratio_core=core6['qty']/core5['qty']
    assert 1.1 < ratio_core < 1.3, f'core ratio {ratio_core:.3f} not near 1.2'
    ratio_init=init6['qty']/init5['qty']
    assert 1.1 < ratio_init < 1.3, f'init lot ratio {ratio_init:.3f} not near 1.2'


def test_run_research_accepts_lot_budget_and_gap(tmp_path):
    """run_research must accept lot_budget and gap kwargs and pass them to simulate."""
    r=module()
    inp=tmp_path/'synthetic-input';inp.mkdir();(inp/'bars').mkdir()
    pd.DataFrame([dict(code=c,name=c,eligible=True) for c in [*r.HOLDINGS,'sh510050']]).to_csv(inp/'eligibility.csv',index=False)
    days=pd.bdate_range('2026-06-30',periods=63).strftime('%Y-%m-%d').tolist()
    for code in [*r.HOLDINGS,'sh510050']:
        bars(days).to_csv(inp/'bars'/f'{code}-m5.csv',index=False)
    out=tmp_path/'synthetic-custom'
    result=r.run_research(input_path=inp,output_path=out,offline=True,asof=days[-1],
                          lot_budget=6000,gap=0.015)
    assert result['summary']['attempted_runs']==16
    assert result['summary']['successful_runs']+result['summary']['failed_runs']==16
