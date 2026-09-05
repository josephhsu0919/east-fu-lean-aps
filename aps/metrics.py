from __future__ import annotations

import pandas as pd

from .parser import get_schedule_window
from .scheduler import MACHINES


def calculate_kpis(schedule_df: pd.DataFrame, settings: pd.DataFrame) -> dict[str, float]:
    start, end, _ = get_schedule_window(settings)
    horizon_hours = (end - start).total_seconds() / 3600
    scheduled = schedule_df[schedule_df["狀態"] == "scheduled"].copy()
    completed = int((schedule_df["狀態"] == "scheduled").sum())
    incomplete = int((schedule_df["狀態"] != "scheduled").sum())
    tardy_count = int(scheduled["是否遲交"].sum()) if not scheduled.empty else 0
    on_time = int((~scheduled["是否遲交"]).sum()) if not scheduled.empty else 0
    total = len(schedule_df)
    total_tardiness = float(schedule_df["遲交時間（小時）"].sum())
    avg_tardiness = total_tardiness / total if total else 0.0
    max_tardiness = float(schedule_df["遲交時間（小時）"].max()) if total else 0.0
    makespan = ((scheduled["結束時間"].max() - start).total_seconds() / 3600) if not scheduled.empty else 0.0
    total_wait = float(schedule_df["等待時間（小時）"].sum())
    avg_wait = total_wait / total if total else 0.0
    loads = scheduled.groupby("指派機台")["加工時間（小時）"].sum().to_dict()
    utilizations = {machine: (loads.get(machine, 0.0) / horizon_hours * 100 if horizon_hours else 0.0) for machine in MACHINES}
    avg_utilization = sum(utilizations.values()) / len(MACHINES)
    load_imbalance = max(utilizations.values()) - min(utilizations.values())
    return {
        "完成工單數": completed,
        "未完成 / 超出 horizon 工單數": incomplete,
        "準時完成率": on_time / total * 100 if total else 0.0,
        "遲交工單數": tardy_count,
        "總遲交時間": total_tardiness,
        "平均遲交時間": avg_tardiness,
        "最大遲交時間": max_tardiness,
        "Makespan": makespan,
        "平均等待時間": avg_wait,
        "總等待時間": total_wait,
        "C2 utilization": utilizations["C2"],
        "C4 utilization": utilizations["C4"],
        "C5 utilization": utilizations["C5"],
        "平均 utilization": avg_utilization,
        "Resource Load Imbalance": load_imbalance,
        "換模次數": int((scheduled.get("換模時間（小時）", 0) > 0).sum()) if not scheduled.empty else 0,
    }


def kpis_to_frame(kpis: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{"KPI": key, "數值": round(value, 4) if isinstance(value, float) else value} for key, value in kpis.items()])
