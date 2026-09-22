import pandas as pd

from aps.parser import default_settings_frame
from aps.scheduler import schedule


START = pd.Timestamp("2026-09-20 08:00")
END = pd.Timestamp("2026-10-10 08:00")


def _workbook(orders, groups=None, initial_group=None, initial_wip=None):
    groups = groups or {}
    rates_rows = []
    products = set()
    if initial_group:
        products.add("__INITIAL__")
    for order in orders:
        products.add(order["工單編號"])
    for product in products:
        rates_rows.append(
            {
                "產品": product,
                "機台": "C2",
                "產速_PCS_per_hr": 100,
                "換模群組": groups.get(product, initial_group if product == "__INITIAL__" else "包紗"),
            }
        )
    workbook = {
        "待排工單": pd.DataFrame(
            [
                {
                    "工單編號": order["工單編號"],
                    "產品": order["工單編號"],
                    "品名": order["工單編號"],
                    "規格": "",
                    "數量": order.get("數量", 100),
                    "單位": "PCS",
                    "優先級": "急單" if order.get("指定優先", False) else "一般",
                    "指定優先": bool(order.get("指定優先", False)),
                    "交期": pd.Timestamp(order["完成日"]),
                    "完成日": pd.Timestamp(order["完成日"]),
                    "最早可排日": pd.Timestamp(order.get("最早可排日", START)),
                    "_原始順序": idx + 1,
                }
                for idx, order in enumerate(orders)
            ]
        ),
        "產品機台產速": pd.DataFrame(rates_rows),
        "換模時間": pd.DataFrame(
            [
                {"來源換模群組": "包紗", "目標換模群組": "包紗", "換模時間_分鐘": 40},
                {"來源換模群組": "沒包紗", "目標換模群組": "沒包紗", "換模時間_分鐘": 40},
                {"來源換模群組": "包紗", "目標換模群組": "沒包紗", "換模時間_分鐘": 45},
                {"來源換模群組": "沒包紗", "目標換模群組": "包紗", "換模時間_分鐘": 45},
                {"來源換模群組": "未知", "目標換模群組": "任何", "換模時間_分鐘": 45},
            ]
        ),
        "排程基本設定": default_settings_frame(START, END),
    }
    if initial_group:
        workbook["機台初始狀態"] = pd.DataFrame([{"機台": "C2", "初始產品": "__INITIAL__"}])
    if initial_wip is not None:
        workbook["期初在製"] = pd.DataFrame([initial_wip])
    return workbook


def _sequence(result):
    scheduled = result[result["工單類型"] == "本次 APS 新排工單"]
    return scheduled.sort_values("排程順序")["工單編號"].tolist()


def test_1_completion_date_priority():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-30 23:59"},
            {"工單編號": "B", "完成日": "2026-09-25 23:59"},
            {"工單編號": "C", "完成日": "2026-09-28 23:59"},
        ]
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["B", "C", "A"]


def test_2_manual_priority_beats_completion_date():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-25 23:59", "指定優先": False},
            {"工單編號": "B", "完成日": "2026-09-30 23:59", "指定優先": True},
        ]
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["B", "A"]


def test_3_completion_date_beats_setup_reduction():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-25 23:59"},
            {"工單編號": "B", "完成日": "2026-09-30 23:59"},
        ],
        groups={"A": "沒包紗", "B": "包紗"},
        initial_group="包紗",
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["A", "B"]


def test_4_setup_breaks_true_tie():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-25 23:59"},
            {"工單編號": "B", "完成日": "2026-09-25 23:59"},
        ],
        groups={"A": "沒包紗", "B": "包紗"},
        initial_group="包紗",
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["B", "A"]


def test_5_release_date_is_feasibility_constraint():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-30 23:59", "最早可排日": "2026-09-20 00:00"},
            {"工單編號": "B", "完成日": "2026-09-21 23:59", "最早可排日": "2026-09-25 00:00"},
        ]
    )
    result = schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)
    b_start = result.loc[result["工單編號"] == "B", "開始時間"].iloc[0]
    assert b_start >= pd.Timestamp("2026-09-25")
    assert _sequence(result) == ["A", "B"]


def test_6_release_date_is_not_permanent_priority():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-10-30 23:59", "最早可排日": "2026-09-20 00:00"},
            {"工單編號": "B", "完成日": "2026-10-01 23:59", "最早可排日": "2026-09-25 00:00"},
        ],
        initial_wip={
            "機台": "C2",
            "是否有期初在製": "是",
            "製令單號": "WIP-001",
            "產品品號": "A",
            "剩餘數量": 1,
            "預計完成時間": pd.Timestamp("2026-09-25 08:00"),
            "目前換模群組": "包紗",
        },
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["B", "A"]


def test_7_initial_wip_blocks_machine_then_priority_applies():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-30 23:59"},
            {"工單編號": "B", "完成日": "2026-09-25 23:59"},
        ],
        initial_wip={
            "機台": "C2",
            "是否有期初在製": "是",
            "製令單號": "WIP-001",
            "產品品號": "A",
            "剩餘數量": 1,
            "預計完成時間": pd.Timestamp("2026-09-20 10:30"),
            "目前換模群組": "包紗",
        },
    )
    result = schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)
    scheduled = result[result["工單類型"] == "本次 APS 新排工單"]
    assert (scheduled["開始時間"] >= pd.Timestamp("2026-09-20 10:30")).all()
    assert _sequence(result) == ["B", "A"]


def test_8_manual_priority_does_not_override_release_feasibility():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-30 23:59", "最早可排日": "2026-09-20 00:00", "指定優先": False},
            {"工單編號": "B", "完成日": "2026-10-01 23:59", "最早可排日": "2026-09-25 00:00", "指定優先": True},
        ]
    )
    result = schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)
    assert result.loc[result["工單編號"] == "B", "開始時間"].iloc[0] >= pd.Timestamp("2026-09-25")
    assert _sequence(result) == ["A", "B"]


def test_9_multiple_manual_priority_jobs_use_completion_date():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-30 23:59", "指定優先": True},
            {"工單編號": "B", "完成日": "2026-09-25 23:59", "指定優先": True},
        ]
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["B", "A"]


def test_10_setup_must_not_dominate_completion_date_order():
    wb = _workbook(
        [
            {"工單編號": "A", "完成日": "2026-09-24 23:59"},
            {"工單編號": "B", "完成日": "2026-09-25 23:59"},
            {"工單編號": "C", "完成日": "2026-09-26 23:59"},
        ],
        groups={"A": "沒包紗", "B": "包紗", "C": "包紗"},
        initial_group="包紗",
    )
    assert _sequence(schedule(wb, "v2_default", horizon_start=START, horizon_end=END, default_changeover_minutes=45)) == ["A", "B", "C"]
