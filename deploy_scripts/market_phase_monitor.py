"""市况右侧信号监控 cron 入口（no_agent，stdout 推飞书，空=静默）。"""
import sys
sys.path.insert(0, 'D:/Code/AH_analyse/tools')

from market_phase_check import monitor_main

if __name__ == '__main__':
    monitor_main()
