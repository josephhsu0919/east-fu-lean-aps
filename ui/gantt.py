from __future__ import annotations

import pandas as pd
import plotly.express as px

from aps.scheduler import MACHINES


def make_gantt(schedule_df: pd.DataFrame, horizon_start: pd.Timestamp, horizon_end: pd.Timestamp):
    horizon_start = pd.Timestamp(horizon_start)
    horizon_end = pd.Timestamp(horizon_end)
    frame = schedule_df[schedule_df["狀態"] == "scheduled"].copy()
    if frame.empty:
        fig = px.timeline(pd.DataFrame(columns=["開始時間", "結束時間", "指派機台"]), x_start="開始時間", x_end="結束時間", y="指派機台")
        fig.update_xaxes(range=[horizon_start, horizon_end])
        fig.update_layout(font=dict(size=15))
        return fig
    frame["工單標籤"] = frame["工單編號"].astype(str)
    fig = px.timeline(
        frame,
        x_start="開始時間",
        x_end="結束時間",
        y="指派機台",
        color="優先級",
        text="工單標籤",
        category_orders={"指派機台": MACHINES},
        hover_data={
            "工單編號": True,
            "產品": True,
            "數量": True,
            "優先級": True,
            "開始時間": True,
            "結束時間": True,
            "加工時間（小時）": ":.2f",
            "交期": True,
            "是否遲交": True,
        },
        color_discrete_map={"急單": "#d1495b", "一般": "#277da1", "低優先": "#84a98c"},
    )
    axis_end = max(horizon_end, frame["結束時間"].max())
    fig.update_yaxes(autorange="reversed", title="機台", tickfont=dict(size=15), title_font=dict(size=16))
    fig.update_xaxes(title="日期時間", range=[horizon_start, axis_end], tickfont=dict(size=15), title_font=dict(size=16))
    fig.update_traces(textposition="inside", insidetextanchor="middle", textfont_size=15)
    for hour in pd.date_range(horizon_start.ceil("h"), axis_end.floor("h"), freq="h"):
        if hour not in {horizon_start, horizon_end}:
            fig.add_vline(x=hour, line_width=0.7, line_dash="dash", line_color="rgba(80, 90, 110, 0.25)")
    fig.add_vline(x=horizon_start, line_width=1, line_dash="dash", line_color="#6c757d")
    fig.add_vline(x=horizon_end, line_width=1, line_dash="dash", line_color="#6c757d")
    for due in sorted(frame["交期"].dropna().unique()):
        fig.add_vline(x=due, line_width=1, line_dash="dot", line_color="#f4a261")
    fig.update_layout(height=460, margin=dict(l=20, r=20, t=30, b=20), legend_title_text="優先級", font=dict(size=15))
    return fig
