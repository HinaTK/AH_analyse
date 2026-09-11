import polars as pl
from pathlib import Path
p = Path(r'D:/Code/AH_analyse/ah_recommendation_system/backend/data/market_store/a_share_spot_20260911.parquet')
df = pl.read_parquet(p)
print('cols', df.columns)
print('rows', df.height)
amount_cols = [c for c in df.columns if 'amount' in c.lower() or 'turnover' in c.lower() or '成交' in c]
print('amount-like', amount_cols)
print(df.select([c for c in ['code','name','price','change_pct','pe','amount','volume','turnover_pct','source'] if c in df.columns]).head(8))
if 'amount' in df.columns:
    s = df['amount']
    print('amount null', s.null_count(), 'zero', (s==0).sum(), 'gt1e8', (s>=1e8).sum(), 'max', s.max(), 'median', s.median())
    print(df.filter(pl.col('code').is_in(['002142','600036','601872','300750'])).select([c for c in df.columns if c in ['code','name','price','amount','volume','pe','source','amount_reference','history_days']]))
