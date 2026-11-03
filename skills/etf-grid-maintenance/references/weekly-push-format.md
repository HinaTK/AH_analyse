# Weekly rotation push format contract (cron 5d8180a8d025)

2026-10-30 user complaint (verbatim): “这个推送真的不知道看什么，你需要分点，然后每个点如果有必要用表格展示的就用表格展示”。
Same-day earlier decision still binding: the push must stay the FULL weekly report（禁缩略，`test_weekly_cli_prints_full_report` 锁定）— the fix is STRUCTURE, not length. Do NOT "solve" readability by switching the push to `summarize()`.

## Render chain (verified 2026-10-30 by reading code + the real pushed output)
- Cron `5d8180a8d025`（every friday 15:25, no_agent, deliver feishu 群）→ `hermes-home/scripts/grid_weekly_rotation.py`（interpreter pin → system Python 3.12, sys.path insert）→ `tools.etf_research.weekly.main()` → prints `result['report']`; cron pushes stdout verbatim.
- `weekly.run_weekly()` line order: title → ~7 provenance machine lines（快照池/窗口/成功失败次数/模型排除/降级/legacy reference ×2）→ `pair_review.report_lines()`（5 行 prose 前言 + 每持仓表格 + 图例行 + 复核状态行）→ rankable 行 → 三持仓表 → `entry_rank_block()`（ENTRY_BLOCK_TITLE + head 行 + `render_markdown` 表）→ 往返前10表 → 综合排名表 → errors 计数 → 免责声明。
- `entry_rank.render_markdown()` 自己还发两行前言（`asof ... 入选 N 只 排除 {...}`、`近20日高/低线=...`），与 `entry_rank_block` 的 head 行重复——10-30 推送同一数字出现两遍（行50/52）。

## Verified defects (2026-10-30 15:25 push, grid-research/20261030-155445-696839/weekly-report.txt)
1. 无结论先行头部：几秒内看不出 复核触发没有/谁领先/持仓健康吗。
2. 开头 7 行是口径机器行，无决策内容。
3. 每持仓的复核状态（唯一可行动行）被图例 prose 压在表格后。
4. entry-rank 区块入选/排除计数重复两遍。
5. taxonomy/name-filter/cross-theme 免责 prose 插在数据前。

## Contract（用户要求）
1. 分点：编号小节，每点先一句结论，确需表格的点才配表。
2. 结论先行头部块：复核触发状态（谁/连续几周/未触发原因）、三持仓健康一行、覆盖是否降级。
3. 口径（池/窗口/费率/模型）压缩成一行或小表，不许 7 行 prose。
4. 数据区仍全部脚本渲染 Markdown 表，数字逐格来自同一 dict（表格交付铁律）。
5. 免责声明置底部原文保留；行 ≤120 字符；禁 `指标名=值` 机器行。
6. 禁止用 summarize() 缩略替代重构。

## Test locks（改表头须同提交改测试；断言用 weekly.ENTRY_BLOCK_TITLE 常量，禁手写子串）
- `test_pair_review.py::test_weekly_report_tables_readable_no_machine_lines`（≤120 字符、无机器行、四区块表格化、ENTRY_BLOCK_TITLE 恰一次）
- `test_research.py::test_weekly_cli_prints_full_report` / `test_weekly_report_includes_entry_rank_gated_listing`（entry 表头整串被断言）
- 新格式断言加进现有 suite，不另起平行 suite。

## Re-render acceptance（格式改动禁止重跑 30 分钟在线研究）
- 生产输出持久在 `cache/grid-research/<ts>/`（result.json + bars/）；格式改动用测试同款 `research_runner=lambda **kw: persisted_result` 注入重渲染，肉眼验收全文。推送的 weekly-report.txt 是交付物。
- 截至 2026-10-30 收盘：双轨周检/三持仓/前10/综合排名表格化已落地（当日上午修）；开头重构+去重+结论头部未落地（TDD 进行中会话中断）。
