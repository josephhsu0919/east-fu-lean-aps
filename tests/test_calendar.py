from datetime import time

import pandas as pd

from aps.calendar import build_calendar_unavailability, parse_non_working_dates


def test_parse_non_working_dates_accepts_lines_and_commas():
    dates = parse_non_working_dates("2026-09-28\n2026-10-10, 2026-10-10")
    assert dates == [pd.Timestamp("2026-09-28"), pd.Timestamp("2026-10-10")]


def test_24_hour_work_mode_adds_no_shift_blocks():
    blocks = build_calendar_unavailability(
        ["C2"],
        pd.Timestamp("2026-09-04 08:00"),
        pd.Timestamp("2026-09-05 08:00"),
        work_time_mode="24 小時連續排程",
    )
    assert blocks.empty


def test_daily_8_hour_work_mode_blocks_after_shift():
    blocks = build_calendar_unavailability(
        ["C2"],
        pd.Timestamp("2026-09-04 08:00"),
        pd.Timestamp("2026-09-05 08:00"),
        work_time_mode="每日 8 小時排程",
        workday_start=time(8, 0),
        daily_work_hours=8,
    )
    assert len(blocks) == 2
    assert blocks.loc[0, "不可用開始"] == pd.Timestamp("2026-09-04 16:00")
    assert blocks.loc[0, "不可用結束"] == pd.Timestamp("2026-09-05 00:00")
    assert blocks.loc[1, "不可用開始"] == pd.Timestamp("2026-09-05 00:00")
    assert blocks.loc[1, "不可用結束"] == pd.Timestamp("2026-09-05 08:00")


def test_daily_8_hour_work_mode_blocks_weekends_full_day():
    blocks = build_calendar_unavailability(
        ["C2", "C4"],
        pd.Timestamp("2026-09-04 08:00"),
        pd.Timestamp("2026-09-07 08:00"),
        exclude_weekends=True,
        work_time_mode="每日 8 小時排程",
        workday_start=time(8, 0),
        daily_work_hours=8,
    )
    weekend = blocks[blocks["不可用開始"] == pd.Timestamp("2026-09-05 00:00")]
    assert set(weekend["機台"]) == {"C2", "C4"}
