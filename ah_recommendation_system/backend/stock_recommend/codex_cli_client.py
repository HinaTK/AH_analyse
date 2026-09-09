"""Small, read-only adapter for local ``codex exec`` calls.

The adapter intentionally has no market-data or tool access.  It receives a
pre-built evidence prompt and returns a structured result for the caller to
validate.  A missing executable, timeout, or malformed output is a normal
degraded state for the daily job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional


class CodexCliClient:
    def __init__(
        self,
        *,
        binary: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self.binary = binary or os.environ.get("AH_CODEX_BIN") or "codex"
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.environ.get("AH_CODEX_TIMEOUT_SECONDS", "90")
        )
        self.model = model or os.environ.get("AH_CODEX_MODEL") or ""
        requested_effort = reasoning_effort or os.environ.get("AH_CODEX_REASONING_EFFORT") or "low"
        self.reasoning_effort = requested_effort if requested_effort in {
            "minimal", "low", "medium", "high", "xhigh"
        } else "low"

    def available(self) -> bool:
        return bool(shutil.which(self.binary))

    def analyze(self, prompt: str) -> Dict[str, Any]:
        started = time.monotonic()
        if not self.available():
            return self._result("disabled", started, error="codex executable not found")

        args = [
            self.binary,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--color",
            "never",
            "--config",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            "--config",
            'model_verbosity="low"',
            "--config",
            'web_search="disabled"',
        ]
        if self.model:
            args.extend(["--model", self.model])

        try:
            with tempfile.TemporaryDirectory(prefix="ah-codex-") as work_dir:
                output_path = Path(work_dir) / "last-message.json"
                args.extend([
                    "--skip-git-repo-check",
                    "-C",
                    work_dir,
                    "--output-last-message",
                    str(output_path),
                    "-",
                ])
                proc = subprocess.run(
                    args,
                    input=prompt,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    cwd=work_dir,
                    timeout=max(1.0, self.timeout_seconds),
                    check=False,
                )
                content = ""
                if output_path.exists():
                    content = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if not content:
                    content = (proc.stdout or "").strip()
                parsed = _parse_json_object(content)
                if proc.returncode != 0:
                    return self._result("failed", started, error=f"codex exit {proc.returncode}", stderr=(proc.stderr or "")[-500:])
                if parsed is None:
                    return self._result("failed", started, error="codex output was not valid JSON")
                result = self._result("used", started, output_valid=True)
                result["data"] = parsed
                return result
        except FileNotFoundError:
            return self._result("disabled", started, error="codex executable not found")
        except subprocess.TimeoutExpired:
            return self._result("failed", started, error="codex timeout")
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            return self._result("failed", started, error=type(exc).__name__)

    @staticmethod
    def _result(status: str, started: float, *, output_valid: bool = False, error: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": status,
            "output_valid": output_valid,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        }
        result.update(extra)
        return result


def _parse_json_object(content: str) -> Optional[Dict[str, Any]]:
    text = (content or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
