from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from .metrics import kpis_to_frame


def export_schedule_excel(schedule_df: pd.DataFrame, kpis: dict[str, float], comparison_df: pd.DataFrame | None = None) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        schedule_df.to_excel(writer, sheet_name="排程結果", index=False)
        kpis_to_frame(kpis).to_excel(writer, sheet_name="KPI", index=False)
        if comparison_df is not None and not comparison_df.empty:
            comparison_df.to_excel(writer, sheet_name="策略比較", index=False)
    return output.getvalue()


def export_schedule_package_zip(excel_bytes: bytes, gantt_html: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("EastFu_APS_Result.xlsx", excel_bytes)
        archive.writestr("EastFu_APS_Gantt.html", gantt_html.encode("utf-8"))
    return output.getvalue()
