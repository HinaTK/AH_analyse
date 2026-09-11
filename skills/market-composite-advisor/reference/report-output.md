# Report and Final Response Rules

Use this reference when saving the Markdown report and producing the final chat answer.

## Persist Every Normal Run

Every normal composite run must save one complete Markdown report before the final chat response.

Rules:

- Create `docs/analyse/` from repository root if missing.
- Use local time filename: `market-composite-analysis-YYYYMMDD-HHMMSS.md`.
- Include metadata: generation time, user request, detected mode, market scope, evidence anchor date, prior report paths if used, ledger path, stats path, output file path.
- After saving, run `python tools/validate_report_theme_rows.py <saved-report>` and fix any failures before final chat.
- The final chat should not paste the whole report by default.

## Required Report Structure

Every normal report must include:

1. `元数据`
2. `模式识别`
3. `搜索通道审计与证据新鲜度 / 来源质量审计`
4. `历史命中率更新`
5. `当前事件与市场状态`
6. `异动归因表`
7. `原因到行业与ETF映射`
8. `行业-角色-催化错配检查`
9. `投资四行业当前评分表`
10. `投资四行业未来1~3个月评分表`
11. `异动结果对投资评分的影响`
12. `默认行业外强势提示`
13. `盘前 / 盘中 / 盘后专项结论`
14. `操作建议矩阵`
15. `提前布局 / 底仓 / 加仓触发表`
16. `ETF方向与最终个股`
17. `结论有效期与失效机制`
18. `新增待验证预测`
19. `假设、反方证据与证伪信号`
20. `结论变更审计`
21. `参考来源`

The search/audit section must start with `搜索通道审计` and show whether preferred providers and fallback routes were attempted.

The `当前事件与市场状态` or `原因到行业与ETF映射` section must include a `细分行业确认表` before any scoring table:

| 宽行业 | 事件 / 价格线索 | 一级细分 | 二级 / 叶子分支 | ETF / 指数验证 | 当前动作 | 不可混入分支 |
| --- | --- | --- | --- | --- | --- | --- |

Report rules for sub-industry granularity:

- `投资四行业当前评分表` and `投资四行业未来1~3个月评分表` may keep the four-sector comparison, but each row must state the confirmed leaf branches driving the score and the weak / contradictory branches.
- `操作建议矩阵`, `提前布局 / 底仓 / 加仓触发表`, and `ETF方向与最终个股` must use leaf branches, not broad labels.
- Leaf branches must not be concatenated. Do not write `水电/火电`, `A股创新药/港股创新药`, `电力运营`, or `绿电运营` as one executable branch; split them into separate rows.
- If an actionable row uses a broad ETF, label it `宽口径替代` or `不使用...仅正文观察`; otherwise the row overstates precision.
- If leaf-branch evidence is unavailable, write `细分不明/等待确认` and keep the action at observation.

Mode-specific section names:

- Pre-Market: `盘前计划与今日验证清单`
- Intraday: `盘中快照与收盘前验证`
- Post-Market: `盘后复盘与明日计划`

## Conclusion Validity and Invalidation

Every normal report must include hard validity and invalidation for each major conclusion:

- `当前结论有效期`
- `未来1~3个月结论复核频率`
- `自动失效条件`
- `降级条件`
- `重新分析触发器`

Default validity windows:

| Mode | Current / tactical validity | Forward review |
| --- | --- | --- |
| 盘前 | valid only until 30-60 minutes after open | review weekly or after major shock |
| 盘中 | valid only until close | review weekly; intraday heat cannot upgrade forward view without close confirmation |
| 盘后 | valid until next session first 30-60 minutes unless overnight events change assumptions | review weekly or after catalyst confirmation/failure |

Use `有效`, `需确认`, `降级观察`, or `已失效` for major conclusions.

## Wording Discipline

- Do not describe a sector as `有戏`, `主攻`, `可以做`, `右侧`, or `确认` unless the report explicitly shows the relevant ETF/index outperforming its benchmark in the current evidence window.
- If the conclusion is based on catalysts but current price confirmation is missing, use `有催化，等待价格确认` or `只观察，不执行`.
- If the latest snapshot contradicts a pre-market thesis, state `盘前假设未确认` and show the underperforming ETF/index. Do not soften this into a bullish conclusion.
- For split A/H evidence, write the split plainly: `港股确认，A股未确认` or `A股确认，港股未确认`. Do not collapse split evidence into a whole-sector conclusion.
- In the final chat, include a one-line `价格确认状态` for every major action direction: `确认 / 未确认 / 反向失效`.

## Final Chat Response

Always include:

- Saved report path.
- Mode.
- Ledger path.
- Stats path.
- `综合结论` with current main direction, 1-3 month main direction, 1-3 month bottom/ambush/wait/downgrade direction, validity window, invalidation/downgrade trigger, key verification signal.
- `量价形态` for post-market reports: classify volume/price as 放量上涨, 缩量上涨, 放量下跌, 缩量下跌, or 量能待确认, then state the practical action meaning.
- `行动建议` with chase/no-chase, pullback buy, pilot/bottom position, add-on trigger, hold/reduce/exit guidance, risk control.
- `提前布局判断` distinguishing core holding, small pilot, right-side add-on, avoid/reduce.
- `价格确认状态` and leaf-branch label for every major action direction. Do not answer with only `科技`, `新能源`, `券商`, or `医疗` as the action direction.

Include the compact `ETF与个股` table unless the user asks for a shorter response or context pressure is material. If individual stocks are not justified, write `最终个股：无，等待确认` or `该方向暂无合适100元以下高弹性替代`.

Never use naked ETF codes in final summary. Use `代码 + 名称 + 对应方向`.

Do not summarize a broad mixed row from a failed final table validator. If the saved report has multiple ETFs or sub-industries in one executable row, split them in the report first, rerun `tools/validate_report_theme_rows.py`, then produce the final chat.

## Final Chat Template

```markdown
**综合分析报告已生成**

- 完整报告：`docs/analyse/market-composite-analysis-YYYYMMDD-HHMMSS.md`
- 模式：盘前 / 盘中 / 盘后
- 历史台账：`docs/analyse/abnormal-movement-ledger.jsonl`
- 统计数据：`docs/analyse/abnormal-movement-stats.md`

**综合结论**
- 当前主攻：...
- 未来1-3个月主投：...
- 未来1-3个月可小仓底仓/可埋伏/降级观察：...
- 当前结论有效期：...
- 失效 / 降级触发：...
- 今日/明日关键验证：...
- 最重要证伪信号：...

**行动建议**
- 追涨：...
- 回调买：...
- 提前布局/底仓：...
- 右侧加仓触发：...
- 可埋伏/降级观察：...
- 暂不观察 / 风险规避：...

**ETF与个股**
| 层级 | 主线方向 | 子行业/真实归属 | ETF | 核心弹性/角色锚点（含价格+状态） | 防御/观察锚（含价格+状态） | 直接催化/传导链 | 触发条件 | 失效条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
```
