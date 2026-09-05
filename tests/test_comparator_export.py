from io import BytesIO
from pathlib import Path

import pandas as pd

from aps.comparator import compare_strategies, recommend_strategy
from aps.exporter import export_schedule_excel, export_schedule_package_zip
from aps.metrics import calculate_kpis
from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def _data():
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    return data


def test_strategy_comparison_uses_same_input():
    data = _data()
    comparison, schedules = compare_strategies(data, ["rush_edd", "edd", "fifo", "spt", "lean"])
    assert len(comparison) == 5
    ids = [tuple(frame["工單編號"].sort_values()) for frame in schedules.values()]
    assert len(set(ids)) == 1


def test_changing_strategy_may_change_schedule_or_kpi():
    data = _data()
    fifo = schedule(data, "fifo")
    spt = schedule(data, "spt")
    fifo_kpis = calculate_kpis(fifo, data["排程基本設定"])
    spt_kpis = calculate_kpis(spt, data["排程基本設定"])
    assert fifo["工單編號"].tolist() != spt["工單編號"].tolist() or fifo_kpis != spt_kpis


def test_recommendation_is_from_comparison_rows():
    comparison, _ = compare_strategies(_data(), ["rush_edd", "edd", "fifo", "spt", "lean"])
    best, reasons = recommend_strategy(comparison)
    assert best["策略"] in set(comparison["策略"])
    assert reasons


def test_export_excel_contains_required_sheets():
    data = _data()
    result = schedule(data, "lean")
    kpis = calculate_kpis(result, data["排程基本設定"])
    comparison, _ = compare_strategies(data, ["fifo", "lean"])
    content = export_schedule_excel(result, kpis, comparison)
    sheets = pd.read_excel(BytesIO(content), sheet_name=None, engine="openpyxl")
    assert {"排程結果", "KPI", "策略比較"} == set(sheets)


def test_export_package_zip_contains_excel_and_gantt_html():
    from zipfile import ZipFile

    content = export_schedule_package_zip(b"excel-bytes", "<html>gantt</html>")
    path = Path("tests/.tmp/package.zip")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    with ZipFile(path) as archive:
        assert set(archive.namelist()) == {"EastFu_APS_Result.xlsx", "EastFu_APS_Gantt.html"}
        assert archive.read("EastFu_APS_Result.xlsx") == b"excel-bytes"
        assert b"gantt" in archive.read("EastFu_APS_Gantt.html")
