# 异动预测命中率统计

- 更新时间：2026-07-17 09:44:24 +08:00
- 台账路径：`docs/analyse/abnormal-movement-ledger.jsonl`
- 本轮模式：`盘前分析 / pre-market composite（生成过程中已进入开盘后早盘验证窗口）`
- 更新说明：正式结算 2026-07-16 到期的 11 条样本，新增 6 条 2026-07-17 待验证预测。X早期信号已按用户偏好禁用，未调用X/Twitter工具。

## 汇总

| 指标 | 数值 | 说明 |
| --- | ---: | --- |
| 台账总行数 | 359 | 本轮新增 6 条 pending 预测 |
| 已评估行数 | 226 | `status=evaluated`，不含 `data_missing` |
| 可计算命中样本 | 154 | `status=evaluated` 且 `composite_hit` 非空 |
| 总命中率 | 54.55% | 84/154 |
| 最近20条命中率 | 60.00% | 12/20 |
| Thesis样本数 | 130 | 去重 thesis 口径历史样本 |
| Thesis命中率 | 55.38% | 72/130 |
| 待评估行数 | 86 | 含本轮新增预测 |
| `data_missing` | 47 | 历史数据缺失或无法客观评估 |
| 2026-07-17已正式评估 | 11 | 本轮用7月16日收盘/7月17日快照prev_close结算到期样本 |
| 2026-07-17新增 | 6 | 本轮盘前/早盘新建预测 |

## 本轮台账处理

| 项目 | 结果 |
| --- | --- |
| 到期行处理 | 结算 2026-07-16 到期的 T+1 / T+0 close 样本 11 条；2026-07-17 收盘到期或 T+3 样本暂不提前结算 |
| 命中率变化 | 总命中率更新为 84/154 = 54.55%；最近20条 12/20 = 60.00% |
| 数据质量 | 使用 `docs/analyse/runtime/market_snapshot_20260717.json` 的 2026-07-16 收盘价/集合竞价价，以及 `docs/analyse/runtime/stock_candidate_snapshot_20260717.json` 的09:40候选股快照；行业板块自动发现为空，已走映射库fallback。 |
| 未提前结算 | 2026-07-17 收盘才到期的行只做本报告复核，不改为 evaluated。 |

## 本轮正式评估样本

| 预测ID | 标的 | 方向 | 实际收益 | 基准收益 | 超额 | 结果 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `20260715-155835-a-innovative-drug-postclose-continuation-t1` | `创新药ETF银华(159992)` | benefit | -0.329% | -1.846% | 1.517pct | 命中 |
| `20260715-155835-hk-innovative-drug-postclose-continuation-t1` | `港股创新药ETF广发(513120)` | benefit | -1.635% | 1.353% | -2.988pct | 未命中 |
| `20260715-155835-brokerage-beta-postclose-confirm-t1` | `证券ETF国泰(512880)` | benefit | -1.504% | -1.846% | 0.342pct | 未命中 |
| `20260715-155835-cpo-communication-postclose-pressure-t1` | `通信ETF国泰(515880)` | pressure | -3.557% | -1.846% | -1.711pct | 命中 |
| `20260715-155835-semiconductor-equipment-postclose-pressure-t1` | `半导体设备ETF国泰(159516)` | pressure | -7.597% | -1.846% | -5.751pct | 命中 |
| `20260716-121212-a-innovative-drug-intraday-confirm-t0` | `创新药ETF银华(159992)` | benefit | -0.872% | -0.946% | 0.074pct | 边际命中 |
| `20260716-121212-hk-innovative-drug-intraday-underperform-t0` | `港股创新药ETF广发(513120)` | pressure | -2.116% | -0.365% | -1.751pct | 命中 |
| `20260716-121212-hstech-platform-intraday-confirm-t0` | `恒生科技指数(HSTECH)` | benefit | -0.753% | -0.365% | -0.388pct | 未命中 |
| `20260716-121212-brokerage-intraday-pressure-t0` | `证券ETF国泰(512880)` | pressure | 0.000% | -0.946% | 0.946pct | 未命中 |
| `20260716-121212-cpo-communication-intraday-pressure-t0` | `通信ETF国泰(515880)` | pressure | -1.215% | -0.946% | -0.269pct | 命中 |
| `20260716-121212-semiconductor-equipment-intraday-pressure-t0` | `半导体设备ETF国泰(159516)` | pressure | -4.134% | -0.946% | -3.188pct | 命中 |

## 新增待验证预测

| 预测ID | 标的 / 方向 | 窗口 | 到期日 | 方向 | 置信度 |
| --- | --- | --- | --- | --- | --- |
| `20260717-094031-a-innovative-drug-open-pressure-t0` | `159992 创新药ETF银华` / 医疗 / A股创新药 | T+0 close | 2026-07-17 | pressure | 中 |
| `20260717-094031-hstech-platform-open-split-pressure-t0` | `HSTECH 恒生科技指数` / 科技 / 港股互联网平台 | T+0 close | 2026-07-17 | pressure | 中低 |
| `20260717-094031-cpo-communication-open-pressure-t0` | `515880 通信ETF国泰` / 科技 / 光模块CPO | T+0 close | 2026-07-17 | pressure | 高 |
| `20260717-094031-semiconductor-equipment-open-pressure-t0` | `159516 半导体设备ETF国泰` / 科技 / 半导体设备 | T+0 close | 2026-07-17 | pressure | 中高 |
| `20260717-094031-grid-equipment-recovery-watch-t3` | `159326 电网设备ETF华夏` / 新能源 / 电网自动化 | T+3 | 2026-07-22 | benefit | 中低 |
| `20260717-094031-brokerage-beta-open-outperform-watch-t0` | `512880 证券ETF国泰` / 券商 / 经纪成交贝塔 | T+0 close | 2026-07-17 | benefit | 中低 |

## 复核要点

- 7月17日收盘优先验证 `159992 创新药ETF银华（A股创新药）` 是否重新跑赢沪深300；若失败，A股创新药由此前当前主线降为回踩确认/观察。
- `515880 通信ETF国泰（光模块CPO）` 与 `159516 半导体设备ETF国泰（半导体设备）` 若继续弱于沪深300，A股科技硬件维持回避；不能因长鑫IPO或AI叙事提前抄底。
- `159326 电网设备ETF华夏（电网自动化）` 的T+3观察需要连续跑赢，不能用国电南瑞单股早盘强势替代ETF确认。
- `512880 证券ETF国泰（经纪成交贝塔）` 只有在收盘继续跑赢且成交维持高位时，才允许小仓试错；否则仍为观察。
- 港股科技与港股创新药出现权重分化，需分别看 HSTECH/恒指 与 513120/恒指，不得用单一小米或单一药股代表全行业。
