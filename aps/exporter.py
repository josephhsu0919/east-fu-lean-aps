from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from .metrics import kpis_to_frame


def export_schedule_excel(
    schedule_df: pd.DataFrame,
    kpis: dict[str, float],
    comparison_df: pd.DataFrame | None = None,
    metadata: dict[str, object] | None = None,
) -> bytes:
    output = BytesIO()
    if metadata is None:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            schedule_df.to_excel(writer, sheet_name="排程結果", index=False)
            kpis_to_frame(kpis).to_excel(writer, sheet_name="KPI", index=False)
            if comparison_df is not None and not comparison_df.empty:
                comparison_df.to_excel(writer, sheet_name="策略比較", index=False)
        return output.getvalue()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result_columns = [
            "指派機台",
            "排程順序",
            "工單編號",
            "產品",
            "品名",
            "規格",
            "數量",
            "指定優先",
            "最早可排日",
            "完成日",
            "結關日",
            "換模群組",
            "換模時間（小時）",
            "開始時間",
            "結束時間",
            "是否遲交",
            "狀態",
        ]
        available_columns = [col for col in result_columns if col in schedule_df.columns]
        schedule_df[available_columns].to_excel(writer, sheet_name="排程結果", index=False)

        scheduled = schedule_df[schedule_df.get("狀態", "") == "scheduled"].copy() if "狀態" in schedule_df.columns else schedule_df.copy()
        gantt_cols = [col for col in ["指派機台", "排程順序", "工單編號", "產品", "開始時間", "結束時間", "換模群組", "工單類型"] if col in scheduled.columns]
        scheduled[gantt_cols].sort_values([col for col in ["指派機台", "開始時間", "排程順序"] if col in scheduled.columns]).to_excel(writer, sheet_name="甘特圖", index=False)

        unscheduled = schedule_df[schedule_df.get("狀態", "") != "scheduled"].copy() if "狀態" in schedule_df.columns else pd.DataFrame()
        if not unscheduled.empty:
            unscheduled = unscheduled.assign(reason_not_scheduled=unscheduled["狀態"])
        unscheduled_cols = [col for col in ["工單編號", "產品", "數量", "完成日", "reason_not_scheduled"] if col in unscheduled.columns]
        (unscheduled[unscheduled_cols] if unscheduled_cols else pd.DataFrame(columns=["工單編號", "產品", "數量", "完成日", "reason_not_scheduled"])).to_excel(
            writer, sheet_name="未排工單", index=False
        )

        kpi_frame = kpis_to_frame(kpis)
        if metadata:
            metadata_frame = pd.DataFrame([{"指標": key, "值": value} for key, value in metadata.items()])
            kpi_frame = pd.concat([metadata_frame, kpi_frame], ignore_index=True)
        kpi_frame.to_excel(writer, sheet_name="KPI摘要", index=False)
        if comparison_df is not None and not comparison_df.empty:
            comparison_df.to_excel(writer, sheet_name="策略比較", index=False)
    return output.getvalue()


def export_schedule_package_zip(excel_bytes: bytes, gantt_html: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("EastFu_APS_Result.xlsx", excel_bytes)
        archive.writestr("EastFu_APS_Gantt.html", gantt_html.encode("utf-8"))
    return output.getvalue()
