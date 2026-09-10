# Market Data Cache And Efinance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add short-TTL snapshot caching/prefetch and an optional Efinance fallback provider to the unified market data layer.

**Architecture:** Keep MarketDataManager as the only pipeline entrypoint. Cache only successful full snapshots in memory for 60 seconds, share the cache across manager instances, expose cache health, and add injectable Efinance as final provider and final supplement source.

**Tech Stack:** Python 3.12, unittest, optional efinance, existing circuit-breaker routing.

**Spec:** Approved chat design; no API keys or persistent stale snapshots.

## Global Constraints

- Preserve primary price/change identity during field supplement.
- Do not serve snapshots older than TTL.
- Treat missing optional Efinance dependency as unavailable, not fatal.
- Record real attempted chains in snapshot health.
- Coerce provider numeric placeholders such as "-" before scanner use.

## Tasks

### Task 1: Snapshot Cache And Prefetch

- [x] Failing tests for fresh-cache hit and stale refresh.
- [x] Shared 60-second in-memory cache and prefetch_snapshot().
- [x] Focused tests pass.

### Task 2: Efinance Provider

- [x] Failing tests for fallback and field supplement.
- [x] Efinance row normalization, dependency declaration, and default three-provider chain.
- [x] Numeric placeholder normalization and dynamic-scanner safe amount handling.
- [x] Focused tests, full suite, and live pipeline health audit pass.

### Task 3: Commit

- [ ] Stage implementation, tests, requirements, and this plan only.
