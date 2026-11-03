# ETF 产品/基本面数据端点手册（2026-10-27 实测，push2/akshare 被限流时的存活端点）

场景：给 ETF 做产品级评估（费率/规模/成立/跟踪标的/净值跟踪偏离）时，push2.eastmoney.com
（clist/ulist/push2his 全系）与 akshare `fund_etf_spot_em`（底层就是 push2 clist）同日被限流
断连（RemoteDisconnected）。**fund 域名家族不受影响**，全部走通。

## 端点清单（全部实测 200）

| 数据 | URL | 提取方式 |
|---|---|---|
| 费率/跟踪标的/成立日期 | `https://fundf10.eastmoney.com/jbgk_{code}.html` | HTML 正则：`管理费率</th><td[^>]*>([^<]+)</td>`、`托管费率`、`跟踪标的`、`成立日期[^0-9]*(\d{4}-\d{2}-\d{2})` |
| 规模历史（期末净资产/总份额/变动率） | `https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=gmbd&code={code}&rt=0.1`（需 Referer: `.../gmbd_{code}.html`） | 返回 `var gmbd_apidata={content:"<table...>"}`；行正则：`<tr><td>(\d{4}-\d{2}-\d{2})</td><td class='tor'>([\d.,]+)</td>...` 共6列（日期/申购/赎回/期末总份额/期末净资产/变动率） |
| 净值序列（单位净值） | `https://fund.eastmoney.com/pingzhongdata/{code}.js` | 正则 `Data_netWorthTrend\s*=\s*(\[.*?\]);` → JSON 数组，元素 `{x: 毫秒时间戳, y: 净值}` |
| 价格/成交量 | `https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?param={sym},day,,,{lmt},qfq` | `data[sym]['qfqday'/'day']`，行 `[date,open,close,high,low,volume]` |
| 指数K线（跟踪偏离基准） | 同上腾讯 fqkline，指数代码如 `sz399971`/`sh000852` | 注意部分中证指数腾讯没有（如全指软件 H30202、801750 系）→ 标数据缺失，**禁止拿近似指数硬算** |

## 坑与修法

- **jbgk 页面的"资产规模"字段是 JS 渲染**，HTML 正则抓不到 → 规模一律走 gmbd 接口
  （FundArchivesDatas.aspx），不要在 jbgk HTML 里反复换正则。
- **gmbd 返回的是 JS 变量不是 JSON**：先 `var gmbd_apidata={content:"` 前缀，内容是 HTML
  表格字符串，直接对整段文本跑行正则即可。
- **腾讯日K只有成交量（手）没有成交额**：日均成交额近似 = `vol×100×(high+low)/2`
  的20日均值（512980 实测约3.47亿，量级对）。要精确成交额需东财 push2his（限流时不可得）。
- **净值跟踪偏离 vs 市价跟踪偏离是两个口径**：ETF市价对指数的年化偏离含盘口折溢价
  噪音（512980 实测 4.67%），净值口径才是官方跟踪误差口径（同标的 0.63%）。算跟踪
  误差必须用 pingzhongdata 净值序列，不要拿场内价格糊弄。
- **增强型 ETF 的"大偏离"不是跟踪失败**：159680 净值年化偏离 5.03%、累计 +8.6%——
  是量化增强的主动正向偏离（跑赢），一票否决第3项（跟踪误差>2%）针对被动工具的
  负向持续偏离；增强型要检查的是超额收益能否覆盖费率差。
- akshare 被断连时错误是 `RemoteDisconnected`（requests 层），不是超时——重试无用，
  直接换端点家族。

## 同类清单来源（限流时）

全市场 ETF 现货表（akshare fund_etf_spot_em）拿不到时，同类竞品清单从**自有研究宇宙**
取：`tools/etf_research/research.py load_universe(path)` 或最新研究目录 `result.json`
的 `ranking`（含 code/name，321只）。注意 `load_universe` 需要传 path 参数。

## 本轮实测快照（2026-10-27，供对照）

512980 传媒：46.84亿/0.60%/2017-12-27；515230 软件：52.42亿/0.60%/2021-02-03；
159680 1000增强：17.83亿/0.60%/2022-11-18（vs 同指数被动型 512100 等 0.20%——3倍费率差）。
原始数据存 `D:/Code/AH_analyse/reports/_f10_raw.json`、`_scale_raw.json`、`_established.json`。
