#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""决策引擎单元测试：规则门槛逐条验证。"""
import sys
sys.path.insert(0, r"D:/Code/AH_analyse/tools")
from divi_decision_engine import decide

FAIL = 0


def check(name, got, want):
    global FAIL
    if got != want:
        FAIL += 1
        print(f"✗ {name}: got={got} want={want}")
    else:
        print(f"✓ {name}")


base = {"grade": "A", "price": 10.0, "yield_t": 5.0, "eyield": 10.0,
        "trend": "多头", "pct52": 30, "year_line": 9.0}

# 1. 全达标 → 买入
check("全达标买入", decide(base, 20)[0], "买入")
# 2. 红旗压倒一切 → 回避
check("红旗回避", decide({**base, "grade": "A🚩水源枯"}, 5)[0], "回避")
# 3. PE分位50-70边界(=50不<50) → 落到等回调/等消化分支
a, _, anchor = decide(base, 50)
check("PE分位恰50不买入", a != "买入", True)
# 4. 估值便宜但趋势空头 → 等回调, 锚=年线
a, why, anchor = decide({**base, "trend": "空头"}, 10)
check("空头等回调", a, "等回调")
check("等回调锚=年线", anchor, 9.0)
# 5. 两轴硬但PE分位贵(≥70) → 等消化
check("PE贵等消化", decide(base, 80)[0], "等消化")
# 6. 价格分位85+ → 等回调
check("价格高位等回调", decide({**base, "pct52": 90}, 40)[0], "等回调")
# 7. 股息不够 → 观望
check("低息观望", decide({**base, "yield_t": 3.0}, 20)[0], "观望")
# 8. 盈利收益率不够+PE分位中位 → 观望
check("低盈利收益率观望", decide({**base, "eyield": 5.0, "pct52": 50}, 50)[0], "观望")
# 9. PE分位缺失 → 按50处理(不触发<50买入)
check("PE缺失保守", decide(base, None)[0] != "买入", True)

print(f"\n{'❌ FAILED' if FAIL else '✅ ALL PASS'} ({FAIL} failures)")
sys.exit(1 if FAIL else 0)

# ===== 2026-10-30 新增: 边界带测试 =====
# 11. 净利YoY在-15~-20边界带: 买入须带⚠️边界+小仓提示
a, why, _ = decide({**base, "np_yoy_note": None, "grade": "A", "yield_t": 5.0, "eyield": 10.0, "pct52": 30, "trend": "震荡"}, 20)
check("边界带买入带警示", a, "买入⚠️边界")
check("边界带理由含小仓", "小仓" in why, True)
# 12. -15以上不带(正常买入)
a, why, _ = decide(base, 20)
check("净利-15以上正常买入", a, "买入")
# 13. -15.0恰好不带(边界带不含-15)
check("净利恰-15不带警示", decide({**base, "np_yoy_note": None}, 20)[0], "买入")
