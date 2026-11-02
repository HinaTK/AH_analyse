#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""四大观察哨监控（2026-10-30 历史类比研究的落地，源自 tools/market_history_analog_20261030.md）

哨① 量能地量: 上证5日均额/120日峰值 < 0.33 → 地量（卖压枯竭，右侧信号1/3）
哨② 两融出清: 全市场两融余额 跌破2.20万亿 → 出清加深确认；净偿还连续10日>500亿 → 加速出清
哨③ AI财报季: 财报窗口期标记（2026Q4-2027Q1, 创业板/科创板业绩预告1月底前强制披露）→ 窗口期提示验证临近
哨④ 924级政策: 政策事件型——脚本无法自动判定, 显示"人工盯守"状态 + 备忘清单(SFISF扩容/央行直连工具/化债级财政)

数据源:
  量能: westock kline sh000001 (amount)
  两融: 东财 RPTA_RZRQ_LSHJ (全市场历史序列, 实测可用)
输出: watchdog 模式——有触发/状态翻转才输出, 全部正常静默
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

WESTOCK = r"C:/Users/Administrator/.local/bin/westock.exe"
STATE_PATH = Path("D:/Code/AH_analyse/tools/watchtower_state.json")

# 阈值（研究档案口径）
TH_VOLRATIO = 0.33      # 地量线
TH_MARGIN_CLEAR = 22000.0  # 两融出清线(亿)
TH_MARGIN_ACCEL = 500.0    # 10日净偿还加速线(亿)
EARNINGS_WINDOW = ("2027-01-01", "2027-02-01")  # Q4业绩预告强制披露窗口(1月底前)


def westock(*args):
    r = subprocess.run([WESTOCK, *args], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def volume_ratio():
    """上证: 5日均额/120日峰值。"""
    out = westock("kline", "sh000001", "--period", "day", "--limit", "130")
    lines = [l for l in out.splitlines() if l.startswith("|")]
    if len(lines) < 10:
        return None
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]
    try:
        ai = hdr.index("amount")
        amounts = [float(r[ai]) for r in rows]
    except (ValueError, KeyError, IndexError):
        return None
    if len(amounts) < 120:
        return None
    avg5 = sum(amounts[:5]) / 5
    peak = max(amounts[:120])
    return {"ratio": round(avg5 / peak, 3), "avg5_yi": round(avg5 / 1e8, 0),
            "peak_yi": round(peak / 1e8, 0), "date": rows[0][0]}


def margin_data():
    """东财全市场两融: 最新余额 + 10日净偿还。"""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get?"
           "reportName=RPTA_RZRQ_LSHJ&columns=DIM_DATE,RZYE,RZRQYE,RZYEZB,RZJME10D"
           "&pageSize=8&sortColumns=DIM_DATE&sortTypes=-1")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = json.loads(urllib.request.urlopen(req, timeout=20).read())
        data = ((raw.get("result") or {}).get("data")) or []
        if not data:
            return None
        d = data[0]
        return {
            "date": d["DIM_DATE"][:10],
            "rzye_yi": round(d["RZYE"] / 1e8, 0),        # 融资余额(亿)
            "rzrq_yi": round(d["RZRQYE"] / 1e8, 0),      # 两融余额(亿)
            "pct_ltsz": round(d["RZYEZB"], 2),           # 占流通市值%
            "jme10_yi": round(d["RZJME10D"] / 1e8, 0),   # 10日净偿还(亿, 负=净偿还)
        }
    except Exception as e:
        return {"error": str(e)}


# 哨④ 关键词规则（924级政策=SFISF/回购增持再贷款加码/央行直连股市新工具）
# 化债级财政明确排除（属地方财政常规线，与924工具不同轴）——2026-11-02 定口径
SINA_724_URL = ("https://zhibo.sina.com.cn/api/zhibo/feed?"
                "page={page}&page_size=100&zhibo_id=152&tag_id=0")
SCAN_MAX_PAGES = 20          # 翻页上限（20页×100条≈2天快讯，防接口异常无限回扫）
POLICY_WINDOW_DAYS = 90      # 命中判定窗口：只认90天内的条目
POLICY_STATE_KEYS = ("policy_last_seen_id",)  # 游标持久化键


def fetch_sina_724(page=1):
    """拉取新浪7x24快讯单页（100条）；网络失败返回 None。"""
    try:
        req = urllib.request.Request(
            SINA_724_URL.format(page=page),
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        raw = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace"))
        return parse_sina_feed(raw)
    except Exception:
        return None


def scan_since(last_seen_id):
    """回扫快讯：从新到旧翻页，扫到 last_seen_id（含）或页上限为止。

    无游标（首跑）只扫第一页建基线——不追旧闻、不告警。
    返回新→旧排序的 (id, time, text) 列表；首页失败返回 None（整体降级）。
    """
    items = []
    seen = set()
    max_pages = 1 if last_seen_id is None else SCAN_MAX_PAGES
    for page in range(1, max_pages + 1):
        page_items = fetch_sina_724(page=page)
        if page_items is None:
            if page == 1:
                return None          # 首页失败=拿不到当前快讯，哨④降级
            break                    # 中途失败：返回已收部分（尽力而为）
        stop = False
        for nid, ctime, text in page_items:
            if nid in seen:
                continue
            seen.add(nid)
            items.append((nid, ctime, text))
            if last_seen_id is not None and nid == last_seen_id:
                stop = True
        if stop:
            break
    return items


def load_last_seen_id(path=STATE_PATH):
    """读游标；文件缺失/损坏返回 None。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))["policy_last_seen_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_last_seen_id(news_id, path=STATE_PATH):
    """写游标（保留同文件其他键）。"""
    data = {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["policy_last_seen_id"] = news_id
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
POLICY_KW = [
    # (关键词, 展示名) —— 长词优先，短词需搭配语境词防误伤
    ("互换便利", "SFISF互换便利"),
    ("回购增持再贷款", "回购增持再贷款"),
    ("股票回购增持再贷款", "回购增持再贷款"),
]
POLICY_KW_SHORT = [
    # (短关键词, 语境词元组, 展示名)
    ("直连", ("股市", "资本市场"), "央行直连股市新工具"),
    ("新工具", ("股市", "资本市场"), "央行直连股市新工具"),
]


def parse_sina_feed(raw):
    """新浪7x24结构 result.data.feed.list[] → [(id, create_time, rich_text)]；异常返回 None。"""
    try:
        lst = raw["result"]["data"]["feed"]["list"]
        items = []
        for it in lst:
            if not isinstance(it, dict):
                continue
            text = it.get("rich_text") or ""
            items.append((it.get("id"), it.get("create_time", ""), text))
        return items if items else None
    except (KeyError, TypeError, AttributeError):
        return None


def match_policy_keywords(text):
    """文本 → 命中关键词列表 [(展示名, 原文片段)]；无命中返回 []。"""
    if not text:
        return []
    hits = []
    for kw, display in POLICY_KW:
        if kw in text:
            hits.append((display, text))
    for kw, ctx_words, display in POLICY_KW_SHORT:
        if kw in text and any(c in text for c in ctx_words):
            hits.append((display, text))
    return hits


# 哨④ 命中判级（2026-11-02 用户授权"你来做判级吧"；口径=924配方研究）
#   A级·反转开关候选：新创设工具 / 扩容≥2000亿 / 双工具同文扩容（924组合拳形态）
#   B级·机制完善：费率/完善机制/常规第N次招标/座谈 / 小额或未披露量级扩容——记录不升级
GRADE_A_EXPANSION_YI = 2000.0  # 扩容量级线(亿)：对标924的5000亿+3000亿档
GRADE_A_WORDS = ("创设", "新设", "推出新")
GRADE_B_WORDS = ("完善", "费率", "招标", "座谈", "会议", "例行")
GRADE_EXP_WORDS = ("扩大", "扩容", "加码", "增加", "提高")
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万亿|亿)")


def _amount_yi(text):
    """提取文本中的最大金额（亿）；无金额返回 None。"""
    best = None
    for m in AMOUNT_RE.finditer(text):
        v = float(m.group(1))
        if m.group(2) == "万亿":
            v *= 10000
        best = max(best, v) if best is not None else v
    return best


def grade_policy_text(text, hit_names):
    """单条命中快讯判级 → (tier, reason)。tier: 'A'=反转开关候选 / 'B'=机制完善级。"""
    if not text:
        return ("B", "无文本")
    names = "/".join(hit_names) if hit_names else "政策工具"
    if any(w in text for w in GRADE_A_WORDS):
        return ("A", f"新创设工具（{names}）——924形态")
    amt = _amount_yi(text)
    amt_str = f"量级{amt:.0f}亿" if amt is not None else "未披露量级"
    dual = len(hit_names) >= 2
    exp = any(w in text for w in GRADE_EXP_WORDS)
    if dual:
        if exp and (amt is None or amt >= GRADE_A_EXPANSION_YI):
            return ("A", f"双工具同文扩容（{names}）——924组合拳形态，{amt_str}")
        if exp:
            return ("B", f"双工具扩容但{amt_str}，未到{GRADE_A_EXPANSION_YI:.0f}亿量级线")
        return ("B", f"双工具提及（{names}）但为机制完善/座谈，无扩容语境")
    if amt is not None and exp:
        if amt >= GRADE_A_EXPANSION_YI:
            return ("A", f"扩容{amt:.0f}亿≥{GRADE_A_EXPANSION_YI:.0f}亿量级线（{names}）")
        return ("B", f"扩容{amt:.0f}亿未到{GRADE_A_EXPANSION_YI:.0f}亿量级线")
    if exp:
        return ("B", f"扩容但{amt_str}——等正式数字再升级")
    if any(w in text for w in GRADE_B_WORDS):
        return ("B", "机制完善/常规操作（费率·招标·座谈）")
    return ("B", "命中工具词，无升级语境")


def policy_sentry(news, window_days=POLICY_WINDOW_DAYS):
    """哨④状态机：快讯命中 → (带判级标签的状态, 详情)；否则 ("人工盯守", 巡检正常文案)。

    批级 = 同批最高级（A>B）；A级推"反转开关候选"待人工确认，B级记录不升级。
    """
    if news is None:
        return ("人工盯守", "快讯接口失败降级；盯: SFISF扩容/回购增持再贷款加码/央行直连股市新工具")
    cutoff = datetime.now() - timedelta(days=window_days)
    matched = {}  # nid → (时间, 原文, [命中名], tier, reason)——同一条快讯只报一次
    for nid, ctime, text in news:
        try:
            t = datetime.strptime(ctime, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            t = None
        if t is None or t < cutoff:
            continue
        names = [d for d, _ in match_policy_keywords(text)]
        if names:
            tier, reason = grade_policy_text(text, names)
            m = matched.setdefault(nid, (ctime, text, [], tier, reason))
            for n in names:
                if n not in m[2]:
                    m[2].append(n)
    if matched:
        batch_tier = "A" if any(v[3] == "A" for v in matched.values()) else "B"
        parts = []
        for ctime, text, names, tier, reason in list(matched.values())[:3]:
            parts.append(f"[{tier}]{'/'.join(names)} {ctime[:16]}：{reason}｜{text[:40]}")
        if batch_tier == "A":
            return ("🔔A级命中·反转开关候选", "；".join(parts))
        return ("🔔B级命中·仅记录，不操作", "；".join(parts))
    return ("人工盯守", "已自动扫快讯无命中（近90天窗口）")


def check_sentries():
    sigs = []
    # 哨① 地量
    v = volume_ratio()
    if v:
        if v["ratio"] < TH_VOLRATIO:
            st, note = "✅地量达成", f"量能比{v['ratio']} < {TH_VOLRATIO}，卖压枯竭信号"
        elif v["ratio"] < 0.40:
            st, note = "接近", f"量能比{v['ratio']}（线{TH_VOLRATIO}），趋近地量"
        else:
            st, note = "未到", f"量能比{v['ratio']}（线{TH_VOLRATIO}）"
        sigs.append(("vol_dry", "哨①量能地量(<0.33)", st, note, v["date"]))
    else:
        sigs.append(("vol_dry", "哨①量能地量", "数据缺失", "K线拉取失败", ""))

    # 哨② 两融出清
    m = margin_data()
    if m and "error" not in m:
        notes = []
        st = "未到"
        if m["rzrq_yi"] < TH_MARGIN_CLEAR:
            st = "✅出清加深"
            notes.append(f"两融{m['rzrq_yi']:.0f}亿 < {TH_MARGIN_CLEAR:.0f}亿线")
        else:
            notes.append(f"两融{m['rzrq_yi']:.0f}亿（线{TH_MARGIN_CLEAR:.0f}亿）")
        if abs(m["jme10_yi"]) > TH_MARGIN_ACCEL and m["jme10_yi"] < 0:
            notes.append(f"10日净偿还{abs(m['jme10_yi']):.0f}亿>加速线{TH_MARGIN_ACCEL:.0f}亿")
            if st == "未到":
                st = "⚡加速出清"
        notes.append(f"占流通市值{m['pct_ltsz']}%")
        sigs.append(("margin_clear", "哨②两融出清(<2.2万亿)", st, "；".join(notes), m["date"]))
    else:
        sigs.append(("margin_clear", "哨②两融出清", "数据缺失",
                     (m or {}).get("error", "东财接口失败")[:80], ""))

    # 哨③ AI财报季（日历驱动）
    today = datetime.now().strftime("%Y-%m-%d")
    if EARNINGS_WINDOW[0] <= today <= EARNINGS_WINDOW[1]:
        st, note = "⏰窗口开启", "Q4业绩预告强制披露期（1月底前）——AI盈利验证分水岭"
    else:
        days = (datetime.strptime(EARNINGS_WINDOW[0], "%Y-%m-%d") - datetime.now()).days
        if days > 0:
            st, note = "待窗口", f"距预告披露窗口还有{days}天（2027-01起）"
        else:
            st, note = "窗口已过", "验证已落地，按结果重估情景概率"
    sigs.append(("ai_earnings", "哨③AI财报季验证", st, note, ""))

    # 哨④ 924级政策（新浪7x24快讯自动扫描：回扫到上次游标，关键词规则判定）
    last_seen = load_last_seen_id()
    news = scan_since(last_seen)
    st4, note4 = policy_sentry(news)
    sigs.append(("policy_924", "哨④924级政策开关", st4, note4, ""))
    if news:
        save_last_seen_id(news[0][0])  # 游标推进到本批最新id（新闻→旧）
    return sigs


TRIGGER_MARKS = ("✅", "⚡", "⏰", "🔔")


def is_trigger_state(state):
    """触发态判定：✅⚡⏰🔔 任一标记在状态里即为触发（推送语义）。"""
    if not state:
        return False
    return any(m in state for m in TRIGGER_MARKS)


def render(sigs):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"### 🗼 观察哨（历史类比四哨）@ {now}", "",
             "| 哨 | 状态 | 读数 |", "| --- | --- | --- |"]
    for key, label, st, note, d in sigs:
        dd = f"（{d}）" if d else ""
        lines.append(f"| {label} | {st} | {note}{dd} |")
    lines += ["", "读法：哨①+哨②同时达成=出清末段（右侧三信号的地量件先满足）；哨③财报验证定2022/2021路径分岔；哨④A级（新创设工具/扩容≥2000亿/双工具组合拳）=反转开关候选待人工确认，B级=仅记录，不操作。"]
    return "\n".join(lines)


def write_state(sigs, path=STATE_PATH):
    """落盘四哨状态（保留同文件其他键，如 policy_last_seen_id 游标）。"""
    data = {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    today = datetime.now().strftime("%Y-%m-%d")
    for s in sigs:
        data[s[0]] = {"state": s[2], "date": today}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    as_json = "--json" in sys.argv
    sigs = check_sentries()
    # watchdog: 触发态或状态翻转才输出
    prev = {}
    if STATE_PATH.exists():
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    today = datetime.now().strftime("%Y-%m-%d")
    triggered = []
    for s in sigs:
        if is_trigger_state(s[2]):
            # 同日同状态不重复推（状态翻转日推一次）
            if prev.get(s[0], {}).get("state") != s[2] or prev.get(s[0], {}).get("date") != today:
                triggered.append(s)
    flipped = any(prev.get(s[0], {}).get("state") != s[2] for s in sigs)
    if as_json:
        print(json.dumps({"sentries": [{"key": k, "state": s, "note": n, "date": d} for k, l, s, n, d in sigs]}, ensure_ascii=False))
        return
    if triggered or flipped or not prev:
        print(render(sigs))
    # 落盘（write_state 保留 policy_last_seen_id 游标；翻转检测已在写前完成）
    write_state(sigs)


if __name__ == "__main__":
    main()
