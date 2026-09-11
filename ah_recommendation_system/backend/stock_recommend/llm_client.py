"""LLM client for stock recommendation.

OpenAI-compatible client (works with DeepSeek / Qwen / OpenAI / etc.).
Reads config from env vars; never hard-codes keys.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    temperature: float = 0.3
    max_tokens: int = 4096


def _read_env_config() -> LLMConfig:
    """Read LLM config from env (in priority order)."""
    api_key = (
        os.environ.get("AH_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or ""
    ).strip()

    base_url = (
        os.environ.get("AH_LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.deepseek.com/v1"
    ).strip().rstrip("/")

    model = (
        os.environ.get("AH_LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "deepseek-chat"
    ).strip()

    if not api_key:
        # Mock mode: no real LLM, but downstream code should still work.
        return LLMConfig(
            api_key="",
            base_url=base_url,
            model=model,
        )

    return LLMConfig(api_key=api_key, base_url=base_url, model=model)


class LLMClient:
    """Thin OpenAI-compatible wrapper. Lazy-imports openai to keep mock mode light."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or _read_env_config()
        self._client = None

    @property
    def is_mock(self) -> bool:
        return not self.config.api_key

    def _ensure_client(self):
        if self._client is not None:
            return
        if self.is_mock:
            raise RuntimeError("LLM client in mock mode (no api_key set)")
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "openai package not installed; pip install openai"
            ) from e
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Call LLM and parse response as JSON.

        Falls back to a heuristic stub when in mock mode.
        """
        if self.is_mock:
            return self._mock_json(system=system, user=user)

        self._ensure_client()
        kwargs = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = self._client.chat.completions.create(**kwargs)  # type: ignore
            content = (resp.choices[0].message.content or "").strip()
        except TypeError:
            # Some providers (e.g. older openai-compatible) reject response_format.
            kwargs.pop("response_format", None)
            resp = self._client.chat.completions.create(**kwargs)  # type: ignore
            content = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"LLM call failed, falling back to mock: {e}")
            return self._mock_json(system=system, user=user)

        # Extract the first JSON object in the content
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            logger.warning("LLM returned non-JSON content; using mock fallback")
            return self._mock_json(system=system, user=user)
        try:
            return json.loads(content[start : end + 1])
        except Exception as e:
            logger.warning(f"LLM JSON parse failed: {e}; using mock fallback")
            return self._mock_json(system=system, user=user)

    @staticmethod
    def _mock_json(*, system: str, user: str) -> Dict[str, Any]:
        """Heuristic mock: pick the first 3 candidate codes mentioned in the user prompt.

        Keeps the pipeline runnable without an LLM. Real LLM should be used in production.
        """
        import re

        codes = re.findall(r"\b\d{6}\b", user or "")
        seen: List[str] = []
        for c in codes:
            if c not in seen:
                seen.append(c)
            if len(seen) >= 3:
                break
        picks = []
        for i, code in enumerate(seen or ["000001", "600519", "000858"]):
            picks.append(
                {
                    "code": code,
                    "name": f"候选{code}",
                    "action": "BUY",
                    "confidence": 0.55 - i * 0.05,
                    "buy_zone": "10.00-10.20",
                    "stop_loss": "9.40",
                    "target": "11.50",
                    "holding_days": "5-10",
                    "rationale": "【mock】基于候选池排序前位，缺 LLM 时由规则引擎回退给出。",
                    "key_risks": ["板块系统性回调", "业绩预告低于预期"],
                    "factors": {"fundamental_score": 0.6, "capital_score": 0.5, "event_score": 0.4},
                }
            )
        return {
            "summary": "【mock】未配置 LLM，已用规则回退给出 3 只候选，请在生产环境配置 AH_LLM_API_KEY。",
            "picks": picks,
            "market_view": "中性偏多：基本面修复+资金流入，但事件面催化不集中。",
            "falsification": ["指数跌破 MA20", "北向连续 3 日净流出 > 100 亿"],
        }


_singleton: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton
