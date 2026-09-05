from __future__ import annotations

from pathlib import Path

import pandas as pd


SCHEDULE_START = pd.Timestamp("2026-09-03 08:00")
SCHEDULE_END = pd.Timestamp("2026-09-04 08:00")


def demo_orders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["UAT-260903-001", "SIM-C2-A", 600, "PCS", "急單", "2026-09-04"],
            ["UAT-260903-002", "SIM-C2-B", 480, "PCS", "一般", "2026-09-04"],
            ["UAT-260903-003", "SIM-MULTI-A", 360, "PCS", "一般", "2026-09-04"],
            ["UAT-260903-004", "SIM-C4-A", 720, "PCS", "急單", "2026-09-04"],
            ["UAT-260903-005", "SIM-C4-B", 540, "PCS", "一般", "2026-09-05"],
            ["UAT-260903-006", "SIM-MULTI-B", 420, "PCS", "低優先", "2026-09-05"],
            ["UAT-260903-007", "SIM-C5-A", 900, "PCS", "急單", "2026-09-04"],
            ["UAT-260903-008", "SIM-C5-B", 660, "PCS", "一般", "2026-09-05"],
            ["UAT-260903-009", "SIM-MULTI-C", 300, "PCS", "一般", "2026-09-04"],
            ["UAT-260903-010", "SIM-C2-C", 840, "PCS", "低優先", "2026-09-05"],
        ],
        columns=["工單編號", "產品", "數量", "單位", "優先級", "交期"],
    )


def demo_rates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["SIM-C2-A", "C2", 120],
            ["SIM-C2-B", "C2", 96],
            ["SIM-MULTI-A", "C2", 90],
            ["SIM-MULTI-A", "C4", 84],
            ["SIM-C4-A", "C4", 144],
            ["SIM-C4-B", "C4", 108],
            ["SIM-MULTI-B", "C4", 84],
            ["SIM-MULTI-B", "C5", 78],
            ["SIM-C5-A", "C5", 150],
            ["SIM-C5-B", "C5", 110],
            ["SIM-MULTI-C", "C5", 100],
            ["SIM-MULTI-C", "C2", 92],
            ["SIM-C2-C", "C2", 140],
        ],
        columns=["產品", "機台", "產速_PCS_per_hr"],
    )


def demo_availability() -> pd.DataFrame:
    return pd.DataFrame(
        [["C2", SCHEDULE_START, SCHEDULE_END], ["C4", SCHEDULE_START, SCHEDULE_END], ["C5", SCHEDULE_START, SCHEDULE_END]],
        columns=["機台", "可用開始", "可用結束"],
    )


def demo_settings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["排程開始", SCHEDULE_START],
            ["排程結束", SCHEDULE_END],
            ["時區", "Asia/Taipei"],
            ["允許跨班", "是"],
        ],
        columns=["設定項目", "設定值"],
    )


def demo_initial_state() -> pd.DataFrame:
    return pd.DataFrame(
        [["C2", "SIM-C2-A"], ["C4", "SIM-C4-A"], ["C5", "SIM-C5-A"]],
        columns=["機台", "初始產品"],
    )


def demo_workbook() -> dict[str, pd.DataFrame]:
    return {
        "待排工單": demo_orders(),
        "產品機台產速": demo_rates(),
        "機台可用時間": demo_availability(),
        "排程基本設定": demo_settings(),
        "機台初始狀態": demo_initial_state(),
    }


def write_demo_excel(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, frame in demo_workbook().items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return path
