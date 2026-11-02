# -*- coding: utf-8 -*-
"""哨④ 924级政策自动扫描测试（watchtower_monitor 扩展部分）

哨④原为"人工盯守"占位——政策事件无自动数据源。本次接入新浪7x24快讯
（zhibo.sina.com.cn），按关键词规则扫描最近快讯，命中即状态翻转"🔔命中"。
纯逻辑与 I/O 分离：本文件只测纯函数（feed 解析 + 关键词匹配 + 状态机），
网络路径由脚本实跑验证。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import watchtower_monitor as wm


# ---------- fetch_policy_news（新浪7x24 快讯拉取与解析） ----------

def _feed_items():
    return [
        {"id": 1, "create_time": "2026-11-02 16:04:57", "rich_text": "【中际联合：使用3300万元闲置募集资金购买结构性存款】"},
        {"id": 2, "create_time": "2026-11-02 15:30:00", "rich_text": "【央行：公布SFISF操作情况，第二次互换便利操作规模扩大】"},
        {"id": 3, "create_time": "2026-11-02 14:00:00", "rich6_text": ""},
    ]


def test_parse_sina_feed():
    """新浪 feed 结构 result.data.feed.list[] → (id, time, text) 三元组。"""
    raw = {"result": {"data": {"feed": {"list": _feed_items()}}}}
    items = wm.parse_sina_feed(raw)
    assert len(items) == 3
    assert items[0] == (1, "2026-11-02 16:04:57", "【中际联合：使用3300万元闲置募集资金购买结构性存款】")
    assert items[1][0] == 2


def test_parse_sina_feed_handles_bad_payload():
    """结构异常/空数据返回 None，不抛异常。"""
    assert wm.parse_sina_feed(None) is None
    assert wm.parse_sina_feed({}) is None
    assert wm.parse_sina_feed({"result": {"data": {"feed": {}}}}) is None
    assert wm.parse_sina_feed({"result": {"data": {"feed": {"list": None}}}}) is None


def test_fetch_sina_724_network_error_returns_none(monkeypatch):
    """网络失败返回 None 而非异常（哨④降级为数据缺失，不拖垮整哨）。"""
    def _boom(url, timeout=0):
        raise OSError("conn refused")
    monkeypatch.setattr(wm.urllib.request, "urlopen", _boom)
    assert wm.fetch_sina_724(page=1) is None


# ---------- match_policy_keywords（关键词匹配） ----------

def test_match_hits_sfisf_expansion():
    t = "央行开展第二次互换便利操作 规模较首次扩大"
    hits = wm.match_policy_keywords(t)
    assert any(k == "SFISF互换便利" for k, _ in hits)


def test_match_hits_buyback_reloan():
    t = "股票回购增持再贷款额度增加 3000亿"
    hits = wm.match_policy_keywords(t)
    assert any(k == "回购增持再贷款" for k, _ in hits)


def test_match_hits_central_bank_direct_tool():
    t = "央行创设直连股市新工具 支持资本市场"
    hit = [k for k, _ in wm.match_policy_keywords(t)]
    assert "央行直连股市新工具" in hit


def test_match_ignores_debt_news():
    t = "地方政府化债方案出台，债务限额提高"
    assert wm.match_policy_keywords(t) == []


def test_match_empty_and_none():
    assert wm.match_policy_keywords("") == []
    assert wm.match_policy_keywords(None) == []


def test_match_requires_short_kw_next_to_stock():
    """短关键词（直连/新工具）须与"股市/资本市场"同现才命中，避免政策新闻误伤。"""
    t = "央行推出新工具支持实体经济"
    assert wm.match_policy_keywords(t) == []

    t2 = "央行创设股市新工具"
    hits = wm.match_policy_keywords(t2)
    assert any(k == "央行直连股市新工具" for k, _ in hits)


# ---------- policy_sentry（哨④状态机） ----------

def test_policy_sentry_no_news_normal():
    """接口失败 → 降级为人工盯守，读数明示降级原因并保留清单。"""
    news = None
    st, note = wm.policy_sentry(news)
    assert st == "人工盯守"
    assert "降级" in note
    assert "盯" in note


def test_policy_sentry_no_hits_in_scan():
    """拉到快讯但无命中 → 巡检正常。"""
    items = [(1, "2026-11-02 16:00:00", "【中际联合：购买结构性存款】")]
    st, note = wm.policy_sentry(items)
    assert st == "人工盯守"
    assert "快讯无命中" in note


def test_policy_sentry_triggers_on_sfisf():
    items = [(2, "2026-11-02 15:30:00", "【央行：第二次互换便利操作规模扩大】")]
    st, note = wm.policy_sentry(items)
    assert st.startswith("🔔")  # 2026-11-02 起带判级标签（A级·反转开关候选/B级·机制完善）
    assert "SFISF" in note or "互换" in note
    assert "15:30" in note


def test_policy_sentry_dedupes_one_news_multiple_hits():
    """同一条快讯命中多个关键词 → 读数只报一次该快讯（可读性）。"""
    items = [(2, "2026-11-02 15:30:00",
              "央行完善互换便利与股票回购增持再贷款政策")]
    st, note = wm.policy_sentry(items)
    assert st.startswith("🔔")
    assert note.count("15:30") == 1  # 同一快讯只出现一次
    assert "互换便利" in note and "回购增持再贷款" in note  # 但两个命中名都点到


# ---------- 触发态判定（watchdog 推送语义） ----------

def test_is_trigger_state_recognizes_all_alert_states():
    assert wm.is_trigger_state("✅地量达成") is True
    assert wm.is_trigger_state("⚡加速出清") is True
    assert wm.is_trigger_state("⏰窗口开启") is True
    assert wm.is_trigger_state("🔔A级命中·反转开关候选") is True
    assert wm.is_trigger_state("🔔B级命中·机制完善") is True


def test_is_trigger_state_rejects_quiet_states():
    assert wm.is_trigger_state("人工盯守") is False
    assert wm.is_trigger_state("未到") is False
    assert wm.is_trigger_state("待窗口") is False
    assert wm.is_trigger_state("") is False


def test_is_trigger_state_handles_none():
    assert wm.is_trigger_state(None) is False


def test_policy_sentry_beyond_window_is_ignored():
    """早于90天窗口的旧快讯不参与判定（防历史条目反复触发）。"""
    items = [(1, "2026-06-01 10:00:00", "【央行：互换便利操作规模扩大】")]
    st, note = wm.policy_sentry(items)
    assert st == "人工盯守"


# ---------- scan_since（回扫到上次运行时点，多页翻页） ----------

def _pages_of_ids(*id_groups):
    """构造多页原始快讯：每组 id 列表一页。"""
    pages = []
    for ids in id_groups:
        pages.append([{"id": i, "create_time": "2026-11-02 15:00:00", "rich_text": f"快讯{i}号"}
                      for i in ids])
    return pages


def test_scan_since_collects_until_last_seen_id(monkeypatch):
    """回扫从新到旧翻页，遇到 last_seen_id 即停（刚好停在其所在页尾）。"""
    # 页1: id 105..101，页2: id 100(上次游标)..96，页3: id 95..91
    pages = _pages_of_ids([105, 104, 103, 102, 101], [100, 99, 98, 97, 96], [95, 94, 93, 92, 91])
    calls = []

    def fake_fetch(page=1):
        calls.append(page)
        return [(it["id"], it["create_time"], it["rich_text"]) for it in pages[page - 1]]

    monkeypatch.setattr(wm, "fetch_sina_724", fake_fetch)
    items = wm.scan_since(last_seen_id=100)
    assert calls == [1, 2]                 # 翻到第2页（含游标）即停
    ids = [i[0] for i in items]
    assert ids == [105, 104, 103, 102, 101, 100, 99, 98, 97, 96]


def test_scan_since_without_cursor_scans_first_page_only(monkeypatch):
    """无游标（首次运行）→ 只扫第一页。"""
    pages = _pages_of_ids([105, 104, 103], [102, 101, 100])
    calls = []

    def fake_fetch(page=1):
        calls.append(page)
        return [(it["id"], it["create_time"], it["rich_text"]) for it in pages[page - 1]]

    monkeypatch.setattr(wm, "fetch_sina_724", fake_fetch)
    items = wm.scan_since(last_seen_id=None)
    assert calls == [1]
    assert [i[0] for i in items] == [105, 104, 103]


def test_scan_since_page_cap(monkeypatch):
    """翻页上限保护：防止上游接口无限返回旧数据。"""
    def fake_fetch(page=1):
        return [(100000 - page * 10 + i, "2026-11-02 15:00:00", "旧闻") for i in range(10)]

    monkeypatch.setattr(wm, "fetch_sina_724", fake_fetch)
    items = wm.scan_since(last_seen_id=1)
    assert len(items) == wm.SCAN_MAX_PAGES * 10


def test_scan_since_network_failure_midway(monkeypatch):
    """中途某页失败：返回已收快讯（尽力而为），None 页不中断哨④。"""
    def fake_fetch(page=1):
        if page == 2:
            return None
        # 页1: 105..101（新→旧），页2 失败，后续不再有
        return [(106 - i, "2026-11-02 15:00:00", "快讯") for i in range(1, 6)]

    monkeypatch.setattr(wm, "fetch_sina_724", fake_fetch)
    items = wm.scan_since(last_seen_id=90)
    assert [i[0] for i in items] == [105, 104, 103, 102, 101]


def test_scan_since_dedupes_overlapping_pages(monkeypatch):
    """页间重叠（上游返回重叠窗口）→ 按 id 去重且保持新→旧顺序。"""
    pages = _pages_of_ids([105, 104, 103, 102, 101], [103, 102, 101, 100, 99])

    def fake_fetch(page=1):
        return [(it["id"], it["create_time"], it["rich_text"]) for it in pages[page - 1]]

    monkeypatch.setattr(wm, "fetch_sina_724", fake_fetch)
    items = wm.scan_since(last_seen_id=99)
    assert [i[0] for i in items] == [105, 104, 103, 102, 101, 100, 99]


# ---------- 游标持久化 ----------

def test_load_last_seen_id_reads_state_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"policy_last_seen_id": 5187000}), encoding="utf-8")
    assert wm.load_last_seen_id(p) == 5187000


def test_load_last_seen_id_missing_file(tmp_path):
    assert wm.load_last_seen_id(tmp_path / "nope.json") is None


def test_load_last_seen_id_corrupt_file(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not json", encoding="utf-8")
    assert wm.load_last_seen_id(tmp_path / "state.json") is None


def test_save_last_seen_id_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    wm.save_last_seen_id(42, p)
    assert wm.load_last_seen_id(p) == 42


def test_save_last_seen_id_preserves_other_keys(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"other": 1}), encoding="utf-8")
    wm.save_last_seen_id(42, p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["policy_last_seen_id"] == 42
    assert raw["other"] == 1


def test_save_last_seen_id_corrupt_file_overwrites(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("not json", encoding="utf-8")
    wm.save_last_seen_id(42, p)
    assert wm.load_last_seen_id(p) == 42


# ---------- write_state（哨状态落盘不得抹掉游标） ----------

def test_write_state_preserves_cursor(tmp_path):
    """main() 落盘四哨状态时必须保留 policy_last_seen_id 游标（2026-11-02 bug：整文件覆盖抹游标）。"""
    p = tmp_path / "state.json"
    wm.save_last_seen_id(5187042, p)
    sigs = [
        ("vol_dry", "哨①", "未到", "n", "2026-11-02"),
        ("policy_924", "哨④", "🔔B级命中·机制完善", "n", ""),
    ]
    wm.write_state(sigs, path=p)
    assert wm.load_last_seen_id(p) == 5187042
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["vol_dry"]["state"] == "未到"
    assert raw["policy_924"]["state"] == "🔔B级命中·机制完善"
