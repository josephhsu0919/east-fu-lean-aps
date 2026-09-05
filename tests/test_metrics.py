from aps.metrics import calculate_kpis
from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def test_kpi_calculation_has_expected_fields():
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    result = schedule(data, "lean")
    kpis = calculate_kpis(result, data["排程基本設定"])
    expected = {
        "完成工單數",
        "未完成 / 超出 horizon 工單數",
        "準時完成率",
        "遲交工單數",
        "總遲交時間",
        "平均遲交時間",
        "最大遲交時間",
        "Makespan",
        "平均等待時間",
        "總等待時間",
        "C2 utilization",
        "C4 utilization",
        "C5 utilization",
        "平均 utilization",
        "Resource Load Imbalance",
        "換模次數",
    }
    assert expected == set(kpis)
    assert kpis["完成工單數"] + kpis["未完成 / 超出 horizon 工單數"] == 10
    assert kpis["Makespan"] > 0
