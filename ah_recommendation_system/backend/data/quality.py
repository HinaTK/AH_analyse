from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd


@dataclass(frozen=True)
class DataQuality:
	ok: bool
	reason: str
	rows: int
	latest_date: str

	def to_dict(self) -> Dict:
		return {
			"ok": self.ok,
			"reason": self.reason,
			"rows": self.rows,
			"latest_date": self.latest_date,
		}


def assess_price_frame(df: pd.DataFrame, min_rows: int = 15) -> DataQuality:
	if df is None or df.empty:
		return DataQuality(ok=False, reason="empty", rows=0, latest_date="")

	rows = int(len(df))
	latest = ""
	if "date" in df.columns and rows > 0:
		try:
			latest = pd.to_datetime(df.iloc[-1]["date"]).strftime("%Y-%m-%d")
		except Exception:
			latest = str(df.iloc[-1]["date"])

	if rows < min_rows:
		return DataQuality(ok=False, reason=f"insufficient_rows<{min_rows}", rows=rows, latest_date=latest)

	return DataQuality(ok=True, reason="ok", rows=rows, latest_date=latest)
