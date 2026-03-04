# 快速测试脚本
import sys

sys.path.insert(0, "D:/Code/AH_analyse/ah_recommendation_system/backend")
import os

os.chdir("D:/Code/AH_analyse/ah_recommendation_system/backend")

# 启用模拟数据
from ah_recommendation_system.backend.data.price_fetcher import PriceFetcher

fetcher = PriceFetcher()
fetcher.enable_mock_data()

# 测试配对交易策略
from ah_recommendation_system.backend.strategies.pair_trading import (
    PairTradingStrategy,
)

strategy = PairTradingStrategy()
result = strategy.generate_recommendations()

print("=" * 50)
print("AH股推荐系统测试")
print("=" * 50)
print(f"策略: {result['strategy']}")
print(f"分析股票数: {result['summary']['total_analyzed']}")
print(f"买入信号: {result['summary']['buy_signals']}只")
print(f"卖出信号: {result['summary']['sell_signals']}只")
print(f"持有信号: {result['summary']['hold_signals']}只")
print()

if result["signals"]["buy_ah"]:
    print("推荐买入A股 (AH溢价率偏低):")
    for s in result["signals"]["buy_ah"][:3]:
        print(f"  - {s['name']}: 溢价率={s['current_premium']:.1f}%")

print()
print("=" * 50)
print("测试通过! 系统运行正常")
print("=" * 50)
