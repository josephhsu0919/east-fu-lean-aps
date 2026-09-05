from pathlib import Path

import pandas as pd

from aps.history import create_schedule_version, load_history, save_history, version_schedule_frame
from aps.metrics import calculate_kpis
from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def main() -> None:
    path = Path("data/schedule_history.json")
    save_history([], path)
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues

    start = pd.Timestamp("2026-09-03 08:00")
    end = pd.Timestamp("2026-09-04 08:00")
    result = schedule(data, "edd", horizon_start=start, horizon_end=end)
    kpis = calculate_kpis(result, data["排程基本設定"])
    create_schedule_version(data, result, kpis, "edd", "交期優先 EDD", start, end, "INITIAL", path=path)

    data["待排工單"] = pd.concat(
        [
            data["待排工單"],
            pd.DataFrame(
                [
                    {
                        "工單編號": "URGENT-001",
                        "產品": "SIM-C2-A",
                        "數量": 120,
                        "單位": "PCS",
                        "優先級": "急單",
                        "交期": pd.Timestamp("2026-09-03 18:00"),
                        "_原始順序": 11,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    urgent = schedule(data, "rush_edd", horizon_start=start, horizon_end=end)
    urgent_kpis = calculate_kpis(urgent, data["排程基本設定"])
    create_schedule_version(data, urgent, urgent_kpis, "rush_edd", "急單優先", start, end, "URGENT_ORDER", path=path)

    downtime = pd.DataFrame([{"機台": "C4", "不可用開始": pd.Timestamp("2026-09-03 12:00"), "不可用結束": pd.Timestamp("2026-09-03 14:00"), "原因": "UAT"}])
    down = schedule(data, "rush_edd", horizon_start=start, horizon_end=end, unavailability=downtime)
    down_kpis = calculate_kpis(down, data["排程基本設定"])
    create_schedule_version(data, down, down_kpis, "rush_edd", "急單優先", start, end, "MACHINE_DOWN", unavailability=downtime, path=path)

    history = load_history(path)
    assert [v["version_id"] for v in history] == ["V001", "V002", "V003"]
    assert all(not version_schedule_frame(v).empty for v in history)
    c4 = down[(down["指派機台"] == "C4") & (down["狀態"] == "scheduled")]
    assert all((r["結束時間"] <= pd.Timestamp("2026-09-03 12:00")) or (r["開始時間"] >= pd.Timestamp("2026-09-03 14:00")) for _, r in c4.iterrows())
    print("UAT smoke PASS")
    print(f"Initial on-time: {kpis['準時完成率']:.1f}%")
    print(f"Urgent on-time: {urgent_kpis['準時完成率']:.1f}%")
    print(f"Downtime on-time: {down_kpis['準時完成率']:.1f}%")
    print(f"History versions: {len(history)}")


if __name__ == "__main__":
    main()
