from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ReportStore:
	root_dir: Path

	@property
	def reports_dir(self) -> Path:
		p = self.root_dir / "data" / "daily_reports"
		p.mkdir(parents=True, exist_ok=True)
		return p

	def latest_path(self) -> Optional[Path]:
		paths = sorted(self.reports_dir.glob("report_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
		return paths[0] if paths else None

	def list_reports(self, limit: int = 30) -> list[Dict[str, Any]]:
		items: list[Dict[str, Any]] = []
		for p in sorted(self.reports_dir.glob("report_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
			st = p.stat()
			items.append(
				{
					"name": p.name,
					"path": str(p),
					"size": st.st_size,
					"modified_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
				}
			)
		return items

	def load_path(self, path: Path) -> Dict[str, Any]:
		return json.loads(path.read_text(encoding="utf-8"))

	def load_latest(self) -> Optional[Dict[str, Any]]:
		p = self.latest_path()
		return self.load_path(p) if p else None

	def load_by_date(self, yyyymmdd: str) -> Optional[Dict[str, Any]]:
		p = self.reports_dir / f"report_{yyyymmdd}.json"
		return self.load_path(p) if p.exists() else None

	def save(self, report: Dict[str, Any]) -> Path:
		date_str = datetime.now().strftime("%Y%m%d")
		path = self.reports_dir / f"report_{date_str}.json"
		path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

		# Also write a stable pointer for UIs
		latest = self.reports_dir / "latest.json"
		latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
		return path


def get_report_store() -> ReportStore:
	root = Path(__file__).resolve().parents[1]
	return ReportStore(root_dir=root)
