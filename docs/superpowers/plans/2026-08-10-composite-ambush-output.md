# Composite Analysis Ambush Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore mandatory advance-layout and ambush-direction output to every market-composite mode.

**Architecture:** Persist the requirement at repository and skill layers, then correct the current intraday report with a gated advance-layout matrix. Use focused text assertions because all modified artifacts are Markdown workflow/report files.

**Tech Stack:** Markdown workflow instructions, PowerShell assertions, current A/H market evidence already collected for the report.

---

### Task 1: Persist The Repository Rule

**Files:**
- Modify: `AGENTS.md`

- [x] **Step 1: Add mandatory output layers**

Require `当前主攻`, `未来1~3个月主投`, `可小仓底仓 / 可埋伏 / 等待触发 / 降级观察`, and `回避 / 撤退` in all three composite modes.

- [x] **Step 2: Add ambush gate and execution fields**

Require improving slow-variable evidence, price-structure veto, no thesis-breaking event, a 10%-30% intended-direction pilot cap, right-side add-on trigger, and invalidation/exit trigger.

- [x] **Step 3: Verify repository text**

Run `rg -n '提前布局判断|可小仓底仓|10%-30%|右侧确认加仓' AGENTS.md` and require all terms.

### Task 2: Restore The Active Skill Contract

**Files:**
- Modify: `skills/market-composite-advisor/SKILL.md`

- [x] **Step 1: Add hard rules**

Add mandatory advance-layout output and the ambush reliability gate to `必守规则`.

- [x] **Step 2: Add report structure and matrix**

Add `提前布局判断 / 可埋伏方向` to the normal report structure with columns for layer, direction, ETF, evidence, action, cap, add-on, invalidation, status, and window.

- [x] **Step 3: Add final-chat requirement**

Require a compact advance-layout conclusion in the final response, including what can be held, piloted, added only after right-side confirmation, or avoided.

- [x] **Step 4: Verify active skill text**

Run `rg -n '提前布局判断|可埋伏|10%-30%|右侧确认加仓|回避/撤退' skills/market-composite-advisor/SKILL.md` and require all terms.

### Task 3: Correct The Current Intraday Report

**Files:**
- Modify: `docs/analyse/market-composite-analysis-20260810-115134.md`

- [x] **Step 1: Add the advance-layout matrix**

Classify current attack, 1-3 month main, small pilot/ambush, and avoid/exit directions using the current report evidence.

- [x] **Step 2: Add execution limits**

For each row include ETF code and name, status, validity window, pilot cap where applicable, right-side add-on trigger, and invalidation/exit condition.

- [x] **Step 3: Verify report completeness**

Run focused assertions for all four layers, ETF names, 10%-30% cap, add-on and invalidation fields, and non-personalized-analysis boundary.

### Task 4: Final Verification

**Files:**
- Verify: `AGENTS.md`
- Verify: `skills/market-composite-advisor/SKILL.md`
- Verify: `docs/analyse/market-composite-analysis-20260810-115134.md`

- [x] **Step 1: Run combined requirement assertions**

Use PowerShell to check every required label and fail if any item is missing or mojibake is detected.

- [x] **Step 2: Confirm plan completion**

Require zero unchecked implementation steps and report the assertion count and failure count.
