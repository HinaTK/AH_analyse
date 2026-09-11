# ETF and Individual-Stock Discipline

Use this reference whenever ETFs, stocks, or final candidates are discussed.

## ETF Rules

- Never output bare ETF codes by themselves.
- Every ETF mention must include `代码 + 常用名称 + 对应方向`, e.g. `159516 半导体设备ETF国泰`.
- ETF lists must include priority labels: `P1主线`, `P2确认`, `P3对冲/观察`, or `规避/暂不追`.
- ETF action rows must include objective trigger and invalidation / downgrade condition.
- Do not rely on a previous table to define bare ETF codes later.

## Theme-Fit Source of Truth

Use:

- `docs/analyse/reference/stock_industry_map.jsonl`
- `docs/analyse/reference/etf_theme_map.jsonl`
- `tools/validate_theme_fit.py`

Before any final ETF / stock table, run the checker for every named candidate.

Mismatch table:

| 标的 | 主线方向 | 真实子行业 | 交易角色 | 催化关系 | ETF/指数匹配 | 处理 |
| --- | --- | --- | --- | --- | --- | --- |

If the checker says `间接受益`, `仅防御相关`, `无明确关系`, `部分匹配`, or `不匹配`, the stock cannot be listed as `核心弹性`, `当前主攻`, or `高弹性` for that row. Use `防御锚`, `观察锚`, `ETF优先`, or `剔除/降权`.

If the checker output says `禁止进入当前主线行`, `禁止混入当前混合主线`, or `单独防御/对冲行`, do not place the candidate anywhere inside that main-direction row, including the `防御/观察锚` column. Create a separate row using the candidate's real sub-industry / direction, or omit it from the final table.

If a candidate is direct for one branch but excluded by another branch in the same broad theme, split the row before writing the final table. Example: water-power dividend stocks may be `水电红利/绿电防御` observation anchors, but they must not appear inside an `AI能源/电网设备/算力用电` row.

If source evidence contradicts mapping, add `map_update_needed` in `结论变更审计` and use the safer role until the mapping file is updated.

## Stock Role Gate

Every named stock must have exactly one primary role and one execution status.

Roles:

- `情绪龙头/高度龙头`
- `产业龙头/中军`
- `高弹性/低位扩散`
- `防御锚/对冲锚`
- `剔除/降权`

Execution statuses:

- `可交易候选`
- `开盘后确认候选`
- `回调确认候选`
- `观察锚`
- `高位风险锚/不追高`
- `剔除/降权`

If evidence is incomplete, default to safer statuses: `开盘后确认候选`, `回调确认候选`, `观察锚`, `高位风险锚/不追高`, or `剔除/降权`.

## Role Definitions

| Role | Required evidence | Proves | Does not prove | Default output status |
| --- | --- | --- | --- | --- |
| `情绪龙头/高度龙头` | Consecutive limit-up, highest board, strongest seal, theme recognition | Current heat | 1-3 month investability | `高位风险锚/不追高` unless pullback/open confirmation |
| `产业龙头/中军` | Industry position, orders/earnings/policy linkage, ETF weight | Medium-term thesis | Current trade suitability | `观察锚` or `回调确认候选` |
| `高弹性/低位扩散` | Same-chain relevance, catalyst linkage, relative strength vs ETF | Higher beta after sector confirmation | Low price alone | `开盘后确认候选` / `回调确认候选` |
| `防御锚/对冲锚` | Stable cash flow, dividend, balance-sheet defense | Risk control | Short-term theme elasticity | `观察锚` / `可小仓底仓` |
| `ETF` | Sector ETF/index runs ahead of benchmark with volume/breadth/close confirmation | Sector-level confirmation | Individual stock buyability | Preferred when stock evidence is mixed |

## Final Stock Validation Workflow

1. Start from sector thesis and ETF expression.
2. Pull latest available price / percentage change for candidates.
3. Run `tools/validate_theme_fit.py` with current mode, theme, candidates.
4. If checker returns `未收录`, `无明确关系`, `不匹配`, or `剔除降权`, do not keep the stock except as a documented exclusion.
5. Compare candidates with the mapped ETF, benchmark, and same-chain peers where feasible.
6. Include high-board leaders only if checker and ETF/breadth gates support the role; otherwise state exclusion reason.
7. Assign validation window matching role.
8. Write concrete trigger and invalidation for each stock.
9. If validation is incomplete, keep in observation pool or write `无合适候选` / `ETF优先，个股等待确认`.

## Fallback Candidate Pool

If automatic board discovery fails or `stock_candidates` is empty:

1. Use mapped ETFs and event evidence to choose candidates from `stock_industry_map.jsonl`.
2. Include representative roles when available: industry leader, high elasticity, defensive anchor, exclusion candidate.
3. Fetch exact quotes with `--a-code` / `--hk-code` and `--skip-boards`.
4. Run theme-fit checker.
5. Output `开盘后确认候选`, `回调确认候选`, `观察锚`, `高位风险锚/不追高`, or `剔除/降权`; do not output unconditional buy.

## Per-Sector Discipline

- 科技 / AI硬件: choose candidates only from the confirmed atomic branch. Split 光模块CPO, 交换机, PCB载板, MLCC被动元件, HBM存储, AI服务器ODM, 液冷散热, 数据中心电源, 连接器, 半导体设备, 半导体材料, 先进封装, 封测, AI应用SaaS, 港股互联网平台, 消费电子终端, AI眼镜XR, 机器人核心部件, and 机器人本体 when present.
- 新能源 / AI能源: split 火电弹性, 水电红利, 核电, 风电运营, 光伏运营, 特高压, 配网, 电网自动化, 二次设备, 电力IT, 电缆材料, 变压器, 开关设备, 大储系统, 工商业储能, 户储, PCS逆变器, 储能温控, 储能消防, 光伏硅料, 光伏硅片, 光伏组件, 光伏逆变器, 光伏辅材, 风电整机, 风电海缆, 风电塔筒, 风电轴承, 锂电池, 固态电池, 钠电池, 正极材料, 负极材料, 新能源车整车, 智能驾驶, and 充换电. Do not merge 水电, 火电, 核电, 风电, 光伏, grid equipment, storage, or manufacturing into one executable row.
- 券商: split 经纪成交贝塔, 财富管理, 基金代销, IPO投行, 并购重组, 自营权益弹性, 债券自营, 两融, 衍生品, 资本中介, 跨境合规, QDII, 港股通, 金融IT, 交易系统, and 港股IPO链 when relevant. Require securities/brokerage ETF relative strength before final picks.
- 医疗 / 创新药: split A股创新药, 港股创新药, 出海BD, ASCO临床数据, CRO, CDMO, IVD, 高值耗材, 医疗影像设备, 手术机器人, 医疗服务, 眼科服务, 牙科服务, 医美, 中药, 原料药, 仿制药, 普药, 疫苗, 血制品, AI医疗, and 医疗信息化. Do not recommend a broad innovation-drug candidate solely from one BD event. Require innovation-drug ETF or HK healthcare breadth confirmation.
- 资源 / 黄金 / 油气: use as hedge unless commodity price and equity ETF/stock breadth both confirm.

## ETF Purity Labels

Every ETF in an executable row must be labeled as one of:

- `高贴合`: directly tracks the leaf branch or a narrow equivalent.
- `次优替代`: adjacent to the leaf branch, acceptable only with explicit caveat.
- `宽口径替代`: broad basket that contains the leaf branch but also unrelated exposure; cannot justify current action alone.
- `不使用`: too broad, stale, misconfigured, or contradicted by latest price.

If the pure ETF does not exist or is too illiquid, state that explicitly and keep the action at `观察` or `ETF优先，个股等待确认` rather than forcing a broad ETF into a precise branch.

## Pre-Market Stock Rules

- All current-direction stocks default to `开盘后确认候选`.
- Do not label any stock `可交易候选` before open unless valid post-open price evidence exists.
- The trigger must say `等开盘后30-60分钟确认`.
- If the user prefers sub-100 CNY high-elasticity names, apply it by default; if no qualified name exists, state `该方向暂无合适100元以下高弹性替代`.
- A below-100 CNY stock that is weak versus mapped ETF is `低价但不合格，剔除/降权`.

## Final Table Format

| 层级 | 主线方向 | 子行业/真实归属 | ETF | 核心弹性/角色锚点（含价格+状态） | 防御/观察锚（含价格+状态） | 直接催化/传导链 | 触发条件 | 失效条件 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Rules:

- The `子行业/真实归属` cell must describe one atomic executable branch only. Do not combine branches such as `水电/火电`, `电力运营`, `电网设备+光伏设备`, or `A股创新药/港股创新药` in one row.
- The `子行业/真实归属` cell should use the atomic taxonomy from `event-scoring.md`; avoid broad labels such as `AI硬件`, `AI能源`, `电力`, `电力运营`, `综合电力`, `绿电运营`, `创新药`, `港股科技`, or `券商贝塔`.
- A row that is `降级观察`, `P3观察`, or `防御/观察` still must obey the same split-by-branch rule.
- If one thesis needs multiple ETFs from different real sub-industries, split the ETFs into separate rows. Do not put `电力ETF + 电网设备ETF + 光伏ETF` in one final row.
- If a broad ETF maps to multiple branches, either split the expression, mark it `宽口径替代`, or write `不使用...仅正文观察`; do not place it in the ETF cell as if it were a clean branch tracker.
- If a defensive anchor belongs to a different real sub-industry than the row, create a separate defensive row or omit it. Example: `600900 长江电力` belongs to `水电红利`; it cannot sit inside `火电弹性`, `核电`, `电网设备`, or `AI能源` rows.
- For `新能源 / AI能源`, split at least these branches when present: `火电弹性`, `水电红利`, `核电`, `风电运营`, `光伏运营`, `特高压`, `配网`, `电网自动化`, `二次设备`, `电力IT`, `大储系统`, `工商业储能`, `户储`, `PCS逆变器`, `储能温控`, `储能消防`, `光伏硅料`, `光伏硅片`, `光伏组件`, `光伏逆变器`, `光伏辅材`, `风电整机`, `风电海缆`, `风电塔筒`, `风电轴承`, `锂电池`, `固态电池`, `钠电池`, `新能源车整车`, `智能驾驶`, `充换电`.
- For `科技 / AI硬件`, split at least these branches when present: `光模块CPO`, `MLCC被动元件`, `PCB载板`, `HBM存储`, `半导体设备`, `半导体材料`, `科创芯片`, `IC设计`, `先进封装`, `封测`, `AI服务器ODM`, `液冷散热`, `AI应用SaaS`, `港股互联网平台`, `机器人核心部件`, `机器人本体`.
- For `医疗 / 创新药`, split A股创新药, 港股创新药, 出海BD, ASCO临床数据, CRO, CDMO, IVD, 医疗影像设备, 高值耗材, 医疗服务, 中药, 原料药, 仿制药, 普药, 疫苗, 血制品, AI医疗, 医疗信息化, and 港股医疗 when confirmations diverge.
- For `券商`, split 经纪成交贝塔, 财富管理, 基金代销, IPO投行, 并购重组, 自营权益弹性, 债券自营, 两融, 衍生品, 资本中介, 跨境合规, QDII, 港股通, 金融IT, 交易系统, and 港股IPO链 when these drivers diverge.
- After saving any composite report, run `python tools/validate_report_theme_rows.py <saved-report>`. A failing validator means the report is structurally invalid and must be fixed before final chat.

Do not use legacy rows like `龙头1`, `龙头2`, `高弹性1`, or `高弹性2`.
