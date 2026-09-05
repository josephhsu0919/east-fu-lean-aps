from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, time
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from aps.calendar import build_calendar_unavailability, parse_non_working_dates
from aps.comparator import compare_strategies, recommend_strategy
from aps.exporter import export_schedule_excel
from aps.history import create_schedule_version, load_history, version_orders_frame, version_schedule_frame
from aps.metrics import calculate_kpis, kpis_to_frame
from aps.parser import get_schedule_window, load_workbook
from aps.sample_data import demo_workbook, write_demo_excel
from aps.scheduler import MACHINES, schedule
from aps.strategies import STRATEGIES
from aps.validator import validate_workbook
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
    div[data-testid="stMetricValue"] { font-size: 2.2rem; }
    h1 { font-size: 2.6rem; }
    h2, h3 { font-size: 1.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state() -> None:
    defaults = {
        "workbook": None,
        "validation": None,
        "schedule_df": None,
        "kpis": None,
        "comparison_df": None,
        "selected_strategy": "rush_edd",
        "upload_filename": "demo",
        "horizon_mode": "24 小時",
        "custom_start": pd.Timestamp("2026-09-03 08:00"),
        "custom_end": pd.Timestamp("2026-09-04 08:00"),
        "changeover_minutes": 30,
        "unavailability": pd.DataFrame(columns=["機台", "不可用開始", "不可用結束", "原因"]),
        "work_time_mode": "24 小時連續排程",
        "workday_start_time": time(8, 0),
        "daily_work_hours": 8,
        "exclude_weekends": False,
        "non_working_dates": "",
        "assistant_question": "",
        "last_version": None,
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
    base_start, _, _ = get_schedule_window(data["排程基本設定"])
    mode = st.session_state.horizon_mode
    if mode == "自訂":
        return pd.Timestamp(st.session_state.custom_start), pd.Timestamp(st.session_state.custom_end)
    return base_start, base_start + pd.to_timedelta(HORIZON_HOURS[mode], unit="h")


def with_horizon_settings(data: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    copied = {name: frame.copy() for name, frame in data.items()}
    settings = copied["排程基本設定"].copy()
    settings.loc[settings["設定項目"] == "排程開始", "設定值"] = start
    settings.loc[settings["設定項目"] == "排程結束", "設定值"] = end
    copied["排程基本設定"] = settings
    return copied


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
    return build_calendar_unavailability(
        MACHINES,
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


FAQ_ANSWERS = [
    (
        ["excel", "欄位", "資料", "準備", "上傳"],
        "Excel 至少需要 `待排工單`、`產品機台產速`、`機台可用時間`、`排程基本設定`。待排工單要有工單編號、產品、數量、單位、優先級、交期；產品機台產速要有產品、機台、產速。",
    ),
    (
        ["允許機台", "限定機台", "c4", "c5", "指定機台"],
        "`產品機台產速` 用來定義產品原則上可在哪些機台做；`待排工單` 的 `允許機台` 是單張工單的例外限制，例如 `C4,C5`。",
    ),
    (
        ["換模", "換線", "群組"],
        "`換模群組` 是產品族群。排程時若前後工單群組不同，會查 `換模時間` 表的來源群組到目標群組分鐘數；查不到才用預設換模時間。",
    ),
    (
        ["週末", "假日", "國定", "不排程", "休假"],
        "在 `基本設定` 勾選 `週末不排程`，國定假日可填在 `指定日期不排程`。系統會把那些日期轉成全機台不可用時段。",
    ),
    (
        ["8小時", "8 小時", "工時", "24小時", "24 小時", "上班"],
        "`工時模式` 可選 `24 小時連續排程` 或 `每日 8 小時排程`。每日 8 小時會從你設定的每日開始時間往後排指定工時，其餘時間不排程。",
    ),
    (
        ["甘特", "圖", "下載", "匯出"],
        "排程完成後，結果區下方可下載排程 Excel、甘特圖 HTML，或一次下載 Excel + 甘特圖 ZIP。",
    ),
    (
        ["排不進去", "無合格機台", "超出", "不能排"],
        "常見原因是排程期間太短、產品沒有產速、工單限定機台後沒有合格機台、休假/停機時段太多，或每日 8 小時模式下單張工單加工時間超過可用工時。",
    ),
]


def answer_usage_question(question: str) -> str:
    text = question.strip().lower()
    if not text:
        return "請輸入你遇到的操作問題，例如：換模群組怎麼填、為什麼排不進去、C4/C5 怎麼指定。"
    scored = []
    for keywords, answer in FAQ_ANSWERS:
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        if score:
            scored.append((score, answer))
    if scored:
        return sorted(scored, reverse=True)[0][1]
    return "目前小幫手還沒有完全對應這個問題。你可以先檢查：Excel 必要欄位、產品機台產速、排程期間、工時模式、週末/假日設定、以及工單是否有限定機台。"


def load_demo() -> None:
    write_demo_excel(DEMO_EXCEL_PATH)
    st.session_state.workbook = load_workbook(DEMO_EXCEL_PATH)
    st.session_state.validation = validate_workbook(st.session_state.workbook)
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
        st.session_state.schedule_df = result
        st.session_state.kpis = kpis
        st.session_state.workbook = data
        st.session_state.validation = validate_workbook(data)
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
                "work_time_mode": st.session_state.work_time_mode,
                "workday_start_time": st.session_state.workday_start_time.strftime("%H:%M"),
                "daily_work_hours": st.session_state.daily_work_hours,
                "exclude_weekends": st.session_state.exclude_weekends,
                "non_working_dates": [day.strftime("%Y-%m-%d") for day in parse_non_working_dates(st.session_state.non_working_dates)],
            },
        )
        st.success("排程完成")
    except Exception:
        st.error("排程時發生問題，請確認 Excel 欄位、產速與排程期間設定。")


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


init_state()
st.title("東福精實生產排程系統")
st.caption("Excel 驅動的 Lean APS 排程與決策支援工具")

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
with controls[1]:
    st.session_state.selected_strategy = st.selectbox("排程策略", MAIN_STRATEGIES, format_func=lambda code: STRATEGIES[code].name)

quick = st.columns(3)
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
    with st.expander("⚠ 今日異常"):
        down_machine = st.selectbox("Machine", MACHINES)
        down_from = datetime_fields("Unavailable from", pd.Timestamp("2026-09-03 12:00"), "down_from")
        down_until = datetime_fields("Unavailable until", pd.Timestamp("2026-09-03 14:00"), "down_until")
        reason = st.text_input("Reason", value="")
        if st.button("重新排程", key="downtime_replan", use_container_width=True):
            st.session_state.unavailability = pd.concat(
                [
                    st.session_state.unavailability,
                    pd.DataFrame([{"機台": down_machine, "不可用開始": down_from, "不可用結束": down_until, "原因": reason}]),
                ],
                ignore_index=True,
            )
            run_schedule("MACHINE_DOWN")
with quick[2]:
    with st.expander("歷史排程"):
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

with st.expander("基本設定", expanded=data is not None):
    if data is None:
        st.caption("載入資料後可查看與編輯基本設定。")
    else:
        st.session_state.work_time_mode = st.radio("工時模式", ["24 小時連續排程", "每日 8 小時排程"], horizontal=True)
        if st.session_state.work_time_mode == "每日 8 小時排程":
            work_cols = st.columns(2)
            st.session_state.workday_start_time = work_cols[0].time_input("每日開始時間", value=st.session_state.workday_start_time)
            st.session_state.daily_work_hours = work_cols[1].number_input("每日可排工時", min_value=1.0, max_value=24.0, value=float(st.session_state.daily_work_hours), step=0.5)
        st.session_state.changeover_minutes = st.number_input("預設換模時間（分鐘）", min_value=0, value=int(st.session_state.changeover_minutes), step=5)
        st.session_state.exclude_weekends = st.checkbox("週末不排程（星期六、星期日）", value=bool(st.session_state.exclude_weekends))
        st.session_state.non_working_dates = st.text_area("指定日期不排程（國定假日 / 盤點 / 全廠休假）", value=st.session_state.non_working_dates, placeholder="例如：\n2026-09-28\n2026-10-10")
        st.caption("若待排工單有 `允許機台` 欄位，可填 C5 或 C4,C5；空白代表依產品機台產速表自動選機台。")
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

action_cols = st.columns([2, 1])
with action_cols[1]:
    if st.button("確認設定並開始排程", type="primary", disabled=data is None, use_container_width=True):
        run_schedule("INITIAL")

with st.expander("操作問題小幫手", expanded=False):
    st.session_state.assistant_question = st.text_input("請輸入操作問題", value=st.session_state.assistant_question, placeholder="例如：為什麼某張工單排不進去？")
    if st.session_state.assistant_question:
        st.info(answer_usage_question(st.session_state.assistant_question))

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
