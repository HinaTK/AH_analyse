# 持久化持仓列表改造方案（TDD RED→GREEN）

## 问题
`CODES` 硬编码为两只 ETF，159992 被排除在 00:01 之外，可卖份额永久为 null。
根因：没有独立的持久化持仓列表；每处都从 `CODES` 元组枚举。

## 目标结构
`cache/grid-account/holdings.json`：
```json
{"holdings": {
  "sh589720": {"name": "科创创新药ETF国泰", "lot_budget": "8000", "active": true},
  "sz159363": {"name": "创业板人工智能ETF华宝", "lot_budget": "6000", "active": true},
  "sz159992": {"name": "创新药ETF银华", "lot_budget": null, "active": false}
}}
```
规则：
- 持仓列表是唯一枚举来源；CODES 只做兼容常量。
- active=false 的 ETF 只读不写（00:01 不碰、不生成卖单、不接回）。
- 159992 有真实成交记录，不能被清零或推导。

## 验收
- 00:01 重算三只；159992 sellable_qty=18300，sellable_updated_on=今日。
- plan() 不为 159992 生成卖单；render() 明确标注迁移退出。
- 159992 任何 sell record 因 sellable=null 被拒。
- 全部回归通过；真实三账 SHA256 不变。