# Event Triage and Scoring Rules

Use this reference for event classification, abnormal movement attribution, sector scoring, and layout decisions.

## Mandatory Event Triage Gate

Before scoring sectors or selecting ETFs / stocks, build a `重大事件分流表`. This gate is mandatory for every normal composite run.

Workflow:

1. Collect the live event universe first; score market sectors second.
2. Classify material events into `P0重大必写`, `P1重要候选`, or `P2背景资料`.
3. Every `P0重大必写` event must appear in the report and cause-to-industry mapping even if price confirmation is absent.
4. If a `P0` event is not actionable, label it `需价格确认` instead of omitting it.
5. Convert each `P0` and relevant `P1` event into: `事件 -> 上游触发 -> 中观传导 -> 市场放大器 -> 行业映射 -> ETF/指数验证 -> 今日/明日验证信号`.
6. Separate `事件重要性` from `价格确认度`.

Mandatory table:

| 事件 | 等级 | 来源质量 | 是否价格确认 | 影响行业 | 真实子行业 | ETF/指数验证 | 处理 |
| --- | --- | --- | --- | --- | --- | --- | --- |

`P0重大必写` examples:

- high-level diplomatic meetings, state visits, trade talks, tariff / sanction changes.
- war escalation, ceasefire, blockade, geopolitical shocks.
- central-bank rate decisions, CPI / PPI / employment shocks, FX or bond-yield shocks.
- State Council, ministry, regulator, exchange, fiscal / monetary policy releases.
- major official industry rules, procurement / tender changes, price reform, planning documents.
- company filings or deals large enough to affect an industry ETF.

Scoring correction:

- `P0 + 已价格确认`: can affect current and forward scoring, subject to ETF/breadth checks.
- `P0 + 需价格确认`: must affect event radar, scenario planning, and verification checklist; may affect forward scoring only with slow-variable evidence.
- `P0 + 未价格确认`: watchlist and falsification module only.
- `P1 + 已价格确认`: can affect current scoring if ETF/breadth confirms.
- `P2背景资料`: support assumptions, not current action.

## Mandatory Sub-Industry Resolution Gate

The default four sectors are only comparison containers. They must not be used as executable directions.

Before abnormal attribution, investment scores, ETF ideas, stock candidates, or action advice, build a `细分行业确认表`:

| 宽行业 | 事件 / 价格线索 | 一级细分 | 二级 / 叶子分支 | ETF / 指数验证 | 当前动作 | 不可混入分支 |
| --- | --- | --- | --- | --- | --- | --- |

Rules:

- Each `P0` and actionable `P1` event must map to at least one leaf branch. If it cannot, write `细分不明/等待确认` and keep the action at observation.
- A broad theme such as `科技`, `AI硬件`, `新能源`, `AI能源`, `电力`, `电力运营`, `综合电力`, `绿电运营`, `创新药`, `券商`, or `港股科技` is not a leaf branch by itself.
- A leaf branch must be atomic. Do not join multiple real branches with `/`, `、`, `+`, or `和` in `二级 / 叶子分支`, action matrices, or final ETF / stock rows. Example: `水电/火电`, `水电+核电`, and `电力运营` are invalid; use separate `水电红利`, `火电弹性`, and `核电` rows.
- If multiple leaf branches are plausible, split them into separate rows and score them separately. Do not average them into a single broad action.
- A sector score may summarize leaf branches, but the report must show which leaf branches drive the score and which branches are weak or contradictory.
- A broad ETF may be used only as `宽口径替代` unless it directly tracks the confirmed leaf branch.

Minimum leaf-branch taxonomy:

| 宽行业 | 一级细分 | 二级 / 叶子分支 examples |
| --- | --- | --- |
| 科技 | AI算力硬件 | 光模块CPO, 交换机, PCB载板, MLCC被动元件, HBM存储, AI服务器ODM, 液冷散热, 数据中心电源, 连接器 |
| 科技 | 半导体 | 半导体设备, 半导体材料, 晶圆制造, IC设计, 存储芯片, 先进封装, 封测, 功率半导体 |
| 科技 | 应用与终端 | AI应用SaaS, 港股互联网平台, 消费电子终端, AI眼镜XR, 机器人核心部件, 机器人本体, 卫星互联网, 军工电子 |
| 新能源 | 发电运营 | 火电弹性, 水电红利, 核电, 风电运营, 光伏运营 |
| 新能源 | 电网与电力设备 | 特高压, 配网, 电网自动化, 二次设备, 电力IT, 电缆材料, 变压器, 开关设备, 虚拟电厂 |
| 新能源 | 储能与新能源制造 | 大储系统, 工商业储能, 户储, PCS逆变器, 储能温控, 储能消防, 光伏硅料, 光伏硅片, 光伏组件, 光伏逆变器, 光伏辅材, 风电整机, 风电海缆, 风电塔筒, 风电轴承, 锂电池, 固态电池, 钠电池, 正极材料, 负极材料, 隔膜, 电解液 |
| 新能源 | 新能源车与补能 | 整车, 智能驾驶, 电驱/电控, 充换电, 汽车电子, 零部件 |
| 券商 | 业务线 | 经纪成交贝塔, 财富管理, 基金代销, IPO投行, 并购重组, 自营权益弹性, 债券自营, 两融, 衍生品, 资本中介, 跨境合规, QDII, 港股通, 金融IT, 交易系统, 港股IPO链 |
| 医疗 | 创新药与外包 | A股创新药, 港股创新药, 出海BD, ASCO临床数据, CRO, CDMO |
| 医疗 | 器械与服务 | IVD, 高值耗材, 医疗影像设备, 手术机器人, 医疗服务, 眼科服务, 牙科服务, 医美, AI医疗, 医疗信息化 |
| 医疗 | 防御与传统医药 | 中药, 原料药, 仿制药, 普药, 疫苗, 血制品, 药店, 医药流通 |

Minimum scoring output:

| 宽行业 | 当前确认叶子分支 | 当前反向 / 未确认分支 | 未来1-3个月候选叶子分支 | 行业总分是否被叶子分支支撑 |
| --- | --- | --- | --- | --- |

If all leaf branches in a broad sector are unconfirmed or contradictory, that broad sector cannot receive a high-conviction current action even if the macro story is plausible.

## Abnormal Movement Score

Use:

```text
行业影响分 = 事件强度 x 行业相关度 x 传导确定性 x 资金关注度 x 持续时间
```

Score each dimension 1-5 and explain unusual scores.

## Investment Score

Always score the default four sectors unless the user explicitly narrows scope:

- 科技
- 新能源
- 券商
- 医疗

For current and 1-3 month views, score separately using:

- 市场环境
- 行业景气度 / 行业景气展望
- 估值位置 / 估值承接
- 催化剂 / 后续催化
- 资金偏好 / 资金持续性

Show how abnormal movement changes investment scoring:

| 行业 | 真实子行业 | 异动归因输入 | 直接/间接受益 | 对当前评分影响 | 对未来1~3个月影响 | 是否改变动作 |
| --- | --- | --- | --- | --- | --- | --- |

## Action Mapping

- `异动强 + 投资评分强`: priority opportunity; follow-through or pullback buy depending on mode.
- `异动强 + 投资评分弱`: tactical trade only; do not convert heat into medium-term allocation.
- `异动弱 + 投资评分强`: layout candidate; prefer pullbacks or confirmation.
- `异动弱 + 投资评分弱`: low priority / avoid.

## Trend and Relative-Strength Veto

- Use trend and relative strength as the first veto. A sector in a falling stage, making lower lows, or persistently underperforming its benchmark cannot be upgraded solely because the story is plausible.
- Value/reversal logic is a second-stage test, not a bypass.
- Falling-knife setups default to `降级观察` unless stop-loss, position-size caution, and at least two independent confirmation signals are stated.
- Separate explanation from decision.

## Catalyst Versus Execution Gate

This gate prevents event logic from being worded as an executable signal before price confirms it.

- `事件催化`, `产业逻辑`, `政策慢变量`, `会议窗口`, `BD/订单/临床数据预期` only create a hypothesis. They do not by themselves justify `当前主攻`, `有戏`, `可做`, `加仓`, or `追涨` wording.
- For current-session action, the sector's primary ETF/index must already outperform its benchmark in the latest quote snapshot. If it underperforms, classify the thesis as `等待确认`, `降级观察`, or `已失效`, even when the catalyst is strong.
- When A/H confirmations diverge, do not let the stronger market represent the whole sector. Example: 港股创新药强 but A股创新药/医疗ETF弱 means `港股创新药单线强，A股未确认`, not `医疗/创新药主攻`.
- If a pre-market thesis says `需开盘后30-60分钟确认` and the confirmation fails, immediately write `盘前假设未确认 / 降级`, not `仍有戏`.
- Do not use casual bullish wording such as `有戏`, `看好`, `可以上`, or `主线确认` unless the action class is explicitly `当前主攻` or `右侧确认加仓` and the price-confirmation gate is passed.
- Default downgrade map: `强催化 + 价格未确认` -> `等待触发`; `强催化 + 价格反向` -> `降级观察`; `强催化 + A/H分裂` -> `单线观察，不代表全行业`; `强催化 + ETF弱于基准` -> `不可执行，只能复核`.

## Advance Layout / Pilot-Position Gate

Every major sector and ETF must be classified into one of:

- `当前主攻`
- `右侧确认加仓`
- `可小仓底仓`
- `等待触发`
- `降级观察`
- `回避/撤退`

`可小仓底仓` is allowed before full confirmation only when:

1. 1-3 month slow-variable evidence is improving.
2. Price is no longer in uncontrolled breakdown, or risk can be predefined.
3. No fresh P0 negative event directly invalidates the thesis.
4. Position-size cap is stated, normally 10%-30% of intended final position.
5. Add-on and cut-loss / downgrade triggers are stated.

`右侧确认加仓` requires ETF/index relative strength, breadth expansion, volume support, or close-confirmed confirmation.

## Ambush / Layout Reliability Gate

Do not label a sector as `1~3个月埋伏`, `可埋伏`, or `左侧布局` only because it has fallen, looks cheap, or has a plausible slow catalyst.

If the relevant ETF/index is down roughly 10% or more over the latest 20 trading days, keeps making lower lows, or underperforms its benchmark/peer ETF, use `降级观察` or `等待确认`, not `可埋伏`.

Healthcare / innovative drug special rule: do not upgrade broad HK healthcare to `可埋伏` while it materially underperforms Hang Seng / Hang Seng Tech and A-share innovation-drug ETF confirmation is absent.
