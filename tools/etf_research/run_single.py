"""Run grid_model.simulate() on a single ETF by bare 6-digit code.
Standalone: fetches its own bars, picks last N trading days, simulates.
Handles the 1% first-bar-volume constraint by catching and reporting.
Usage: python -m tools.etf_research.run_single <code> [gap] [sessions] [slip]
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.etf_research import engine
from tools.etf_research.grid_model import simulate
from tools.etf_research.research import latest_session

def run(code, gap=0.02, sessions=63, slip=0.0005, lot_budget=5000):
    prefixed = code
    if not prefixed.startswith(('sh', 'sz')):
        if code.startswith(('5', '6', '9')):
            prefixed = 'sh' + code
        else:
            prefixed = 'sz' + code

    print(f"  fetching {prefixed} ...")
    frame = engine.fetch_bars(prefixed)
    last = str(frame.time.iloc[-1])
    print(f"  bars: {len(frame)}, last={last}")

    asof = latest_session()
    print(f"  asof={asof}")

    daily = frame[frame.time.str[:10] <= asof].groupby(frame.time.str[:10]).agg(
        open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
        close=('close', 'last'), volume=('volume', 'sum')).reset_index()
    daily = daily.sort_values('time')
    dates = list(daily['time'].iloc[-sessions:])
    print(f"  window: {dates[0]} -> {dates[-1]} ({len(dates)} trading days)")

    sub = frame[frame.time.str[:10].isin(dates)].reset_index(drop=True)
    groups = sub.groupby(sub.time.str[:10])
    if sorted(groups.groups) != dates:
        raise ValueError("incomplete common window")
    min_bars = min(len(g) for _, g in groups)
    if min_bars < 40:
        raise ValueError(f"insufficient intraday coverage: min bars/day = {min_bars}")

    # first bar volume check
    first_vol_shares = sub.volume.iloc[0] * 100  # lots -> shares
    pct1 = first_vol_shares * 0.01
    print(f"  first bar: {sub.time.iloc[0]}, vol={sub.volume.iloc[0]} lots ({first_vol_shares:.0f} shares), 1% limit={pct1:.0f} shares")

    try:
        result = simulate(sub, gap=gap, t0=False, slip=slip, trace=True, lot_budget=lot_budget)
    except ValueError as e:
        if 'initial orders exceed 1% first bar volume' in str(e):
            print(f"  WARNING: {e}")
            print(f"  The model's initial order (core 10k + 4×5k = ~30k shares at ~1.4 price ≈ 21k shares)")
            print(f"  exceeds 1% of first bar volume ({pct1:.0f} shares).")
            print(f"  This is a model constraint, not a real-trading problem.")
            print(f"  Skipping simulation for {code}.")
            return None
        raise

    result['code'] = code
    result['prefixed_code'] = prefixed
    result['window_start'] = dates[0]
    result['window_end'] = dates[-1]
    result['gap'] = gap
    result['sessions'] = sessions
    return result

def main():
    code = sys.argv[1]
    gap = float(sys.argv[2]) if len(sys.argv) > 2 else 0.02
    sessions = int(sys.argv[3]) if len(sys.argv) > 3 else 63
    slip = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0005

    print(f"Running {code} with gap={gap}, sessions={sessions}, slip={slip}")
    r = run(code, gap=gap, sessions=sessions, slip=slip)

    if r is None:
        print("\nNo results — model constraint blocked simulation.")
        return

    print("\n=== RESULTS ===")
    keys = ['code', 'prefixed_code', 'gap', 'window_start', 'window_end', 'sessions',
            'days', 'bars', 'cycles', 'cycle_net', 'cycle_return_on_40k_pct',
            'sales', 'initial_sales', 'realized_total',
            'inventory_pnl', 'inventory_loss', 'account_pnl', 'return_pct',
            'max_drawdown_pct', 'same_exposure_bh_pct', 'max_exposure_bh_pct',
            'excess_same_bh_pct', 'fees', 'trades', 'avg_cost',
            'max_cost', 'end_cost', 'min_cash', 'end_cash',
            'median_cycle_days', 'p90_cycle_days', 'max_unclosed_cycle_days',
            'max_no_sale_days', 'settlement_blocks', 'cancelled_signals',
            'end_slots', 'start', 'end']
    for k in keys:
        if k in r:
            v = r[k]
            if isinstance(v, float):
                print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")

    out_dir = Path("D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-research")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"single_{code}.json"
    r_clean = {k: v for k, v in r.items() if k not in ('events', 'equity_curve')}
    out_file.write_text(json.dumps(r_clean, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nSaved to {out_file}")

if __name__ == '__main__':
    main()