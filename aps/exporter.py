from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .metrics import kpis_to_frame


HEADER_FILL = "1F4E78"
HEADER_FONT = "FFFFFF"


def _number_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _format_workbook(writer: pd.ExcelWriter) -> None:
    workbook = writer.book
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=False)
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
            cell.font = Font(color=HEADER_FONT, bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for column_cells in sheet.columns:
            values = [str(cell.value) for cell in column_cells if cell.value is not None]
            width = min(max([len(value) for value in values] + [10]) + 2, 42)
            sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if "時間" in str(sheet.cell(1, cell.column).value or "") or "日期" in str(sheet.cell(1, cell.column).value or ""):
                    cell.number_format = "yyyy/mm/dd hh:mm"
        sheet.auto_filter.ref = sheet.dimensions


def _friendly_schedule(schedule_df: pd.DataFrame) -> pd.DataFrame:
    frame = schedule_df.copy()
    if "換模時間（小時）" in frame.columns:
        frame["換模時間（分）"] = (pd.to_numeric(frame["換模時間（小時）"], errors="coerce").fillna(0) * 60).round(0)
    rename = {
        "指派機台": "產線",
        "排程順序": "順序",
        "工單編號": "製令單號",
        "產品": "產品品號",
        "品名": "品名",
        "規格": "規格",
        "數量": "數量",
        "指定優先": "指定優先",
        "最早可排日": "最早可排日",
        "完成日": "確認完成日",
        "結關日": "結關日",
        "換模群組": "換模群組",
        "開始時間": "開始時間",
        "結束時間": "結束時間",
        "加工時間（小時）": "加工時間（小時）",
        "換模時間（分）": "換模時間（分）",
        "是否遲交": "是否遲交",
        "遲交時間（小時）": "遲交時間（小時）",
        "狀態": "狀態",
    }
    columns = [col for col in rename if col in frame.columns]
    result = frame[columns].rename(columns=rename)
    sort_cols = [col for col in ["產線", "開始時間", "順序"] if col in result.columns]
    return result.sort_values(sort_cols, kind="mergesort") if sort_cols else result


def _line_summary(schedule_df: pd.DataFrame) -> pd.DataFrame:
    scheduled = schedule_df[schedule_df.get("狀態", "") == "scheduled"].copy() if "狀態" in schedule_df.columns else schedule_df.copy()
    if scheduled.empty or "指派機台" not in scheduled.columns:
        return pd.DataFrame(columns=["產線", "工單數", "急單數", "總數量", "加工小時", "換模分鐘", "最早開始", "最晚結束"])
    priority = scheduled["優先級"] if "優先級" in scheduled.columns else scheduled.get("指定優先", False)
    scheduled["急單旗標"] = pd.Series(priority, index=scheduled.index).astype(str).isin(["急單", "True", "true", "1", "是"])
    scheduled["數量_摘要"] = _number_series(scheduled, "數量")
    scheduled["加工小時_摘要"] = _number_series(scheduled, "加工時間（小時）")
    scheduled["換模小時_摘要"] = _number_series(scheduled, "換模時間（小時）")
    summary = scheduled.groupby("指派機台", dropna=False).agg(
        工單數=("工單編號", "count"),
        急單數=("急單旗標", "sum"),
        總數量=("數量_摘要", "sum"),
        加工小時=("加工小時_摘要", "sum"),
        換模小時=("換模小時_摘要", "sum"),
        最早開始=("開始時間", "min"),
        最晚結束=("結束時間", "max"),
    ).reset_index()
    summary["換模分鐘"] = (summary.pop("換模小時").fillna(0) * 60).round(0)
    summary = summary.rename(columns={"指派機台": "產線"})
    columns = ["產線", "工單數", "急單數", "總數量", "加工小時", "換模分鐘", "最早開始", "最晚結束"]
    return summary[columns].sort_values("產線")


def _daily_line_summary(schedule_df: pd.DataFrame) -> pd.DataFrame:
    scheduled = schedule_df[schedule_df.get("狀態", "") == "scheduled"].copy() if "狀態" in schedule_df.columns else schedule_df.copy()
    if scheduled.empty or not {"指派機台", "開始時間"}.issubset(scheduled.columns):
        return pd.DataFrame(columns=["日期", "產線", "工單數", "總數量", "加工小時", "換模分鐘"])
    scheduled["日期"] = pd.to_datetime(scheduled["開始時間"], errors="coerce").dt.date
    scheduled["數量_摘要"] = _number_series(scheduled, "數量")
    scheduled["加工小時_摘要"] = _number_series(scheduled, "加工時間（小時）")
    scheduled["換模小時_摘要"] = _number_series(scheduled, "換模時間（小時）")
    summary = scheduled.groupby(["日期", "指派機台"], dropna=False).agg(
        工單數=("工單編號", "count"),
        總數量=("數量_摘要", "sum"),
        加工小時=("加工小時_摘要", "sum"),
        換模小時=("換模小時_摘要", "sum"),
    ).reset_index()
    summary["換模分鐘"] = (summary.pop("換模小時").fillna(0) * 60).round(0)
    return summary.rename(columns={"指派機台": "產線"}).sort_values(["日期", "產線"])


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
        scheduled = schedule_df[schedule_df.get("狀態", "") == "scheduled"].copy() if "狀態" in schedule_df.columns else schedule_df.copy()

        guide = pd.DataFrame(
            [
                {"項目": "建議閱讀順序", "說明": "先看排程總覽，再看每日產線摘要，最後依 C2/C4/C5 分頁確認各產線工單。"},
                {"項目": "指定優先", "說明": "True 代表人工指定優先排程。"},
                {"項目": "換模時間（分）", "說明": "由換模設定換算成分鐘，方便現場閱讀。"},
                {"項目": "未排工單", "說明": "若有資料，代表超出期間或沒有合格機台/產速。"},
            ]
        )
        guide.to_excel(writer, sheet_name="閱讀說明", index=False)

        metadata_frame = pd.DataFrame([{"項目": key, "內容": value} for key, value in metadata.items()])
        kpi_frame = kpis_to_frame(kpis).rename(columns={"KPI": "項目", "數值": "內容"})
        metadata_frame.to_excel(writer, sheet_name="排程總覽", index=False, startrow=0)
        kpi_frame.to_excel(writer, sheet_name="排程總覽", index=False, startrow=len(metadata_frame) + 3)
        _line_summary(schedule_df).to_excel(writer, sheet_name="產線總覽", index=False)
        _daily_line_summary(schedule_df).to_excel(writer, sheet_name="每日產線摘要", index=False)

        available_columns = [col for col in result_columns if col in schedule_df.columns]
        schedule_df[available_columns].to_excel(writer, sheet_name="排程結果", index=False)

        friendly = _friendly_schedule(schedule_df)
        friendly.to_excel(writer, sheet_name="全部排程明細", index=False)
        if "產線" in friendly.columns:
            for machine, machine_frame in friendly.groupby("產線", dropna=False):
                sheet_name = str(machine)[:28] if pd.notna(machine) else "未指定產線"
                machine_frame.to_excel(writer, sheet_name=sheet_name, index=False)

        gantt_cols = [col for col in ["指派機台", "排程順序", "工單編號", "產品", "開始時間", "結束時間", "換模群組", "工單類型"] if col in scheduled.columns]
        scheduled[gantt_cols].sort_values([col for col in ["指派機台", "開始時間", "排程順序"] if col in scheduled.columns]).to_excel(writer, sheet_name="甘特圖資料", index=False)

        unscheduled = schedule_df[schedule_df.get("狀態", "") != "scheduled"].copy() if "狀態" in schedule_df.columns else pd.DataFrame()
        if not unscheduled.empty:
            unscheduled = unscheduled.assign(reason_not_scheduled=unscheduled["狀態"])
        unscheduled_cols = [col for col in ["工單編號", "產品", "品名", "數量", "完成日", "reason_not_scheduled"] if col in unscheduled.columns]
        unscheduled_export = unscheduled[unscheduled_cols].rename(columns={"產品": "產品品號", "reason_not_scheduled": "未排原因"}) if unscheduled_cols else pd.DataFrame(columns=["工單編號", "產品品號", "數量", "完成日", "未排原因"])
        unscheduled_export.to_excel(
            writer, sheet_name="未排工單", index=False
        )

        kpis_to_frame(kpis).to_excel(writer, sheet_name="KPI摘要", index=False)
        if comparison_df is not None and not comparison_df.empty:
            comparison_df.to_excel(writer, sheet_name="策略比較", index=False)
        _format_workbook(writer)
    return output.getvalue()


def export_schedule_package_zip(excel_bytes: bytes, gantt_html: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("EastFu_APS_Result.xlsx", excel_bytes)
        archive.writestr("EastFu_APS_Gantt.html", gantt_html.encode("utf-8"))
    return output.getvalue()
