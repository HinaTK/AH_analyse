"""Synthetic metrics only; no broker, ledger or market-data writes."""
import importlib
from copy import deepcopy
import pytest


@pytest.mark.parametrize('malformed', [
    None, 'not-an-entry', [],
    dict(verified=True, sources='https://official.example/index'),
    dict(verified=True, sources=['not-a-URL']),
    dict(verified=True, sources=[None]),
    dict(verified=True, sources=['ftp://official.example/index']),
    dict(verified=True, sources=['https:///index']),
    dict(verified=True, sources=['https://official.example:bad/index']),
    dict(verified=True, sources=['https://official.example/a b']),
    dict(verified=True, sources=['https://official.example/index', 'not-a-URL']),
    dict(verified=1, sources=['https://official.example/index']),
    dict(verified=True, sources=[]),
])
def test_malformed_taxonomy_entries_fail_closed_for_classification_and_coverage(malformed):
    p=api();r=fixture();tax=taxonomy()
    if isinstance(malformed, dict):
        malformed=dict(tax['entries']['sh510001'], **malformed)
    tax['entries']['sh510001']=malformed
    r['ranking']=[row('510001',20,4)]
    for holding, candidate in [('sz159363','510001'), ('510001','sz159363')]:
        assert p.classify(holding,candidate,tax)=='unknown'
    out=p.run_pair_review(r,state_path=None,taxonomy=tax)
    assert out['taxonomy_coverage']==dict(verified_assets=5,universe_verified=2,unknown_assets=2)
    for data in out['holdings'].values():
        assert all(g['priority'] is None for g in data['tracks'].values())
        assert [x['code'] for x in data['unknown']]==['510001']
        assert data['unknown'][0]['status']=='observe'
    assert all(x['candidate'] is None and x['consecutive_weeks']==0 for x in out['state']['pairs'].values())


@pytest.mark.parametrize('entries', [None, [], 'not-entries'])
def test_malformed_taxonomy_container_fails_closed(entries):
    p=api();r=fixture();r['ranking']=[row('510001',20,4)]
    out=p.run_pair_review(r,state_path=None,taxonomy={'assets':entries})
    assert out['taxonomy_coverage']==dict(verified_assets=0,universe_verified=0,unknown_assets=4)
    assert all(x['classification']=='unknown' for data in out['holdings'].values() for x in data['unknown'])


@pytest.mark.parametrize('holding_code', [
    '159363', 'sh159363', 'sz159363',
    '589720', 'sh589720', 'sz589720',
    '159992', 'sh159992', 'sz159992',
])
def test_all_holding_aliases_excluded_before_selection_preserving_candidate_code(holding_code):
    p=api();r=fixture();tax=taxonomy()
    if holding_code not in tax['entries']:
        tax['entries'][holding_code]=deepcopy(tax['entries']['sh510001'])
    r['ranking']=[row(holding_code,99,99),row('510001',20,4)]
    out=p.run_pair_review(r,state_path=None,taxonomy=tax)
    for holding, data in out['holdings'].items():
        track='same_class' if holding=='sz159363' else 'cross_theme'
        assert data['tracks'][track]['priority']['code']=='510001'
        assert not data['unknown']
        assert all(not g['observe'] for g in data['tracks'].values())
    assert all(x['candidate'] in (None,'510001') for x in out['state']['pairs'].values())


def api():
    try:
        return importlib.import_module('tools.etf_research.pair_review')
    except ModuleNotFoundError:
        raise AssertionError('independent pair review module missing')


def row(code, cycles=10, efficiency=2, recent=3, recent_eff=1, **extra):
    return dict(code=code, name=code, has_all_four_windows=True,
                full_cycles=cycles, full_cycle_net_per_avg_cost_pct=efficiency,
                recent20_cycles=recent, recent20_cycle_net_per_avg_cost_pct=recent_eff,
                corr_sh589720=.25, corr_sz159363=.85, **extra)


def fixture():
    return dict(summary=dict(asof='2026-10-09', version='research-v1',
                production_scope=True, full_pool=True, offline=False,
                data_failed_runs=0, fetch_errors=0),
                holdings={c: row(c) for c in ('sz159363', 'sh589720', 'sz159992')},
                ranking=[row('sh510001',20,4), row('sh510002',15,3,2,.5),
                         row('sh510003',18,4), row('sh510004',30,5),
                         row('sz159992',50,10), row('sh510005',12,3)])


def taxonomy():
    entries={c:dict(verified=True,index_id=i,theme_id=t,sources=['https://official.example/index'])
             for c,i,t in [('sz159363','ai1','ai'),('sh589720','drug1','drug'),
                          ('sh510001','ai1','ai'),('sh510002','ai2','ai'),
                          ('sh510003','drug2','drug'),('sh510004','other','other')]}
    return dict(version='official-test-v1',entries=entries)


def test_pair_selection_is_per_holding_two_tracks_verified_only():
    p=api();result=fixture()
    # More efficient than drug holding but not than AI holding.
    result['holdings']['sz159363']=row('sz159363',19,3.5)
    out=p.evaluate(result,taxonomy=taxonomy())
    assert set(out['holdings'])=={'sz159363','sh589720'}
    ai=out['holdings']['sz159363'];drug=out['holdings']['sh589720']
    assert ai['tracks']['same_class']['priority']['code']=='sh510001'
    assert drug['tracks']['same_class']['priority']['code']=='sh510003'
    assert ai['tracks']['cross_theme']['priority']['code']=='sh510004'
    assert ai['tracks']['same_class']['priority']['classification']=='same_index'
    assert drug['tracks']['same_class']['priority']['classification']=='same_theme'
    assert [x['code'] for x in drug['unknown']]==['sh510005']
    assert drug['tracks']['same_class']['priority']['retained_holding']=='sz159363'
    assert drug['tracks']['same_class']['priority']['retained_correlation']==.85
    assert 'sz159992' not in str(out['holdings'])


def test_filters_strict_metrics_completeness_and_observe_cap():
    p=api();r=fixture();tax=taxonomy()
    r['ranking']=[row('sh510001',10,5), row('sh510002',20,2),
                  dict(row('sh510003',99,9),has_all_four_windows=False),
                  dict(row('sh510004',99,9),name='港股恒生H股ETF')]
    assert all(v['priority'] is None for v in p.evaluate(r,taxonomy=tax)['holdings']['sh589720']['tracks'].values())
    assert p.evaluate(r,taxonomy=tax,name_exclusions=())['holdings']['sh589720']['tracks']['cross_theme']['priority']['code']=='sh510004'
    r['ranking']=[row(f'sh5100{i}',20+i,4,2,1) for i in range(1,6)]
    for x in r['ranking']:tax['entries'][x['code']]=deepcopy(tax['entries']['sh510003'])
    obs=p.evaluate(r,taxonomy=tax)['holdings']['sh589720']['tracks']['same_class']['observe']
    assert len(obs)==3 and all(x['status']=='observe' for x in obs)
    r['ranking'][0]['recent20_cycles']=3
    assert p.evaluate(r,taxonomy=tax)['holdings']['sh589720']['tracks']['same_class']['priority']['code']=='sh51001'
    tax['entries']['sh51001']['verified']=False
    assert p.evaluate(r,taxonomy=tax)['holdings']['sh589720']['tracks']['same_class']['priority'] is None


def test_second_priority_qualifier_is_shown_as_observe_not_dropped():
    p=api();r=fixture();tax=taxonomy()
    r['ranking']=[row('sh510001',20,4), row('sh510002',15,3)]
    group=p.evaluate(r,taxonomy=tax)['holdings']['sz159363']['tracks']['same_class']
    assert group['priority']['code']=='sh510001'
    assert [x['code'] for x in group['observe']]==['sh510002']
    assert group['observe'][0]['status']=='observe'
    assert '已有priority leader' in group['observe'][0]['reason']


def test_degraded_freeze_does_not_attach_old_count_to_other_candidate(tmp_path):
    p=api();r=fixture();tax=taxonomy();path=tmp_path/'pairs.json'
    def run():return p.run_pair_review(r,state_path=path,taxonomy=tax)['state']['pairs']['sz159363/same_class']
    assert run()==dict(holding='sz159363',track='same_class',candidate='sh510001',consecutive_weeks=1,review_due=False,executable=False)
    r['summary'].update(asof='2026-10-16',data_failed_runs=1)
    assert run()['consecutive_weeks']==1
    r['ranking'][0]['recent20_cycles']=2
    frozen=run()
    assert frozen['candidate'] is None and frozen['consecutive_weeks']==0


def test_pair_state_adjacent_idempotent_resets_and_legacy_isolation(tmp_path):
    p=api();r=fixture();tax=taxonomy();path=tmp_path/'pairs.json'
    path.write_text('{"version":"legacy","consecutive_weeks":50}')
    def run():return p.run_pair_review(r,state_path=path,taxonomy=tax)
    def signal(out):return out['state']['pairs']['sz159363/same_class']
    assert signal(run())['consecutive_weeks']==1
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-10-16'
    assert signal(run())['review_due'] is True
    r['summary']['asof']='2026-10-30'
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-11-06'
    r['ranking'].append(row('sh510006',21,5));tax['entries']['sh510006']=deepcopy(tax['entries']['sh510001'])
    assert signal(run())['candidate']=='sh510006'
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-11-13';tax['version']='official-v2'
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-11-20';r['summary']['version']='research-v2'
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-11-27';r['ranking'].append(row('sh510007',1,1))
    assert signal(run())['consecutive_weeks']==1
    r['summary']['asof']='2026-12-04'
    changed=p.run_pair_review(r,state_path=path,taxonomy=tax,name_exclusions=())
    assert signal(changed)['consecutive_weeks']==1
    import json
    assert json.loads(path.read_text())==changed['state']
    r['summary']['asof']='2026-11-27'
    import pytest
    with pytest.raises(ValueError,match='rewind'):run()


def test_nonproduction_never_reads_writes_or_reviews_and_degraded_never_advances(tmp_path):
    p=api();r=fixture();path=tmp_path/'pairs.json';tax=taxonomy()
    def run():return p.run_pair_review(r,state_path=path,taxonomy=tax)
    run();original=path.read_bytes()
    r['summary']['asof']='2026-10-16';r['summary']['data_failed_runs']=1
    bad=run()
    assert all(not x['review_due'] and x['consecutive_weeks']<=1 for x in bad['state']['pairs'].values())
    assert path.read_bytes()==original
    r['summary']['asof']='2026-10-23';r['summary']['data_failed_runs']=0
    assert run()['state']['pairs']['sz159363/same_class']['consecutive_weeks']==1
    # Invalid JSON proves validation does not even read the production target.
    path.write_text('not JSON')
    for patch in [dict(offline=True),dict(full_pool=False),dict(production_scope=False),
                  dict(production_scope=False,scope='historical'),dict(production_scope=False,scope='custom')]:
        r['summary'].update(production_scope=True,full_pool=True,offline=False,**{})
        r['summary'].update(patch)
        out=run()
        assert all(not x['review_due'] and x['consecutive_weeks']<=1 for x in out['state']['pairs'].values())
        assert path.read_text()=='not JSON'
    r['summary'].update(production_scope=True,full_pool=True,offline=False)
    path.unlink();r['summary']['data_failed_runs']=1
    assert all(x['consecutive_weeks']==0 for x in run()['state']['pairs'].values())
    assert not path.exists()


def test_weekly_single_research_call_pair_report_and_no_legacy_review(tmp_path):
    from tools.etf_research import weekly, research
    r=fixture();r.update(leader=dict(code='sh510001',full_cycles=20),errors=[])
    r['summary'].update(version=research.VERSION,window_start='2026-07-07',window_end='2026-10-09',
                        successful_runs=1284,failed_runs=0,attempted_assets=321)
    calls=[]
    def runner(**kwargs):calls.append(kwargs);return r
    def run():return weekly.run_weekly(state_path=tmp_path/'legacy.json',pair_state_path=tmp_path/'pair.json',
                                      research_runner=runner,taxonomy=taxonomy())
    first=run()
    assert len(calls)==1 and calls[0]=={}
    assert 'pair_review' in first
    assert '【逐持仓双轨周检】' in first['report']
    assert 'name-based' in first['report'] and '有限过滤' in first['report']
    assert 'unknown' in first['report'] and '待核' in first['report']
    assert '159992 exit-only' in first['report']
    assert '保留sz159363相关性=0.850' in first['report']
    assert '同类替换' in first['report'] and '跨主题' in first['report']
    r['summary']['asof']='2026-10-16'
    assert 'HUMAN_ROTATION_REVIEW' in run()['report']
    # Legacy can still hit its historical threshold but cannot drive the new report.
    r['ranking'][0]['recent20_cycles']=2
    r['summary']['asof']='2026-10-23'
    final=run()
    assert final['state']['review_due'] is True
    assert 'HUMAN_ROTATION_REVIEW sz159363 same_class' not in final['report']


def test_official_assets_schema_unknown_observe_and_diagnostics():
    p=api();r=fixture()
    tax=taxonomy();official={'version':tax['version'],'assets':{c:dict(v,theme=v['theme_id'],index_name=v['index_id'],verified_date='2026-10-11') for c,v in tax['entries'].items()}}
    for x in r['ranking']:
        x.update(early_cycles=2,late_cycles=8,early_cycle_net_per_avg_cost_pct=.4,
                 late_cycle_net_per_avg_cost_pct=2.5,full_max_unclosed_cycle_days=35,
                 full_avg_cost=32000,full_end_cost=41000,full_inventory_pnl=-600)
    out=p.run_pair_review(r,taxonomy=official,state_path=None)
    assert out['holdings']['sz159363']['tracks']['same_class']['priority']['code']=='sh510001'
    unknown=out['holdings']['sz159363']['unknown']
    assert all(x['status']=='observe' for x in unknown)
    assert all('待核' in x['reason'] for x in unknown)
    report='\n'.join(p.report_lines(out))
    assert '前半' in report and '后半' in report and '未闭合' in report and '平均占用' in report
    assert '35.000' in report and '32000.000' in report


def test_default_taxonomy_and_same_index_precedence(tmp_path,monkeypatch):
    p=api();r=fixture();tax=taxonomy()
    import json
    target=tmp_path/'taxonomy.json';target.write_text(json.dumps(tax))
    monkeypatch.setattr(p,'DEFAULT_TAXONOMY',target,raising=False)
    # same-index candidates are shown ahead of more efficient same-theme candidates.
    tax['entries']['sh510003']=dict(tax['entries']['sh510001'],index_id='ai2')
    target.write_text(json.dumps(tax));r['ranking'][2].update(full_cycles=50,full_cycle_net_per_avg_cost_pct=10)
    out=p.run_pair_review(r,state_path=None)
    assert out['holdings']['sz159363']['tracks']['same_class']['priority']['code']=='sh510001'


def test_cli_pair_options_do_not_leak_to_research(tmp_path,monkeypatch):
    from tools.etf_research import weekly
    captured=[]
    monkeypatch.setattr(weekly,'run_weekly',lambda **kw:captured.append(kw) or {'report':'test'})
    weekly.main(['--asof','2026-10-09','--taxonomy-path','official.json','--pair-state-path',str(tmp_path/'pair.json'),'--include-hong-kong'])
    assert captured[0]['taxonomy_path']=='official.json'
    assert captured[0]['pair_state_path']==str(tmp_path/'pair.json')
    assert captured[0]['name_exclusions']==()


def test_incomplete_holding_and_nonfinite_metrics_cannot_review():
    p=api();r=fixture()
    r['holdings']['sz159363']['has_all_four_windows']=False
    assert all(g['priority'] is None for g in p.evaluate(r,taxonomy=taxonomy())['holdings']['sz159363']['tracks'].values())
    r['holdings']['sz159363']['has_all_four_windows']=True
    r['ranking'][0]['full_cycle_net_per_avg_cost_pct']=float('inf')
    assert p.evaluate(r,taxonomy=taxonomy())['holdings']['sz159363']['tracks']['same_class']['priority'] is None


def test_high_retained_correlation_warns_not_veto_and_taxonomy_coverage():
    p=api();r=fixture()
    r['ranking'][3]['corr_sh589720']=.998
    out=p.run_pair_review(r,state_path=None,taxonomy=taxonomy())
    assert out['holdings']['sz159363']['tracks']['cross_theme']['priority']['code']=='sh510004'
    report='\n'.join(p.report_lines(out))
    assert '高重叠需人工核验' in report and '不代表组合互补' in report
    assert 'taxonomy已核' in report and '未知待核' in report
    assert out['taxonomy_coverage']['verified_assets']==6


def test_real_default_taxonomy_same_index_and_known_pair_lines():
    import json
    p=api();tax=json.loads(p.DEFAULT_TAXONOMY.read_text(encoding='utf-8'))
    assert p.classify('sz159363','sz159246',tax)=='same_index'
    assert p.classify('sh589720','sh589120',tax)=='same_index'
    r=fixture();r['ranking']=[row('sz159246',20,4),row('sh589120',18,4)]
    out=p.run_pair_review(r,state_path=None)
    for holding, candidate in [('sz159363','sz159246'),('sh589720','sh589120')]:
        leader=out['holdings'][holding]['tracks']['same_class']['priority']
        assert leader['code']==candidate
        assert leader['classification']=='same_index'
        assert not out['holdings'][holding]['unknown']
    entries=tax['assets']
    universe=set(r['holdings']) | {x['code'] for x in r['ranking']}
    expected=sum(p.taxonomy_entry(entries,c).get('verified') is True and bool(p.taxonomy_entry(entries,c).get('sources')) for c in universe)
    assert out['taxonomy_coverage']['universe_verified']==expected
    report='\n'.join(p.report_lines(out))
    assert 'sz159246 sz159246 [same_index/priority]' in report
    assert 'sh589120 sh589120 [same_index/priority]' in report


def test_subthemes_preserved_report_does_not_claim_no_overlap():
    import json
    p=api();tax=json.loads(p.DEFAULT_TAXONOMY.read_text(encoding='utf-8'))
    # This slice checks fine-theme semantics with explicitly verified synthetic evidence;
    # default official sources may remain pending and must then classify unknown.
    tax=deepcopy(tax)
    tax['assets']['515120'].update(verified=True,sources=['https://official.example/index'])
    assert p.classify('sh589720','sh515120',tax)=='cross_theme'
    assert tax['assets']['589720']['theme']=='科创板创新药'
    assert tax['assets']['515120']['theme']=='创新药'
    r=fixture();r['ranking']=[row('sh515120',20,4)]
    out=p.run_pair_review(r,state_path=None,taxonomy=tax)
    assert out['holdings']['sh589720']['tracks']['cross_theme']['priority']['code']=='sh515120'
    assert '细分分类不等于无重叠' in '\n'.join(p.report_lines(out))


def test_bare_identifiers_lookup_prefixed_taxonomy_without_changing_codes():
    p=api();tax=taxonomy()
    assert p.classify('159363','510001',tax)=='same_index'
    assert p.classify('sz159363','510001',tax)=='same_index'
    ambiguous=deepcopy(tax['entries']);ambiguous['sz510001']=deepcopy(ambiguous['sh510001'])
    assert p.taxonomy_entry(ambiguous,'510001')=={}
    names=deepcopy(tax)
    for code in ('sz159363','sh510001'):
        names['entries'][code].update(index_id=None,index_name='官方同一指数')
    assert p.classify('sz159363','sh510001',names)=='same_index'
    names['entries']['sh510001']['sources']=[]
    assert p.classify('sz159363','sh510001',names)=='unknown'
    names['entries']['sh510001'].update(sources=['https://official.example/index'],index_id='B')
    names['entries']['sz159363']['index_id']='A'
    assert p.classify('sz159363','sh510001',names)=='same_theme'
    assert p.taxonomy_entry(tax['entries'],'invalid159363')=={}
    assert p.taxonomy_entry(tax['entries'],'15936')=={}
    r=fixture();r['ranking']=[row('510001',20,4)]
    out=p.run_pair_review(r,state_path=None,taxonomy=tax)
    assert out['holdings']['sz159363']['tracks']['same_class']['priority']['code']=='510001'


def test_six_digit_official_identifiers_match_prefixed_research_codes():
    p=api();r=fixture();tax=taxonomy()
    tax['entries']={code[2:]:v for code,v in tax['entries'].items()}
    out=p.run_pair_review(r,state_path=None,taxonomy=tax)
    assert out['holdings']['sz159363']['tracks']['same_class']['priority']['code']=='sh510001'
    assert out['taxonomy_coverage']['universe_verified']==6
