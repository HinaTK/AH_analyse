# 每日 A 股推荐

默认使用免费、可审计的规则引擎，不需要云端大模型、Tushare 积分或付费行情。流程先扫描当次 A 股快照，再用重点行业、龙虎榜机构和游资活跃度补充候选来源；行业标签本身不会成为推荐理由。

正式推荐允许为 0～3 只。只有趋势/量价等至少三个独立证据维度、历史覆盖和质量门槛都通过时才会入选；数据缺失、陈旧快照或重大负面事件只进入观察池。买入区间、风险边界和压力位来自支撑、阻力与 ATR，条件不足时明确提示等待确认。

```powershell
$env:PYTHONPATH = 'D:\Code\AH_analyse'
$env:AH_FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:AH_WECHAT_WEBHOOK = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'

# 无网络验收
python -m ah_recommendation_system.backend.stock_recommend.run --mock

# 实盘采集、保存并推送（未配置的推送渠道会自动跳过）
python -m ah_recommendation_system.backend.stock_recommend.run --push
python -m ah_recommendation_system.backend.stock_recommend.run --open-confirm --push
python -m ah_recommendation_system.backend.stock_recommend.run --post-market --push
python -m ah_recommendation_system.backend.stock_recommend.run --weekly-reweight
```

同花顺 Financial-API 是可选的首选行情源。申请到免费 Key 后，任选一种配置方式：

```powershell
$env:HITHINK_FINANCE_API_KEY = 'your-key'
# 或者把 Key 单独放入文件
$env:HITHINK_FINANCE_API_KEY_FILE = 'C:\path\to\hithink_key.txt'
```

程序也会自动检查 `~/.hithink-finance/api_key` 和 `C:\Users\Administrator\Downloads\hithink_key.txt`。Key 不可用时会继续尝试 AKShare / 腾讯等免费来源；全部实时源失败时，最近一次缓存只能生成观察池，报告状态会标为 `failed`，不会伪装成“今日无机会”。

长期运行可使用仓库根目录 `tools/install_stock_recommend_tasks.ps1` 注册 Windows 任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_stock_recommend_tasks.ps1
```

默认任务时间为工作日 08:30（盘前）和 18:30（盘后），并在周五 19:00 执行有限幅度因子调权。`AH_FEISHU_SECRET` 可选，用于飞书签名校验。环境变量需要持久化到计划任务运行账户，而不只是当前 PowerShell 窗口。

最新报告保存在 `backend/data/stock_recommend/latest.json` 和 `latest.md`。JSON 中的 `coverage`、`quality`、`factor_scores`、`evidence` 与 `rejection_reasons` 可用于核查覆盖范围、因子贡献、证据来源和未入选原因。
