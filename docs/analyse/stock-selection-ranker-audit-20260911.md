# 选股排序内核改造审计说明（2026-09-11）

## 本次改动边界

本次只替换排序内核与证据留存链路，不改变 08:30 盘前报告的外壳、质量门、风险审查、防守降仓、WATCH 口径和推送流程。

## 进池口径

- `scan_snapshot(..., limit=None)` 现在只做可交易预筛：6 位 A 股代码、价格大于 0、剔除 ST/退市/暂停/B 股类名称、成交额不低于 1 亿元。
- 原来的标签丢弃、标签排序、固定 600 截断、市值/PE/价格硬门不再决定进池；这些保留为质量观察或特征，不再作为唯一入场资格。
- 标签与行业来源转入 `source_tags_sidecar` / `candidate_sources`，只做人读溯源，不参与排序。

## 影子面板与标签

- 每日 run 会把可交易截面写入 `backend/data/stock_recommend/panels/ranking_panel_YYYYMMDD.parquet`，并记录 `point_in_time_snapshot=true`、`panel_scope=all_tradable` 和 `source=live_execution|mock`。
- 标签使用 T+1 开盘到 T+5 收盘的可执行模拟，净收益减沪深300。停牌或数据缺失为 `unfilled`，未到期为 `pending`。
- mock 面板不会晋级模型，也不会覆盖 live 最新报告。

## 模型晋级门

`rolling_calibrate_ranker` 采用 purged walk-forward：

- 只接受 `status=filled`、六维特征完整、`label_end` 已到期的样本。
- 必须 `source=live_execution` 且 `panel_scope=all_tradable`。
- 至少 3 个滚动折，且不少于 600 行有效样本。
- 晋级要求至少三分之二折的样本外超额收益超过现有六维 0.55 基线，且最新折不能失败。

线上排序键由 `factor_weights.json` 控制。只有晋级通过才写 `ranking_key=model_score`、`factor_version=ranker-v1` 和模型分空间的 `minimum_score`。默认仍为 `ranking_key=composite`；周更未通过时会写 `ranking_key_not_promoted`。

## 当前结论与限制

- 合并后的默认行为仍是六维 composite 排序；模型键不会自动切换。
- 目前历史 live 全截面面板和到期标签不足，模型晋级尚未发生，这符合保守门设计。
- 本次不声明模型有 alpha；是否有效只能由后续真实全截面、可执行标签和滚动样本外结果验证。
- LightGBM 路径保留为可选扩展，当前线上与晋级评估使用缺失感知的线性/岭回归排序器。

## 验证

核心目标套件共 70 个测试通过，覆盖进池、截面变换、影子面板、标签、排序器、晋级门、周更配置和盘后语义。

## 面板标签所需的外部输入

影子面板只是当截面快照。当周要把它变成可训练样本，还需要两份可复核输入：

- 各股票从信号日前到 T+5 后的不复权执行价格；缺 BaoStock 覆盖的标的会保留 `unfilled`。
- 明确标注沪深300的 `benchmark_calendar.json`，字段为 `date/open/close`。

这两项是执行验证，不能被mock价或行情缓存替代。缺少任一项时，周更不会晋级排序键。

## 2026-09-11 晚间实测补充

第一次 live 运行因 Financial-API 价格快照缺少估值字段、AKShare/Efinance 限流断连，被质量门正确拒绝，退化为 109 只有限样本。
已把 Financial-API 的估值/市值/换手补充接到价格快照后，重跑成功：全市场 5,571 只扫描，2,928 只可交易候选进入影子面板；PE 覆盖 99.95%，价格覆盖 99.62%。
当晚最终报告通过质量门，`latest.json` 为 23:21:02 的 live run，`ranking_key=composite`，输出 2 只 WATCH 观察（601872、600150），无 P0，ETF 当晚无合格标的。
影子面板 `panel_scope=all_tradable`、`point_in_time_snapshot=true`、`source=live_execution`，成交额门槛最小值约 1.00076 亿元。
