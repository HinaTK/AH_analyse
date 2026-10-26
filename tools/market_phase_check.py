# -*- coding: utf-8 -*-
"""市况判定数据采集（配套 caopan-baodian / market-phase-detection 能力卡）

用途：为"现在是牛市还是熊市"提供客观量价证据，不做主观定性。
输出每只标的：
  - 最新收盘、MA20/30/60 位置
  - 量能对比：近5日平均成交额 vs 近120日峰值成交额（地量检查：<1/3）
  - 回撤：距近120日/250日最高收盘的跌幅
  - 跌势验证：近5/10/20个交易日累计涨跌幅、连跌天数
  - ADX(14) + DI+/DI-（书口径：ADX<25 震荡，>=25 单边）
数据源：东方财富公开K线接口（push2his.eastmoney.com），日线前复权。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

# (secid, 名称) —— 东财 secid: 1=沪, 0=深
INSTRUMENTS = [
    ("1.000001", "上证指数"),
    ("1.000300", "沪深300"),
    ("0.399006", "创业板指"),
    ("1.000688", "科创50"),
    ("1.589720", "589720科创创新药ETF"),
    ("0.159363", "159363创业板人工智能ETF"),
]


def fetch_kline(secid: str, lmt: int = 300, klt: str = "101"):
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": klt,     # 101=日线, 102=周线
        "fqt": "1",     # 前复权
        "end": "20500101",
        "lmt": str(lmt),
    }
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           + urllib.parse.urlencode(params))
    last_err = None
    for attempt in range(3):  # 东财限流会瞬断，间隔重试
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0",
                              "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            last_err = e
            if attempt == 2:
                raise
            time.sleep(3)
    rows = []
    for line in data.get("data", {}).get("klines", []):
        p = line.split(",")
        rows.append({
            "date": p[0],
            "open": float(p[1]), "close": float(p[2]),
            "high": float(p[3]), "low": float(p[4]),
            "volume": float(p[5]),   # 手
            "amount": float(p[6]),   # 元
            "pct": float(p[8]),      # 涨跌幅 %
        })
    return rows


def ma(closes, n, offset=0):
    """截至 len(closes)-1-offset 处的 n 日均线；数据不足返回 None。"""
    end = len(closes) - offset
    if end < n:
        return None
    return sum(closes[end - n:end]) / n


def wilder_adx(rows, n=14):
    """标准 Wilder DMI/ADX。返回 (adx, +DI, -DI) 或 None。"""
    if len(rows) < 2 * n + 2:
        return None
    trs, pdms, mdms = [], [], []
    for i in range(1, len(rows)):
        h, l = rows[i]["high"], rows[i]["low"]
        pc, ph, pl = rows[i - 1]["close"], rows[i - 1]["high"], rows[i - 1]["low"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up, dn = h - ph, pl - l
        pdm = up if up > dn and up > 0 else 0.0
        mdm = dn if dn > up and dn > 0 else 0.0
        trs.append(tr); pdms.append(pdm); mdms.append(mdm)

    def wilder_smooth(xs):
        out = [sum(xs[:n])]
        for x in xs[n:]:
            out.append(out[-1] - out[-1] / n + x)
        return out

    s_tr, s_pdm, s_mdm = wilder_smooth(trs), wilder_smooth(pdms), wilder_smooth(mdms)
    dx_list = []
    pdi_last = mdi_last = None
    for i in range(len(s_tr)):
        pdi = 100.0 * s_pdm[i] / s_tr[i] if s_tr[i] else 0.0
        mdi = 100.0 * s_mdm[i] / s_tr[i] if s_tr[i] else 0.0
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
        dx_list.append(dx)
        pdi_last, mdi_last = pdi, mdi
    adx_series = [sum(dx_list[:n]) / n]
    for dx in dx_list[n:]:
        adx_series.append((adx_series[-1] * (n - 1) + dx) / n)
    return adx_series[-1], pdi_last, mdi_last


def weekly_kdj(rows, n=9):
    """对周K序列算标准 KDJ(9,3,3)，返回 [(K,D), ...]。

    rows 应为周K线（klt=102，见 fetch_kline 的 klt 参数）；日期字段
    形如 2026-10-23（周K最后一根交易日）。直接以每根周K为一期，
    不做二次聚合。
    """
    k = d = 50.0
    out = []
    for r in rows:
        hi, lo, c = r["high"], r["low"], r["close"]
        rng = hi - lo
        rsv = 50.0 if rng == 0 else 100.0 * (c - lo) / rng
        k = (2.0 * k + rsv) / 3.0
        d = (2.0 * d + k) / 3.0
        out.append((k, d))
    return out


def kdj_golden_cross(series):
    """最后一根是否金叉且 K<50（书口径：50 以下金叉才是底部进场信号）。"""
    if len(series) < 2:
        return False, None
    (k1, d1), (k2, d2) = series[-2], series[-1]
    golden = k1 <= d1 and k2 > d2
    return golden, k2


def adx_with_prev(rows, n=14):
    """返回 (当前ADX, 前一交易日ADX)。数据不足返回 (None, None)。"""
    cur = wilder_adx(rows, n)
    prev = wilder_adx(rows[:-1], n) if len(rows) > n else None
    return (cur[0], prev[0]) if cur and prev else (None, None)


def _state_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "market_phase_state.json")


def should_push(state, secid, date):
    return state.get(secid) != date


def record_push(state, secid, date):
    state[secid] = date
    return state


def evaluate_phase_signals(metrics):
    """右侧三信号判定（纯函数，供盘后监控用）。

    三条全中才 trigger（承诺口径：信号齐了才推飞书）：
      1. dilVolume: 近5日均额/峰值 < 1/3（地量，卖压衰竭）
      2. adx_break: ADX 从 >=25 上方降到 <25（单边动能衰竭；一直在 25 下方不算）
      3. kdj_golden: 周线 KDJ 金叉且 K<50（底部区金叉）
    """
    dil_volume = metrics["vol_ratio"] < 1.0 / 3.0
    adx_break = metrics["adx_prev"] >= 25.0 > metrics["adx"]
    kdj_golden = bool(metrics["kdj_golden"]) and metrics["kdj_k"] < 50.0
    trigger = dil_volume and adx_break and kdj_golden
    return {"dilVolume": dil_volume, "adx_break": adx_break,
            "kdj_golden": kdj_golden, "kdj_k": metrics["kdj_k"],
            "trigger": trigger}


def action_label(m):
    """输出 (动作, 成数, 理由)。成数=目标方向仓位（非总账户）。

    决策树（书口径 + 信号点亮数渐进）：
      三信号齐              → 买入 7成（右侧确认进场）
      单边下跌              → 0成观望；地量或周线金叉先行 → 1成试错
      单边上涨              → 持有 8成（+DI主导，别乱动）
      震荡 + 深回撤(<=-30%)  → 3成分批埋伏
      震荡 + 浅回撤          → 5成网格波段
    """
    if m["trigger"]:
        return "买入", "7成", "右侧三信号齐：地量+ADX降破25+周线金叉"
    if m["adx"] >= 25:
        if m["trend"] == "up":
            return "持有", "8成", f"单边上涨 ADX={m['adx']:.0f}，持筹不折腾"
        if m["dilVolume"]:
            return "试仓买入", "1成", f"单边下跌 ADX={m['adx']:.0f} 但地量已现，卖压衰竭试探"
        if m["kdj_golden"]:
            return "试仓买入", "1成", f"周线金叉先行，日线动能 ADX={m['adx']:.0f} 未衰竭，轻仓试探"
        return "空仓观望", "0成", f"单边下跌 ADX={m['adx']:.0f}，右侧未确认别接刀"
    if m["dd250"] <= -30:
        return "分批埋伏", "3成", f"震荡+深回撤{m['dd250']:.0f}%，网格接回窗口"
    return "网格波段", "5成", f"震荡市 ADX={m['adx']:.0f}，网格主场"


def build_alert(results):
    """拼接触发警报的标的清单；无触发返回空串（空 stdout = cron 不推送）。"""
    lines = []
    for row in results:
        sig = row.get("signals") or {}
        if not sig.get("trigger"):
            continue
        parts = []
        if sig.get("dilVolume"):
            parts.append("地量")
        if sig.get("adx_break"):
            parts.append("ADX降破25")
        if sig.get("kdj_golden"):
            parts.append(f"周线金叉K={sig.get('kdj_k', 0):.1f}")
        lines.append(f"[{row['name']}] {row['date']} 收盘 {row['close']}  "
                     + " + ".join(parts))
    return "\n".join(lines)


def render_header(date):
    """富渲染表头：带口径说明，让人不查文档也看得懂。"""
    return (
        f"📈 市况操作信号（{date}）\n"
        "右侧三信号 = 地量(近5日均额<峰值1/3) + ADX从≥25降破25(单边动能死) + 周线KDJ金叉K<50(底部金叉)；\n"
        "三信号齐→🔔买入信号。成数指方向仓/新开仓目标，不是清仓网格；网格挂单照常由09:20任务管。"
    )


def render_instrument(m):
    """单标的富渲染：关键读数全量输出（2026-10-26 用户要求：简报看不出是什么）。"""
    sig = m.get("signals") or {}
    on = lambda key, label: (f"✅{label}" if sig.get(key) else f"○{label}未亮")
    ma = m.get("ma_pos") or {}
    ma20 = ma.get(20)
    ma60 = ma.get(60)
    ma20_txt = f"{ma20:+.1f}%" if ma20 is not None else "—"
    ma60_txt = f"{ma60:+.1f}%" if ma60 is not None else "—"
    lines = [
        f"【{m['name']}】收 {m['close']:.2f}（{m.get('pct', 0):+.2f}%）",
        f"  均线：MA20 {ma20_txt}｜MA60 {ma60_txt}｜距250日高点 {m['dd250']:+.1f}%",
        f"  量能：近5日均额/近120日峰值 = {m['vol_ratio']:.2f}（<0.33为地量）",
        f"  动能：ADX {m['adx']:.1f}（前日 {m['adx_prev']:.1f}）｜+DI {m['pdi']:.1f} / -DI {m['mdi']:.1f}"
        f" → {'单边' if m['adx'] >= 25 else '震荡'}市，{'多头' if m['trend'] == 'up' else '空头'}方向",
        f"  右侧信号：{on('dilVolume', '地量')} {on('adx_break', 'ADX降破25')} {on('kdj_golden', '周线金叉')}"
        + (f"（K={m['kdj_k']:.1f}）" if m.get('kdj_k') is not None else ""),
        f"  ▶ 结论：{m['label']}·{m['fraction']} —— {m['reason']}",
    ]
    return "\n".join(lines)


def render_report(results):
    """整份富渲染报告：表头 + 每标的块 + 新触发提示。"""
    out = [render_header(results[0]["date"]), ""]
    for r in results:
        out.append(render_instrument(r))
        out.append("")
    return "\n".join(out).rstrip()


def analyze(secid, name):
    rows = fetch_kline(secid)
    if len(rows) < 70:
        print(f"[{name}] 数据不足（{len(rows)} 根）")
        return
    closes = [r["close"] for r in rows]
    amounts = [r["amount"] for r in rows]
    last = rows[-1]
    c = last["close"]

    # 均线位置
    ma_pos = {}
    for n in (20, 30, 60):
        m = ma(closes, n)
        ma_pos[n] = (c - m) / m * 100 if m else None

    # 量能：近5日均额 vs 近120日峰值（地量 = <1/3）
    win = min(120, len(amounts))
    peak_amt = max(amounts[-win:])
    avg5_amt = sum(amounts[-5:]) / 5
    vol_ratio = avg5_amt / peak_amt

    # 回撤
    def dd(ndays):
        w = min(ndays, len(closes))
        return (c / max(closes[-w:]) - 1) * 100
    dd120, dd250 = dd(120), dd(250)

    # 近期跌势
    def chg(ndays):
        w = min(ndays + 1, len(closes))
        return (c / closes[-w] - 1) * 100
    chg5, chg10, chg20 = chg(5), chg(10), chg(20)

    # 连跌天数（按收盘价）
    down_streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            down_streak += 1
        else:
            break

    adx = wilder_adx(rows)

    print(f"\n=== {name} （{last['date']} 收盘） ===")
    print(f"  收盘: {c:.2f}   当日涨跌: {last['pct']:+.2f}%")
    for n in (20, 30, 60):
        v = ma_pos[n]
        side = "上方" if (v or 0) > 0 else "下方"
        print(f"  MA{n}: {side} {v:+.2f}%")
    print(f"  量能: 近5日均额 {avg5_amt/1e8:.0f}亿 vs 近{win}日峰值 {peak_amt/1e8:.0f}亿"
          f"  比值 {vol_ratio:.2f}  （地量阈值 <0.33）")
    print(f"  回撤: 距120日高点 {dd120:+.1f}%   距250日高点 {dd250:+.1f}%")
    print(f"  近期: 5日 {chg5:+.1f}% / 10日 {chg10:+.1f}% / 20日 {chg20:+.1f}%"
          f"   连跌 {down_streak} 天")
    if adx:
        a, pdi, mdi = adx
        regime = "单边" if a >= 25 else "震荡（书口径：指标失效）"
        trend = "多头方向" if pdi > mdi else "空头方向"
        print(f"  ADX(14): {a:.1f}  +DI {pdi:.1f} / -DI {mdi:.1f}"
              f"  → {regime}，{trend}")


def monitor_main():
    """盘后监控主流程：每日输出操作信号表；三信号齐的新触发才标🔔。

    输出格式（stdout 推飞书）：
      测试指数 | 2026-10-23 | 收3600 | 空仓观望 | 单边下跌 ADX=44，右侧未确认别接刀
    去重：状态文件记录每标的最后触发日，同日重跑不重复标🔔。
    """
    state = {}
    if os.path.exists(_state_path()):
        try:
            with open(_state_path(), encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}

    results = []
    for secid, name in INSTRUMENTS:
        try:
            daily = fetch_kline(secid, lmt=300, klt="101")
            time.sleep(0.8)  # 东财接口限流：连续请求会被断连
            weekly = fetch_kline(secid, lmt=120, klt="102")
            time.sleep(0.8)
            if len(daily) < 70 or len(weekly) < 10:
                continue
            closes = [r["close"] for r in daily]
            amounts = [r["amount"] for r in daily]
            win = min(120, len(amounts))
            vol_ratio = (sum(amounts[-5:]) / 5) / max(amounts[-win:])
            adx_raw = wilder_adx(daily)
            adx_prev_raw = wilder_adx(daily[:-1])
            if adx_raw is None or adx_prev_raw is None:
                continue
            adx_cur, pdi, mdi = adx_raw
            adx_prev = adx_prev_raw[0]
            golden, kdj_k = kdj_golden_cross(weekly_kdj(weekly))
            dd250 = (closes[-1] / max(closes[-250:]) - 1) * 100
            ma_pos = {}
            for n in (20, 30, 60):
                m_val = ma(closes, n)
                ma_pos[n] = ((closes[-1] - m_val) / m_val * 100) if m_val else None
            signals = evaluate_phase_signals({
                "vol_ratio": vol_ratio, "adx": adx_cur, "adx_prev": adx_prev,
                "kdj_golden": golden, "kdj_k": kdj_k if kdj_k is not None else 100.0,
            })
            label, fraction, reason = action_label({
                "trigger": signals["trigger"], "adx": adx_cur,
                "trend": "up" if pdi > mdi else "down", "dd250": dd250,
                "dilVolume": signals["dilVolume"], "kdj_golden": signals["kdj_golden"],
            })
            results.append({"name": name, "secid": secid,
                            "date": daily[-1]["date"], "close": closes[-1],
                            "pct": daily[-1].get("pct", 0.0),
                            "label": label, "fraction": fraction, "reason": reason,
                            "signals": signals,
                            "ma_pos": ma_pos, "vol_ratio": vol_ratio,
                            "adx": adx_cur, "adx_prev": adx_prev,
                            "pdi": pdi, "mdi": mdi,
                            "dd250": dd250, "trend": "up" if pdi > mdi else "down",
                            "kdj_k": kdj_k})
        except Exception as e:
            print(f"[{name}] 获取失败: {e}", file=sys.stderr)

    if not results:
        return
    lines = [render_header(results[0]["date"]), ""]
    new_triggers = []
    for r in results:
        bell = ""
        if r["signals"]["trigger"]:
            if should_push(state, r["secid"], r["date"]):
                bell = " 🔔新触发"
                new_triggers.append(r)
            else:
                bell = "（已推）"
        r = dict(r)
        if bell:
            r["reason"] = r["reason"] + bell
        lines.append(render_instrument(r))
        lines.append("")
    print("\n".join(lines).rstrip())
    if new_triggers:
        print()
        print("🔔 右侧三信号齐：地量+ADX降破25+周线金叉 → 买入信号，今日新触发")
        for r in new_triggers:
            record_push(state, r["secid"], r["date"])
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)


def main():
    print(f"数据源: 东方财富 push2his 日K线（前复权）；拉取时间: 本次运行")
    for secid, name in INSTRUMENTS:
        try:
            analyze(secid, name)
        except Exception as e:
            print(f"\n[{name}] 获取失败: {e}")


if __name__ == "__main__":
    main()
