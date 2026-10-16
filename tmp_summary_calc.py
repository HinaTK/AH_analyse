import json
from pathlib import Path
from datetime import date, timedelta

home = Path("D:/Hermes Agent CN Desktop/data/hermes-home/cache/grid-account")
codes = ("589720", "159363", "159992")
tot_ni = 0.0
tot_t = 0.0
tot_qty = 0
all_dates = set()
for c in codes:
    d = json.loads((home / ("confirmed-" + c + ".json")).read_text(encoding="utf-8"))
    trades = d["trades"]
    buy_amt = sum(float(t["amount"]) for t in trades if t["side"] == "buy")
    sell_amt = sum(float(t["amount"]) for t in trades if t["side"] == "sell")
    buy_qp = sum(float(t["qty"]) * float(t["price"]) for t in trades if t["side"] == "buy")
    sell_qp = sum(float(t["qty"]) * float(t["price"]) for t in trades if t["side"] == "sell")
    ni = float(d["net_invested"])
    t_net = float(d.get("t_net", 0))
    tot_ni += ni
    tot_t += t_net
    tot_qty += d["qty"]
    dates = sorted({t["date"] for t in trades if t.get("date")})
    all_dates |= set(dates)
    print(c, "trades", len(trades), "qty", d["qty"], "net_invested", round(ni, 2), "t_net", round(t_net, 2))
    print("   buy_amount_sum", round(buy_amt, 2), "sell_amount_sum", round(sell_amt, 2), "buy_qp", round(buy_qp, 2), "sell_qp", round(sell_qp, 2))
    print("   recomputed_net_amounts", round(buy_amt - sell_amt, 2), "distinct_dates", len(dates), dates)
print("TOTAL net_invested", round(tot_ni, 2), "t_net", round(tot_t, 2), "qty", tot_qty)
start = date(2026, 9, 23)
end = date(2026, 10, 16)
days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
biz = [x for x in days if x.weekday() < 5]
print("calendar", start, "~", end, "days", len(days), "business_days", len(biz))
print("trade_dates_present", sorted(all_dates))