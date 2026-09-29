"""Time-in-zone bar chart (HR or pace zones) from `ZoneTimeDTO` rows."""

import plotly.graph_objects as go

from training.services.dto import ZoneTimeDTO

from .format import fmt_duration_hms, fmt_pct, fmt_zone_range
from .theme import ZONE_COLORS, apply_base_layout, empty_figure


def zones_bar(zones: list[ZoneTimeDTO], *, kind: str = "hr") -> go.Figure:
    """Horizontal bars, Z1 on top; the label carries time, share and the zone's bounds (`kind`: hr | pace)."""
    if not zones:
        return empty_figure("Žiadne dáta o zónach (chýba prah alebo tep).", height=200)
    rows = sorted(zones, key=lambda z: z.zone)
    fig = go.Figure(
        go.Bar(
            orientation="h",
            x=[z.seconds / 60.0 for z in rows],
            y=[f"Z{z.zone}  {fmt_zone_range(z.lower, z.upper, kind)}" for z in rows],
            marker_color=[ZONE_COLORS[z.zone] for z in rows],
            text=[f"{fmt_duration_hms(z.seconds)} · {fmt_pct(z.share)}" for z in rows],
            textposition="auto",
            hovertemplate="%{text}<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title_text="minúty v zóne")
    fig.update_layout(hovermode="closest")
    return apply_base_layout(fig, height=230, legend=False)
