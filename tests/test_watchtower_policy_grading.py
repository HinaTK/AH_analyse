# -*- coding: utf-8 -*-
"""哨④命中判级测试（2026-11-02 用户授权"你来做判级吧"）

判级口径（源自 market_history_analog_20261030.md §一.9 的 924 配方研究）：
924 反转配方 = 央行直连股市工具**新创设**（SFISF 5000亿 + 回购再贷款 3000亿）+ 化债级财政；
普通降准降息、日常汇金增持、机制完善/费率调整都不算。

两级判级：
- A级·反转开关候选：新创设工具 / 扩容带量级(≥2000亿) / 双工具同文扩容（924组合拳形态）
- B级·机制完善：费率调整 / 完善机制 / 常规第N次招标 / 小额或无量级扩容 —— 记录不升级
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import watchtower_monitor as wm


# ---------- grade_policy_text（单条快讯判级） ----------

def test_grade_creates_new_tool_is_A():
    t = "央行创设直连股市新工具，支持资本市场流动性"
    tier, reason = wm.grade_policy_text(t, ["央行直连股市新工具"])
    assert tier == "A"
    assert "创设" in reason


def test_grade_expansion_over_2000yi_is_A():
    t = "互换便利额度增加5000亿，回购增持再贷款扩容"
    tier, reason = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "A"
    assert "5000" in reason


def test_grade_wanyi_amount_is_A():
    """万亿单位换算成亿再比阈值。"""
    t = "央行宣布互换便利规模扩大至1万亿"
    tier, _ = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "A"


def test_grade_small_expansion_is_B():
    t = "互换便利规模扩大300亿"
    tier, reason = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B"
    assert "扩容" in reason or "量级" in reason


def test_grade_expansion_no_amount_single_tool_is_B():
    """单工具扩容但快讯不带量级 → B（等正式数字再升级）。"""
    t = "央行宣布进一步扩大互换便利操作规模"
    tier, _ = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B"


def test_grade_dual_tools_expansion_no_amount_is_A():
    """双工具同文扩容 = 924 组合拳形态 → A。"""
    t = "央行宣布扩大互换便利和股票回购增持再贷款支持力度"
    tier, reason = wm.grade_policy_text(t, ["SFISF互换便利", "回购增持再贷款"])
    assert tier == "A"
    assert "组合" in reason


def test_grade_mechanism_refinement_is_B():
    t = "央行将进一步完善互换便利机制，互换费率有望进一步降低"
    tier, reason = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B"
    assert "机制" in reason or "费率" in reason


def test_grade_routine_auction_is_B():
    t = "央行明日启动第三次互换便利操作招标"
    tier, _ = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B"


def test_grade_plain_hit_falls_to_B():
    """仅命中工具词、无任何升级语境 → B（保守归档）。"""
    t = "某基金公司参与互换便利操作获备案"
    tier, _ = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B"


# ---------- policy_sentry（批级=最高级，状态带判级标签） ----------

def test_policy_sentry_tier_a_label():
    items = [(1, "2026-11-02 15:30:00", "央行创设直连股市新工具支持资本市场")]
    st, note = wm.policy_sentry(items)
    assert "A级" in st and "反转开关候选" in st
    assert "创设" in note


def test_policy_sentry_tier_b_label():
    items = [(1, "2026-11-02 15:30:00", "央行将进一步完善互换便利机制")]
    st, note = wm.policy_sentry(items)
    assert "B级" in st and "仅记录" in st  # 2026-11-02 用户定文案：B级直接写"仅记录，不操作"
    assert "反转开关候选" not in st


def test_policy_sentry_batch_takes_max():
    """同批快讯 B+A 混合 → 取最高级 A。"""
    items = [
        (1, "2026-11-02 15:30:00", "央行将进一步完善互换便利机制"),
        (2, "2026-11-02 15:37:00", "互换便利额度增加5000亿"),
    ]
    st, note = wm.policy_sentry(items)
    assert "A级" in st


# ---------- 今日实战回归锁（2026-11-02 15:37 SFISF 双快讯判 B） ----------

def test_today_real_news_batch_is_B():
    """2026-11-02 真实三快讯：费率完善 + 第三次招标 + 政策座谈 → 整批 B级。"""
    items = [
        (5187050, "2026-11-02 15:37:00",
         "央行将进一步完善SFISF机制、互换费率有望进一步降低"),
        (5187051, "2026-11-02 15:37:30",
         "央行预告明日启动第三次互换便利操作招标"),
        (5187052, "2026-11-02 15:38:00",
         "央行召开完善证券、基金、保险公司互换便利（SFISF）与股票回购增持再贷款政策座谈会"),
    ]
    st, note = wm.policy_sentry(items)
    assert "B级" in st and "仅记录" in st
    assert "A级" not in st


# ---------- "创设以来"短语误伤回归锁（2026-11-03 实战事故） ----------

def test_grade_since_creation_phrase_not_A():
    """2026-11-03 15:31 平安证券快讯："这是该工具创设以来的第三次操作"——
    "创设以来"是对2024年存量工具的历史指称，不是新创设；第三次常规操作 → B级。
    （当天曾被误判A级·反转开关候选推送用户，根因=关键词"创设"撞短语。）"""
    t = ("2026年11月2日，中国人民银行发布公告，为支持资本市场健康稳定发展，"
         "于2026年11月3日开展证券、基金、保险公司互换便利（SFISF）操作，互换期限1年，"
         "可视情展期；目前已有31家证券、基金公司申报需求，意向申报额度超过1000亿元。"
         "这是该工具创设以来的第三次操作，也是金融管理部门在近期市场波动背景下"
         "又一次及时、明确的表态")
    tier, reason = wm.grade_policy_text(t, ["SFISF互换便利"])
    assert tier == "B", f"应为B级（常规第三次操作），实际{tier}：{reason}"


def test_today_20261103_real_batch_is_B():
    """2026-11-03 真实三快讯整批：平安证券"创设以来"表述 + 中信建投申报 + 央行开展操作
    → 全批 B级，不得出现 A级·反转开关候选。"""
    items = [
        (5187100, "2026-11-03 13:01:00",
         "【中信建投正申报SFISF操作 称三大因素有望推动A股见底回升】"),
        (5187150, "2026-11-03 15:31:39",
         "【平安证券：积极推动互换便利业务落地】央行于2026年11月3日开展证券、基金、保险"
         "公司互换便利（SFISF）操作，意向申报额度超过1000亿元。这是该工具创设以来的第三次操作"),
        (5187200, "2026-11-03 12:31:00",
         "央行：根据参与机构需求情况，于2026年11月3日开展了证券、基金、保险公司互换便利操作"),
    ]
    st, note = wm.policy_sentry(items)
    assert "B级" in st, f"应整批B级，实际：{st}"
    assert "A级" not in st and "反转开关候选" not in st


# ---------- render（读法行同步判级口径） ----------

def test_render_mentions_grading():
    sigs = [("policy_924", "哨④924级政策开关", "🔔B级命中·仅记录，不操作", "x", "")]
    out = wm.render(sigs)
    assert "A级" in out and "B级" in out
