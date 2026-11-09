"""Five-minute OpenViking fallback and failure-only reporting entrypoint."""
import sys

sys.path.insert(0, r"C:\Users\Administrator\.openviking")

if __name__ == "__main__":
    try:
        from openviking_watchdog import run_once
        run_once(report=True)
    except Exception as exc:
        print(f"⚠️ OpenViking 监控自身异常（{type(exc).__name__}），请检查 .openviking/logs/watchdog.log。")
