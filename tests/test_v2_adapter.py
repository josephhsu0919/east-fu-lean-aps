from pathlib import Path

import pandas as pd

from aps.metrics import calculate_kpis
from aps.scheduler import schedule
from aps.v2_adapter import (
    build_scheduler_workbook,
    detect_customs_closing_date,
    load_east_fu_erp_orders,
    load_v2_master_data,
    parse_release_date,
    suggested_completion_date,
    validate_v2_orders,
)


MASTER_PATH = Path(r"C:\Users\User\Downloads\EastFu_APS_Lite_V2_MasterData_Template.xlsx")
ERP_PATH = Path(r"C:\Users\User\Downloads\BK製令_K69835-結關2026.09.09-已排.xlsx")
ERP_NAME = "BK製令_K69835-結關2026.09.09-已排.xlsx"


def _master_with_rates():
    master = load_v2_master_data(MASTER_PATH)
    products = master["產品主檔"][["產品品號", "品名"]].copy()
    products["機台"] = "C2"
    products["產速_PCS_per_hr"] = 120
    products["啟用"] = "是"
    products["備註"] = "test"
    master["產品機台產速"] = products
    return master


def test_v2_erp_header_mapping_and_dates():
    orders, header_row = load_east_fu_erp_orders(ERP_PATH, ERP_NAME)
    assert header_row == 3
    assert len(orders) == 72
    assert orders.loc[0, "work_order_id"] == "20260729001"
    assert orders.loc[0, "product_id"] == "ACNC003005"
    assert orders.loc[0, "release_date"] == pd.Timestamp("2026-07-29")
    assert detect_customs_closing_date(ERP_NAME) == pd.Timestamp("2026-09-09")
    assert suggested_completion_date(ERP_NAME) == pd.Timestamp("2026-09-06")


def test_v2_release_date_parser_rejects_invalid_dates():
    assert parse_release_date("20260729001") == pd.Timestamp("2026-07-29")
    assert parse_release_date("20261399001") is None
    assert parse_release_date("ABC") is None


def test_v2_validation_reports_blank_master_rates():
    master = load_v2_master_data(MASTER_PATH)
    orders, _ = load_east_fu_erp_orders(ERP_PATH, ERP_NAME)
    summary, validated = validate_v2_orders(orders, master)
    assert summary.total_rows == 72
    assert summary.issue_rows == 72
    assert validated["問題"].str.contains("產品沒有有效機台產速").any()


def test_v2_scheduler_respects_release_date_and_initial_wip():
    master = _master_with_rates()
    orders, _ = load_east_fu_erp_orders(ERP_PATH, ERP_NAME)
    orders = orders.head(3).copy()
    orders["completion_date"] = pd.Timestamp("2026-09-06")
    orders.loc[1, "manual_priority"] = True
    master["期初在製"] = pd.DataFrame(
        [
            {
                "機台": "C2",
                "是否有期初在製": "是",
                "製令單號": "WIP-001",
                "產品品號": orders.loc[0, "product_id"],
                "品名": orders.loc[0, "product_name"],
                "剩餘數量": 10,
                "預計完成時間": pd.Timestamp("2026-07-29 10:30"),
                "目前換模群組": "沒包紗",
            }
        ]
    )
    summary, validated = validate_v2_orders(orders, master)
    assert summary.issue_rows == 0
    workbook = build_scheduler_workbook(validated, master, pd.Timestamp("2026-07-28 08:00"), pd.Timestamp("2026-07-30 08:00"))
    result = schedule(workbook, "v2_default", horizon_start="2026-07-28 08:00", horizon_end="2026-07-30 08:00", default_changeover_minutes=45)
    scheduled = result[result["工單類型"] == "本次 APS 新排工單"]
    assert result.iloc[0]["工單類型"] == "期初在製"
    assert (scheduled["開始時間"] >= pd.Timestamp("2026-07-29")).all()
    first_new = scheduled.sort_values("開始時間").iloc[0]
    assert first_new["工單編號"] == orders.loc[1, "work_order_id"]
    kpis = calculate_kpis(result, workbook["排程基本設定"])
    assert kpis["完成工單數"] == 3
