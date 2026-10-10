# 统一 ETF 5 分钟研究入口

## 边界

仅研究、报告与独立版本化连续周状态，不导入账本/委托模块，不下单。生产旧入口已替换为薄 wrapper，统一指向本模块；旧脚本先备份，历史 CSV/报告不改，真实账本与交易脚本不改。`deploy_launchers.py` 可重装三个兼容入口，支持 `ETF_RESEARCH_REPO` 覆盖项目路径。每周仍为周五15:25、原飞书渠道；定时投递需等下一次实际运行验证。

全池指 **2026-09-23 历史资格快照的321只 eligible ETF，加当前三持仓**，不是每次重新发现今天全部上市ETF。默认每次重新请求 Sina 5分钟端点，端点无有效数据时记录失败，禁止静默回退旧缓存。旧 bars 只用于明确重叠价格一致后的合并；重叠价格差异超过0.5%保守排除。窗口内隔夜价格跳变超过11%作为潜在除权/异常保守排除，不是完整除权识别。

默认最近63个**已收盘**交易日，2026年上交所官方休市表验证连续性；周末/节假日回溯最近交易日，15:15前回溯前一日。2027年日历未知会 fail closed，需维护日历，不猜日期。两个基准 `sh589720`、`sz159363` 必须当日15:00数据有效，完整连续共同窗口，不足/过期/模拟失败中止。所有候选用同一窗口，至少40根/日及15:00收盘；offline也执行这些验证。

## 单模型、两个视图

`grid_model.py` 从原104日研究模型逐字复制，仅将 `fee()` 最低佣金5元改为1元：万一、最低1元。保留前5分钟收盘信号、下一根开盘 IOC近似、T+1、100股整手、0.05%滑点、1%当根成交量参与上限、现金/成本约束。full/early/late/recent20 一次模拟供全部排名消费。

* **轮换视图**：完整有效四窗口、非当前持仓，full完成往返次数严格领先589720；按往返次数、完成循环净差价、净差价/平均库存成本排序。**不加 corr<0.8 的互补门槛**。
* **综合研究/第三ETF互补视图**：沿用原窗口循环数、空闲卖出日、普通/下跌相关性门槛，以及35% idle效率、20% full效率、15% recent20效率、15%较弱半窗效率、15%低下跌相关性百分位评分。持仓不参与leader/候选评分。

weekly只调用 `research.run_research()` 一次，展示所有三持仓（失败也展示）、轮换leader及综合研究排名；不另取日线、不另做模拟。同候选连续相邻两周仅人工复核，同周重复不累加、跳周清零；旧日线状态版本不继承。offline/smoke/历史日期/非63日窗口/自定义资格池不继承生产连续周，也不写生产状态或宣称复核达标。`full_pool` 仅代表所选资格池已全量尝试，不等于321生产池或完整成功；另用 `production_pool`、`production_scope`、覆盖计数及 `latest_claim` 区分。

## 运行

从 `D:/Code/AH_analyse`：

```bash
python -m tools.etf_research.research
python -m tools.etf_research.weekly
python -m tools.etf_research.research --asof 2026-10-09 --limit 2 --output-path D:/scratch/research-smoke
python -m tools.etf_research.research --offline --asof 2026-10-09 --input-path D:/scratch/verification-input --output-path D:/scratch/research-offline
python -m pytest tools/etf_research/test_research.py -q
```

CLI还支持 `--sessions`、`--workers`。input目录含 `eligibility.csv` 与 `bars/{code}-m5.csv`。默认源为 managed Hermes home 下 `cache/grid-broad-20260923`，默认输出为 `cache/grid-research/{run timestamp}`，默认周状态在 `cache/grid-account/rotation/{STATE_VERSION}.json`。数据缺失/抓取失败不推进连续周；合法模型流动性/整手排除允许在相同完整合格覆盖签名下累计，覆盖改变重置；默认weekly在休市/收盘未确认时不运行，手动 `--asof` 可以研究。新输出目录不能位于历史输入目录内。

`--limit N` 为N只非持仓加全部持仓的 smoke，明确非全池；offline永远不宣称最新。输出 `result.json`、`summary.json`、`ranking.csv`、`runs.csv`、`daily-returns.csv`、`bars/`、`data-checks.json`、`errors.json`、追加式 `progress.jsonl`，weekly额外 `weekly-report.txt`。JSON NaN/Infinity统一为null。占位排名行不等于成功；successful_assets、failed_assets、rankable_rows分别明确披露，模拟覆盖严格满足successful_runs+failed_runs=attempted_assets×4。

## 已验证与限制

测试行情只在临时 `synthetic-input` / `synthetic-output` 下生成，明确 synthetic，和真实Sina结果隔离。逐次RED→GREEN覆盖资格池+三持仓、周末日期、共同窗口/缺日、模型费用与约束、四窗口/失败计数/合法JSON、weekly单调用/版本状态/连续周/仅人工复核、离线日内不足拒绝。

真实在线 smoke（5只）：Sina端点有效、最后2026-10-09 15:00，共同63日2026-07-07→2026-10-09，20次模拟成功、0失败；非全池不宣称最新。另实抓321只，全部最新到10月9日，再经已部署weekly入口离线复算：1,284个窗口中1,149成功、135失败/排除（95个模型资格排除、40个数据窗口失败），258只完整覆盖四窗口、63只未完整覆盖。报告明确降级，不推进生产连续周状态；结果位于 managed home 的 `cache/research-unification/final321/`。随后经已部署weekly入口完整在线刷新并重算，覆盖与上述回放一致：321只抓取成功、1,149窗口成功/135失败或排除、258只完整；生产范围标识为true，但覆盖降级使 `latest_claim=false`，未推进生产连续周状态。完整在线结果在 `cache/research-unification/final-online-full321/`。这是真实抓取数据回测，不是合成数据或实际交易。

这是独立10万元账户模拟，不能相加预测共享账户利润。使用当根总成交量限制存在前视偏差；未建模真实盘口、股息现金调整与共同资金分配。原模型未改变，不将历史资格快照称实时上市全市场筛选，不将模拟当买入授权。
