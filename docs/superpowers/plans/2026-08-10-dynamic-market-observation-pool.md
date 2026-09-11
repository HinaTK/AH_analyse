# Dynamic Market Observation Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every market-composite analysis rebuild its stock observation pool from the current A/H market instead of carrying forward a static list.

**Architecture:** Add the rule at the repository instruction layer and the market-composite workflow layer, then correct the current report with a fresh market-wide candidate scan. Verification uses text assertions for the hard rules and a report checklist for dynamic-scan evidence.

**Tech Stack:** Markdown workflow instructions, PowerShell verification, live market/news sources already used by the repository workflow.

---

### Task 1: Persist The Repository-Level Rule

**Files:**
- Modify: `AGENTS.md`

- [x] **Step 1: Add the dynamic-pool constraint**

Add a composite-analysis rule stating that every run must scan current A/H leaders, volume, highs, resilience, and catalyst laggards before selecting 4-6 stocks; previous pools are comparison-only and cannot be automatically retained.

- [x] **Step 2: Add failure semantics**

Require the label `有限样本观察池` when broad live coverage is unavailable and prohibit calling such output dynamic or market-wide.

- [x] **Step 3: Verify the repository rule**

Run:

```powershell
rg -n "动态重建|有限样本观察池|不得.*沿用" AGENTS.md
```

Expected: all three constraints are present.

### Task 2: Enforce The Skill-Level Selection Gate

**Files:**
- Modify: `skills/market-composite-advisor/SKILL.md`

- [x] **Step 1: Add a mandatory dynamic scan before stock selection**

Require a fresh candidate scan across both markets and rank current candidates by relative strength, turnover confirmation, intraday range position, catalyst/price consistency, and representative role.

- [x] **Step 2: Prevent static carry-over**

State that prior-report and pre-market stocks survive only when the current scan independently requalifies them.

- [x] **Step 3: Add report audit fields**

Require scan timestamp, candidate source, inclusion rationale, and notable exclusions; downgrade incomplete coverage to `有限样本观察池`.

- [x] **Step 4: Verify the skill gate**

Run:

```powershell
rg -n "动态重建|独立重新入选|扫描时间|有限样本观察池" skills/market-composite-advisor/SKILL.md
```

Expected: selection, carry-over, audit, and failure rules are all present.

### Task 3: Replace The Invalid Current Observation Pool

**Files:**
- Modify: `docs/analyse/market-composite-analysis-20260810-115134.md`

- [x] **Step 1: Collect a fresh A/H candidate snapshot**

Query current A-share and Hong Kong sector/stock rankings, then validate selected candidates with direct quotes and same-day catalysts. Do not start from the existing six stocks.

- [x] **Step 2: Rank and select 4-6 stocks**

Cover current leadership, volume, range strength, resilience, and negative catalyst/price confirmation. Keep a prior-pool stock only if it independently ranks in the fresh scan.

- [x] **Step 3: Replace the report section**

Add a `动态观察池扫描审计` section and replace the inherited table. Record scan time, candidate sources, inclusion reasons, exclusions, triggers, invalidations, and status labels.

- [x] **Step 4: Verify report completeness**

Run a PowerShell checklist that asserts: dynamic-scan audit exists; the pool contains 4-6 stocks; HSBC is evaluated; scan timestamp and exclusions exist; all candidates have trigger, invalidation, and status; no text claims the pool came from the pre-market list.

Expected: exit code 0 with all checks true.

### Task 4: Final Verification

**Files:**
- Verify: `AGENTS.md`
- Verify: `skills/market-composite-advisor/SKILL.md`
- Verify: `docs/analyse/market-composite-analysis-20260810-115134.md`

- [x] **Step 1: Inspect the focused diff**

Run:

```powershell
git diff -- AGENTS.md skills/market-composite-advisor/SKILL.md docs/analyse/market-composite-analysis-20260810-115134.md
```

Expected: only the approved workflow rule and current-report correction appear.

- [x] **Step 2: Run the combined assertion checklist**

Run focused text assertions for all design requirements and fail on any missing rule, audit field, or malformed encoding.

Expected: exit code 0 and zero missing requirements.
