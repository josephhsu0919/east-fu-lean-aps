from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .parser import clean_label, default_settings_frame


ERP_REQUIRED_COLUMNS = [
    "客戶單號",
    "製令單號",
    "品名",
    "規格",
    "預計產量",
    "產品品號",
    "單位",
    "計劃批號",
    "訂單單號",
    "客戶簡稱",
]


@dataclass(frozen=True)
class ImportSummary:
    total_rows: int
    ready_rows: int
    issue_rows: int
    issues: list[str]


@dataclass(frozen=True)
class ReadinessItem:
    message: str
    section: str
    action: str


@dataclass(frozen=True)
class ScheduleReadiness:
    blocking: list[ReadinessItem]
    warnings: list[ReadinessItem]

    @property
    def ready(self) -> bool:
        return not self.blocking


def _read_workbook(source: str | Path | BinaryIO) -> dict[str, pd.DataFrame]:
    return pd.read_excel(source, sheet_name=None, header=None, engine="openpyxl")


def _read_sheet(source: str | Path | BinaryIO, sheet_name: str, header: int = 0) -> pd.DataFrame:
    return pd.read_excel(source, sheet_name=sheet_name, header=header, engine="openpyxl")


def _find_header_row(raw: pd.DataFrame, expected_columns: list[str]) -> int:
    best_score = -1
    best_idx = 0
    expected = {clean_label(col) for col in expected_columns}
    for idx, row in raw.head(30).iterrows():
        labels = {clean_label(value) for value in row.tolist() if pd.notna(value)}
        score = len(labels & expected)
        if score > best_score:
            best_score = score
            best_idx = int(idx)
    return best_idx


def _enabled(frame: pd.DataFrame) -> pd.DataFrame:
    if "啟用" not in frame.columns:
        return frame.copy()
    return frame[frame["啟用"].fillna("是").astype(str).str.strip().isin(["是", "Y", "y", "yes", "YES", "1", "True", "true"])].copy()


def _clean_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [clean_label(col) for col in result.columns]
    return result.dropna(how="all").reset_index(drop=True)


def load_v2_master_data(source: str | Path | BinaryIO) -> dict[str, pd.DataFrame]:
    sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")
    cleaned = {clean_label(name): _clean_columns(frame) for name, frame in sheets.items()}

    product_master = _enabled(cleaned.get("產品主檔", pd.DataFrame()))
    rates = _enabled(cleaned.get("產品機台產速", pd.DataFrame()))
    machines = _enabled(cleaned.get("機台資料", pd.DataFrame()))
    setup = cleaned.get("換模設定", pd.DataFrame())
    initial_wip = cleaned.get("期初在製", pd.DataFrame())
    settings = cleaned.get("基本設定", pd.DataFrame())

    if "產品品號" in rates.columns and "產品品號" in product_master.columns:
        product_groups = product_master[["產品品號", "換模群組"]].drop_duplicates("產品品號")
        rates = rates.merge(product_groups, on="產品品號", how="left")

    if not setup.empty:
        setup = setup.rename(columns={"來源群組": "來源換模群組", "目標群組": "目標換模群組"})
        if "換模時間_分鐘" in setup.columns:
            setup["換模時間_分鐘"] = pd.to_numeric(setup["換模時間_分鐘"], errors="coerce")

    if not initial_wip.empty and "是否有期初在製" in initial_wip.columns:
        yes = initial_wip["是否有期初在製"].fillna("否").astype(str).str.strip().isin(["是", "Y", "y", "yes", "YES", "1", "True", "true"])
        initial_wip = initial_wip[yes].copy()

    return {
        "產品主檔": product_master,
        "產品機台產速": rates,
        "機台資料": machines,
        "換模設定": setup,
        "期初在製": initial_wip,
        "基本設定": settings,
    }


def detect_customs_closing_date(filename: str) -> pd.Timestamp | None:
    match = re.search(r"結關\s*(\d{4})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", filename)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    try:
        return pd.Timestamp(year=year, month=month, day=day)
    except ValueError:
        return None


def suggested_completion_date(filename: str, offset_days: int = 3) -> pd.Timestamp | None:
    closing = detect_customs_closing_date(filename)
    return closing - pd.Timedelta(days=offset_days) if closing is not None else None


def _parse_time_value(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return pd.Timestamp(year=2000, month=1, day=1, hour=int(value.hour), minute=int(value.minute), second=int(getattr(value, "second", 0)))
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(year=2000, month=1, day=1, hour=int(parsed.hour), minute=int(parsed.minute), second=int(parsed.second))


def _build_machine_daily_availability(
    machines: pd.DataFrame,
    schedule_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
    work_time_mode: str,
    daily_start_time: object = None,
    daily_end_time: object = None,
) -> pd.DataFrame:
    if work_time_mode == "24 小時連續排程" or machines.empty:
        return pd.DataFrame(columns=["機台", "可用開始", "可用結束"])
    if "機台" not in machines.columns:
        return pd.DataFrame(columns=["機台", "可用開始", "可用結束"])

    rows: list[dict[str, object]] = []
    days = pd.date_range(pd.Timestamp(schedule_start).normalize(), pd.Timestamp(horizon_end).normalize(), freq="D")
    global_start_time = _parse_time_value(daily_start_time)
    global_end_time = _parse_time_value(daily_end_time)
    for _, machine_row in machines.iterrows():
        machine = str(machine_row.get("機台", "")).strip()
        start_time = global_start_time or _parse_time_value(machine_row.get("每日開始時間"))
        end_time = global_end_time or _parse_time_value(machine_row.get("每日結束時間"))
        if not machine or start_time is None or end_time is None:
            continue
        for day in days:
            available_start = pd.Timestamp(day) + pd.Timedelta(hours=start_time.hour, minutes=start_time.minute, seconds=start_time.second)
            available_end = pd.Timestamp(day) + pd.Timedelta(hours=end_time.hour, minutes=end_time.minute, seconds=end_time.second)
            if available_end <= available_start:
                available_end += pd.Timedelta(days=1)
            available_start = max(available_start, pd.Timestamp(schedule_start))
            available_end = min(available_end, pd.Timestamp(horizon_end))
            if available_start < available_end:
                rows.append({"機台": machine, "可用開始": available_start, "可用結束": available_end})
    return pd.DataFrame(rows, columns=["機台", "可用開始", "可用結束"])


def parse_release_date(work_order_id: object) -> pd.Timestamp | None:
    text = re.sub(r"\D", "", str(work_order_id).strip())
    if len(text) < 8:
        return None
    try:
        return pd.Timestamp(year=int(text[:4]), month=int(text[4:6]), day=int(text[6:8]))
    except ValueError:
        return None


def load_east_fu_erp_orders(source: str | Path | BinaryIO, filename: str = "") -> tuple[pd.DataFrame, int]:
    workbook = _read_workbook(source)
    sheet_name = "單頭資料" if "單頭資料" in workbook else next(iter(workbook))
    raw = workbook[sheet_name]
    header = _find_header_row(raw, ERP_REQUIRED_COLUMNS)
    frame = _clean_columns(_read_sheet(source, sheet_name, header=header))
    missing = [col for col in ERP_REQUIRED_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"ERP 檔缺少必要欄位：{', '.join(missing)}")

    orders = pd.DataFrame(
        {
            "work_order_id": frame["製令單號"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip(),
            "product_id": frame["產品品號"].astype(str).str.strip(),
            "product_name": frame["品名"].astype(str).str.strip(),
            "specification": frame["規格"].astype(str).str.strip(),
            "quantity": pd.to_numeric(frame["預計產量"], errors="coerce"),
            "unit": frame["單位"].astype(str).str.strip(),
            "customer_order_no": frame["客戶單號"].astype(str).str.strip(),
            "customer_name": frame["客戶簡稱"].astype(str).str.strip(),
            "sales_order_no": frame["訂單單號"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip(),
            "planning_batch_no": frame["計劃批號"].astype(str).str.strip(),
            "source_row": frame.index + header + 2,
            "source_filename": filename,
        }
    )
    orders["release_date"] = orders["work_order_id"].map(parse_release_date)
    orders["customs_closing_date"] = detect_customs_closing_date(filename)
    orders["suggested_completion_date"] = suggested_completion_date(filename)
    orders["completion_date"] = orders["suggested_completion_date"]
    orders["manual_priority"] = False
    return orders, header + 1


def validate_v2_orders(orders: pd.DataFrame, master_data: dict[str, pd.DataFrame]) -> tuple[ImportSummary, pd.DataFrame]:
    frame = orders.copy()
    frame["問題"] = ""
    product_master = master_data.get("產品主檔", pd.DataFrame())
    rates = master_data.get("產品機台產速", pd.DataFrame())
    products = set(product_master.get("產品品號", pd.Series(dtype=str)).dropna().astype(str))
    valid_rates = rates.copy()
    if not valid_rates.empty:
        valid_rates["產速_PCS_per_hr"] = pd.to_numeric(valid_rates.get("產速_PCS_per_hr"), errors="coerce")
        valid_rates = valid_rates.dropna(subset=["產品品號", "機台", "產速_PCS_per_hr"])
        valid_rates = valid_rates[valid_rates["產速_PCS_per_hr"] > 0]
    rated_products = set(valid_rates.get("產品品號", pd.Series(dtype=str)).dropna().astype(str))

    duplicate = frame["work_order_id"].duplicated(keep=False)
    for idx, row in frame.iterrows():
        issues: list[str] = []
        if not str(row.get("work_order_id", "")).strip() or str(row.get("work_order_id")) == "nan":
            issues.append("缺少製令單號")
        if duplicate.loc[idx]:
            issues.append("製令單號重複")
        if pd.isna(row.get("release_date")):
            issues.append("製令單號無法解析最早可排日")
        if not str(row.get("product_id", "")).strip() or str(row.get("product_id")) == "nan":
            issues.append("缺少產品品號")
        elif str(row["product_id"]) not in products:
            issues.append("產品品號不在 Master Data")
        elif str(row["product_id"]) not in rated_products:
            issues.append("產品沒有有效機台產速")
        if pd.isna(row.get("quantity")) or float(row.get("quantity") or 0) <= 0:
            issues.append("預計產量必須大於 0")
        if not str(row.get("unit", "")).strip() or str(row.get("unit")) == "nan":
            issues.append("缺少單位")
        if pd.isna(row.get("completion_date")):
            issues.append("缺少完成日")
        elif pd.notna(row.get("release_date")) and pd.Timestamp(row["completion_date"]) < pd.Timestamp(row["release_date"]):
            issues.append("完成日早於最早可排日")
        frame.at[idx, "問題"] = "；".join(issues)

    issue_rows = int((frame["問題"] != "").sum())
    summary = ImportSummary(
        total_rows=int(len(frame)),
        ready_rows=int(len(frame) - issue_rows),
        issue_rows=issue_rows,
        issues=sorted({part for text in frame["問題"] for part in str(text).split("；") if part}),
    )
    return summary, frame


def assess_v2_schedule_readiness(
    *,
    master_data: dict[str, pd.DataFrame] | None,
    orders: pd.DataFrame | None,
    summary: ImportSummary | None,
    validated_orders: pd.DataFrame | None,
    selected_machines: list[str] | None,
    schedule_start: object,
    horizon_end: object,
) -> ScheduleReadiness:
    blocking: list[ReadinessItem] = []
    warnings: list[ReadinessItem] = []

    if not master_data:
        blocking.append(ReadinessItem("尚未載入 V2 Master Data / 生產設定。", "1. 載入 V2 Master Data / 生產設定", "前往上傳 Master Data Excel"))
    if orders is None or orders.empty:
        blocking.append(ReadinessItem("尚未上傳 East Fu ERP 製令 Excel。", "2. 上傳 East Fu ERP 製令 Excel", "前往上傳 ERP 製令 Excel"))

    start = pd.to_datetime(schedule_start, errors="coerce")
    end = pd.to_datetime(horizon_end, errors="coerce")
    if pd.isna(start):
        blocking.append(ReadinessItem("尚未設定有效的排程開始時間。", "排程條件", "前往設定 V2 排程開始日期與時間"))
    if pd.isna(end):
        blocking.append(ReadinessItem("尚未設定有效的排程期間。", "排程條件", "前往設定 V2 排程期間"))
    if pd.notna(start) and pd.notna(end) and end <= start:
        blocking.append(ReadinessItem("排程結束時間必須晚於排程開始時間。", "排程條件", "前往調整 V2 排程期間"))

    if not selected_machines:
        blocking.append(ReadinessItem("尚未選擇本次排程機台。", "排程條件", "前往選擇本次排程機台"))

    if validated_orders is not None and not validated_orders.empty:
        problem_mask = validated_orders.get("問題", pd.Series("", index=validated_orders.index)).fillna("").astype(str) != ""
        problem_rows = int(problem_mask.sum())
        if problem_rows:
            problem_text = validated_orders.loc[problem_mask, "問題"].fillna("").astype(str)
            missing_rate_mask = problem_text.str.contains("產品沒有有效機台產速", regex=False)
            missing_rate_products = int(validated_orders.loc[problem_mask & missing_rate_mask, "product_id"].dropna().astype(str).nunique())
            if missing_rate_products:
                blocking.append(
                    ReadinessItem(
                        f"{missing_rate_products} 個產品尚未建立有效機台/產速。",
                        "產品機台產速",
                        "前往「產品機台產速」分頁補齊產品、機台、產速_PCS_per_hr",
                    )
                )

            missing_completion = int(problem_text.str.contains("缺少完成日", regex=False).sum())
            if missing_completion:
                blocking.append(ReadinessItem(f"{missing_completion} 筆工單尚未確認完成日。", "確認完成日 / 工單清單", "前往確認完成日"))

            missing_completion_mask = problem_text.str.contains("缺少完成日", regex=False)
            other_issue_rows = int((~missing_rate_mask & ~missing_completion_mask).sum())
            if other_issue_rows > 0:
                blocking.append(ReadinessItem(f"{other_issue_rows} 筆工單資料驗證失敗。", "ERP 工單驗證結果", "前往問題列查看並修正"))

    elif summary is not None and summary.issue_rows:
        blocking.append(ReadinessItem(f"{summary.issue_rows} 筆工單資料驗證失敗。", "ERP 工單驗證結果", "前往問題列查看並修正"))

    if selected_machines and master_data:
        rates = master_data.get("產品機台產速", pd.DataFrame()).copy()
        if not rates.empty and "機台" in rates.columns:
            rate_machines = set(rates["機台"].dropna().astype(str))
            selected_without_rates = [machine for machine in selected_machines if str(machine) not in rate_machines]
            if selected_without_rates:
                warnings.append(
                    ReadinessItem(
                        f"{len(selected_without_rates)} 台已選機台目前沒有任何產速資料：{', '.join(selected_without_rates)}。",
                        "產品機台產速",
                        "可排程，但這些機台不會被分配工單；需要時請補產速",
                    )
                )

    return ScheduleReadiness(blocking=blocking, warnings=warnings)


def build_scheduler_workbook(
    orders: pd.DataFrame,
    master_data: dict[str, pd.DataFrame],
    schedule_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
    work_time_mode: str = "每日固定工時",
    daily_start_time: object = "08:00",
    daily_end_time: object = "20:00",
) -> dict[str, pd.DataFrame]:
    product_master = master_data["產品主檔"].copy()
    rates = master_data["產品機台產速"].copy()
    machines = master_data.get("機台資料", pd.DataFrame()).copy()
    setup = master_data.get("換模設定", pd.DataFrame()).copy()
    initial_wip = master_data.get("期初在製", pd.DataFrame()).copy()
    machine_available_from = master_data.get("機台可排起始時間", pd.DataFrame()).copy()

    group_lookup = product_master.dropna(subset=["產品品號"]).drop_duplicates("產品品號").set_index("產品品號").get("換模群組", pd.Series(dtype=object)).to_dict()
    due = pd.to_datetime(orders["completion_date"], errors="coerce")
    due = due.dt.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    scheduler_orders = pd.DataFrame(
        {
            "工單編號": orders["work_order_id"],
            "產品": orders["product_id"],
            "品名": orders["product_name"],
            "規格": orders["specification"],
            "數量": orders["quantity"],
            "單位": orders["unit"],
            "優先級": orders["manual_priority"].map(lambda value: "急單" if bool(value) else "一般"),
            "指定優先": orders["manual_priority"].astype(bool),
            "交期": due,
            "完成日": due,
            "最早可排日": pd.to_datetime(orders["release_date"], errors="coerce"),
            "結關日": pd.to_datetime(orders["customs_closing_date"], errors="coerce"),
            "客戶單號": orders["customer_order_no"],
            "客戶簡稱": orders["customer_name"],
            "訂單單號": orders["sales_order_no"],
            "計劃批號": orders["planning_batch_no"],
            "_原始順序": range(1, len(orders) + 1),
        }
    )
    rates = rates.rename(columns={"產品品號": "產品"})
    if "換模群組" not in rates.columns:
        rates["換模群組"] = rates["產品"].map(group_lookup)
    rates["產速_PCS_per_hr"] = pd.to_numeric(rates["產速_PCS_per_hr"], errors="coerce")
    rates = rates.dropna(subset=["產品", "機台", "產速_PCS_per_hr"])
    rates = rates[rates["產速_PCS_per_hr"] > 0].copy()

    if not setup.empty:
        setup = setup.rename(columns={"來源群組": "來源換模群組", "目標群組": "目標換模群組"})
        setup = setup[["來源換模群組", "目標換模群組", "換模時間_分鐘"]].dropna(subset=["來源換模群組", "目標換模群組", "換模時間_分鐘"])
    else:
        setup = pd.DataFrame(columns=["來源換模群組", "目標換模群組", "換模時間_分鐘"])

    settings = default_settings_frame(schedule_start, horizon_end)
    return {
        "待排工單": scheduler_orders,
        "產品機台產速": rates,
        "機台可用時間": _build_machine_daily_availability(machines, schedule_start, horizon_end, work_time_mode, daily_start_time, daily_end_time),
        "換模時間": setup,
        "期初在製": initial_wip,
        "機台可排起始時間": machine_available_from,
        "排程基本設定": settings,
    }
