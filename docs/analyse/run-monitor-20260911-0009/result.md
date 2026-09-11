# A 股盘前推荐 · 2026-09-11

> 仅保留具备可追溯趋势/量价及至少三类独立证据的候选；证据不足时不生成个股推荐。

## 大盘环境判断

- **姿态**：防守｜状态 `降级观察`｜环境分 35.0｜轻仓 20%-30%；不主动加仓，等待市场修复后再提高仓位
- 证据：行业盘面正向信号0项（deterministic_market_engine，2026-09-11）
- 证据：已交叉验证热点0项（deterministic_market_engine，2026-09-11）

## 提前布局判断 / 可埋伏方向

- **当前主攻**：暂无价格确认主线｜等待开盘后价格、成交和宽度确认｜需确认｜窗口：开盘前至早盘确认；触发：行业指数、成交和上涨宽度同步确认；失效：高开回落且宽度收窄，或指数与主线同步跌破关键支撑
- **未来1~3个月主投**：暂无通过慢变量门槛的中期主线｜等待确认｜需确认｜窗口：1~3个月；触发：慢变量改善且趋势、相对强度转正；失效：慢变量证伪或价格结构持续破坏
- **可小仓底仓 / 可埋伏 / 等待触发**：无合格方向，等待触发
- **回避 / 撤退**：A股全市场宽度｜回避/撤退｜有效｜窗口：至价格结构修复；触发：重新放量站回关键均线后再分析；失效：行业宽度和相对强度恢复

## 跨市场环境

- 状态：degraded｜风险等级：normal｜时间：2026-09-11 00:10:50
- **对A股结论**：外部环境中性，对A股方向影响有限；以A股自身成交、宽度和行业强弱确认仓位。

**大盘看法**: 默认保持均衡仓位；只有触发条件确认后才进入观察或试错。

**证据覆盖**：财务 29/30；相对基准 11/30。基准状态：defense，行情截止 2026-09-10。
财务覆盖为候选子集年报；历史接口不是修订版本档案。权重晋级需通过滚动样本外及组合风险验证。

## 市场热点

- **科技**｜候选方向待确认｜驱动：候选池 2 只标的同向出现，等待行业宽度与成交确认｜行业：科技｜代表：佰维存储、赛微电子
- **半导体**｜候选方向待确认｜驱动：候选池 2 只标的同向出现，等待行业宽度与成交确认｜行业：半导体｜代表：佰维存储、赛微电子

**整体证伪信号**:
- 沪深300跌破阶段低点
- 市场成交额显著萎缩且涨跌家数恶化

> ⚠️ 今日无正式个股推荐：没有标的同时通过数据质量、证据数量和趋势/量价确认门槛。
## ETF观察

- 银行ETF富国 (159887)：主线｜综合 74.0｜趋势 100｜相对强度 50｜流动性 50｜风险控制 84｜主题匹配 65；20/60日收益为 6.2% / 9.0%；价格站上 MA20 与 MA60；MA20 高于 MA60，中期趋势偏强
## 观察池（未达正式推荐门槛）

- 龙头｜敦煌种业 (600354)：market:基准处于下行趋势，仅观察
- 弹性｜宁波银行 (002142)：market:基准处于下行趋势，仅观察
- 中军｜盾安环境 (002011)：market:基准处于下行趋势，仅观察
- 验证｜中国船舶 (600150)：market:基准处于下行趋势，仅观察
- 防御｜招商轮船 (601872)：market:基准处于下行趋势，仅观察
- 避雷｜中国出版 (601949)：market:基准处于下行趋势，仅观察
---
**数据告警**:
- local_store:Unable to write struct type with no child field to Parquet. Consider adding a dummy child field.
- llm_hotspots:codex exit 1

## 搜索与数据通道审计

- 行情/数据源：{'hithink_financial_api': 'healthy', 'hithink_probe': {'available': True, 'capabilities': {'snapshot': True, 'valuations': True, 'dragon_tiger': True}, 'error_types': {}}, 'akshare': 'unknown', 'tencent_sina_fallback': 'standby', 'market_data_attempted': ['hithink_financial_api', 'akshare:supplement', 'efinance:supplement'], 'market_data_skipped': [], 'history': {'history_sources': {'hithink_financial_api': 99}, 'akshare_history': 'healthy', 'history_errors': ['hithink_financial_api:RuntimeError', 'akshare:ConnectionError']}, 'news': {'akshare_stock_news': 'healthy', 'company_notices': 'healthy', 'rss': 'empty', 'macro_fallback': 'empty'}, 'cross_market': 'degraded', 'llm_codex': {'backend': 'codex_cli', 'hotspot_status': 'failed', 'event_status': 'used', 'event_input_candidate_count': 10, 'event_submitted_count': 3, 'event_reviewed_count': 2, 'hotspot_duration_ms': 78639, 'hotspot_error': 'codex exit 1', 'candidate_count_before': 30, 'candidate_count_after': 30, 'event_duration_ms': 17906, 'event_error': None, 'event_llm_share': 0.3, 'risk_review_status': 'used', 'risk_reviewed_count': 30, 'risk_p0_count': 0}}
- 新闻源：{'akshare_stock_news': 'healthy', 'company_notices': 'healthy', 'rss': 'empty', 'macro_fallback': 'empty'}
- X早期信号已按用户偏好禁用，未调用X/Twitter工具

_生成时间: 2026-09-11 00:15:12_  ·  LLM mock: False