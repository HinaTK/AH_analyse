@echo off
REM AH股推荐系统导入测试
REM ====================

cd /d %~dp0

echo 测试AH股推荐系统导入...

python -c "
import sys
sys.path.insert(0, '.')

print('测试导入...')

try:
    from config import STRATEGY_CONFIG
    print('✓ config.py')
except Exception as e:
    print(f'✗ config.py: {e}')

try:
    from data.ah_stock_list import get_ah_pairs
    print('✓ ah_stock_list.py')
except Exception as e:
    print(f'✗ ah_stock_list.py: {e}')

try:
    from data.price_fetcher import PriceFetcher
    print('✓ price_fetcher.py')
except Exception as e:
    print(f'✗ price_fetcher.py: {e}')

try:
    from strategies.pair_trading import PairTradingStrategy
    print('✓ pair_trading.py')
except Exception as e:
    print(f'✗ pair_trading.py: {e}')

try:
    from strategies.multi_factor import MultiFactorStrategy
    print('✓ multi_factor.py')
except Exception as e:
    print(f'✗ multi_factor.py: {e}')

try:
    from strategies.ml_predictor import MLPredictorStrategy
    print('✓ ml_predictor.py')
except Exception as e:
    print(f'✗ ml_predictor.py: {e}')

print('')
print('测试完成!')
"

pause
