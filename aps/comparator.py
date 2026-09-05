from __future__ import annotations

import pandas as pd

from .metrics import calculate_kpis
from .scheduler import schedule
from .strategies import STRATEGIES


COMPARE_COLUMNS = [
    "策略",
    "完成工單數",
    "準時完成率",
    "遲交工單數",
    "總遲交時間",
    "平均遲交時間",
    "Makespan",
    "平均等待時間",
    "C2 使用率",
    "C4 使用率",
    "C5 使用率",
    "負載不均衡",
    "換模次數",
]


def compare_strategies(workbook: dict[str, pd.DataFrame], strategy_codes: list[str]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    schedules: dict[str, pd.DataFrame] = {}
    rows = []
    for code in strategy_codes:
        result = schedule(workbook, code)
        schedules[code] = result
        kpis = calculate_kpis(result, workbook["排程基本設定"])
        rows.append(
            {
                "策略代碼": code,
                "策略": STRATEGIES[code].name,
                "完成工單數": kpis["完成工單數"],
                "準時完成率": round(kpis["準時完成率"], 2),
                "遲交工單數": kpis["遲交工單數"],
                "總遲交時間": round(kpis["總遲交時間"], 2),
                "平均遲交時間": round(kpis["平均遲交時間"], 2),
                "Makespan": round(kpis["Makespan"], 2),
                "平均等待時間": round(kpis["平均等待時間"], 2),
                "C2 使用率": round(kpis["C2 utilization"], 2),
                "C4 使用率": round(kpis["C4 utilization"], 2),
                "C5 使用率": round(kpis["C5 utilization"], 2),
                "負載不均衡": round(kpis["Resource Load Imbalance"], 2),
                "換模次數": kpis.get("換模次數", 0),
            }
        )
    return pd.DataFrame(rows), schedules


def recommend_strategy(comparison: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    ranked = comparison.sort_values(
        ["準時完成率", "總遲交時間", "平均等待時間", "負載不均衡", "Makespan"],
        ascending=[False, True, True, True, True],
        kind="mergesort",
    )
    best = ranked.iloc[0]
    reasons = [
        f"準時完成率為 {best['準時完成率']:.2f}%",
        f"總遲交時間為 {best['總遲交時間']:.2f} 小時",
        f"平均等待時間為 {best['平均等待時間']:.2f} 小時",
        f"負載不均衡為 {best['負載不均衡']:.2f} 個百分點",
    ]
    return best, reasons
