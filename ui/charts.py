from __future__ import annotations

import plotly.express as px


def comparison_bar(comparison_df, y: str, title: str):
    fig = px.bar(comparison_df, x="策略", y=y, text=y, title=title, color="策略")
    fig.update_layout(height=320, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside", cliponaxis=False)
    return fig

