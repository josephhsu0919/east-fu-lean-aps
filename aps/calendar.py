from __future__ import annotations

from datetime import time

import pandas as pd


def parse_non_working_dates(text: str) -> list[pd.Timestamp]:
    dates: list[pd.Timestamp] = []
    for item in str(text).replace(",", "\n").replace("，", "\n").splitlines():
        item = item.strip()
        if not item:
            continue
        parsed = pd.to_datetime(item, errors="coerce")
        if pd.notna(parsed):
            dates.append(pd.Timestamp(parsed).normalize())
    return sorted(set(dates))


def _combine(day: pd.Timestamp, clock: time) -> pd.Timestamp:
    return pd.Timestamp.combine(day.date(), clock)


def build_calendar_unavailability(
    machines: list[str],
    horizon_start: pd.Timestamp,
    horizon_end: pd.Timestamp,
    exclude_weekends: bool = False,
    non_working_dates: str = "",
    work_time_mode: str = "24 小時連續排程",
    workday_start: time = time(8, 0),
    daily_work_hours: float = 8,
) -> pd.DataFrame:
    start = pd.Timestamp(horizon_start)
    end = pd.Timestamp(horizon_end)
    days = list(pd.date_range(start.normalize(), end.normalize(), freq="D"))
    full_day_blocks: set[pd.Timestamp] = set(parse_non_working_dates(non_working_dates))
    if exclude_weekends:
        full_day_blocks.update(pd.Timestamp(day).normalize() for day in days if day.weekday() >= 5)

    rows = []
    for day in days:
        day = pd.Timestamp(day).normalize()
        day_start = max(day, start)
        day_end = min(day + pd.Timedelta(days=1), end)
        if day_start >= day_end:
            continue
        if day in full_day_blocks:
            work_blocks = [(day_start, day_end)]
        elif work_time_mode == "每日 8 小時排程":
            work_start = max(_combine(day, workday_start), start)
            work_end = min(_combine(day, workday_start) + pd.to_timedelta(daily_work_hours, unit="h"), day_end)
            work_blocks = []
            if day_start < work_start:
                work_blocks.append((day_start, work_start))
            if work_end < day_end:
                work_blocks.append((work_end, day_end))
            if work_start >= work_end:
                work_blocks = [(day_start, day_end)]
        else:
            work_blocks = []

        for block_start, block_end in work_blocks:
            for machine in machines:
                rows.append({"機台": machine, "不可用開始": block_start, "不可用結束": block_end, "原因": "工時模式/休假日"})
    return pd.DataFrame(rows, columns=["機台", "不可用開始", "不可用結束", "原因"])
