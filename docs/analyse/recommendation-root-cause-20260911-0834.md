# 2026-09-11 08:34 推荐异常诊断

核验对象为 recommend_20260911.json（generated_at=2026-09-11 08:34:08）及同日 market_store Parquet。与此前 07:10 报告不同，本次报告的 picks=0、candidate_panel=30、四个热点 mapped_count=0。

## 个股为空

- 原始快照 provider_health 表明 Financial API 返回 empty_or_unusable、AKShare 连接断开，最终采用 efinance。
- efinance 原始列为“动态市盈率”，market_data.EfinanceSnapshotProvider 仅映射“市盈率”→pe。宁波银行原始动态 PE=7.15、盾安环境=15.12、招商轮船=11.94；最终候选却均为 pe=null。动态 PE 与此前 TTM PE 口径不同，修复必须保留口径。
- 30/30 候选包含“quality:估值缺失或无效”。这是数据适配故障，不足以推出市场没有合格股票。
- 备用源成功后提前返回，不补齐字段且未写入行级 source；collect_fundamental 默认标成 akshare.stock_zh_a_spot_em，导致来源显示错误。候选 Financial API 补全也因 source/quote_source 条件未触发。
- data_status 主要检查行数、模式与新鲜度，质量门禁未检查估值覆盖。空 picks 的 all(...) 证据检查自动通过，因此数据缺陷被“ok / passed”掩盖。

## 热点没有代表标的

- 备用路径采用科技/新能源/券商/医疗的小型静态行业表，无法覆盖此次四个细分主题；映射仅使用收窄后的30只候选，原始快照没有行业字段。四个 mapped_count 均为0。
- 独立缺陷：hotspot_analyzer 的输出 schema / normalize_hotspots 不生成 representatives；hotspot_mapper 只返回 mapped_count 与另一组 rows，未把成员写入 representatives。market_hotspots 却直接读取 representatives。
- 离线复现：已匹配1个行业成员时，市场热点 representatives 依然为空。故仅扩大行业词库无法彻底解决展示问题。
- 热点代表标的应来自可核验行业成员，作为观察对象，与是否通过正式交易推荐门槛分别处理。

## 新闻去重与置信度

- 采集层存在标题/时间等精确去重；news_ranker 有 URL 优先去重，无 URL 时使用标题前12个汉字（否则前16字符）。
- 不同 URL 的同标题转载不会合并；带追踪参数的 URL 也不归一。没有同事件语义聚类、原始来源追踪或独立来源计数。无 URL 的短标题前缀还可能误合并不同事件。
- 离线复现：同标题两条不同 URL 输入，输出仍为2条；使用两个不同 event_id 的热点可通过 normalize_hotspots，模型 confidence=0.90 原样保留。
- evidence_refs 仅做 ID 去重与存在性检查；event_id 由 URL/标题/时间生成，并不代表独立事件。显示“证据2条”不等于两条独立验证。
- 86%/90% 等是模型输出数字经格式转换后展示，没有基于独立性、原始出处、反证或历史命中率校准。不得解释为事实真实性概率或收益概率。
- 本次报告未保存完整入模新闻包，现有证据不能确认截图每个主题具体有几条转载；已验证的是系统允许重复计证据的代码路径和最小复现。

## 修复验收重点

先修备用源字段映射、口径/来源保留与关键字段覆盖报警；再补齐主题到行业成员到代表标的的完整数据链；最后增加同事件去重与独立来源审计，区分模型主观评分和可核验的证据等级。验证应包含主源失败的备用路径、映射成功但无正式推荐的热点，以及跨站转载。不能通过降低选股门槛或填入固定股票掩盖问题。

本次为原因分析与只读离线复现，未修改生产逻辑、重跑或发送外部消息。
