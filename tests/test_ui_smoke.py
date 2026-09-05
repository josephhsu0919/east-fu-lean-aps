import py_compile
from pathlib import Path

import pandas as pd

from aps.sample_data import demo_workbook
from aps.scheduler import schedule
from ui.gantt import make_gantt


def test_gantt_generation():
    data = demo_workbook()
    result = schedule(data, "edd")
    fig = make_gantt(result, pd.Timestamp("2026-09-03 08:00"), pd.Timestamp("2026-09-04 08:00"))
    assert len(fig.data) > 0


def test_streamlit_critical_flow_compiles():
    py_compile.compile(str(Path("app.py")), doraise=True)
