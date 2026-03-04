from __future__ import annotations

import subprocess
import sys
import time

import httpx


def main() -> int:
	proc = subprocess.Popen(
		[
			sys.executable,
			"-m",
			"uvicorn",
			"main:app",
			"--host",
			"127.0.0.1",
			"--port",
			"8010",
			"--log-level",
			"warning",
		],
	)
	try:
		time.sleep(2)
		r = httpx.get("http://127.0.0.1:8010/", timeout=20)
		print("GET /", r.status_code, r.headers.get("content-type"))
		r2 = httpx.get("http://127.0.0.1:8010/api/v1/report/latest", timeout=20)
		print("GET /api/v1/report/latest", r2.status_code)
		r3 = httpx.get("http://127.0.0.1:8010/api/v1/pair-trading?source=stored", timeout=60)
		print("GET /api/v1/pair-trading?source=stored", r3.status_code)
		return 0
	finally:
		proc.terminate()
		try:
			proc.wait(timeout=10)
		except Exception:
			proc.kill()


if __name__ == "__main__":
	raise SystemExit(main())
