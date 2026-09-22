from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, time
from io import BytesIO
from inspect import signature
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from aps.calendar import build_calendar_unavailability, parse_non_working_dates
from aps.comparator import compare_strategies, recommend_strategy
from aps.exporter import export_schedule_excel
from aps.history import create_schedule_version, load_history, version_orders_frame, version_schedule_frame
from aps.manual import answer_from_manual, manual_text
from aps.metrics import calculate_kpis, kpis_to_frame
from aps.parser import clean_label, get_schedule_window, load_workbook
from aps.project_store import frame_to_records, list_projects, load_project, load_project_bytes, project_to_bytes, records_to_frame, save_project
from aps.sample_data import write_demo_excel
from aps.scheduler import MACHINES, schedule
from aps.strategies import STRATEGIES
from aps.validator import validate_workbook
from aps.v2_adapter import assess_v2_schedule_readiness, build_scheduler_workbook, load_east_fu_erp_orders, load_v2_master_data, validate_v2_orders
from ui.charts import comparison_bar
from ui.gantt import make_gantt


PROJECT_ROOT = Path(__file__).resolve().parent
DEMO_EXCEL_PATH = PROJECT_ROOT / "data" / "EastFu_Lean_APS_Demo.xlsx"
MAIN_STRATEGIES = ["rush_edd", "edd", "fifo", "spt", "changeover"]
HORIZON_HOURS = {"24 小時": 24, "48 小時": 48, "72 小時": 72, "一週": 168}


st.set_page_config(page_title="東福精實生產排程系統", page_icon="EF", layout="wide")
st.markdown(
    """
    <style>
    html, body, [class*="css"] { font-size: 18px; }
    .stButton button, .stDownloadButton button { font-size: 20px; font-weight: 700; min-height: 3rem; }
    .stButton button[kind="primary"] { background: #ff464d; border-color: #ff464d; box-shadow: 0 8px 18px rgba(255,70,77,.22); }
    .stButton button:disabled { background: #e5e7eb !important; border-color: #d1d5db !important; color: #6b7280 !important; box-shadow: none !important; }
    div[data-testid="stMetricValue"] { font-size: 2.2rem; }
    h1 { font-size: 2.6rem; }
    h2, h3 { font-size: 1.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state() -> None:
    default_start = pd.Timestamp.now(tz="Asia/Taipei").tz_localize(None).normalize() + pd.Timedelta(hours=8)
    defaults = {
        "workbook": None,
        "validation": None,
        "schedule_df": None,
        "kpis": None,
        "comparison_df": None,
        "selected_strategy": "rush_edd",
        "upload_filename": "demo",
        "horizon_mode": "24 小時",
        "schedule_start": default_start,
        "custom_start": default_start,
        "custom_end": default_start + pd.Timedelta(hours=24),
        "changeover_minutes": 30,
        "selected_machines": MACHINES.copy(),
        "capacity_mode": "正常產能（100%）",
        "custom_capacity_percent": 100,
        "unavailability": pd.DataFrame(columns=["機台", "不可用開始", "不可用結束", "原因"]),
        "work_time_mode": "24 小時連續排程",
        "workday_start_time": time(8, 0),
        "daily_work_hours": 8,
        "exclude_weekends": False,
        "non_working_dates": "",
        "assistant_question": "",
        "last_version": None,
        "v2_master_data": None,
        "v2_orders": None,
        "v2_orders_validated": None,
        "v2_import_summary": None,
        "v2_header_row": None,
        "v2_schedule_df": None,
        "v2_kpis": None,
        "v2_workbook": None,
        "v2_erp_filename": "",
        "v2_project_name": "2026W39_ProductionSchedule",
        "v2_planning_mode": "本批最晚結關日",
        "v2_custom_horizon_end": default_start + pd.Timedelta(days=14),
        "v2_execution_window_hours": 48,
        "v2_work_time_mode": "24 小時連續排程",
        "v2_daily_start_time": time(8, 0),
        "v2_daily_end_time": time(20, 0),
        "v2_strategy_preset": "東福標準",
        "v2_priority_order": ["指定優先", "完成日", "減少換模"],
        "v2_lock_execution_window": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def valid_data() -> dict[str, pd.DataFrame] | None:
    validation = st.session_state.validation
    if validation is None:
        return None
    ok, _, data = validation
    return data if ok else None


def horizon_window(data: dict[str, pd.DataFrame]) -> tuple[pd.Timestamp, pd.Timestamp]:
    mode = st.session_state.horizon_mode
    if mode == "自訂":
        return pd.Timestamp(st.session_state.custom_start), pd.Timestamp(st.session_state.custom_end)
    base_start = pd.Timestamp(st.session_state.schedule_start)
    return base_start, base_start + pd.to_timedelta(HORIZON_HOURS[mode], unit="h")


def upsert_setting(settings: pd.DataFrame, item: str, value: object) -> pd.DataFrame:
    result = settings.copy()
    if "設定項目" not in result.columns or "設定值" not in result.columns:
        result = pd.DataFrame(columns=["設定項目", "設定值"])
    mask = result["設定項目"] == item
    if mask.any():
        result.loc[mask, "設定值"] = value
    else:
        result = pd.concat([result, pd.DataFrame([[item, value]], columns=["設定項目", "設定值"])], ignore_index=True)
    return result


def with_horizon_settings(data: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    copied = {name: frame.copy() for name, frame in data.items()}
    settings = copied["排程基本設定"].copy()
    settings = upsert_setting(settings, "排程開始", start)
    settings = upsert_setting(settings, "排程結束", end)
    settings = upsert_setting(settings, "時區", "Asia/Taipei")
    copied["排程基本設定"] = settings
    return copied


def capacity_factor() -> float:
    if st.session_state.capacity_mode == "人力不足（80%）":
        return 0.8
    if st.session_state.capacity_mode == "嚴重不足（60%）":
        return 0.6
    if st.session_state.capacity_mode == "自訂":
        return float(st.session_state.custom_capacity_percent) / 100
    return 1.0


def apply_run_constraints(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame] | None:
    selected_machines = [machine for machine in st.session_state.selected_machines if machine in MACHINES]
    if not selected_machines:
        st.error("請至少選擇一台本次排程使用機台。")
        return None
    copied = {name: frame.copy() for name, frame in data.items()}
    rates = copied["產品機台產速"].copy()
    rates = rates[rates["機台"].astype(str).isin(selected_machines)].copy()
    if rates.empty:
        st.error("本次選擇的機台沒有任何產品產速資料，請調整機台選擇或產品機台產速表。")
        return None
    factor = capacity_factor()
    rates["產速_PCS_per_hr"] = pd.to_numeric(rates["產速_PCS_per_hr"], errors="coerce") * factor
    copied["產品機台產速"] = rates
    return copied


def apply_workbook_defaults(data: dict[str, pd.DataFrame]) -> None:
    start, end, _ = get_schedule_window(data["排程基本設定"])
    if pd.notna(start):
        st.session_state.schedule_start = pd.Timestamp(start)
        st.session_state.custom_start = pd.Timestamp(start)
    if pd.notna(end):
        st.session_state.custom_end = pd.Timestamp(end)


def has_timing_defaults(workbook: dict[str, pd.DataFrame]) -> bool:
    sheet_names = {clean_label(name) for name in workbook}
    return bool({"排程基本設定", "機台可用時間"} & sheet_names)


def render_kpis(kpis: dict[str, float]) -> None:
    cols = st.columns(4)
    cols[0].metric("準時率", f"{kpis['準時完成率']:.1f}%")
    cols[1].metric("遲交工單", int(kpis["遲交工單數"]))
    cols[2].metric("未排入", int(kpis["未完成 / 超出 horizon 工單數"]))
    cols[3].metric("換模次數", int(kpis.get("換模次數", 0)))
    cols = st.columns(4)
    cols[0].metric("總遲交", f"{kpis['總遲交時間']:.1f} 小時")
    cols[1].metric("最大遲交", f"{kpis['最大遲交時間']:.1f} 小時")
    cols[2].metric("Makespan", f"{kpis['Makespan']:.1f} 小時")
    cols[3].metric("平均使用率", f"{kpis['平均 utilization']:.1f}%")


def datetime_fields(label: str, value: pd.Timestamp, key: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    cols = st.columns(2)
    selected_date = cols[0].date_input(f"{label}日期", value=timestamp.date(), key=f"{key}_date")
    selected_time = cols[1].time_input(f"{label}時間", value=timestamp.time().replace(microsecond=0), key=f"{key}_time")
    if isinstance(selected_date, date) and isinstance(selected_time, time):
        return pd.Timestamp(datetime.combine(selected_date, selected_time))
    return timestamp


def calendar_unavailability(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    selected_machines = [machine for machine in st.session_state.selected_machines if machine in MACHINES] or MACHINES
    return build_calendar_unavailability(
        selected_machines,
        start,
        end,
        exclude_weekends=st.session_state.exclude_weekends,
        non_working_dates=st.session_state.non_working_dates,
        work_time_mode=st.session_state.work_time_mode,
        workday_start=st.session_state.workday_start_time,
        daily_work_hours=st.session_state.daily_work_hours,
    )


def effective_unavailability(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frames = [st.session_state.unavailability, calendar_unavailability(start, end)]
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["機台", "不可用開始", "不可用結束", "原因"])
    return pd.concat(frames, ignore_index=True)


def export_schedule_package_zip(excel_bytes: bytes, gantt_html: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("EastFu_APS_Result.xlsx", excel_bytes)
        archive.writestr("EastFu_APS_Gantt.html", gantt_html.encode("utf-8"))
    return output.getvalue()


def answer_usage_question(question: str) -> str:
    return answer_from_manual(question)


def load_demo() -> None:
    write_demo_excel(DEMO_EXCEL_PATH)
    st.session_state.workbook = load_workbook(DEMO_EXCEL_PATH)
    st.session_state.validation = validate_workbook(st.session_state.workbook)
    if has_timing_defaults(st.session_state.workbook) and st.session_state.validation[0] and st.session_state.validation[2] is not None:
        apply_workbook_defaults(st.session_state.validation[2])
    st.session_state.upload_filename = DEMO_EXCEL_PATH.name
    st.session_state.schedule_df = None
    st.session_state.kpis = None
    st.session_state.comparison_df = None


def run_schedule(reason: str = "INITIAL") -> None:
    data = valid_data()
    if data is None:
        st.error("Excel 格式有問題，請先修正驗證訊息。")
        return
    start, end = horizon_window(data)
    if start >= end:
        st.error("排程開始時間必須早於排程結束時間。")
        return
    data = with_horizon_settings(data, start, end)
    data = apply_run_constraints(data)
    if data is None:
        return
    blocked_periods = effective_unavailability(start, end)
    try:
        result = schedule(
            data,
            st.session_state.selected_strategy,
            horizon_start=start,
            horizon_end=end,
            default_changeover_minutes=st.session_state.changeover_minutes,
            unavailability=blocked_periods,
        )
        kpis = calculate_kpis(result, data["排程基本設定"])
    except Exception as exc:
        st.error(f"排程計算失敗：{type(exc).__name__}: {exc}")
        st.caption("請確認產品是否有可用機台產速、排程期間是否足夠、停機/休假是否讓全部候選機台不可用。")
        return

    st.session_state.schedule_df = result
    st.session_state.kpis = kpis
    st.session_state.workbook = data
    st.session_state.validation = validate_workbook(data)
    try:
        st.session_state.last_version = create_schedule_version(
            data,
            result,
            kpis,
            st.session_state.selected_strategy,
            STRATEGIES[st.session_state.selected_strategy].name,
            start,
            end,
            reason,
            upload_filename=st.session_state.upload_filename,
            input_source="內建標準資料" if st.session_state.upload_filename == DEMO_EXCEL_PATH.name else "Uploaded Excel",
            unavailability=blocked_periods,
            default_changeover_minutes=st.session_state.changeover_minutes,
            rule_configuration={
                "strategy_code": st.session_state.selected_strategy,
                "horizon_mode": st.session_state.horizon_mode,
                "default_changeover_minutes": st.session_state.changeover_minutes,
                "selected_machines": st.session_state.selected_machines,
                "capacity_mode": st.session_state.capacity_mode,
                "capacity_factor": capacity_factor(),
                "work_time_mode": st.session_state.work_time_mode,
                "workday_start_time": st.session_state.workday_start_time.strftime("%H:%M"),
                "daily_work_hours": st.session_state.daily_work_hours,
                "exclude_weekends": st.session_state.exclude_weekends,
                "non_working_dates": [day.strftime("%Y-%m-%d") for day in parse_non_working_dates(st.session_state.non_working_dates)],
            },
        )
    except Exception as exc:
        st.session_state.last_version = None
        st.warning(f"排程已完成，但歷史版本暫時無法儲存：{type(exc).__name__}: {exc}")
    st.success("排程完成")


def add_urgent_order(order_id: str, product: str, qty: float, due: pd.Timestamp, priority: str, allowed: list[str] | None = None) -> bool:
    data = valid_data()
    if data is None:
        st.error("請先載入或上傳有效 Excel。")
        return False
    new_row = pd.DataFrame(
        [
            {
                "工單編號": order_id,
                "產品": product,
                "數量": qty,
                "單位": "PCS",
                "優先級": priority,
                "交期": due,
                "允許機台": ",".join(allowed or []),
                "_原始順序": len(data["待排工單"]) + 1,
            }
        ]
    )
    updated = {name: frame.copy() for name, frame in data.items()}
    updated["待排工單"] = pd.concat([updated["待排工單"], new_row], ignore_index=True)
    st.session_state.workbook = updated
    st.session_state.validation = validate_workbook(updated)
    return st.session_state.validation[0]


def v2_machine_options() -> list[str]:
    master = st.session_state.v2_master_data
    if not master or master.get("機台資料", pd.DataFrame()).empty:
        return MACHINES
    machines = master["機台資料"]["機台"].dropna().astype(str).tolist()
    return machines or MACHINES


def v2_horizon_end(orders: pd.DataFrame, start: pd.Timestamp, mode: str, custom_end: pd.Timestamp) -> pd.Timestamp:
    if mode == "本批最晚結關日":
        dates = pd.to_datetime(orders.get("customs_closing_date"), errors="coerce").dropna()
        if not dates.empty:
            return max(pd.Timestamp(dates.max()).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59), start)
    if mode == "本批最晚完成日":
        dates = pd.to_datetime(orders.get("completion_date"), errors="coerce").dropna()
        if not dates.empty:
            return max(pd.Timestamp(dates.max()).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59), start)
    if mode == "1 週":
        return start + pd.Timedelta(days=7)
    if mode == "2 週":
        return start + pd.Timedelta(days=14)
    if mode == "1 個月":
        return start + pd.DateOffset(months=1)
    return pd.Timestamp(custom_end)


def default_machine_status(machines: list[str], baseline: pd.Timestamp, existing: pd.DataFrame | None = None) -> pd.DataFrame:
    if existing is not None and not existing.empty and {"機台", "可排起始時間"}.issubset(existing.columns):
        keep_cols = [col for col in ["機台", "可排起始時間", "備註"] if col in existing.columns]
        frame = existing[keep_cols].copy()
        for machine in machines:
            if not (frame["機台"].astype(str) == machine).any():
                frame = pd.concat([frame, pd.DataFrame([{"機台": machine, "可排起始時間": baseline, "備註": ""}])], ignore_index=True)
        return frame
    return pd.DataFrame(
        [{"機台": machine, "可排起始時間": baseline, "備註": ""} for machine in machines]
    )


def apply_machine_status_to_master(master: dict[str, pd.DataFrame], machine_status: pd.DataFrame) -> None:
    status = machine_status.copy()
    status["可排起始時間"] = pd.to_datetime(status["可排起始時間"], errors="coerce")
    master["機台可排起始時間"] = status[["機台", "可排起始時間"]].dropna(subset=["機台"]).copy()
    master["期初在製"] = pd.DataFrame()


def priority_order_text(order: list[str]) -> str:
    return " → ".join(order)


def run_v2_schedule(orders: pd.DataFrame, schedule_start: pd.Timestamp, horizon_end: pd.Timestamp) -> None:
    master = st.session_state.v2_master_data
    if not master:
        st.error("請先載入 V2 Master Data。")
        return
    summary, validated = validate_v2_orders(orders, master)
    st.session_state.v2_import_summary = summary
    st.session_state.v2_orders_validated = validated
    if summary.issue_rows:
        st.error("仍有工單需要修正，請先處理問題列再排程。")
        return
    workbook = build_scheduler_workbook(
        validated,
        master,
        schedule_start,
        horizon_end,
        work_time_mode=st.session_state.get("v2_work_time_mode", "24 小時連續排程"),
        daily_start_time=st.session_state.get("v2_daily_start_time", time(8, 0)),
        daily_end_time=st.session_state.get("v2_daily_end_time", time(20, 0)),
    )
    selected_machines = st.session_state.get("v2_selected_machines", v2_machine_options())
    workbook["產品機台產速"] = workbook["產品機台產速"][workbook["產品機台產速"]["機台"].astype(str).isin(selected_machines)].copy()
    try:
        schedule_kwargs = {
            "horizon_start": schedule_start,
            "horizon_end": horizon_end,
            "default_changeover_minutes": 45,
        }
        if "priority_order" in signature(schedule).parameters:
            schedule_kwargs["priority_order"] = st.session_state.get("v2_priority_order", ["指定優先", "完成日", "減少換模"])
        result = schedule(workbook, "v2_default", **schedule_kwargs)
        kpis = calculate_kpis(result, workbook["排程基本設定"])
    except Exception as exc:
        st.error(f"V2 排程失敗：{type(exc).__name__}: {exc}")
        return
    st.session_state.v2_workbook = workbook
    st.session_state.v2_schedule_df = result
    st.session_state.v2_kpis = kpis
    st.session_state.schedule_df = result
    st.session_state.kpis = kpis
    st.session_state.workbook = workbook
    st.session_state.validation = validate_workbook(workbook)
    st.success("V2 排程完成")


def render_v2_readiness(readiness) -> None:
    if readiness.ready:
        st.success("✓ 排程資料已準備完成，可以開始排程")
    else:
        lines = ["**目前尚無法開始排程，請先完成以下項目：**"]
        for item in readiness.blocking:
            lines.append(f"- **{item.message}**（{item.section}｜{item.action}）")
        st.error("\n".join(lines))

    if readiness.warnings:
        lines = ["**提醒：以下項目不會阻擋排程，但可能影響結果：**"]
        for item in readiness.warnings:
            lines.append(f"- {item.message}（{item.section}｜{item.action}）")
        st.warning("\n".join(lines))


def _project_time(value: object, fallback: time) -> time:
    parsed = pd.to_datetime(value, errors="coerce")
    return fallback if pd.isna(parsed) else parsed.time()


def apply_v2_project_document(document: dict, label: str) -> None:
    payload = document.get("payload", document)
    st.session_state.v2_erp_filename = payload.get("erp_filename", "")
    st.session_state.v2_master_data = {name: records_to_frame(records) for name, records in payload.get("master_data", {}).items()} or st.session_state.v2_master_data
    st.session_state.v2_orders = records_to_frame(payload.get("orders"))
    st.session_state.v2_orders_validated = records_to_frame(payload.get("orders"))
    st.session_state.v2_schedule_df = records_to_frame(payload.get("schedule"))
    st.session_state.v2_kpis = payload.get("kpis")
    if payload.get("workbook_orders") or payload.get("rates") or payload.get("settings"):
        st.session_state.v2_workbook = {
            "待排工單": records_to_frame(payload.get("workbook_orders")),
            "產品機台產速": records_to_frame(payload.get("rates")),
            "排程基本設定": records_to_frame(payload.get("settings")),
        }
    st.session_state.v2_selected_machines = payload.get("selected_machines", st.session_state.get("v2_selected_machines", []))
    st.session_state.v2_strategy_preset = payload.get("strategy", "東福標準")
    st.session_state.v2_priority_order = payload.get("priority_order", ["指定優先", "完成日", "減少換模"])
    st.session_state.v2_planning_mode = payload.get("planning_horizon_mode", "本批最晚結關日")
    st.session_state.v2_execution_window_hours = payload.get("execution_window_hours", 48)
    st.session_state.v2_work_time_mode = payload.get("work_time_mode", "24 小時連續排程")
    st.session_state.v2_daily_start_time = _project_time(payload.get("daily_start_time", "08:00"), time(8, 0))
    st.session_state.v2_daily_end_time = _project_time(payload.get("daily_end_time", "20:00"), time(20, 0))
    if st.session_state.v2_master_data is not None and payload.get("machine_status"):
        st.session_state.v2_master_data["機台目前狀態"] = records_to_frame(payload.get("machine_status"))
    metadata = document.get("metadata", {})
    if metadata.get("schedule_name"):
        st.session_state.v2_project_name = metadata["schedule_name"]
    st.success(f"已開啟：{label}")


init_state()
st.title("East Fu APS Lite V2")
st.caption("ERP Excel → Upload → Confirm → Schedule → Review → Save")

with st.container(border=True):
    st.subheader("V2 工作區")
    master_file = st.file_uploader("1. 載入 V2 Master Data / 生產設定", type=["xlsx"], key="v2_master_upload")
    if master_file is not None:
        try:
            st.session_state.v2_master_data = load_v2_master_data(master_file)
            st.success("V2 Master Data 已載入")
        except Exception as exc:
            st.error(f"Master Data 無法讀取：{type(exc).__name__}: {exc}")

    if st.session_state.v2_master_data:
        master = st.session_state.v2_master_data
        master_tabs = st.tabs(["產品主檔", "產品機台產速", "機台資料", "換模設定"])
        with master_tabs[0]:
            st.dataframe(master["產品主檔"], use_container_width=True, height=180)
        with master_tabs[1]:
            st.caption("若 Master Data 產速尚未填寫，可先在這裡補上後再排程。")
            master["產品機台產速"] = st.data_editor(master["產品機台產速"], use_container_width=True, num_rows="dynamic", key="v2_rates_editor")
        with master_tabs[2]:
            st.dataframe(master["機台資料"], use_container_width=True, height=180)
        with master_tabs[3]:
            master["換模設定"] = st.data_editor(master["換模設定"], use_container_width=True, num_rows="dynamic", key="v2_setup_editor")

    erp_file = st.file_uploader("2. 上傳 East Fu ERP 製令 Excel", type=["xlsx"], key="v2_erp_upload")
    if erp_file is not None:
        try:
            orders, header_row = load_east_fu_erp_orders(erp_file, erp_file.name)
            st.session_state.v2_orders = orders
            st.session_state.v2_erp_filename = erp_file.name
            st.session_state.v2_header_row = header_row
            st.success(f"ERP 已匯入：偵測標題列第 {header_row} 列，共 {len(orders)} 筆")
        except Exception as exc:
            st.error(f"ERP 檔無法匯入：{type(exc).__name__}: {exc}")

    if st.session_state.v2_orders is not None:
        orders = st.session_state.v2_orders.copy()
        suggested = orders["suggested_completion_date"].dropna()
        default_completion = pd.Timestamp(suggested.iloc[0]).date() if not suggested.empty else pd.Timestamp.now().date()
        st.markdown("### 排程設定")
        cols = st.columns(3)
        completion_date = cols[0].date_input("確認完成日", value=default_completion, key="v2_completion_date")
        st.session_state.v2_selected_machines = cols[1].multiselect("本次排程機台", v2_machine_options(), default=v2_machine_options(), key="v2_selected_machines_widget")
        schedule_start = datetime_fields("排程基準時間", pd.Timestamp(st.session_state.schedule_start), "v2_schedule_start")
        settings_cols = st.columns(4)
        st.session_state.v2_planning_mode = settings_cols[0].selectbox(
            "規劃範圍",
            ["本批最晚結關日", "本批最晚完成日", "1 週", "2 週", "1 個月", "自訂日期"],
            index=["本批最晚結關日", "本批最晚完成日", "1 週", "2 週", "1 個月", "自訂日期"].index(st.session_state.v2_planning_mode),
            key="v2_planning_mode_widget",
        )
        if st.session_state.v2_planning_mode == "自訂日期":
            st.session_state.v2_custom_horizon_end = datetime_fields("規劃至", pd.Timestamp(st.session_state.v2_custom_horizon_end), "v2_custom_horizon_end")
        st.session_state.v2_execution_window_hours = settings_cols[1].selectbox("近期執行區", [24, 48, 72, 168], index=[24, 48, 72, 168].index(int(st.session_state.v2_execution_window_hours)), format_func=lambda h: f"{h} 小時" if h < 168 else "1 週", key="v2_execution_window_hours_widget")
        st.session_state.v2_strategy_preset = settings_cols[2].selectbox("排程策略", ["東福標準", "自訂"], index=0 if st.session_state.v2_strategy_preset == "東福標準" else 1, key="v2_strategy_preset_widget")
        work_time_options = ["24 小時連續排程", "每日固定工時"]
        current_work_time_mode = st.session_state.get("v2_work_time_mode", "24 小時連續排程")
        if current_work_time_mode not in work_time_options:
            current_work_time_mode = "24 小時連續排程"
        st.session_state.v2_work_time_mode = settings_cols[3].selectbox(
            "工時模式",
            work_time_options,
            index=work_time_options.index(current_work_time_mode),
            key="v2_work_time_mode_widget",
        )
        if st.session_state.v2_work_time_mode == "每日固定工時":
            daily_cols = st.columns(2)
            st.session_state.v2_daily_start_time = daily_cols[0].time_input("每日開始時間", value=st.session_state.get("v2_daily_start_time", time(8, 0)), key="v2_daily_start_time_widget")
            st.session_state.v2_daily_end_time = daily_cols[1].time_input("每日結束時間", value=st.session_state.get("v2_daily_end_time", time(20, 0)), key="v2_daily_end_time_widget")
            st.caption("工時模式：每台本次排程機台套用同一組每日開始/結束時間。")
        else:
            st.caption("工時模式：24 小時連續排程，不受每日開始/結束時間限制。")
        if st.session_state.v2_strategy_preset == "東福標準":
            st.session_state.v2_priority_order = ["指定優先", "完成日", "減少換模"]
            st.caption("目前優先順序：指定優先 → 完成日 → 減少換模")
        else:
            selected_order = st.multiselect(
                "自訂優先順序（依選取順序套用）",
                ["指定優先", "完成日", "減少換模"],
                default=st.session_state.v2_priority_order,
                max_selections=3,
                key="v2_priority_order_widget",
            )
            st.session_state.v2_priority_order = selected_order + [item for item in ["指定優先", "完成日", "減少換模"] if item not in selected_order]
            st.caption(f"目前優先順序：{priority_order_text(st.session_state.v2_priority_order)}")
        orders["completion_date"] = pd.Timestamp(completion_date)
        horizon_end = v2_horizon_end(orders, pd.Timestamp(schedule_start), st.session_state.v2_planning_mode, pd.Timestamp(st.session_state.v2_custom_horizon_end))
        st.markdown("### 本次機台可排起始時間")
        st.caption("若某台機前面有單尚未做完，直接把該機台的可排起始時間延後即可；不用在 Excel 填期初在製。")
        machine_status = default_machine_status(st.session_state.v2_selected_machines or v2_machine_options(), pd.Timestamp(schedule_start), st.session_state.v2_master_data.get("機台目前狀態") if st.session_state.v2_master_data else None)
        machine_status = st.data_editor(machine_status, use_container_width=True, num_rows="fixed", key="v2_machine_status_editor")
        st.session_state.v2_master_data["機台目前狀態"] = machine_status
        apply_machine_status_to_master(st.session_state.v2_master_data, machine_status)
        editable_cols = [
            "manual_priority",
            "work_order_id",
            "product_id",
            "product_name",
            "specification",
            "quantity",
            "unit",
            "release_date",
            "completion_date",
            "customs_closing_date",
            "customer_order_no",
            "customer_name",
        ]
        edited_orders = st.data_editor(orders[editable_cols], use_container_width=True, num_rows="dynamic", key="v2_orders_editor")
        orders.update(edited_orders)
        if st.session_state.v2_master_data:
            summary, validated = validate_v2_orders(orders, st.session_state.v2_master_data)
            st.session_state.v2_import_summary = summary
            st.session_state.v2_orders_validated = validated
            st.info(f"Imported orders: {summary.total_rows}；Ready for scheduling: {summary.ready_rows}；Need correction/mapping: {summary.issue_rows}")
            if summary.issues:
                st.warning("；".join(summary.issues))
            problem_rows = validated[validated["問題"] != ""]
            if not problem_rows.empty:
                st.dataframe(problem_rows, use_container_width=True, height=220)
            st.info(
                f"本次規劃範圍：{pd.Timestamp(schedule_start):%Y/%m/%d %H:%M} ～ {pd.Timestamp(horizon_end):%Y/%m/%d %H:%M}；"
                f"近期執行區：前 {int(st.session_state.v2_execution_window_hours)} 小時；"
                f"工時模式：{st.session_state.v2_work_time_mode}"
                f"{f'（{st.session_state.v2_daily_start_time:%H:%M}～{st.session_state.v2_daily_end_time:%H:%M}）' if st.session_state.v2_work_time_mode == '每日固定工時' else ''}；"
                f"排程策略：{st.session_state.v2_strategy_preset}；"
                f"優先順序：{priority_order_text(st.session_state.v2_priority_order)}"
            )
            for _, status_row in machine_status.iterrows():
                st.caption(f"{status_row.get('機台')} 可排：{pd.to_datetime(status_row.get('可排起始時間'), errors='coerce')}")
            readiness = assess_v2_schedule_readiness(
                master_data=st.session_state.v2_master_data,
                orders=orders,
                summary=summary,
                validated_orders=validated,
                selected_machines=st.session_state.v2_selected_machines,
                schedule_start=schedule_start,
                horizon_end=horizon_end,
            )
            render_v2_readiness(readiness)
            if st.button("確認設定並開始排程", type="primary", disabled=not readiness.ready, use_container_width=True, key="v2_run_schedule"):
                run_v2_schedule(validated, pd.Timestamp(schedule_start), horizon_end)

    if st.session_state.v2_schedule_df is not None and st.session_state.v2_kpis is not None and st.session_state.v2_workbook is not None:
        start, end, _ = get_schedule_window(st.session_state.v2_workbook["排程基本設定"])
        st.subheader("V2 甘特圖")
        gantt_cols = st.columns(2)
        gantt_view = gantt_cols[0].selectbox("甘特圖顯示範圍", ["24H", "48H", "1週", "2週", "全部"], index=1, key="v2_gantt_view")
        gantt_machines = gantt_cols[1].multiselect("甘特圖機台", v2_machine_options(), default=v2_machine_options(), key="v2_gantt_machines")
        view_hours = {"24H": 24, "48H": 48, "1週": 168, "2週": 336}
        view_end = end if gantt_view == "全部" else min(end, start + pd.Timedelta(hours=view_hours[gantt_view]))
        gantt_frame = st.session_state.v2_schedule_df[st.session_state.v2_schedule_df["指派機台"].astype(str).isin(gantt_machines)].copy()
        gantt_frame = gantt_frame[(pd.to_datetime(gantt_frame["結束時間"], errors="coerce") >= start) & (pd.to_datetime(gantt_frame["開始時間"], errors="coerce") <= view_end)]
        gantt_fig = make_gantt(gantt_frame, start, view_end)
        st.plotly_chart(gantt_fig, use_container_width=True)
        gantt_html = gantt_fig.to_html(full_html=True, include_plotlyjs=True)
        st.download_button(
            "下載甘特圖 HTML",
            gantt_html,
            "EastFu_APS_Lite_V2_Gantt.html",
            mime="text/html",
            use_container_width=True,
            key="v2_download_gantt_html",
        )
        st.subheader("V2 KPI")
        render_kpis(st.session_state.v2_kpis)
        st.dataframe(st.session_state.v2_schedule_df, use_container_width=True)
        export_metadata = {
            "規劃開始": str(start),
            "規劃結束": str(end),
            "近期執行區": f"{st.session_state.v2_execution_window_hours} 小時",
            "工時模式": st.session_state.v2_work_time_mode,
            "每日工時": f"{st.session_state.v2_daily_start_time:%H:%M}～{st.session_state.v2_daily_end_time:%H:%M}" if st.session_state.v2_work_time_mode == "每日固定工時" else "24 小時",
            "排程策略": st.session_state.v2_strategy_preset,
            "優先順序": priority_order_text(st.session_state.v2_priority_order),
        }
        v2_excel = export_schedule_excel(st.session_state.v2_schedule_df, st.session_state.v2_kpis, metadata=export_metadata)
        package_bytes = export_schedule_package_zip(v2_excel, gantt_html)
        export_cols = st.columns(2)
        export_cols[0].download_button("下載 Excel 排程", v2_excel, "EastFu_APS_Lite_V2_Schedule.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, key="v2_download_excel")
        export_cols[1].download_button("一併下載 Excel + 甘特圖", package_bytes, "EastFu_APS_Lite_V2_Package.zip", mime="application/zip", use_container_width=True, key="v2_download_package")
        save_cols = st.columns([2, 1, 1])
        st.session_state.v2_project_name = save_cols[0].text_input("排程專案名稱", value=st.session_state.v2_project_name)
        payload = {
            "erp_filename": st.session_state.v2_erp_filename,
            "orders": frame_to_records(st.session_state.v2_orders_validated),
            "schedule": frame_to_records(st.session_state.v2_schedule_df),
            "kpis": st.session_state.v2_kpis,
            "master_data": {name: frame_to_records(frame) for name, frame in st.session_state.v2_master_data.items()} if st.session_state.v2_master_data else {},
            "workbook_orders": frame_to_records(st.session_state.v2_workbook["待排工單"]),
            "rates": frame_to_records(st.session_state.v2_workbook["產品機台產速"]),
            "settings": frame_to_records(st.session_state.v2_workbook["排程基本設定"]),
            "schedule_start": str(start),
            "horizon_end": str(end),
            "selected_machines": st.session_state.get("v2_selected_machines", []),
            "strategy": st.session_state.v2_strategy_preset,
            "priority_order": st.session_state.v2_priority_order,
            "planning_horizon_mode": st.session_state.v2_planning_mode,
            "planning_horizon_end": str(end),
            "execution_window_hours": st.session_state.v2_execution_window_hours,
            "work_time_mode": st.session_state.v2_work_time_mode,
            "daily_start_time": str(st.session_state.v2_daily_start_time),
            "daily_end_time": str(st.session_state.v2_daily_end_time),
            "machine_status": frame_to_records(st.session_state.v2_master_data.get("機台目前狀態") if st.session_state.v2_master_data else None),
        }
        if save_cols[1].button("Save", use_container_width=True, key="v2_save_project"):
            path = save_project(st.session_state.v2_project_name, payload, save_as=False)
            st.session_state.v2_last_project_path = str(path)
            st.success(f"已儲存：{path.name}")
        if save_cols[2].button("Save As", use_container_width=True, key="v2_save_project_as"):
            path = save_project(st.session_state.v2_project_name, payload, save_as=True)
            st.session_state.v2_last_project_path = str(path)
            st.success(f"已另存版本：{path.name}")
        project_file_name, project_bytes = project_to_bytes(st.session_state.v2_project_name, payload)
        st.download_button(
            "下載排程專案檔 JSON（可帶到其他電腦開啟）",
            project_bytes,
            project_file_name,
            mime="application/json",
            use_container_width=True,
            key="v2_download_project_json",
        )

    projects = list_projects()
    with st.expander("Open / Import Saved Project"):
        uploaded_project = st.file_uploader("上傳排程專案檔 JSON", type=["json"], key="v2_project_upload")
        if uploaded_project is not None and st.button("開啟上傳的專案檔", use_container_width=True, key="v2_open_uploaded_project"):
            try:
                loaded = load_project_bytes(uploaded_project.getvalue())
                apply_v2_project_document(loaded, uploaded_project.name)
            except Exception as exc:
                st.error(f"專案檔無法開啟：{type(exc).__name__}: {exc}")

        if projects:
            labels = [p["file"] for p in projects]
            selected_project = st.selectbox("選擇專案版本", labels)
            if st.button("Open Project", key="v2_open_project"):
                loaded = load_project(selected_project)
                apply_v2_project_document(loaded, selected_project)
        else:
            st.caption("目前這個 App 環境尚未儲存任何內部專案。可改用上方 JSON 上傳。")

if str(st.query_params.get("legacy_v1", "")).lower() not in {"1", "true", "yes"}:
    st.stop()

st.divider()
st.subheader("Legacy V1 / 手動 Excel 流程")
st.caption("保留原 APS Lite V1 匯入方式，作為回退與手動資料流程。")

top = st.columns([1, 2])
with top[0]:
    if st.button("載入東福標準排程資料", type="primary", use_container_width=True):
        load_demo()
with top[1]:
    uploaded = st.file_uploader("上傳排程 Excel", type=["xlsx"], label_visibility="collapsed")
    if uploaded is not None:
        try:
            st.session_state.workbook = load_workbook(uploaded)
            st.session_state.validation = validate_workbook(st.session_state.workbook)
            if has_timing_defaults(st.session_state.workbook) and st.session_state.validation[0] and st.session_state.validation[2] is not None:
                apply_workbook_defaults(st.session_state.validation[2])
            st.session_state.upload_filename = uploaded.name
            st.session_state.schedule_df = None
            st.session_state.kpis = None
        except Exception:
            st.error("Excel 格式有問題，無法讀取工作簿。")

data = valid_data()
if st.session_state.validation is None:
    st.info("請載入東福標準排程資料或上傳排程 Excel。")
else:
    ok, issues, data_or_none = st.session_state.validation
    if ok and data_or_none is not None:
        st.success(f"資料驗證通過：{len(data_or_none['待排工單'])} / {len(data_or_none['待排工單'])} orders valid")
    else:
        st.error(f"Excel 格式有問題，發現 {len(issues)} 個問題")
        for issue in issues:
            st.write(f"- {issue}")

controls = st.columns([1.3, 1.1])
with controls[0]:
    st.session_state.horizon_mode = st.radio("排程期間", ["24 小時", "48 小時", "72 小時", "一週", "自訂"], horizontal=True)
    if st.session_state.horizon_mode == "自訂":
        st.session_state.custom_start = datetime_fields("開始", pd.Timestamp(st.session_state.custom_start), "custom_start")
        st.session_state.custom_end = datetime_fields("結束", pd.Timestamp(st.session_state.custom_end), "custom_end")
    else:
        st.session_state.schedule_start = datetime_fields("排程開始", pd.Timestamp(st.session_state.schedule_start), "schedule_start")
with controls[1]:
    st.session_state.selected_strategy = st.selectbox("排程策略", MAIN_STRATEGIES, format_func=lambda code: STRATEGIES[code].name)
    st.session_state.selected_machines = st.multiselect("本次排程使用機台", MACHINES, default=st.session_state.selected_machines)

quick = st.columns(2)
with quick[0]:
    with st.expander("＋ 急單"):
        urgent_id = st.text_input("工單編號", value="URGENT-001")
        urgent_product = st.text_input("產品", value="SIM-C2-A")
        urgent_qty = st.number_input("數量", min_value=1.0, value=120.0)
        urgent_due = datetime_fields("交期", pd.Timestamp("2026-09-03 18:00"), "urgent_due")
        urgent_allowed = st.multiselect("限定機台（不選 = 依產品產速表）", MACHINES, default=[])
        if st.button("重新排程", key="urgent_replan", use_container_width=True):
            if add_urgent_order(urgent_id, urgent_product, urgent_qty, pd.Timestamp(urgent_due), "急單", urgent_allowed):
                run_schedule("URGENT_ORDER")
                st.success("急單重排完成")
with quick[1]:
    with st.expander("特殊狀況 / 停機"):
        downtime_machines = st.session_state.selected_machines or MACHINES
        down_machine = st.selectbox("機台", downtime_machines)
        down_from = datetime_fields("不可用開始", pd.Timestamp(st.session_state.schedule_start) + pd.Timedelta(hours=4), "down_from")
        down_until = datetime_fields("不可用結束", pd.Timestamp(st.session_state.schedule_start) + pd.Timedelta(hours=6), "down_until")
        reason = st.text_input("原因", value="")
        if not st.session_state.unavailability.empty:
            st.dataframe(st.session_state.unavailability, use_container_width=True)
        downtime_cols = st.columns(2)
        with downtime_cols[0]:
            add_downtime = st.button("加入並重新排程", key="downtime_replan", use_container_width=True)
        with downtime_cols[1]:
            clear_downtime = st.button("清除特殊狀況", key="clear_downtime", use_container_width=True)
        if clear_downtime:
            st.session_state.unavailability = pd.DataFrame(columns=["機台", "不可用開始", "不可用結束", "原因"])
            st.success("已清除特殊狀況")
        if add_downtime:
            st.session_state.unavailability = pd.concat(
                [
                    st.session_state.unavailability,
                    pd.DataFrame([{"機台": down_machine, "不可用開始": down_from, "不可用結束": down_until, "原因": reason}]),
                ],
                ignore_index=True,
            )
            run_schedule("MACHINE_DOWN")

with st.expander("基本設定", expanded=data is not None):
    if data is None:
        st.caption("載入資料後可查看與編輯基本設定。")
    else:
        st.session_state.work_time_mode = st.radio("工時模式", ["24 小時連續排程", "每日 8 小時排程"], horizontal=True)
        if st.session_state.work_time_mode == "每日 8 小時排程":
            work_cols = st.columns(2)
            st.session_state.workday_start_time = work_cols[0].time_input("每日開始時間", value=st.session_state.workday_start_time)
            st.session_state.daily_work_hours = work_cols[1].number_input("每日可排工時", min_value=1.0, max_value=24.0, value=float(st.session_state.daily_work_hours), step=0.5)
        st.session_state.capacity_mode = st.radio("今日人力 / 產能狀況", ["正常產能（100%）", "人力不足（80%）", "嚴重不足（60%）", "自訂"], horizontal=True)
        if st.session_state.capacity_mode == "自訂":
            st.session_state.custom_capacity_percent = st.number_input("自訂產能比例（%）", min_value=10, max_value=150, value=int(st.session_state.custom_capacity_percent), step=5)
        st.session_state.changeover_minutes = st.number_input("預設換模時間（分鐘）", min_value=0, value=int(st.session_state.changeover_minutes), step=5)
        st.session_state.exclude_weekends = st.checkbox("週末不排程（星期六、星期日）", value=bool(st.session_state.exclude_weekends))
        st.session_state.non_working_dates = st.text_area("指定日期不排程（國定假日 / 盤點 / 全廠休假）", value=st.session_state.non_working_dates, placeholder="例如：\n2026-09-28\n2026-10-10")
        st.caption("產品原則上可用機台請填在產品機台產速表；單張工單若有特殊限制，可在 `工單限定機台` 填 C5 或 C4,C5。")
        edited_rates = st.data_editor(data["產品機台產速"], use_container_width=True, num_rows="dynamic")
        changeover_source = data.get("換模時間", pd.DataFrame(columns=["來源換模群組", "目標換模群組", "換模時間_分鐘"]))
        edited_changeovers = st.data_editor(changeover_source, use_container_width=True, num_rows="dynamic")
        if st.button("保存產品 / 機台產速 / 換模時間"):
            updated = {name: frame.copy() for name, frame in data.items()}
            updated["產品機台產速"] = edited_rates
            updated["換模時間"] = edited_changeovers
            st.session_state.workbook = updated
            st.session_state.validation = validate_workbook(updated)
            st.success("產品機台產速與換模時間已保存")

st.markdown("### 開始排程")
if st.button("確認設定並開始排程", type="primary", disabled=data is None, use_container_width=True, key="legacy_v1_run_schedule"):
    run_schedule("INITIAL")

with st.expander("操作問題小幫手", expanded=False):
    st.session_state.assistant_question = st.text_input("請輸入操作問題", value=st.session_state.assistant_question, placeholder="例如：為什麼某張工單排不進去？")
    if st.session_state.assistant_question:
        st.info(answer_usage_question(st.session_state.assistant_question))

with st.expander("內建使用手冊", expanded=False):
    st.markdown(manual_text())

with st.expander("歷史排程", expanded=False):
    history = load_history()
    if not history:
        st.caption("尚無歷史版本")
    else:
        labels = [f"{v['created_at']}  {v['version_id']}  {v['order_count']} 筆  {v['scheduling_rule_name']}" for v in history]
        selected = st.selectbox("版本", range(len(labels)), format_func=lambda idx: labels[idx], index=len(labels) - 1)
        version = history[selected]
        st.write(f"{version['reason']} | {version['horizon_start']} - {version['horizon_end']}")
        st.dataframe(version_orders_frame(version), use_container_width=True)
        old_schedule = version_schedule_frame(version)
        if not old_schedule.empty:
            st.plotly_chart(make_gantt(old_schedule, pd.Timestamp(version["horizon_start"]), pd.Timestamp(version["horizon_end"])), use_container_width=True)
            st.dataframe(kpis_to_frame(version["kpis"]), use_container_width=True)

if st.session_state.schedule_df is not None and st.session_state.kpis is not None and st.session_state.workbook is not None:
    start, end = horizon_window(st.session_state.workbook)
    st.subheader("甘特圖")
    gantt_fig = make_gantt(st.session_state.schedule_df, start, end)
    st.plotly_chart(gantt_fig, use_container_width=True)
    st.subheader("KPI")
    render_kpis(st.session_state.kpis)
    unscheduled = st.session_state.schedule_df[st.session_state.schedule_df["狀態"] != "scheduled"]
    if not unscheduled.empty:
        st.warning(f"目前有 {len(unscheduled)} 張工單無法在排程期間完成")
        st.dataframe(unscheduled, use_container_width=True)
    st.subheader("排程摘要")
    st.dataframe(st.session_state.schedule_df, use_container_width=True)
    blocked_periods = effective_unavailability(start, end)
    st.session_state.comparison_df, _ = compare_strategies(
        st.session_state.workbook,
        MAIN_STRATEGIES,
        horizon_start=start,
        horizon_end=end,
        default_changeover_minutes=st.session_state.changeover_minutes,
        unavailability=blocked_periods,
    )
    best, _ = recommend_strategy(st.session_state.comparison_df)
    st.success(f"推薦方案：{best['策略']}")
    st.dataframe(st.session_state.comparison_df.drop(columns=["策略代碼"], errors="ignore"), use_container_width=True)
    cols = st.columns(2)
    cols[0].plotly_chart(comparison_bar(st.session_state.comparison_df, "準時完成率", "準時完成率比較"), use_container_width=True)
    cols[1].plotly_chart(comparison_bar(st.session_state.comparison_df, "總遲交時間", "總遲交時間比較"), use_container_width=True)
    gantt_html = gantt_fig.to_html(full_html=True, include_plotlyjs=True)
    excel_bytes = export_schedule_excel(st.session_state.schedule_df, st.session_state.kpis, st.session_state.comparison_df)
    package_bytes = export_schedule_package_zip(excel_bytes, gantt_html)
    download_cols = st.columns(3)
    download_cols[0].download_button("下載排程結果 Excel", excel_bytes, "EastFu_APS_Result.xlsx", use_container_width=True)
    download_cols[1].download_button("下載甘特圖 HTML", gantt_html, "EastFu_APS_Gantt.html", mime="text/html", use_container_width=True)
    download_cols[2].download_button("一併下載 Excel + 甘特圖", package_bytes, "EastFu_APS_Package.zip", mime="application/zip", use_container_width=True)
