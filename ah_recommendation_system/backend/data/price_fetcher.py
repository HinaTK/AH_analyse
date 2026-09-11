# 股价和汇率数据获取
# ===================

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

import akshare as ak
import numpy as np
import pandas as pd
import requests
from loguru import logger

try:
	import baostock as bs  # type: ignore
except Exception:  # pragma: no cover
	bs = None  # type: ignore

from ah_recommendation_system.backend.stock_recommend.hithink_client import HithinkClient
from ah_recommendation_system.backend.stock_recommend.execution_data import _SESSION_LOCK


_A_SHARE_SUFFIXES = (".SH", ".SZ")
_H_SHARE_SUFFIX = ".HK"


def _normalize_a_share_symbol(symbol: str) -> str:
	"""Normalize A-share symbol for AKShare.

	AKShare stock_zh_a_hist usually expects a 6-digit code like "600519".
	We accept: "600519", "sh600519", "sz000001", "600519.SH", "000001.SZ".
	"""
	s = (symbol or "").strip()
	if not s:
		return ""

	s_up = s.upper()
	for suf in _A_SHARE_SUFFIXES:
		if s_up.endswith(suf):
			s_up = s_up[: -len(suf)]
			break

	s_up = s_up.strip()
	if s_up.startswith("SH") or s_up.startswith("SZ"):
		s_up = s_up[2:]

	m = re.search(r"(\d{6})", s_up)
	return m.group(1) if m else ""


def _normalize_h_share_symbol(symbol: str) -> str:
	"""Normalize H-share symbol for AKShare.

	AKShare stock_hk_hist expects a numeric HK code like "0939".
	We accept: "0939", "0939.HK", "hk0939".
	"""
	s = (symbol or "").strip()
	if not s:
		return ""

	s_up = s.upper()
	if s_up.endswith(_H_SHARE_SUFFIX):
		s_up = s_up[: -len(_H_SHARE_SUFFIX)]

	if s_up.startswith("HK"):
		s_up = s_up[2:]

	m = re.search(r"(\d{1,5})", s_up)
	if not m:
		return ""

	code = m.group(1)
	if len(code) < 4:
		code = code.zfill(4)
	return code


class PriceFetcher:
	"""价格数据获取器"""

	def __init__(self):
		self.cache: Dict[str, tuple[datetime, pd.DataFrame]] = {}
		self.cache_duration = 300
		self.use_mock_data = False

		self._fx_cache: Optional[tuple[datetime, float]] = None
		self._fx_cache_ttl_seconds = 3600
		self._ak_history_failures = 0
		self._ak_history_open_until = 0.0
		self._hithink_history_failures = 0
		self._hithink_history_open_until = 0.0
		self._ak_history_cooldown = 60.0
		self.history_source_counts: Dict[str, int] = {}
		self.history_errors: list[str] = []

	def _record_history_source(self, source: str) -> None:
		self.history_source_counts[source] = self.history_source_counts.get(source, 0) + 1

	def provider_health(self) -> Dict[str, object]:
		return {
			"history_sources": dict(self.history_source_counts),
			"akshare_history": "open" if time.time() < self._ak_history_open_until else "healthy",
			"history_errors": list(self.history_errors[-10:]),
		}

	def _get_hithink_history(self, normalized: str, start: str, end: str) -> pd.DataFrame:
		client = HithinkClient()
		if not client.enabled:
			return pd.DataFrame()
		start_ms = int(datetime.strptime(start, "%Y%m%d").timestamp() * 1000)
		end_ms = int(datetime.strptime(end, "%Y%m%d").timestamp() * 1000)
		rows = client.historical(normalized, start_ms=start_ms, end_ms=end_ms)
		if not rows:
			return pd.DataFrame()
		df = pd.DataFrame(rows)
		if "date" in df.columns:
			unit = "ms" if pd.api.types.is_numeric_dtype(df["date"]) else None
			df["date"] = pd.to_datetime(df["date"], errors="coerce", unit=unit).dt.tz_localize(None)
		return df

	def _get_baostock_history(self, normalized: str, start: str, end: str) -> pd.DataFrame:
		if bs is None or normalized.startswith(("8", "43", "92")):
			return pd.DataFrame()
		with _SESSION_LOCK:
			login = bs.login()
			if getattr(login, "error_code", "1") != "0":
				return pd.DataFrame()
			try:
				code = ("sh." if normalized.startswith(("5", "6", "9")) else "sz.") + normalized
				result = bs.query_history_k_data_plus(
					code, "date,open,high,low,close,volume,amount", start_date=f"{start[:4]}-{start[4:6]}-{start[6:]}",
					end_date=f"{end[:4]}-{end[4:6]}-{end[6:]}", frequency="d", adjustflag="2",
				)
				if getattr(result, "error_code", "1") != "0":
					return pd.DataFrame()
				rows = []
				while result.next():
					rows.append(result.get_row_data())
				return pd.DataFrame(rows, columns=result.fields)
			finally:
				bs.logout()

	def _get_mock_price_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
		"""生成模拟价格数据"""
		if start_date and len(start_date) == 8:
			start = datetime.strptime(start_date, "%Y%m%d")
		else:
			start = datetime.now() - timedelta(days=100)

		if end_date and len(end_date) == 8:
			end = datetime.strptime(end_date, "%Y%m%d")
		else:
			end = datetime.now()

		days = (end - start).days
		if days < 1:
			days = 100
			start = end - timedelta(days=100)

		np.random.seed(hash(symbol) % 2**32)
		base_price = 10 + np.random.random() * 90

		dates = pd.date_range(start=start, periods=days, freq="B")
		prices = base_price * (1 + np.cumsum(np.random.randn(len(dates)) * 0.02))

		return pd.DataFrame(
			{
				"date": dates,
				"open": prices * (1 + np.random.randn(len(dates)) * 0.01),
				"close": prices,
				"high": prices * (1 + np.abs(np.random.randn(len(dates)) * 0.02)),
				"low": prices * (1 - np.abs(np.random.randn(len(dates)) * 0.02)),
				"volume": np.random.randint(1000000, 10000000, len(dates)),
			}
		)

	def get_a_share_price(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
		"""获取A股历史价格"""
		if self.use_mock_data:
			return self._get_mock_price_data(symbol, start_date, end_date)

		normalized = _normalize_a_share_symbol(symbol)
		if not normalized:
			logger.warning(f"A-share symbol cannot be parsed: {symbol}")
			return pd.DataFrame()

		cache_key = f"a_price_{normalized}_{start_date}_{end_date}"
		cached = self.cache.get(cache_key)
		if cached:
			cached_time, cached_data = cached
			if datetime.now() - cached_time < timedelta(seconds=self.cache_duration):
				return cached_data

		start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
		end = end_date or datetime.now().strftime("%Y%m%d")

		# Prefer the official Financial-API when configured, then an independent
		# historical provider.  AKShare remains the final compatibility fallback.
		providers = []
		if time.time() >= self._hithink_history_open_until:
			providers.append(("hithink_financial_api", self._get_hithink_history))
		else:
			logger.warning("HiThink historical circuit open; skipping {}", normalized)
		providers.append(("baostock", self._get_baostock_history))
		for source, provider in providers:
			try:
				df = provider(normalized, start, end)
				if df is not None and not df.empty:
					if source == "hithink_financial_api":
						self._hithink_history_failures = 0
					self._record_history_source(source)
					self.cache[cache_key] = (datetime.now(), df)
					return df
			except Exception as e:
				if source == "hithink_financial_api":
					self._hithink_history_failures += 1
					if self._hithink_history_failures >= 3:
						self._hithink_history_open_until = time.time() + 900
				self.history_errors.append(f"{source}:{type(e).__name__}")
				logger.warning(f"Historical provider {provider.__name__} failed for {normalized}: {e}")

		if time.time() < self._ak_history_open_until:
			logger.warning(f"AKShare historical circuit open; skipping {normalized}")
			return pd.DataFrame()

		last_exc: Optional[Exception] = None
		for attempt in range(3):
			try:
				df = ak.stock_zh_a_hist(
					symbol=normalized,
					period="daily",
					start_date=start,
					end_date=end,
					adjust="qfq",
				)
				if df is None or df.empty:
					return pd.DataFrame()

				df = df.rename(
					columns={
						"日期": "date",
						"开盘": "open",
						"收盘": "close",
						"最高": "high",
						"最低": "low",
						"成交量": "volume",
						"成交额": "amount",
						"振幅": "amplitude",
						"涨跌幅": "change_pct",
						"涨跌额": "change",
					}
				)
				df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
				self.cache[cache_key] = (datetime.now(), df)
				self._ak_history_failures = 0
				self._record_history_source("akshare")
				return df
			except Exception as e:
				last_exc = e
				self._ak_history_failures += 1
				if self._ak_history_failures >= 2:
					self._ak_history_open_until = time.time() + self._ak_history_cooldown
					break
				time.sleep(0.6 * (attempt + 1))

		logger.warning(f"Failed to fetch A-share price {symbol} (normalized={normalized}): {last_exc}")
		self.history_errors.append(f"akshare:{type(last_exc).__name__ if last_exc else 'empty'}")
		return pd.DataFrame()

	def get_h_share_price(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
		"""获取港股历史价格"""
		if self.use_mock_data:
			return self._get_mock_price_data(symbol, start_date, end_date)

		normalized = _normalize_h_share_symbol(symbol)
		if not normalized:
			logger.warning(f"H-share symbol cannot be parsed: {symbol}")
			return pd.DataFrame()

		cache_key = f"h_price_{normalized}_{start_date}_{end_date}"
		cached = self.cache.get(cache_key)
		if cached:
			cached_time, cached_data = cached
			if datetime.now() - cached_time < timedelta(seconds=self.cache_duration):
				return cached_data

		start = start_date or (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
		end = end_date or datetime.now().strftime("%Y%m%d")

		last_exc: Optional[Exception] = None
		for attempt in range(3):
			try:
				df = ak.stock_hk_hist(
					symbol=normalized,
					period="daily",
					start_date=start,
					end_date=end,
				)
				if df is None or df.empty:
					return pd.DataFrame()

				df = df.rename(
					columns={
						"日期": "date",
						"开盘": "open",
						"收盘": "close",
						"最高": "high",
						"最低": "low",
						"成交量": "volume",
						"成交额": "amount",
					}
				)
				df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
				self.cache[cache_key] = (datetime.now(), df)
				return df
			except Exception as e:
				last_exc = e
				time.sleep(0.6 * (attempt + 1))

		logger.warning(f"Failed to fetch H-share price {symbol} (normalized={normalized}): {last_exc}")
		return pd.DataFrame()

	def get_ah_premium(self, a_symbol: str, h_symbol: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
		"""计算AH溢价率

		A股: CNY
		H股: HKD
		溢价率 = A / (H * HKD_CNY) - 1
		"""
		a_df = self.get_a_share_price(a_symbol, start_date, end_date)
		h_df = self.get_h_share_price(h_symbol, start_date, end_date)

		if a_df.empty or h_df.empty:
			return pd.DataFrame()

		a_df = a_df[["date", "close"]].rename(columns={"close": "a_close"})
		h_df = h_df[["date", "close"]].rename(columns={"close": "h_close"})

		merged = pd.merge(a_df, h_df, on="date", how="inner")
		if merged.empty:
			return pd.DataFrame()

		hkd_cny = self.get_hkd_cny_exchange_rate()
		merged["hkd_cny"] = hkd_cny
		merged["premium_pct"] = (merged["a_close"] / (merged["h_close"] * hkd_cny) - 1) * 100

		return merged[["date", "a_close", "h_close", "hkd_cny", "premium_pct"]]

	def get_hkd_cny_exchange_rate(self) -> float:
		"""获取港币兑人民币汇率 (cached)."""
		if self.use_mock_data:
			return 0.92

		if self._fx_cache:
			ts, rate = self._fx_cache
			if datetime.now() - ts < timedelta(seconds=self._fx_cache_ttl_seconds):
				return rate

		try:
			# Use a free endpoint that provides base HKD.
			url = "https://api.exchangerate-api.com/v4/latest/HKD"
			response = requests.get(url, timeout=10)
			if response.status_code == 200:
				data = response.json()
				rate = float(data.get("rates", {}).get("CNY", 0.92))
				self._fx_cache = (datetime.now(), rate)
				return rate
			return 0.92
		except Exception as e:
			logger.warning(f"Failed to fetch FX rate HKD->CNY: {e}")
			return 0.92

	def get_usd_cnh_exchange_rate(self) -> float:
		"""DEPRECATED: kept for compatibility. Use get_hkd_cny_exchange_rate."""
		return self.get_hkd_cny_exchange_rate()

	def clear_cache(self) -> None:
		"""清空缓存"""
		self.cache.clear()
		self._fx_cache = None

	def enable_mock_data(self) -> None:
		"""启用模拟数据"""
		self.use_mock_data = True


# 全局实例
price_fetcher = PriceFetcher()


def get_price_fetcher() -> PriceFetcher:
	return price_fetcher
