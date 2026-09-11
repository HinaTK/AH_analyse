"""Pull GigaDevice 兆易创新 data with hard timeout per call."""
import sys
import json
import traceback
import signal
from datetime import datetime, timedelta
from pathlib import Path

LOG = Path(r"D:\Code\AH_analyse\ah_recommendation_system\backend\logs\zjc_k.log")
LOG.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    line = msg + "\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        print(msg, flush=True)
    except Exception:
        pass

def timeout_handler(signum, frame):
    raise TimeoutError("akshare call timed out")

# set default alarm: 20s per call
def call_with_timeout(fn, args=(), kwargs=None, seconds=20):
    """Run fn with SIGALRM timeout (works on Linux/Mac; on Windows it's a soft guard)."""
    kwargs = kwargs or {}
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

log(f"=== start {datetime.now().isoformat()} ===")
import akshare as ak
log(f"akshare version: {ak.__version__}")

code = "603986"
end = datetime.now().strftime("%Y%m%d")
start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

# 1. K 线 (前复权)
try:
    df = call_with_timeout(ak.stock_zh_a_hist, kwargs=dict(
        symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
    ), seconds=30)
    if df is None or df.empty:
        log("K-line: empty")
    else:
        log(f"K-line rows: {len(df)}")
        tail = df.tail(15)[["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]]
        log(tail.to_string(index=False))
        Path(r"D:\Code\AH_analyse\ah_recommendation_system\backend\logs\zjc_k.json").write_text(
            json.dumps(df.tail(30).to_dict(orient="records"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
except Exception as e:
    log(f"K-line failed: {e}")

# 2. 实时行情（盘后/周末通常仍可取）
try:
    spot = call_with_timeout(ak.stock_zh_a_spot_em, seconds=30)
    if spot is not None and not spot.empty:
        row = spot[spot["代码"] == code]
        if not row.empty:
            log("=== 实时行情 ===")
            cols = [c for c in ["代码", "名称", "最新价", "涨跌幅", "换手率", "市盈率-动态", "市净率", "总市值", "60日涨跌幅", "年初至今涨跌幅"] if c in row.columns]
            log(row.iloc[0][cols].to_string())
        else:
            log(f"spot: code {code} not found in table")
    else:
        log("spot: empty (likely non-trading day or rate-limited)")
except Exception as e:
    log(f"spot failed: {e}")

# 3. 个股新闻
try:
    news = call_with_timeout(ak.stock_news_em, kwargs=dict(symbol=code), seconds=30)
    if news is not None and not news.empty:
        log(f"=== 个股新闻 ({len(news)} 条) ===")
        for _, r in news.head(10).iterrows():
            log(f"- [{r.get('发布时间','')}] {r.get('新闻标题','')} ({r.get('来源','')})")
    else:
        log("news: empty")
except Exception as e:
    log(f"news failed: {e}")

log("=== done ===")
