# Repository notes for OpenCode

## External repository research
- Before proposing optimizations based on another repository, download its source, record the exact revision, and trace the relevant entrypoints, formulas, filters, execution/backtest assumptions, and tests. README descriptions alone are insufficient evidence of implementation or effectiveness.
- Compare the external implementation against this app with file/line references. Distinguish verified code, documented intent, unverified claims, and proposed adaptations; do not present general best practices as features verified in a reference repo.
- Research and comparison come before changes to recommendation logic. Do not implement a supposed advantage until its assumptions, limitations, and applicability have been established.

## Scope
- The real app lives in `ah_recommendation_system/`. Repo-root `data/`, `logs/`, and `tools/` are mostly artifacts/helpers, not the main app.
- Default working directory for backend work should be `D:\Code\AH_analyse\ah_recommendation_system\backend`.

## Real entrypoints
- API + UI server: `ah_recommendation_system/backend/main.py`
- Batch report generation: `ah_recommendation_system/backend/run_daily_job.py`
- Stored-report refresh/status flow: `ah_recommendation_system/backend/api/report_routes.py` + `backend/reporting/report_refresh.py`
- Frontend: `ah_recommendation_system/frontend/index.html` (single-file Vue/Axios/ECharts/Tailwind from CDNs; there is no frontend build step)

## Commands agents should actually use
- Set `PYTHONPATH` before running backend entrypoints so absolute imports resolve consistently:
  - PowerShell: `$env:PYTHONPATH='D:\Code\AH_analyse'`
- Install deps: `python -m pip install -r requirements.txt`
- Run server: `python -m uvicorn main:app --host 127.0.0.1 --port 8000`
- Generate a stored report without network: `python run_daily_job.py --mock`
- Generate a stored report with live upstream data: `python run_daily_job.py`
- One-shot report run via scheduler wrapper: `python -m scheduler.daily_job --run-now`
- Run grid/tools tests (from repo root): `python -m unittest discover -s tests -t . -p "test_*.py"`
- Run one grid test module: `python -m unittest tests.test_grid_state`
- Run app tests: `python -m unittest discover -s ah_recommendation_system/backend/tests -t . -p "test_*.py"`
- Do not use `discover -s . -t .` across the whole repo: the app's `tests` package and the root `tests` package share the name `tests`, so one shadows the other and imports fail.
- Optional type check (no repo-local pyright install): `pyright -p pyrightconfig.json`

## Runtime / data quirks
- `main.py` defaults to mock mode unless `AH_DATA_MODE` is set to `live`.
- `AH_HOURLY_REFRESH=0` disables the hourly APScheduler refresh started at app startup.
- `AH_DYNAMIC_AH_LIST=1` enables AKShare-based A/H pair discovery; default behavior is the small static fallback map in `backend/data/ah_stock_list.py`.
- Most API endpoints default to `source=stored`, so the UI expects an already-generated report. If `/api/v1/report/latest` returns 404 or data looks empty, run `python run_daily_job.py --mock` first.
- Stored reports are written under `backend/data/daily_reports/` by `backend/reporting/report_store.py`.
- Export and log paths in `backend/config.py` are cwd-relative (`data/exports`, `logs/`), while report storage is code-relative. Run commands from `backend/` to avoid scattering outputs into repo root.

## Verified mismatches worth remembering
- `README.md` and `start.ps1` / `start.bat` still steer toward `python main.py`; use the `uvicorn` command above instead.
- `backend/scheduler/daily_job.py` is not a long-running scheduler daemon; it just runs one report generation pass.
- README/config mention PDF export, but `backend/api/export_routes.py` only implements `xlsx` and `csv`.
- Tests use `unittest`; there is no pytest config in the repo.
- There is no repo-local CI workflow, pre-commit config, formatter config, lockfile, or `opencode.json`.

## Custom conversational triggers
- If the user says `投资分析` with or without extra sector names, treat it as a request to run the investment sector analysis template located at `skills/investment-sector-advisor/SKILL.md`.
- Default comparison set for `投资分析` is always: `科技 / 新能源 / 券商 / 医疗`.
- If the user mentions one of those sectors (for example `投资分析 科技`), still compare all four by default, with the mentioned sector treated as the focal sector.
- Only narrow scope if the user explicitly says things like `只看科技`、`不要默认行业`、`仅比较科技和医药`.
- The analysis must perform live web research before scoring, then output: current scoring table, 1~3 month forward scoring table, evidence list, assumptions, falsification signals, final sector judgment, and ETF ideas.
- If the user says `异动分析` with or without extra event, industry, or market terms, treat it as a request to run the abnormal movement analysis template located at `skills/abnormal-movement-advisor/SKILL.md`.
- Default scope for `异动分析` is A股 / 港股 sector abnormal movement attribution, unless the user explicitly narrows scope.
- The analysis must perform live web research before attribution, first update the historical prediction ledger and hit probabilities, then output: current abnormal movement table, reason attribution, reason-to-industry mapping, international / economic / policy inference chains, benefit and pressure industries, confidence, falsification signals, ETF / sector ideas, and newly added predictions for future verification.
- The abnormal movement ledger is `docs/analyse/abnormal-movement-ledger.jsonl`; the stats summary is `docs/analyse/abnormal-movement-stats.md`.
- If the user says `大盘分析`, `综合分析`, `综合模式`, `投资异动综合`, `盘前分析`, `盘中分析`, `盘后分析`, `收盘复盘`, `今天怎么看`, or `明天怎么看`, treat it as a request to run the three-mode broad-market template located at `skills/market-composite-advisor/SKILL.md`.
- 综合/大盘模式 is now a lightweight three-stage workflow: `盘前看环境`, `盘中看强弱`, `盘后做复盘`; it should not force the old abnormal-movement + four-sector scoring workflow unless the user explicitly asks for `异动分析` / `命中率` / `预测验证`.
- 综合/大盘模式 must run in window-safe mode by default: use `tools/analyse_context_summary.py --latest-reports 1 --recent-rows 8 --section-lines 6` when useful, avoid reading full ledgers / prior reports / raw web pages into chat, and keep final chat to saved report path plus a compact decision block.
- 综合/大盘模式 must choose one of three session modes by explicit wording first, otherwise by local China-market time: `盘前模式`, `盘中模式`, or `盘后模式`; weekends/holidays are next-session prep.
- `盘前模式` focuses on environment: whether the market is strong, A股 / 港股 / 美股 relative direction, sectors with catalysts, and whether today favors offense or defense; it must not pretend to know current-session price action.
- `盘中模式` focuses on strength: leaders, volume expansion, new highs, resilient sectors/stocks, and positive-catalyst laggards; all conclusions must be labeled as intraday snapshots.
- `盘后模式` focuses on review: strongest sectors, strongest stocks, mistakes, and tomorrow's watchlist, using close-confirmed behavior.
- 综合/大盘模式 must save a report under `docs/analyse/market-composite-analysis-YYYYMMDD-HHMMSS.md`; post-market/review runs should include or append a simple row concept for `docs/analyse/market-review-ledger.jsonl` with date, strongest sectors, strongest stocks, mistakes, tomorrow watchlist, and invalidation signals.
- 综合/大盘模式 defaults to ETF + stock watch output; stocks are observation/representative candidates, not personalized advice. Major conclusions must be labeled `有效`, `需确认`, `降级观察`, or `已失效` with usable time window and objective invalidation/downgrade signals.
- 综合/大盘模式的个股观察池必须每次运行时动态重建：先扫描当次 A 股/港股的领涨、放量、阶段新高、抗跌和利好不涨候选，再按相对强度、成交确认、日内位置、催化/价格一致性和代表性排序后选出 4-6 只。上一份报告、盘前名单或固定清单只能作为对照，不能自动沿用；旧标的只有在本次扫描中独立重新入选才可保留。
- 报告必须写入动态扫描时间、候选来源、入选/排除理由和覆盖范围；如果无法完成足够广的实时扫描，必须标注 `有限样本观察池`，披露缺口，不得声称为动态或全市场观察池。
- 综合/大盘模式的盘前、盘中、盘后报告及最终聊天总结都必须包含 `提前布局判断 / 可埋伏方向`，至少区分 `当前主攻`、`未来1~3个月主投`、`可小仓底仓 / 可埋伏 / 等待触发 / 降级观察`、`回避 / 撤退`；不得用当日强势排名替代中期与提前布局判断。
- `可埋伏` 必须通过可靠性门槛：1~3个月慢变量改善、价格不再无序破位或接近客观止损位、无直接证伪的新P0事件、试错仓上限为目标方向最终计划仓位的10%-30%（不是总账户仓位），并给出 `右侧确认加仓` 与减仓/退出条件。趋势或相对强度不合格时只能写 `等待触发` 或 `降级观察`，不能因跌幅大、估值低或故事合理就称为可埋伏。
- Abnormal-movement ledger/stat updates and hit-rate tables are only required when the user explicitly asks for `异动分析`, `命中率`, `预测验证`, or historical prediction verification.
- X/Twitter early-signal lookup is disabled by default. Do not call X/Twitter MCP tools, X search tools, or browser navigation to `x.com` during `盘前分析`、`盘中分析`、`盘后分析`、`综合分析`、`异动分析`、`投资分析` unless the user explicitly asks to use X/Twitter. If a report needs an audit line, write `X早期信号已按用户偏好禁用，未调用X/Twitter工具` and continue with official, market-data, and mainstream-media sources.

## ETF 网格脚本开发规范（用户既定习惯，动手前必读）

适用：所有网格、监控、记账、跨境类脚本（AH_analyse 开发，部署到 hermes-home/scripts 运行）。

1. **数据真实性**：账本、持仓、做T、盈亏等一切汇报数据必须由脚本实际写入并读回核验；禁止手工推算、临时测试账本、旧票据数据；未核实的现金、现价、市值、浮盈不报告；不得把测试结果当成实际保存值。
2. **成交入库**：严格按用户给定顺序入库，不混入旧账本；日期未提供则留空、不补造；格子标签（A–Z）与做T配对由脚本按该 ETF 当前最大序号自动生成（买入取下一号并更新，卖出取当前号、成交后退一号）；成交 ID 按 ETF 序列自动递增，不要求用户提供券商编号；手续费按分段 fee_rule 由脚本计算（2026-09-23 至 09-30 每笔最低 5 元；2026-10-08 起万一免五、每笔最低 1 元）。
3. **账本口径**：逐格记录数量/单价/含费成本/T+1 可卖状态；总份额与 T+1 可用两个口径并存；卖出使用总可卖库存池、不按买入批次绑定，同一批库存不得被多个卖单重复占用；买入须同时满足 CASH_FLOOR=0、TOTAL_CAP=100000、holdings.json 的 per-ETF quota；每次入账后校验 pos["qty"] == lot 合计。
4. **测试纪律**：测试必须隔离账本路径，禁止覆盖真实账本（2026-09-29 事故）；账本改动前后核对哈希；先复现、查根因，再修复验证，不叠未验证补丁。
5. **交付完整性**：改代码必须同步切换全部自动链路（00:01 可卖份额、09:10 预告、09:20 建议、盘中每分钟检查、15:20 收盘评估、15:25/15:30 regime 与轮换），并读写同一份持久化状态；禁止只在新脚本里演示通过而旧链路继续运行；交付不完整必须主动说明，不等用户追问。
6. **唯一真源**：confirmed-*.json 已确认子账为唯一账本来源；旧 ledger.json 与旧脚本不得留在活跃路径。
7. **定时任务**：暂停或恢复通知任务后必须读回确认启用状态。
8. **规则固化**：同一规则类错误不允许出现第二次；修复优先做成脚本检查或 skill，不靠口头记忆。
9. **仓库分工**：AH_analyse 为开发源（deploy_scripts/ 与 tools/confirmed_grid/launchers/ 出启动脚本，经 deploy.py 复制到 hermes-home/scripts 并做字节校验）；hermes-home 只保留运行时数据（cache/grid-account、cron、output）与已部署副本。改代码改 AH_analyse 一侧，部署走既有链路；不要把运行数据搬进本仓库。
