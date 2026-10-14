# 已确认ETF统一运行链路：验收边界

权威状态仅为 managed Hermes home 的 `cache/grid-account/confirmed-589720.json` 与 `confirmed-159363.json`。其他ETF未重新对账，账户现金不得推算或伪造。

## 必须验证
- preview、execute、intraday、eod、midnight、confirm实际入口使用同一新状态路径，不从旧ledger/tickets推导成交。
- 成交ID唯一，重试幂等；裸“成功”不得整票登记。历史日期null保持原样。
- 买入只加qty；卖出核对sellable_qty并扣减两者；每日00:01从成交重算qty并写sellable_qty=qty，同日重复不能恢复已卖库存。
- max_grid买进一号/卖退一号，经济配对ID与T+1库存分开。
- 同一文件读改写须互斥并原子保存。测试用临时路径，不写真实成交。
- 两ETF一买一卖，1.5%，8000/6000元买格预算；买入价格来自当前最大格买价/1.015，卖价乘1.015。
- 未核现金/组合额度/券商旧单只给条件参考，非已验证可执行委托。
- 行情同交易日>=09:30、交易时段门控；触价非成交；日内高低价与现价按日期代码方向价位共用去重。
- 缺日期不报告最近20日实际往返；报价末价与收盘价区分。
- 实际脚本exit0与定时送达分开验证；不把修改cron prompt当成切换脚本实现（no_agent忽略prompt）。

## 原始保护基线（2026-10-14修改前）
- confirmed-589720.json SHA256 `4f98a8518678a22586f1f93e5785988e174ca1d6a4ae552791c8ea70079b72dd`
- confirmed-159363.json SHA256 `13b6b5cf8cb0b599de1ffa5e4bb3afaa1b1957b78baed176cca91a00d8759edb`

## 已核实00:01实际执行
managed cron output `ed9d5c85e0c4/2026-10-14_00-01-47-738581-jyoqv_vx.md` 保存了两ETF输出：589720持有/可卖28200，max C；159363持有/可卖29000，max F，更新日均2026-10-14。此为旧午夜入口首次夜间实际执行证据；新版午夜入口部署验收另行验证。

文档为验收要求，完成状态以实际测试、部署、读回为准。
