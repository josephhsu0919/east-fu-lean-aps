from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd


HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "schedule_history.json"


def _is_missing_scalar(value: Any) -> bool:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, bool) else False


def _json_ready(value: Any) -> Any:
    if _is_missing_scalar(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, pd.Timedelta):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        return _json_ready(value.item())
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = frame.to_dict(orient="records")
    return [_json_ready(record) for record in records]


def _records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in ["交期", "開始時間", "結束時間"]:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def load_history(path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            history = json.load(handle)
    except json.JSONDecodeError:
        return []
    return history if isinstance(history, list) else []


def save_history(history: list[dict[str, Any]], path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(_json_ready(history), handle, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def next_version_id(history: list[dict[str, Any]]) -> str:
    return f"V{len(history) + 1:03d}"


def create_schedule_version(
    workbook: dict[str, pd.DataFrame],
    schedule_df: pd.DataFrame,
    kpis: dict[str, float],
    strategy_code: str,
    strategy_name: str,
    horizon_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
    reason: str,
    upload_filename: str = "demo",
    input_source: str = "Excel",
    unavailability: pd.DataFrame | None = None,
    default_changeover_minutes: float = 30,
    manual_adjustment: dict[str, Any] | None = None,
    rule_configuration: dict[str, Any] | None = None,
    path: Path = HISTORY_PATH,
) -> dict[str, Any]:
    history = load_history(path)
    version = {
        "version_id": next_version_id(history),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_source": input_source,
        "upload_filename": upload_filename,
        "order_count": int(len(workbook["待排工單"])),
        "horizon_start": pd.Timestamp(horizon_start).strftime("%Y-%m-%d %H:%M:%S"),
        "horizon_end": pd.Timestamp(horizon_end).strftime("%Y-%m-%d %H:%M:%S"),
        "scheduling_rule": strategy_code,
        "scheduling_rule_name": strategy_name,
        "rule_configuration": rule_configuration or {"strategy_code": strategy_code},
        "reason": reason,
        "changeover_configuration": {
            "default_changeover_minutes": default_changeover_minutes,
            "same_group_minutes": 0,
            "changeover_table": _frame_to_records(workbook.get("換模時間", pd.DataFrame())),
        },
        "machine_initial_state": _frame_to_records(workbook.get("機台初始狀態", pd.DataFrame())),
        "manual_adjustment": manual_adjustment or {},
        "orders": _frame_to_records(workbook["待排工單"]),
        "processing_rate_snapshot": _frame_to_records(workbook["產品機台產速"]),
        "resource_availability_snapshot": _frame_to_records(workbook.get("機台可用時間", pd.DataFrame())),
        "rates": _frame_to_records(workbook["產品機台產速"]),
        "availability": _frame_to_records(workbook.get("機台可用時間", pd.DataFrame())),
        "unavailability": _frame_to_records(unavailability if unavailability is not None else pd.DataFrame()),
        "schedule": _frame_to_records(schedule_df),
        "kpis": kpis,
    }
    history.append(version)
    save_history(history, path)
    return version


def version_schedule_frame(version: dict[str, Any]) -> pd.DataFrame:
    return _records_to_frame(version.get("schedule", []))


def version_orders_frame(version: dict[str, Any]) -> pd.DataFrame:
    return _records_to_frame(version.get("orders", []))
