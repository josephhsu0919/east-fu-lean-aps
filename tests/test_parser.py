from pathlib import Path

from aps.parser import inspect_workbook_schema, load_workbook, normalize_workbook
from aps.sample_data import write_demo_excel
from aps.scheduler import schedule
from aps.validator import validate_workbook


def test_demo_excel_can_be_read():
    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(exist_ok=True)
    path = write_demo_excel(temp_dir / "demo.xlsx")
    workbook = load_workbook(path)
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert data is not None
    assert len(data["待排工單"]) == 10
    assert "換模時間" in data
    assert "排程基本設定" not in workbook
    assert "排程基本設定" in data


def test_product_machine_rate_mappings_are_correct():
    path = Path("data/EastFu_Lean_APS_Demo.xlsx")
    write_demo_excel(path)
    workbook = load_workbook(path)
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    rates = data["產品機台產速"]
    assert len(rates) == 13
    assert "換模群組" in rates.columns
    assert set(rates.loc[rates["產品"] == "SIM-MULTI-C", "機台"]) == {"C5", "C2"}
    assert rates.loc[(rates["產品"] == "SIM-C2-C") & (rates["機台"] == "C2"), "產速_PCS_per_hr"].iloc[0] == 140


def test_column_alias_normalization_for_canonical_uat_shape():
    workbook = {
        "待排工單": __import__("pandas").DataFrame(
            [{"WO": "UAT-1", "產品編號": "SIM-C2-A", "Quantity": 10, "需求日期": "2026-09-04", "Priority": "急單"}]
        ),
        "產品機台產速": __import__("pandas").DataFrame([{"Product": "SIM-C2-A", "Machine": "C2", "PCS/hr": 120}]),
        "機台可用時間": __import__("pandas").DataFrame([{"Machine": "C2", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"}]),
        "排程基本設定": __import__("pandas").DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert data["待排工單"].loc[0, "工單編號"] == "UAT-1"
    assert data["待排工單"].loc[0, "產品"] == "SIM-C2-A"
    assert data["待排工單"].loc[0, "交期"].year == 2026


def test_schedule_settings_sheet_is_optional():
    import pandas as pd

    workbook = {
        "待排工單": pd.DataFrame([{"工單編號": "UAT-1", "產品": "SIM-C2-A", "數量": 10, "單位": "PCS", "交期": "2026-09-04", "優先級": "一般"}]),
        "產品機台產速": pd.DataFrame([{"產品": "SIM-C2-A", "機台": "C2", "產速_PCS_per_hr": 120}]),
        "機台可用時間": pd.DataFrame([{"機台": "C2", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"}]),
    }
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert data["排程基本設定"].loc[data["排程基本設定"]["設定項目"] == "排程開始", "設定值"].iloc[0] == pd.Timestamp("2026-09-03 08:00")
    assert data["排程基本設定"].loc[data["排程基本設定"]["設定項目"] == "排程結束", "設定值"].iloc[0] == pd.Timestamp("2026-09-04 08:00")


def test_missing_required_column_returns_friendly_error():
    workbook = {
        "待排工單": __import__("pandas").DataFrame([{"工單編號": "UAT-1", "產品": "SIM-C2-A", "數量": 10, "優先級": "急單"}]),
        "產品機台產速": __import__("pandas").DataFrame([{"產品": "SIM-C2-A", "機台": "C2", "產速_PCS_per_hr": 120}]),
        "機台可用時間": __import__("pandas").DataFrame([{"機台": "C2", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"}]),
        "排程基本設定": __import__("pandas").DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    ok, issues, _ = validate_workbook(workbook)
    assert not ok
    assert "Excel 訂單資料缺少必要欄位：交期" in issues[0]
    assert "目前偵測到欄位" in issues[0]


def test_datetime_and_priority_normalization():
    workbook = {
        "待排工單": __import__("pandas").DataFrame(
            [{"work_order_no": "UAT-1", "product_code": "SIM-C2-A", "qty": 10, "due_date": "2026/09/04 17:30", "priority": "URGENT"}]
        ),
        "產品機台產速": __import__("pandas").DataFrame([{"product_code": "SIM-C2-A", "machine": "C2", "rate": 120}]),
        "機台可用時間": __import__("pandas").DataFrame([{"machine": "C2", "available_from": "2026-09-03 08:00", "available_until": "2026-09-04 08:00"}]),
        "排程基本設定": __import__("pandas").DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert data["待排工單"].loc[0, "優先級"] == "急單"
    assert data["待排工單"].loc[0, "交期"].hour == 17


def test_missing_processing_rate_gives_friendly_validation():
    workbook = {
        "待排工單": __import__("pandas").DataFrame([{"工單編號": "UAT-1", "產品": "SIM-X", "數量": 10, "交期": "2026-09-04", "優先級": "一般"}]),
        "產品機台產速": __import__("pandas").DataFrame([{"產品": "SIM-C2-A", "機台": "C2", "產速_PCS_per_hr": 120}]),
        "機台可用時間": __import__("pandas").DataFrame([{"機台": "C2", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"}]),
        "排程基本設定": __import__("pandas").DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    ok, issues, _ = validate_workbook(workbook)
    assert not ok
    assert any("產品 SIM-X 尚未設定機台產速" in issue for issue in issues)


def test_east_fu_actual_order_headers_normalize_to_canonical_schema():
    import pandas as pd

    orders = pd.DataFrame(
        [
            {
                "製令單號": f"UAT-{idx:03d}",
                "產品品號": "SIM-C2-A" if idx <= 5 else "SIM-C4-A",
                "品名": "測試品",
                "產品規格": "UAT",
                "預計產量": 100 + idx,
                "數量單位": "PCS",
                "每件長度": 1,
                "長度單位": "M",
                "交期": "2026-09-04",
                "工單急迫程度": "急單" if idx == 1 else "一般",
                "最早可排程時間": "2026-09-03 08:00",
                "客戶訂單號": f"SO-{idx:03d}",
                "計劃批號": "BATCH",
                "換模群組": "G1",
                "優先機台": "C2",
                "急單原因/備註": "",
                "其他備註": "",
                "單位": "PCS",
                "原始順序": idx,
            }
            for idx in range(1, 11)
        ]
    )
    rates = pd.DataFrame(
        [
            {"產品品號": "SIM-C2-A", "品名": "測試品", "產品規格": "UAT", "機台": "C2", "可生產": "是", "優先機台": "是", "標準產速": 120, "產速單位": "PCS/hr", "生效日期": "2026-09-01", "失效日期": "", "換模群組": "G1", "資料來源/備註": ""},
            {"產品品號": "SIM-C4-A", "品名": "測試品", "產品規格": "UAT", "機台": "C4", "可生產": "是", "優先機台": "是", "標準產速": 90, "產速單位": "PCS/hr", "生效日期": "2026-09-01", "失效日期": "", "換模群組": "G1", "資料來源/備註": ""},
            {"產品品號": "SIM-C4-A", "品名": "測試品", "產品規格": "UAT", "機台": "C5", "可生產": "否", "優先機台": "否", "標準產速": 80, "產速單位": "PCS/hr", "生效日期": "2026-09-01", "失效日期": "", "換模群組": "G1", "資料來源/備註": ""},
        ]
    )
    workbook = {
        "待排工單": orders,
        "產品機台產速": rates,
        "機台可用時間": pd.DataFrame(
            [
                {"機台": "C2", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"},
                {"機台": "C4", "可用開始": "2026-09-03 08:00", "可用結束": "2026-09-04 08:00"},
            ]
        ),
        "排程基本設定": pd.DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    normalized = normalize_workbook(workbook)
    assert {"工單編號", "產品", "數量", "單位", "交期", "優先級"}.issubset(normalized["待排工單"].columns)
    assert {"產品", "機台", "產速_PCS_per_hr", "產速單位"}.issubset(normalized["產品機台產速"].columns)
    assert len(normalized["待排工單"]) == 10
    assert len(normalized["產品機台產速"]) == 2

    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert len(data["待排工單"]) == 10
    assert data["待排工單"].loc[0, "工單編號"] == "UAT-001"
    assert data["待排工單"].loc[0, "產品"] == "SIM-C2-A"
    assert data["待排工單"].loc[0, "數量"] == 101
    assert data["待排工單"].loc[0, "優先級"] == "急單"
    assert data["產品機台產速"].loc[data["產品機台產速"]["產品"] == "SIM-C2-A", "產速_PCS_per_hr"].iloc[0] == 120
    result = schedule(data, "edd")
    assert len(result) == 10
    assert set(result["指派機台"]) == {"C2", "C4"}


def test_workbook_schema_detection_lists_headers_and_counts():
    import pandas as pd

    temp_dir = Path("tests/.tmp")
    temp_dir.mkdir(exist_ok=True)
    path = temp_dir / "schema_detection.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([{"製令單號": "UAT-001", "產品品號": "SIM-C2-A"}]).to_excel(writer, sheet_name="待排工單", index=False)
    schema = inspect_workbook_schema(path)
    assert schema["待排工單"]["row_count"] == 1
    assert schema["待排工單"]["headers"] == ["製令單號", "產品品號"]


def test_east_fu_required_star_headers_normalize_to_canonical_schema():
    import pandas as pd

    workbook = {
        "待排工單": pd.DataFrame(
            [{"製令單號*": "UAT-001", "產品品號*": "SIM-C2-A", "預計產量*": 100, "數量單位*": "PCS", "交期*": "2026-09-04", "工單急迫程度*": "一般"}]
        ),
        "產品機台產速": pd.DataFrame([{"產品品號*": "SIM-C2-A", "機台*": "C2", "可生產*": "是", "標準產速*": 120, "產速單位*": "PCS/hr"}]),
        "機台可用時間": pd.DataFrame([{"機台*": "C2", "可用起始時間*": "2026-09-03 08:00", "可用結束時間*": "2026-09-04 08:00"}]),
        "排程基本設定": pd.DataFrame([["排程開始", "2026-09-03 08:00"], ["排程結束", "2026-09-04 08:00"]], columns=["設定項目", "設定值"]),
    }
    ok, issues, data = validate_workbook(workbook)
    assert ok, issues
    assert data["待排工單"].loc[0, "工單編號"] == "UAT-001"
    assert data["待排工單"].loc[0, "產品"] == "SIM-C2-A"
    assert data["待排工單"].loc[0, "數量"] == 100
    assert data["待排工單"].loc[0, "優先級"] == "一般"
    assert data["產品機台產速"].loc[0, "產速_PCS_per_hr"] == 120
    assert data["機台可用時間"].loc[0, "可用開始"].hour == 8
    assert data["機台可用時間"].loc[0, "可用結束"].hour == 8
