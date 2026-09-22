from __future__ import annotations

import math
import re

import pandas as pd

from .parser import get_schedule_window, normalize_workbook
from .strategies import sort_orders


MACHINES = ["C2", "C4", "C5"]


def eligible_rates(rates: pd.DataFrame, product: str) -> pd.DataFrame:
    return rates[rates["產品"] == product].copy().sort_values(["機台"]).reset_index(drop=True)


def allowed_machines(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    machines = []
    for item in re.split(r"[,，/、;；\s]+", str(value).upper().strip()):
        cleaned = item.strip()
        if cleaned:
            machines.append(cleaned)
    return machines


def _blocked_windows(unavailability: pd.DataFrame | None, machine: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if unavailability is None or unavailability.empty:
        return []
    frame = unavailability[unavailability["機台"] == machine].copy()
    return [(pd.Timestamp(r["不可用開始"]), pd.Timestamp(r["不可用結束"])) for _, r in frame.iterrows()]


def _calendar_blocks(availability: pd.DataFrame, machine: str, horizon_start: pd.Timestamp, horizon_end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if availability.empty or "機台" not in availability.columns:
        return []
    rows = availability[availability["機台"] == machine]
    if rows.empty:
        return [(horizon_start, horizon_end)]
    row = rows.iloc[0]
    available_start = max(pd.Timestamp(row["可用開始"]), horizon_start)
    available_end = min(pd.Timestamp(row["可用結束"]), horizon_end)
    blocks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    if horizon_start < available_start:
        blocks.append((horizon_start, available_start))
    if available_end < horizon_end:
        blocks.append((available_end, horizon_end))
    if available_start >= available_end:
        return [(horizon_start, horizon_end)]
    return blocks


def _next_available_start(candidate_start: pd.Timestamp, duration_hours: float, horizon_end: pd.Timestamp, blocks: list[tuple[pd.Timestamp, pd.Timestamp]]) -> pd.Timestamp | None:
    current = candidate_start
    duration = pd.to_timedelta(duration_hours, unit="h")
    for block_start, block_end in sorted(blocks):
        if current + duration <= block_start or current >= block_end:
            continue
        current = block_end
    return current if current + duration <= horizon_end else None


def _rate_changeover_group(candidate: pd.Series, order: pd.Series) -> str:
    group = candidate.get("換模群組", order.get("換模群組", order["產品"]))
    if group is None or pd.isna(group) or str(group).strip() == "":
        return str(order["產品"])
    return str(group).strip()


def _changeover_minutes(
    from_group: str | None,
    to_group: str,
    changeover_lookup: dict[tuple[str, str], float],
    default_changeover_minutes: float,
) -> float:
    if from_group is None:
        return 0.0
    if (from_group, to_group) in changeover_lookup:
        return float(changeover_lookup[(from_group, to_group)])
    if (from_group, "任何") in changeover_lookup:
        return float(changeover_lookup[(from_group, "任何")])
    if ("未知", "任何") in changeover_lookup and (not from_group or not to_group):
        return float(changeover_lookup[("未知", "任何")])
    return float(default_changeover_minutes)


def _changeover_lookup(changeover_df: pd.DataFrame) -> dict[tuple[str, str], float]:
    if changeover_df.empty or not {"來源換模群組", "目標換模群組", "換模時間_分鐘"}.issubset(changeover_df.columns):
        return {}
    lookup: dict[tuple[str, str], float] = {}
    for _, row in changeover_df.iterrows():
        if pd.isna(row["來源換模群組"]) or pd.isna(row["目標換模群組"]) or pd.isna(row["換模時間_分鐘"]):
            continue
        lookup[(str(row["來源換模群組"]).strip(), str(row["目標換模群組"]).strip())] = float(row["換模時間_分鐘"])
    return lookup


def _order_id(order: pd.Series) -> str:
    return str(order.get("工單編號", ""))


def _manual_priority_rank(order: pd.Series) -> int:
    return 0 if bool(order.get("指定優先", False)) else 1


def _completion_date(order: pd.Series) -> pd.Timestamp:
    completion = pd.to_datetime(order.get("完成日", order.get("交期")), errors="coerce")
    return pd.Timestamp.max if pd.isna(completion) else pd.Timestamp(completion)


def _append_unscheduled_row(rows: list[dict], sequence: int, order: pd.Series, status: str) -> None:
    rows.append(
        {
            "排程順序": sequence,
            "工單編號": order["工單編號"],
            "產品": order["產品"],
            "品名": order.get("品名", ""),
            "規格": order.get("規格", ""),
            "數量": float(order["數量"]),
            "單位": order.get("單位", "PCS"),
            "優先級": order["優先級"],
            "指定優先": bool(order.get("指定優先", False)),
            "交期": order["交期"],
            "完成日": order.get("完成日", order["交期"]),
            "最早可排日": order.get("最早可排日", pd.NaT),
            "換模群組": order.get("換模群組", pd.NA),
            "指派機台": "無合格機台" if status == "無合格機台" else "",
            "產速": 0.0,
            "加工時間（小時）": 0.0,
            "換模時間（小時）": 0.0,
            "開始時間": pd.NaT,
            "結束時間": pd.NaT,
            "狀態": status,
            "是否遲交": False,
            "遲交時間（小時）": 0.0,
            "等待時間（小時）": 0.0,
            "工單類型": "本次 APS 新排工單",
        }
    )


def _append_scheduled_row(
    rows: list[dict],
    sequence: int,
    order: pd.Series,
    chosen: pd.Series,
    item_start: pd.Timestamp,
    item_end: pd.Timestamp,
    horizon_start: pd.Timestamp,
) -> None:
    duration_hours = float(chosen["duration_hours"])
    changeover_hours = float(chosen.get("changeover_hours", 0.0))
    tardiness_hours = max((item_end - order["交期"]).total_seconds() / 3600, 0.0)
    wait_hours = max((item_start - horizon_start).total_seconds() / 3600, 0.0)
    setup_group = _rate_changeover_group(chosen, order)
    rows.append(
        {
            "排程順序": sequence,
            "工單編號": order["工單編號"],
            "產品": order["產品"],
            "品名": order.get("品名", ""),
            "規格": order.get("規格", ""),
            "數量": float(order["數量"]),
            "單位": order.get("單位", "PCS"),
            "優先級": order["優先級"],
            "指定優先": bool(order.get("指定優先", False)),
            "交期": order["交期"],
            "完成日": order.get("完成日", order["交期"]),
            "最早可排日": order.get("最早可排日", pd.NaT),
            "換模群組": setup_group,
            "指派機台": str(chosen["機台"]),
            "產速": float(chosen["產速_PCS_per_hr"]),
            "加工時間（小時）": round(duration_hours, 4),
            "換模時間（小時）": round(changeover_hours, 4),
            "開始時間": item_start,
            "結束時間": item_end,
            "狀態": "scheduled",
            "是否遲交": bool(item_end > order["交期"]),
            "遲交時間（小時）": round(tardiness_hours, 4),
            "等待時間（小時）": round(wait_hours, 4),
            "工單類型": "本次 APS 新排工單",
        }
    )


def _candidate_for_machine(
    order: pd.Series,
    rate: pd.Series,
    machine_ready: dict[str, pd.Timestamp],
    machine_last_group: dict[str, str | None],
    horizon_end: pd.Timestamp,
    default_changeover_minutes: float,
    changeover_lookup: dict[tuple[str, str], float],
    block_map: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]],
) -> pd.Series | None:
    candidate = rate.copy()
    machine = str(candidate["機台"])
    target_group = _rate_changeover_group(candidate, order)
    changeover_hours = _changeover_minutes(machine_last_group[machine], target_group, changeover_lookup, default_changeover_minutes) / 60
    duration_hours = float(order["數量"]) / float(candidate["產速_PCS_per_hr"])
    raw_start = machine_ready[machine] + pd.to_timedelta(changeover_hours, unit="h")
    release_date = pd.to_datetime(order.get("最早可排日"), errors="coerce")
    if pd.notna(release_date):
        raw_start = max(raw_start, pd.Timestamp(release_date))
    available_start = _next_available_start(raw_start, duration_hours, horizon_end, block_map.get(machine, []))
    if available_start is None:
        return None
    candidate["duration_hours"] = duration_hours
    candidate["changeover_hours"] = changeover_hours
    candidate["ready_time"] = available_start
    candidate["projected_end"] = available_start + pd.to_timedelta(duration_hours, unit="h")
    candidate["target_group"] = target_group
    return candidate


def _schedule_v2_default(
    orders: pd.DataFrame,
    rates: pd.DataFrame,
    rows: list[dict],
    machine_ready: dict[str, pd.Timestamp],
    machine_load: dict[str, float],
    machine_last_group: dict[str, str | None],
    start: pd.Timestamp,
    horizon_end: pd.Timestamp,
    default_changeover_minutes: float,
    changeover_lookup: dict[tuple[str, str], float],
    block_map: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]],
) -> pd.DataFrame:
    remaining = orders.copy()
    sequence = 1
    while not remaining.empty:
        decision_time = min(machine_ready.values())
        ready_machines = [machine for machine, ready in machine_ready.items() if ready == decision_time]
        candidates: list[tuple[tuple, int, pd.Series, pd.Series]] = []
        future_releases: list[pd.Timestamp] = []

        for idx, order in remaining.iterrows():
            options = eligible_rates(rates, order["產品"])
            allowed = allowed_machines(order.get("允許機台"))
            if allowed:
                options = options[options["機台"].astype(str).str.upper().isin(allowed)].copy()
            if options.empty:
                continue

            release_date = pd.to_datetime(order.get("最早可排日"), errors="coerce")
            if pd.notna(release_date) and pd.Timestamp(release_date) > decision_time:
                future_releases.append(pd.Timestamp(release_date))
                continue

            for _, rate in options.iterrows():
                machine = str(rate["機台"])
                if machine not in ready_machines:
                    continue
                candidate = _candidate_for_machine(order, rate, machine_ready, machine_last_group, horizon_end, default_changeover_minutes, changeover_lookup, block_map)
                if candidate is None:
                    continue
                sort_key = (
                    _manual_priority_rank(order),
                    _completion_date(order),
                    float(candidate["changeover_hours"]),
                    _order_id(order),
                    pd.Timestamp(candidate["projected_end"]),
                    machine,
                )
                candidates.append((sort_key, idx, order, candidate))

        if not candidates:
            if future_releases:
                next_release = min(ts for ts in future_releases if ts > decision_time)
                for machine in ready_machines:
                    machine_ready[machine] = min(next_release, horizon_end)
                if next_release < horizon_end:
                    continue

            later_machine_ready = [ready for ready in machine_ready.values() if ready > decision_time]
            if later_machine_ready:
                next_ready = min(later_machine_ready)
                for machine in ready_machines:
                    machine_ready[machine] = next_ready
                continue

            # Nothing can be scheduled from the current state. Emit clear unscheduled rows.
            ordered = sort_orders(remaining, rates, "v2_default")
            for _, order in ordered.iterrows():
                status = "無合格機台" if eligible_rates(rates, order["產品"]).empty else "超出排程期間"
                _append_unscheduled_row(rows, sequence, order, status)
                sequence += 1
            break

        candidates.sort(key=lambda item: item[0])
        _, order_idx, order, chosen = candidates[0]
        machine = str(chosen["機台"])
        item_start = pd.Timestamp(chosen["ready_time"])
        item_end = pd.Timestamp(chosen["projected_end"])
        _append_scheduled_row(rows, sequence, order, chosen, item_start, item_end, start)
        machine_ready[machine] = item_end
        machine_load[machine] += float(chosen["duration_hours"]) + float(chosen["changeover_hours"])
        machine_last_group[machine] = str(chosen["target_group"])
        remaining = remaining.drop(index=order_idx)
        sequence += 1

    result = pd.DataFrame(rows)
    if not result.empty:
        result["數量"] = result["數量"].apply(lambda v: v if pd.isna(v) else int(v) if math.isclose(v, int(v)) else v)
    return result


def _pick_machine(
    row: pd.Series,
    product_rates: pd.DataFrame,
    machine_ready: dict[str, pd.Timestamp],
    machine_load: dict[str, float],
    strategy_code: str,
    horizon_end: pd.Timestamp,
    machine_last_group: dict[str, str | None],
    default_changeover_minutes: float,
    changeover_lookup: dict[tuple[str, str], float],
    block_map: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]],
) -> pd.Series:
    candidates = product_rates.copy()
    candidates["ready_time"] = candidates["機台"].map(machine_ready)
    candidates["current_load"] = candidates["機台"].map(machine_load)
    candidates["duration_hours"] = row["數量"] / candidates["產速_PCS_per_hr"]
    starts = []
    changeovers = []
    projected_ends = []
    projected_tardiness = []
    for _, candidate in candidates.iterrows():
        machine = str(candidate["機台"])
        target_group = _rate_changeover_group(candidate, row)
        changeover = _changeover_minutes(machine_last_group[machine], target_group, changeover_lookup, default_changeover_minutes) / 60
        release_date = pd.to_datetime(row.get("最早可排日"), errors="coerce")
        feasible_start = machine_ready[machine] + pd.to_timedelta(changeover, unit="h")
        if pd.notna(release_date):
            feasible_start = max(feasible_start, pd.Timestamp(release_date))
        raw_start = feasible_start
        available_start = _next_available_start(raw_start, float(candidate["duration_hours"]), horizon_end, block_map.get(machine, []))
        starts.append(available_start if available_start is not None else pd.Timestamp.max)
        projected_ends.append(
            available_start + pd.to_timedelta(float(candidate["duration_hours"]), unit="h") if available_start is not None else pd.Timestamp.max
        )
        projected_tardiness.append(
            max(((available_start + pd.to_timedelta(float(candidate["duration_hours"]), unit="h")) - row["交期"]).total_seconds() / 3600, 0.0)
            if available_start is not None
            else 1_000_000_000.0
        )
        changeovers.append(changeover)
    candidates["ready_time"] = starts
    candidates["changeover_hours"] = changeovers
    candidates["projected_end"] = projected_ends
    candidates["projected_tardiness"] = projected_tardiness
    candidates["_can_fit"] = candidates["ready_time"] < pd.Timestamp.max
    schedulable = candidates[candidates["_can_fit"]].copy()
    if not schedulable.empty:
        candidates = schedulable
    if len(candidates) == 1:
        return candidates.iloc[0]
    if strategy_code == "changeover":
        return candidates.sort_values(["changeover_hours", "projected_end", "機台"], kind="mergesort").iloc[0]
    if strategy_code == "load_balance":
        return candidates.sort_values(["current_load", "duration_hours", "機台"], kind="mergesort").iloc[0]
    if strategy_code == "short_wait":
        return candidates.sort_values(["ready_time", "duration_hours", "機台"], kind="mergesort").iloc[0]
    if strategy_code == "lean":
        horizon_hours = max(candidates["duration_hours"].sum(), 1)
        candidates["_score"] = (
            candidates["projected_tardiness"] * 100
            + ((candidates["ready_time"] - min(machine_ready.values())).dt.total_seconds() / 3600).clip(lower=0) * 4
            + (candidates["current_load"] / horizon_hours) * 6
            + candidates["duration_hours"]
        )
        return candidates.sort_values(["_score", "projected_end", "機台"], kind="mergesort").iloc[0]
    return candidates.sort_values(["duration_hours", "ready_time", "機台"], kind="mergesort").iloc[0]


def schedule(
    workbook: dict[str, pd.DataFrame],
    strategy_code: str,
    manual_machine_overrides: dict[str, str] | None = None,
    horizon_start: pd.Timestamp | None = None,
    horizon_end: pd.Timestamp | None = None,
    default_changeover_minutes: float = 30,
    unavailability: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if "排程基本設定" not in workbook:
        workbook = normalize_workbook(workbook)
    manual_machine_overrides = manual_machine_overrides or {}
    orders = workbook["待排工單"].copy()
    rates = workbook["產品機台產速"].copy()
    settings = workbook["排程基本設定"]
    availability = workbook.get("機台可用時間", pd.DataFrame()).copy()
    changeover_df = workbook.get("換模時間", pd.DataFrame()).copy()
    orders["交期"] = pd.to_datetime(orders["交期"], errors="coerce")
    orders["數量"] = pd.to_numeric(orders["數量"], errors="coerce")
    rates["產速_PCS_per_hr"] = pd.to_numeric(rates["產速_PCS_per_hr"], errors="coerce")
    if not changeover_df.empty and "換模時間_分鐘" in changeover_df.columns:
        changeover_df["換模時間_分鐘"] = pd.to_numeric(changeover_df["換模時間_分鐘"], errors="coerce")
    if not availability.empty:
        availability["可用開始"] = pd.to_datetime(availability["可用開始"], errors="coerce")
        availability["可用結束"] = pd.to_datetime(availability["可用結束"], errors="coerce")
    start, horizon_end, _ = get_schedule_window(settings, horizon_start, horizon_end)
    machine_ready = {machine: start for machine in MACHINES}
    machine_load = {machine: 0.0 for machine in MACHINES}
    initial_state = workbook.get("機台初始狀態", pd.DataFrame()).copy()
    product_groups = rates.dropna(subset=["產品"]).drop_duplicates("產品").set_index("產品")["換模群組"].to_dict() if "換模群組" in rates.columns else {}
    changeover_lookup = _changeover_lookup(changeover_df)
    machine_last_group: dict[str, str | None] = {machine: None for machine in MACHINES}
    if not initial_state.empty and {"機台", "初始產品"}.issubset(initial_state.columns):
        for _, row in initial_state.iterrows():
            machine = str(row["機台"])
            if machine in machine_last_group and pd.notna(row["初始產品"]):
                initial_product = str(row["初始產品"])
                machine_last_group[machine] = str(product_groups.get(initial_product, initial_product))
    rows = []
    initial_wip = workbook.get("期初在製", pd.DataFrame()).copy()
    if not initial_wip.empty and "機台" in initial_wip.columns:
        for _, wip in initial_wip.iterrows():
            machine = str(wip.get("機台", "")).strip()
            if machine not in machine_ready:
                continue
            product = wip.get("產品品號", wip.get("產品", "期初在製"))
            finish = pd.to_datetime(wip.get("預計完成時間"), errors="coerce")
            if pd.isna(finish):
                remaining_qty = pd.to_numeric(pd.Series([wip.get("剩餘數量")]), errors="coerce").iloc[0]
                rate_rows = rates[(rates["產品"].astype(str) == str(product)) & (rates["機台"].astype(str) == machine)]
                if pd.notna(remaining_qty) and not rate_rows.empty and float(rate_rows.iloc[0]["產速_PCS_per_hr"]) > 0:
                    finish = start + pd.to_timedelta(float(remaining_qty) / float(rate_rows.iloc[0]["產速_PCS_per_hr"]), unit="h")
            if pd.isna(finish):
                continue
            finish = max(pd.Timestamp(finish), start)
            raw_qty = pd.to_numeric(pd.Series([wip.get("剩餘數量", 0)]), errors="coerce").iloc[0]
            wip_qty = 0.0 if pd.isna(raw_qty) else float(raw_qty)
            machine_ready[machine] = finish
            setup_group = wip.get("目前換模群組")
            if pd.isna(setup_group) or str(setup_group).strip() == "":
                setup_group = product_groups.get(str(product), str(product))
            machine_last_group[machine] = str(setup_group)
            rows.append(
                {
                    "排程順序": 0,
                    "工單編號": wip.get("製令單號", f"{machine}-期初在製"),
                    "產品": product,
                    "品名": wip.get("品名", ""),
                    "規格": wip.get("規格", ""),
                    "數量": wip_qty,
                    "單位": wip.get("單位", "PCS"),
                    "優先級": "期初在製",
                    "指定優先": False,
                    "交期": pd.NaT,
                    "完成日": pd.NaT,
                    "最早可排日": pd.NaT,
                    "換模群組": str(setup_group),
                    "指派機台": machine,
                    "產速": 0.0,
                    "加工時間（小時）": round((finish - start).total_seconds() / 3600, 4),
                    "換模時間（小時）": 0.0,
                    "開始時間": start,
                    "結束時間": finish,
                    "狀態": "scheduled",
                    "是否遲交": False,
                    "遲交時間（小時）": 0.0,
                    "等待時間（小時）": 0.0,
                    "工單類型": "期初在製",
                }
            )
    block_map = {
        machine: _calendar_blocks(availability, machine, start, horizon_end) + _blocked_windows(unavailability, machine)
        for machine in MACHINES
    }
    if strategy_code == "v2_default":
        return _schedule_v2_default(
            orders,
            rates,
            rows,
            machine_ready,
            machine_load,
            machine_last_group,
            start,
            horizon_end,
            default_changeover_minutes,
            changeover_lookup,
            block_map,
        )
    sorted_orders = sort_orders(orders, rates, strategy_code)
    for sequence, (_, order) in enumerate(sorted_orders.iterrows(), start=1):
        options = eligible_rates(rates, order["產品"])
        allowed = allowed_machines(order.get("允許機台"))
        if allowed:
            options = options[options["機台"].astype(str).str.upper().isin(allowed)].copy()
        if options.empty:
            rows.append(
                {
                    "排程順序": sequence,
                    "工單編號": order["工單編號"],
                    "產品": order["產品"],
                    "數量": float(order["數量"]),
                    "單位": order.get("單位", "PCS"),
                    "優先級": order["優先級"],
                    "交期": order["交期"],
                    "完成日": order.get("完成日", order["交期"]),
                    "最早可排日": order.get("最早可排日", pd.NaT),
                    "指派機台": "無合格機台",
                    "產速": 0.0,
                    "加工時間（小時）": 0.0,
                    "換模時間（小時）": 0.0,
                    "開始時間": pd.NaT,
                    "結束時間": pd.NaT,
                    "狀態": "無合格機台",
                    "是否遲交": False,
                    "遲交時間（小時）": 0.0,
                    "等待時間（小時）": 0.0,
                    "工單類型": "本次 APS 新排工單",
                }
            )
            continue
        override = manual_machine_overrides.get(str(order["工單編號"]))
        if override and override in set(options["機台"]):
            chosen = options[options["機台"] == override].iloc[0].copy()
            chosen["duration_hours"] = order["數量"] / chosen["產速_PCS_per_hr"]
            target_group = _rate_changeover_group(chosen, order)
            changeover = _changeover_minutes(machine_last_group[override], target_group, changeover_lookup, default_changeover_minutes) / 60
            raw_start = machine_ready[override] + pd.to_timedelta(changeover, unit="h")
            release_date = pd.to_datetime(order.get("最早可排日"), errors="coerce")
            if pd.notna(release_date):
                raw_start = max(raw_start, pd.Timestamp(release_date))
            chosen["ready_time"] = _next_available_start(raw_start, float(chosen["duration_hours"]), horizon_end, block_map.get(override, [])) or pd.Timestamp.max
            chosen["changeover_hours"] = changeover
        else:
            chosen = _pick_machine(order, options, machine_ready, machine_load, strategy_code, horizon_end, machine_last_group, default_changeover_minutes, changeover_lookup, block_map)
        machine = str(chosen["機台"])
        rate = float(chosen["產速_PCS_per_hr"])
        duration_hours = float(order["數量"]) / rate
        changeover_hours = float(chosen.get("changeover_hours", 0.0))
        item_start = chosen.get("ready_time", machine_ready[machine] + pd.to_timedelta(changeover_hours, unit="h"))
        can_schedule = pd.Timestamp(item_start) < pd.Timestamp.max
        visible_start = item_start if can_schedule else pd.NaT
        item_end = item_start + pd.to_timedelta(duration_hours, unit="h") if can_schedule else pd.NaT
        tardiness_hours = max((item_end - order["交期"]).total_seconds() / 3600, 0.0) if can_schedule else 0.0
        wait_hours = max((item_start - start).total_seconds() / 3600, 0.0) if can_schedule else 0.0
        if can_schedule:
            machine_ready[machine] = item_end
            machine_load[machine] += duration_hours + changeover_hours
            machine_last_group[machine] = _rate_changeover_group(chosen, order)
        rows.append(
            {
                "排程順序": sequence,
                "工單編號": order["工單編號"],
                "產品": order["產品"],
                "數量": float(order["數量"]),
                "單位": order.get("單位", "PCS"),
                "優先級": order["優先級"],
                "交期": order["交期"],
                "完成日": order.get("完成日", order["交期"]),
                "最早可排日": order.get("最早可排日", pd.NaT),
                "指派機台": machine,
                "產速": rate,
                "加工時間（小時）": round(duration_hours, 4),
                "換模時間（小時）": round(changeover_hours, 4),
                "開始時間": visible_start,
                "結束時間": item_end,
                "狀態": "scheduled" if can_schedule else "超出排程期間",
                "是否遲交": bool(can_schedule and item_end > order["交期"]),
                "遲交時間（小時）": round(tardiness_hours, 4),
                "等待時間（小時）": round(wait_hours, 4),
                "工單類型": "本次 APS 新排工單",
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["數量"] = result["數量"].apply(lambda v: v if pd.isna(v) else int(v) if math.isclose(v, int(v)) else v)
    return result
