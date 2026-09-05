from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def _data():
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    return data


def test_sim_multi_c_never_goes_to_c4():
    data = _data()
    for code in ["rush_edd", "edd", "fifo", "spt", "short_wait", "load_balance", "lean"]:
        result = schedule(data, code)
        row = result[result["產品"] == "SIM-MULTI-C"].iloc[0]
        assert row["指派機台"] != "C4"


def test_same_machine_has_no_overlap():
    result = schedule(_data(), "lean")
    for _, group in result.sort_values("開始時間").groupby("指派機台"):
        previous_end = None
        for _, row in group.sort_values("開始時間").iterrows():
            if previous_end is not None:
                assert row["開始時間"] >= previous_end
            previous_end = row["結束時間"]


def test_each_work_order_appears_once():
    result = schedule(_data(), "lean")
    assert result["工單編號"].is_unique
    assert len(result) == 10


def test_duration_is_quantity_divided_by_rate():
    result = schedule(_data(), "fifo")
    row = result[result["工單編號"] == "UAT-260903-001"].iloc[0]
    assert row["加工時間（小時）"] == 5


def test_multi_machine_assignment_is_legal():
    data = _data()
    rates = data["產品機台產速"]
    result = schedule(data, "load_balance")
    legal_pairs = set(zip(rates["產品"], rates["機台"]))
    for _, row in result.iterrows():
        assert (row["產品"], row["指派機台"]) in legal_pairs

def test_manual_override_for_multi_machine_product_is_respected():
    result = schedule(_data(), "lean", {"UAT-260903-009": "C2"})
    row = result[result["工單編號"] == "UAT-260903-009"].iloc[0]
    assert row["指派機台"] == "C2"


def test_24h_and_custom_horizon_flag_orders_outside_period():
    import pandas as pd

    data = _data()
    short = schedule(data, "fifo", horizon_start="2026-09-03 08:00", horizon_end="2026-09-03 10:00")
    assert (short["狀態"] != "scheduled").any()
    unscheduled = short[short["狀態"] == "超出排程期間"].iloc[0]
    assert pd.isna(unscheduled["開始時間"])
    assert pd.isna(unscheduled["結束時間"])
    long = schedule(data, "fifo", horizon_start="2026-09-03 08:00", horizon_end="2026-09-05 08:00")
    assert (long["狀態"] == "scheduled").sum() >= (short["狀態"] == "scheduled").sum()


def test_48h_72h_and_one_week_horizons():
    import pandas as pd

    data = _data()
    start = pd.Timestamp("2026-09-03 08:00")
    counts = []
    for hours in [48, 72, 168]:
        result = schedule(data, "fifo", horizon_start=start, horizon_end=start + pd.to_timedelta(hours, unit="h"))
        counts.append(int((result["狀態"] == "scheduled").sum()))
    assert counts == sorted(counts)


def test_processing_rate_affects_duration():
    data = _data()
    fast = schedule(data, "fifo")
    data["產品機台產速"].loc[data["產品機台產速"]["產品"] == "SIM-C2-A", "產速_PCS_per_hr"] = 60
    slow = schedule(data, "fifo")
    assert slow.loc[slow["工單編號"] == "UAT-260903-001", "加工時間（小時）"].iloc[0] == 10
    assert fast.loc[fast["工單編號"] == "UAT-260903-001", "加工時間（小時）"].iloc[0] == 5


def test_changeover_affects_schedule():
    data = _data()
    no_changeover = schedule(data, "fifo", default_changeover_minutes=0)
    with_changeover = schedule(data, "fifo", default_changeover_minutes=60)
    assert with_changeover["換模時間（小時）"].sum() > no_changeover["換模時間（小時）"].sum()
    assert with_changeover["結束時間"].max() >= no_changeover["結束時間"].max()


def test_group_changeover_table_overrides_default_minutes():
    import pandas as pd

    data = _data()
    data["待排工單"] = pd.DataFrame(
        [
            {"工單編號": "A", "產品": "SIM-C2-A", "數量": 120, "單位": "PCS", "優先級": "一般", "交期": "2026-09-04", "_原始順序": 1},
            {"工單編號": "B", "產品": "SIM-C2-B", "數量": 96, "單位": "PCS", "優先級": "一般", "交期": "2026-09-04", "_原始順序": 2},
        ]
    )
    data["機台初始狀態"] = pd.DataFrame([{"機台": "C2", "初始產品": "SIM-C2-A"}])
    data["換模時間"] = pd.DataFrame([{"來源換模群組": "C2-A", "目標換模群組": "C2-B", "換模時間_分鐘": 75}])
    result = schedule(data, "fifo", default_changeover_minutes=30)
    second = result[result["工單編號"] == "B"].iloc[0]
    assert second["換模時間（小時）"] == 1.25


def test_machine_downtime_blocks_resource():
    import pandas as pd

    data = _data()
    downtime = pd.DataFrame([{"機台": "C4", "不可用開始": pd.Timestamp("2026-09-03 12:00"), "不可用結束": pd.Timestamp("2026-09-03 14:00"), "原因": "test"}])
    result = schedule(data, "fifo", unavailability=downtime)
    c4 = result[(result["指派機台"] == "C4") & (result["狀態"] == "scheduled")]
    for _, row in c4.iterrows():
        assert row["結束時間"] <= pd.Timestamp("2026-09-03 12:00") or row["開始時間"] >= pd.Timestamp("2026-09-03 14:00")


def test_non_working_calendar_period_contains_no_job():
    import pandas as pd

    data = _data()
    data["機台可用時間"] = pd.DataFrame(
        [
            {"機台": "C2", "可用開始": pd.Timestamp("2026-09-03 08:00"), "可用結束": pd.Timestamp("2026-09-04 08:00")},
            {"機台": "C4", "可用開始": pd.Timestamp("2026-09-03 14:00"), "可用結束": pd.Timestamp("2026-09-04 08:00")},
            {"機台": "C5", "可用開始": pd.Timestamp("2026-09-03 08:00"), "可用結束": pd.Timestamp("2026-09-04 08:00")},
        ]
    )
    data["機台可用時間"].loc[data["機台可用時間"]["機台"] == "C4", "可用開始"] = pd.Timestamp("2026-09-03 14:00")
    result = schedule(data, "fifo")
    c4 = result[(result["指派機台"] == "C4") & (result["狀態"] == "scheduled")]
    assert (c4["開始時間"] >= pd.Timestamp("2026-09-03 14:00")).all()


def test_same_product_changeover_is_zero_and_initial_setup_affects_first_job():
    import pandas as pd

    data = _data()
    result = schedule(data, "rush_edd")
    first_c2 = result[result["指派機台"] == "C2"].sort_values("開始時間").iloc[0]
    assert first_c2["產品"] == "SIM-C2-A"
    assert first_c2["換模時間（小時）"] == 0

    data["機台初始狀態"] = pd.DataFrame([{"機台": "C2", "初始產品": "SIM-C2-B"}])
    changed = schedule(data, "rush_edd", default_changeover_minutes=30)
    first_c2_changed = changed[changed["指派機台"] == "C2"].sort_values("開始時間").iloc[0]
    assert first_c2_changed["換模時間（小時）"] == 0.4167


def test_no_split_or_preemption_across_downtime():
    import pandas as pd

    data = _data()
    downtime = pd.DataFrame([{"機台": "C4", "不可用開始": pd.Timestamp("2026-09-03 10:00"), "不可用結束": pd.Timestamp("2026-09-03 12:00"), "原因": "test"}])
    result = schedule(data, "rush_edd", unavailability=downtime)
    c4_first = result[(result["指派機台"] == "C4") & (result["狀態"] == "scheduled")].sort_values("開始時間").iloc[0]
    assert not (c4_first["開始時間"] < pd.Timestamp("2026-09-03 10:00") < c4_first["結束時間"])


def test_alternative_eligible_resource_can_be_selected():
    import pandas as pd

    data = _data()
    downtime = pd.DataFrame([{"機台": "C5", "不可用開始": pd.Timestamp("2026-09-03 08:00"), "不可用結束": pd.Timestamp("2026-09-03 20:00"), "原因": "test"}])
    result = schedule(data, "short_wait", unavailability=downtime)
    row = result[result["產品"] == "SIM-MULTI-C"].iloc[0]
    assert row["指派機台"] == "C2"


def test_order_allowed_machines_restrict_assignment():
    data = _data()
    data["待排工單"].loc[data["待排工單"]["工單編號"] == "UAT-260903-009", "允許機台"] = "C5"
    result = schedule(data, "short_wait")
    row = result[result["工單編號"] == "UAT-260903-009"].iloc[0]
    assert row["指派機台"] == "C5"


def test_order_allowed_machines_reports_no_eligible_machine():
    data = _data()
    data["待排工單"].loc[data["待排工單"]["工單編號"] == "UAT-260903-009", "允許機台"] = "C4"
    result = schedule(data, "short_wait")
    row = result[result["工單編號"] == "UAT-260903-009"].iloc[0]
    assert row["指派機台"] == "無合格機台"
    assert row["狀態"] == "無合格機台"


def test_weekend_or_holiday_unavailability_blocks_all_machines():
    import pandas as pd

    data = _data()
    downtime = pd.DataFrame(
        [
            {"機台": machine, "不可用開始": pd.Timestamp("2026-09-05 00:00"), "不可用結束": pd.Timestamp("2026-09-07 00:00"), "原因": "weekend"}
            for machine in ["C2", "C4", "C5"]
        ]
    )
    result = schedule(data, "fifo", horizon_start="2026-09-04 08:00", horizon_end="2026-09-08 08:00", unavailability=downtime)
    scheduled = result[result["狀態"] == "scheduled"]
    for _, row in scheduled.iterrows():
        assert row["結束時間"] <= pd.Timestamp("2026-09-05 00:00") or row["開始時間"] >= pd.Timestamp("2026-09-07 00:00")


def test_daily_8_hour_shift_blocks_are_respected():
    import pandas as pd

    data = _data()
    data["待排工單"] = pd.DataFrame(
        [
            {"工單編號": "A", "產品": "SIM-C2-A", "數量": 900, "單位": "PCS", "優先級": "一般", "交期": "2026-09-05", "_原始順序": 1},
            {"工單編號": "B", "產品": "SIM-C2-A", "數量": 120, "單位": "PCS", "優先級": "一般", "交期": "2026-09-05", "_原始順序": 2},
        ]
    )
    data["產品機台產速"] = data["產品機台產速"][data["產品機台產速"]["產品"] == "SIM-C2-A"]
    downtime = pd.DataFrame([{"機台": "C2", "不可用開始": pd.Timestamp("2026-09-04 16:00"), "不可用結束": pd.Timestamp("2026-09-05 08:00"), "原因": "shift"}])
    result = schedule(data, "fifo", horizon_start="2026-09-04 08:00", horizon_end="2026-09-05 18:00", unavailability=downtime)
    row = result[result["工單編號"] == "B"].iloc[0]
    assert row["開始時間"] >= pd.Timestamp("2026-09-05 08:00")
