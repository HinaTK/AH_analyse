"""Manual smoke test script - bypass run.py entry point."""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"D:\Code\AH_analyse")
sys.path.insert(0, r"D:\Code\AH_analyse\ah_recommendation_system\backend")

print("=== smoke_debug.py start ===", flush=True)

try:
    from ah_recommendation_system.backend.data.price_fetcher import get_price_fetcher
    print("[1] imported price_fetcher", flush=True)
    pf = get_price_fetcher()
    pf.enable_mock_data()
    print(f"[2] mock={pf.use_mock_data}", flush=True)

    from ah_recommendation_system.backend.stock_recommend.data_collector import collect_all
    print("[3] imported collect_all", flush=True)
    snap = collect_all(limit=50)
    print(f"[4] snap date={snap.date} errors={snap.errors}", flush=True)
    print(f"    fundamental rows={len(snap.fundamental.get('rows') or [])}", flush=True)
    print(f"    capital rows={len(snap.capital.get('rows') or [])}", flush=True)
    print(f"    events stock_news={len(snap.events.get('stock_news') or [])}", flush=True)

    from ah_recommendation_system.backend.stock_recommend.candidate_pool import build_candidates, to_dict_list
    print("[5] imported candidate_pool", flush=True)
    cands = build_candidates(snap, top_n=10)
    print(f"[6] candidates={len(cands)}", flush=True)
    for c in cands[:3]:
        print(f"    - {c.code} {c.name} composite={c.composite} fund={c.fundamental_score} cap={c.capital_score} event={c.event_score}", flush=True)

    from ah_recommendation_system.backend.stock_recommend.llm_selector import select_with_llm
    print("[7] imported llm_selector", flush=True)
    selection = select_with_llm(cands, macro_context=snap.events.get("macro_news"), top_n_pick=3)
    print(f"[8] selection picks={len(selection.get('picks') or [])} llm_mock={selection.get('llm_mock')}", flush=True)
    for p in (selection.get("picks") or []):
        print(f"    - {p.get('code')} {p.get('name')} action={p.get('action')} conf={p.get('confidence')}", flush=True)

    from ah_recommendation_system.backend.stock_recommend.report_builder import build_report, save_report
    print("[9] imported report_builder", flush=True)
    cand_dicts = to_dict_list(cands)
    report = build_report(selection=selection, candidates=cand_dicts, snapshot_errors=snap.errors)
    print(f"[10] report picks={len(report['picks'])} cands={report['candidate_count']}", flush=True)

    backend_root = Path(r"D:\Code\AH_analyse\ah_recommendation_system\backend")
    paths = save_report(report, backend_root)
    print(f"[11] saved {paths}", flush=True)
    print("=== smoke_debug.py OK ===", flush=True)

except Exception as e:
    print(f"=== smoke_debug.py FAILED: {e} ===", flush=True)
    traceback.print_exc()
    sys.exit(1)
