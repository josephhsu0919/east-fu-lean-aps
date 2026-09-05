from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


PRIORITY_RANK = {"急單": 0, "一般": 1, "低優先": 2}


@dataclass(frozen=True)
class Strategy:
    code: str
    name: str
    description: str


STRATEGIES = {
    "rush_edd": Strategy("rush_edd", "急單優先＋最早交期", "急單優先，同級依交期與工單編號排序。"),
    "edd": Strategy("edd", "最早交期優先", "依交期早晚排序，再依工單編號。"),
    "fifo": Strategy("fifo", "先進先出", "依 Excel 原始列順序排序。"),
    "spt": Strategy("spt", "最短加工時間優先", "依各工單最短可行加工時間排序。"),
    "changeover": Strategy("changeover", "減少換模", "同優先級與交期下盡量集中相同產品。"),
    "short_wait": Strategy("short_wait", "最短等待時間優先", "每張工單選可最早開始的合格機台。"),
    "load_balance": Strategy("load_balance", "機台負載平衡", "多機台產品優先選累積負荷較低的合格機台。"),
    "lean": Strategy("lean", "東福 Lean 綜合排程", "急單與交期優先，資源選擇兼顧等待、遲交與負載平衡。"),
}


def strategy_options() -> dict[str, str]:
    return {code: strategy.name for code, strategy in STRATEGIES.items()}


def sort_orders(orders: pd.DataFrame, rates: pd.DataFrame, strategy_code: str) -> pd.DataFrame:
    frame = orders.copy()
    frame["_priority_rank"] = frame["優先級"].map(PRIORITY_RANK).fillna(9)
    if strategy_code in {"rush_edd", "lean", "short_wait", "load_balance"}:
        return frame.sort_values(["_priority_rank", "交期", "工單編號"], kind="mergesort").reset_index(drop=True)
    if strategy_code == "changeover":
        return frame.sort_values(["_priority_rank", "產品", "交期", "工單編號"], kind="mergesort").reset_index(drop=True)
    if strategy_code == "edd":
        return frame.sort_values(["交期", "工單編號"], kind="mergesort").reset_index(drop=True)
    if strategy_code == "fifo":
        return frame.sort_values(["_原始順序"], kind="mergesort").reset_index(drop=True)
    if strategy_code == "spt":
        fastest = rates.groupby("產品")["產速_PCS_per_hr"].max()
        frame["_min_processing_hours"] = frame.apply(lambda r: r["數量"] / fastest.loc[r["產品"]], axis=1)
        return frame.sort_values(["_min_processing_hours", "交期", "工單編號"], kind="mergesort").reset_index(drop=True)
    raise ValueError(f"未知排程策略：{strategy_code}")
