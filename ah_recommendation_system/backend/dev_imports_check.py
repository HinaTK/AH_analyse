# 测试AH股推荐系统
import sys
sys.path.insert(0, '.')

print("测试AH股推荐系统...")

# 1. 测试导入
print("\n[1] 测试导入...")
try:
from ah_recommendation_system.backend.config import STRATEGY_CONFIG, DATABASE_CONFIG
    print("  ✓ config.py 导入成功")
except Exception as e:
    print(f"  ✗ config.py 导入失败: {e}")

# 2. 测试数据层
print("\n[2] 测试数据层...")
try:
from ah_recommendation_system.backend.data.ah_stock_list import get_ah_pairs, get_stock_name
    print("  ✓ ah_stock_list.py 导入成功")
except Exception as e:
    print(f"  ✗ ah_stock_list.py 导入失败: {e}")

try:
from ah_recommendation_system.backend.data.price_fetcher import PriceFetcher
    fetcher = PriceFetcher()
    print("  ✓ price_fetcher.py 导入成功")
except Exception as e:
    print(f"  ✗ price_fetcher.py 导入失败: {e}")

# 3. 测试策略
print("\n[3] 测试策略...")
try:
from ah_recommendation_system.backend.strategies.pair_trading import PairTradingStrategy
    print("  ✓ pair_trading.py 导入成功")
except Exception as e:
    print(f"  ✗ pair_trading.py 导入失败: {e}")

try:
from ah_recommendation_system.backend.strategies.multi_factor import MultiFactorStrategy
    print("  ✓ multi_factor.py 导入成功")
except Exception as e:
    print(f"  ✗ multi_factor.py 导入失败: {e}")

try:
from ah_recommendation_system.backend.strategies.ml_predictor import MLPredictorStrategy
    print("  ✓ ml_predictor.py 导入成功")
except Exception as e:
    print(f"  ✗ ml_predictor.py 导入失败: {e}")

# 4. 测试API
print("\n[4] 测试API...")
try:
from ah_recommendation_system.backend.api.models import ResponseModel
    print("  ✓ models.py 导入成功")
except Exception as e:
    print(f"  ✗ models.py 导入成功: {e}")

print("\n测试完成!")
