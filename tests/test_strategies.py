from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from aps.validator import validate_workbook


def _data():
    ok, issues, data = validate_workbook(demo_workbook())
    assert ok, issues
    return data


def test_edd_is_deterministic():
    data = _data()
    first = schedule(data, "edd")["工單編號"].tolist()
    second = schedule(data, "edd")["工單編號"].tolist()
    assert first == second
    assert first[:2] == ["UAT-260903-001", "UAT-260903-002"]


def test_fifo_is_deterministic():
    data = _data()
    first = schedule(data, "fifo")["工單編號"].tolist()
    second = schedule(data, "fifo")["工單編號"].tolist()
    assert first == second
    assert first[0] == "UAT-260903-001"
    assert first[-1] == "UAT-260903-010"


def test_spt_is_deterministic():
    data = _data()
    first = schedule(data, "spt")["工單編號"].tolist()
    second = schedule(data, "spt")["工單編號"].tolist()
    assert first == second
    assert first[0] == "UAT-260903-009"

