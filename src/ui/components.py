"""Shared UI building blocks: theme, pitch drawing, charts, claim audit table.

Streamlit changes some argument names between versions (for example
``use_container_width`` became ``width="stretch"``). The helpers ``chart``,
``chart_select`` and ``table`` try the new form first and fall back to the old
one, so the app works across versions.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analytics.impact_graph import describe_event
from src.models import ClaimResult, Event, Match

BG = "#0B1220"
PANEL = "#111A2E"
TEXT = "#E6EDF7"
MUTED = "#8FA3BF"
CYAN = "#22D3EE"
AMBER = "#F5A524"
GREEN = "#34D399"
RED = "#F87171"
BLUE = "#93C5FD"
GRID = "#1E2B45"

STATUS_COLOR = {"verified": GREEN, "labelled": BLUE, "unverifiable": AMBER, "contradicted": RED, "unsupported": RED}
STATUS_ICON = {"verified": "✔", "labelled": "◆", "unverifiable": "!", "contradicted": "✖", "unsupported": "✖"}

CSS = f"""
<style>
:root {{ --bg:{BG}; --panel:{PANEL}; --text:{TEXT}; --muted:{MUTED}; --cyan:{CYAN}; --amber:{AMBER}; }}
.stApp {{ background: var(--bg); color: var(--text); }}
section[data-testid="stSidebar"] {{ background: #0A1020; border-right: 1px solid {GRID}; }}
h1, h2, h3 {{ letter-spacing: .2px; }}
h1 {{ color: var(--text); }}
.sc-pill {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:.78rem; font-weight:700;
           letter-spacing:.6px; border:1px solid var(--amber); color:var(--amber); background:rgba(245,165,36,.08); }}
.sc-card {{ background: var(--panel); border:1px solid {GRID}; border-radius:12px; padding:14px 16px; margin-bottom:10px; }}
.sc-kpi-label {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.8px; }}
.sc-kpi-value {{ font-size:1.7rem; font-weight:700; color:var(--text); line-height:1.15; }}
.sc-kpi-sub {{ color:var(--muted); font-size:.8rem; }}
.sc-score {{ font-size:2.4rem; font-weight:800; text-align:center; }}
.sc-team {{ font-size:1.05rem; font-weight:600; text-align:center; }}
.sc-chip {{ display:inline-block; padding:2px 9px; border-radius:6px; font-size:.78rem; font-weight:700; }}
.sc-note {{ color:var(--muted); font-size:.85rem; }}
.sc-story {{ background:var(--panel); border-left:3px solid var(--cyan); padding:12px 16px; border-radius:6px;
            white-space:pre-wrap; line-height:1.55; }}
.sc-hyp {{ border-left:3px solid var(--amber); }}
table.sc-audit {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
table.sc-audit th {{ text-align:left; color:var(--muted); border-bottom:1px solid {GRID}; padding:6px 8px; }}
table.sc-audit td {{ border-bottom:1px solid {GRID}; padding:6px 8px; vertical-align:top; }}
@media (max-width: 800px) {{ .sc-score {{ font-size:1.8rem; }} .sc-kpi-value {{ font-size:1.3rem; }} }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def banner(match: Optional[Match] = None) -> None:
    st.markdown(
        '<span class="sc-pill">DEMO / SYNTHETIC DATA</span> '
        '<span class="sc-note">&nbsp;Fictional teams and players. Not an official Premier League product.</span>',
        unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "") -> None:
    st.markdown(
        f'<div class="sc-card"><div class="sc-kpi-label">{html.escape(label)}</div>'
        f'<div class="sc-kpi-value">{html.escape(str(value))}</div><div class="sc-kpi-sub">{html.escape(sub)}</div></div>',
        unsafe_allow_html=True)


def chip(status: str) -> str:
    col = STATUS_COLOR.get(status, MUTED)
    return (f'<span class="sc-chip" style="color:{col};border:1px solid {col};background:{col}1A">'
            f'{STATUS_ICON.get(status, "?")} {html.escape(status)}</span>')


# ---------------------------------------------------------------------------
# Version-tolerant Streamlit wrappers
# ---------------------------------------------------------------------------
def chart(fig: go.Figure, key: Optional[str] = None) -> None:
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=TEXT), margin=dict(l=10, r=10, t=40, b=10))
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def chart_select(fig: go.Figure, key: str) -> Optional[str]:
    """Plot a figure and return the ``customdata`` (node id) of a clicked point, if the Streamlit version supports it."""
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=TEXT), margin=dict(l=10, r=10, t=40, b=10), clickmode="event+select")
    try:
        ev = st.plotly_chart(fig, width="stretch", key=key, on_select="rerun", selection_mode=("points",))
    except TypeError:
        try:
            ev = st.plotly_chart(fig, use_container_width=True, key=key, on_select="rerun", selection_mode=("points",))
        except TypeError:
            st.plotly_chart(fig, use_container_width=True, key=key)
            return None
    try:
        pts = ev["selection"]["points"] if ev else []
        if pts:
            cd = pts[0].get("customdata")
            if isinstance(cd, (list, tuple)):
                cd = cd[0] if cd else None
            return cd
    except Exception:
        return None
    return None


def table(df: pd.DataFrame, height: Optional[int] = None) -> None:
    kw = {"hide_index": True}
    if height:
        kw["height"] = height
    try:
        st.dataframe(df, width="stretch", **kw)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kw)


# ---------------------------------------------------------------------------
# Pitch
# ---------------------------------------------------------------------------
def to_pitch(e: Event, match: Match) -> tuple[Optional[float], Optional[float]]:
    """Mirror the away team so both teams share one pitch (home attacks right, away attacks left)."""
    if e.x is None or e.y is None:
        return None, None
    if e.team_id == match.home.team_id:
        return e.x, e.y
    return 100 - e.x, 100 - e.y


def pitch_base(title: str = "") -> go.Figure:
    fig = go.Figure()
    line = dict(color="#3B4F73", width=1.5)
    shapes = [
        dict(type="rect", x0=0, y0=0, x1=100, y1=100, line=line, fillcolor="#0E2A24", layer="below"),
        dict(type="line", x0=50, y0=0, x1=50, y1=100, line=line),
        dict(type="circle", x0=40.5, y0=40.5, x1=59.5, y1=59.5, line=line),
        dict(type="rect", x0=0, y0=21, x1=16, y1=79, line=line),
        dict(type="rect", x0=84, y0=21, x1=100, y1=79, line=line),
        dict(type="rect", x0=0, y0=37, x1=5.5, y1=63, line=line),
        dict(type="rect", x0=94.5, y0=37, x1=100, y1=63, line=line),
        dict(type="line", x0=100 / 3, y0=0, x1=100 / 3, y1=100, line=dict(color="#2A3B5C", width=1, dash="dot")),
        dict(type="line", x0=200 / 3, y0=0, x1=200 / 3, y1=100, line=dict(color="#2A3B5C", width=1, dash="dot")),
    ]
    fig.update_layout(shapes=shapes, title=title, height=420,
                      xaxis=dict(range=[-2, 102], visible=False, fixedrange=True),
                      yaxis=dict(range=[-2, 102], visible=False, scaleanchor="x", scaleratio=0.68, fixedrange=True),
                      legend=dict(orientation="h", y=-0.02), showlegend=True)
    return fig


_SYMBOL = {"pass": "circle", "turnover": "x", "interception": "diamond", "tackle": "square", "shot": "star",
           "goal": "star-diamond"}


def pitch_figure(events: Iterable[Event], match: Match, title: str = "", max_points: int = 250) -> go.Figure:
    """Scatter of events on the pitch; the home team is cyan, the away team amber."""
    evs = list(events)[-max_points:]
    fig = pitch_base(title)
    for team, col in ((match.home, CYAN), (match.away, AMBER)):
        for etype, sym in _SYMBOL.items():
            pts = [(to_pitch(e, match), e) for e in evs if e.team_id == team.team_id and e.event_type == etype]
            pts = [(xy, e) for xy, e in pts if xy[0] is not None]
            if not pts:
                continue
            fig.add_trace(go.Scatter(
                x=[p[0][0] for p in pts], y=[p[0][1] for p in pts], mode="markers", name=f"{team.name} - {etype}",
                marker=dict(symbol=sym, size=13 if etype in ("shot", "goal") else 8, color=col,
                            line=dict(width=1, color="#0B1220")),
                text=[describe_event(match, p[1]) for p in pts], hoverinfo="text",
                visible=True if etype != "pass" else "legendonly"))
    return fig


def heat_figure(events: Iterable[Event], match: Match, team_id: str, title: str, color: str = CYAN) -> go.Figure:
    """2-D histogram of event positions in TEAM-RELATIVE coordinates (the team always attacks to the right)."""
    pts = [(e.x, e.y) for e in events if e.team_id == team_id and e.x is not None and e.y is not None]
    fig = pitch_base(title)
    if pts:
        fig.add_trace(go.Histogram2d(
            x=[p[0] for p in pts], y=[p[1] for p in pts], xbins=dict(start=0, end=100, size=100 / 6),
            ybins=dict(start=0, end=100, size=100 / 3), colorscale=[[0, "rgba(0,0,0,0)"], [1, color]],
            showscale=False, hovertemplate="count %{z}<extra></extra>"))
    return fig


# ---------------------------------------------------------------------------
# Claim audit panel
# ---------------------------------------------------------------------------
def audit_panel(results: list[ClaimResult], max_rows: int = 60) -> None:
    """Colour-coded claim table: claim, evidence, result, explanation."""
    if not results:
        st.info("No claims were checked yet.")
        return
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    st.markdown(" ".join(f"{chip(s)} <span class='sc-note'>×{n}</span>" for s, n in counts.items()), unsafe_allow_html=True)
    rows = ["<table class='sc-audit'><tr><th>Result</th><th>Claim</th><th>Evidence checked</th><th>Why</th></tr>"]
    for r in results[:max_rows]:
        rows.append(
            f"<tr><td>{chip(r.status)}</td><td>{html.escape(r.claim_text[:220])}"
            f"<div class='sc-note'>{html.escape(r.claim_type)} · {html.escape(r.claim_id)}</div></td>"
            f"<td>{html.escape(r.evidence[:200])}</td><td>{html.escape(r.explanation[:240])}</td></tr>")
    rows.append("</table>")
    st.markdown("".join(rows), unsafe_allow_html=True)
    if len(results) > max_rows:
        st.caption(f"Showing {max_rows} of {len(results)} checks.")


def story_box(text: str, hypothetical: bool = False) -> None:
    cls = "sc-story sc-hyp" if hypothetical else "sc-story"
    st.markdown(f'<div class="{cls}">{html.escape(text)}</div>', unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.markdown(f'<div class="sc-card sc-note">{html.escape(message)}</div>', unsafe_allow_html=True)


def download(label: str, data: str, file_name: str, mime: str, key: str) -> None:
    st.download_button(label, data=data, file_name=file_name, mime=mime, key=key)


def disclaimer_footer() -> None:
    st.caption(config.DISCLAIMER)
