from datetime import datetime, timedelta
from ah_recommendation_system.backend.data.price_fetcher import PriceFetcher

pf = PriceFetcher()
end = datetime.now().strftime('%Y%m%d')
start = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
print('fetch', start, end)
df = pf.get_a_share_price('002142', start, end)
print('empty', df is None or df.empty)
if df is not None and not df.empty:
    print('cols', list(df.columns))
    print(df.tail(5).to_string())
    if 'amount' in df.columns and 'close' in df.columns and 'volume' in df.columns:
        tail = df.tail(3)
        for _, row in tail.iterrows():
            amt = float(row.get('amount') or 0)
            close = float(row.get('close') or 0)
            vol = float(row.get('volume') or 0)
            print('date', row.get('date'), 'amount', amt, 'close', close, 'volume', vol, 'px*vol', close*vol, 'amt/(px*vol)' if close*vol else None, (amt/(close*vol) if close*vol else None))
print('history sources', pf.history_source_counts)
print('history errors', pf.history_errors[-5:])
