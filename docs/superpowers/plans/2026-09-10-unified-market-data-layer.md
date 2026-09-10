# Unified Market Data Layer Implementation Plan

## Goal

吸收 daily_stock_analysis 的行情层经验：统一行情对象、真实故障切换、字段级补全、熔断和本次实际调用链审计。

## Design

Financial-API 继续作为全市场快照主源。新增 MarketDataManager 管理主源和补源；主源价格可用但估值、换手或成交额缺失时，按代码从后源补字段。主源无效时切换到 AKShare。管理器记录 attempted、skipped、supplemented_fields 和错误，报告展示这些真实结果。

## Tasks

1. 新增 UnifiedRealtimeQuote、merge_quote_fields、MarketDataManager 和 SnapshotResult。
2. collect_fundamental 改走管理器：完整主源直接用；部分可用主源保留价格并补字段；不可用主源降级 AKShare。
3. run_pipeline 覆盖度使用实际 attempted/skipped/source/supplement 结果，去掉误导性的静态 fallback_chain。
4. 跑新增测试、相关采集测试和全量测试，再按新代码重新对比行情基础设施。

## Constraints

- 不丢弃当前分支已有改动。
- 不把 API Key 写进代码、测试、日志或报告。
- LLM 不参与全市场扫描。
- 盘前仍不伪造当日盘中结论；只记录观察时间与来源。
