# 导出API端点
# ==========

from __future__ import annotations

import os
import uuid
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ah_recommendation_system.backend.api.models import (
    ExportRequest,
    ExportResponse,
)
from ah_recommendation_system.backend.config import EXPORT_CONFIG
from ah_recommendation_system.backend.reporting.report_store import (
    get_report_store,
)

router = APIRouter(prefix="/api/v1/export", tags=["export"])


def get_export_dir() -> str:
    """获取导出目录"""
    export_dir = EXPORT_CONFIG["export_dir"]
    os.makedirs(export_dir, exist_ok=True)
    return export_dir


def _to_df(value) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, list):
        return pd.DataFrame(value)
    if isinstance(value, dict):
        # Flatten common shapes
        if "recommendations" in value and isinstance(value["recommendations"], list):
            return pd.DataFrame(value["recommendations"])
        if "predictions" in value and isinstance(value["predictions"], list):
            return pd.DataFrame(value["predictions"])
        if "signals" in value and isinstance(value["signals"], dict):
            rows = []
            for k, arr in value["signals"].items():
                if isinstance(arr, list):
                    for item in arr:
                        row = dict(item)
                        row["signal_bucket"] = k
                        rows.append(row)
            return pd.DataFrame(rows)
        return pd.DataFrame([value])
    return pd.DataFrame()


@router.post("/", response_model=ExportResponse)
async def export_data(request: ExportRequest):
    """导出数据（默认从已落盘的 latest report 导出）"""
    try:
        store = get_report_store()
        report = (
            store.load_by_date(request.date) if request.date else store.load_latest()
        )
        if not report:
            return ExportResponse(
                success=False,
                file_path=None,
                message="没有可导出的数据：未找到已生成的报告。请先运行 run_daily_job.py",
                download_url=None,
            )

        export_dir = get_export_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_id = str(uuid.uuid4())[:8]

        frames = []
        sheets = []

        def add_sheet(title: str, payload):
            df = _to_df(payload)
            if not df.empty:
                frames.append(df)
                sheets.append(title)

        if request.data_type in ["pair_trading", "all"]:
            add_sheet("pair_trading", report.get("pair_trading"))
        if request.data_type in ["multi_factor", "all"]:
            add_sheet("multi_factor", report.get("multi_factor"))
        if request.data_type in ["ml_prediction", "all"]:
            add_sheet("ml_prediction", report.get("ml_prediction"))
        if request.data_type in ["etf_trend", "all"]:
            add_sheet("etf_trend", ((report.get("etf_sector") or {}).get("etf_trend")))

        if not frames:
            return ExportResponse(
                success=False,
                file_path=None,
                message="没有可导出的数据：报告中无对应类型内容",
                download_url=None,
            )

        if request.format == "xlsx":
            file_name = f"ah_report_{timestamp}_{file_id}.xlsx"
            file_path = os.path.join(export_dir, file_name)
            with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
                for df, sheet_name in zip(frames, sheets):
                    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        elif request.format == "csv":
            file_name = f"ah_report_{timestamp}_{file_id}.csv"
            file_path = os.path.join(export_dir, file_name)
            combined_df = pd.concat(frames, ignore_index=True)
            combined_df.to_csv(file_path, index=False, encoding="utf-8-sig")
        else:
            raise ValueError(f"不支持的格式: {request.format}")

        return ExportResponse(
            success=True,
            file_path=file_path,
            message=f"导出成功: {file_name}",
            download_url=f"/api/v1/export/download/{file_name}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{file_name}")
async def download_file(file_name: str):
    """下载导出文件"""
    try:
        export_dir = get_export_dir()
        file_path = os.path.join(export_dir, file_name)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(
            path=file_path, filename=file_name, media_type="application/octet-stream"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_exported_files():
    """列出已导出的文件"""
    try:
        export_dir = get_export_dir()
        files = []
        for f in os.listdir(export_dir):
            if f.endswith((".xlsx", ".csv", ".pdf")):
                file_path = os.path.join(export_dir, f)
                stat = os.stat(file_path)
                files.append(
                    {
                        "name": f,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_ctime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )

        return {
            "success": True,
            "files": sorted(files, key=lambda x: x["created"], reverse=True),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
