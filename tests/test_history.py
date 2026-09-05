import pandas as pd
from pathlib import Path

from aps.history import create_schedule_version, load_history, save_history, version_schedule_frame
from aps.metrics import calculate_kpis
from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def test_urgent_order_creates_new_schedule_version():
    path = Path("tests/.tmp/history_urgent.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "INITIAL", path=path)
    data["待排工單"] = pd.concat(
        [data["待排工單"], pd.DataFrame([{"工單編號": "URGENT-1", "產品": "SIM-C2-A", "數量": 10, "單位": "PCS", "優先級": "急單", "交期": pd.Timestamp("2026-09-03 18:00"), "_原始順序": 11}])],
        ignore_index=True,
    )
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "URGENT_ORDER", path=path)
    history = load_history(path)
    assert [v["version_id"] for v in history] == ["V001", "V002"]
    assert history[-1]["reason"] == "URGENT_ORDER"


def test_historical_versions_persist_and_reconstruct_gantt_data():
    path = Path("tests/.tmp/history_restore.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "lean")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "lean", "精實排程", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "INITIAL", path=path)
    history = load_history(path)
    restored = version_schedule_frame(history[0])
    assert not restored.empty
    assert pd.api.types.is_datetime64_any_dtype(restored["開始時間"])


def test_corrupt_history_file_does_not_crash_app():
    path = Path("tests/.tmp/history_corrupt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[", encoding="utf-8")
    assert load_history(path) == []


def test_object_timestamp_values_are_serialized_in_history():
    path = Path("tests/.tmp/history_object_timestamp.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(
        data,
        result,
        kpis,
        "edd",
        "交期優先 EDD",
        pd.Timestamp("2026-09-03 08:00"),
        pd.Timestamp("2026-09-04 08:00"),
        "INITIAL",
        rule_configuration={"schedule_start": pd.Timestamp("2026-09-03 08:00")},
        path=path,
    )
    history = load_history(path)
    assert history[0]["rule_configuration"]["schedule_start"] == "2026-09-03 08:00:00"


def test_history_is_immutable_after_master_setting_changes():
    path = Path("tests/.tmp/history_immutable.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    original_rate = data["產品機台產速"].loc[data["產品機台產速"]["產品"] == "SIM-C2-A", "產速_PCS_per_hr"].iloc[0]
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "INITIAL", path=path)
    data["產品機台產速"].loc[data["產品機台產速"]["產品"] == "SIM-C2-A", "產速_PCS_per_hr"] = 1
    history = load_history(path)
    saved_rate = [r for r in history[0]["processing_rate_snapshot"] if r["產品"] == "SIM-C2-A"][0]["產速_PCS_per_hr"]
    assert saved_rate == original_rate
    assert history[0]["kpis"] == kpis


def test_failed_scheduling_does_not_overwrite_previous_version():
    path = Path("tests/.tmp/history_failed.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "INITIAL", path=path)
    try:
        schedule({"待排工單": data["待排工單"]}, "edd")
    except KeyError:
        pass
    history = load_history(path)
    assert len(history) == 1
    assert history[0]["version_id"] == "V001"


def test_history_snapshot_has_required_reproducible_fields():
    path = Path("tests/.tmp/history_fields.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "edd")
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"), "INITIAL", path=path)
    version = load_history(path)[0]
    for key in [
        "version_id",
        "created_at",
        "input_source",
        "upload_filename",
        "orders",
        "horizon_start",
        "horizon_end",
        "scheduling_rule",
        "rule_configuration",
        "resource_availability_snapshot",
        "processing_rate_snapshot",
        "changeover_configuration",
        "machine_initial_state",
        "schedule",
        "kpis",
        "manual_adjustment",
        "reason",
    ]:
        assert key in version
    assert version["changeover_configuration"]["changeover_table"]
