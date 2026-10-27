"""Page 2 - Match DNA: team behaviour fingerprint."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.match_dna import compare_teams
from src.analytics.metrics import METRIC_DEFINITIONS, windowed_counts
from src.models import LANES, ZONES
from src.ui import components as C
from src.ui.context import Ctx


def render(ctx: Ctx) -> None:
    m = ctx.match
    st.title("Match DNA")
    C.banner(m)
    st.caption("Event-based behaviour fingerprint. Every metric is explained at the bottom of this page.")
    if not ctx.events:
        C.empty_state("No events yet. Press Play in the Match Center or switch off 'only use events revealed so far'.")
        return

    res = compare_teams(ctx.events, m)
    dna = res["dna"]
    h, a = m.home.team_id, m.away.team_id

    # ---- headline numbers ---------------------------------------------------------------------------
    cols = st.columns(4)
    with cols[0]:
        C.kpi("Possession changes", str(dna[h]["possession_changes_total"]), "consecutive events by different teams")
    for col, (tid, color) in zip(cols[1:], ((h, "home"), (a, "away"))):
        d = dna[tid]
        poss = d["possession_share"]
        with col:
            C.kpi(m.team_name(tid), f"{(poss or 0):.0%} possession",
                  f"pass completion {(d['pass_completion']['rate'] or 0):.0%} · shots {d['shots']['shots']}")
    with cols[3]:
        sh = dna[h]["shots"]
        sa = dna[a]["shots"]
        C.kpi("Shot conversion", f"{sh['goals']}/{sh['shots']} vs {sa['goals']}/{sa['shots']}",
              "goals per shot (home vs away); small counts are noisy")

    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        for tid, col in ((h, C.CYAN), (a, C.AMBER)):
            fig.add_trace(go.Bar(name=m.team_name(tid), x=list(ZONES), y=[dna[tid]["turnovers_by_zone"][z] for z in ZONES],
                                 marker_color=col))
        fig.update_layout(title="Turnovers by pitch zone (team-relative thirds)", barmode="group", height=330,
                          yaxis_title="turnovers")
        C.chart(fig, key="dna_zone")
    with right:
        fig = go.Figure()
        for tid, col in ((h, C.CYAN), (a, C.AMBER)):
            fig.add_trace(go.Bar(name=m.team_name(tid), x=list(LANES), y=[dna[tid]["lane_share"][ln] for ln in LANES],
                                 marker_color=col, text=[f"{dna[tid]['lane_counts'][ln]}" for ln in LANES]))
        fig.update_layout(title="Attacking direction: share of final-third passes/shots by lane", barmode="group",
                          height=330, yaxis=dict(tickformat=".0%"))
        C.chart(fig, key="dna_lane")

    # ---- team detail --------------------------------------------------------------------------------------
    st.subheader("Team detail")
    choice = st.radio("Team", [m.home.name, m.away.name], horizontal=True, key="dna_team")
    tid = h if choice == m.home.name else a
    d = dna[tid]
    c1, c2 = st.columns([1, 1])
    with c1:
        C.chart(C.heat_figure(ctx.events, m, tid, f"{choice}: where events happen (team attacks to the right)",
                              C.CYAN if tid == h else C.AMBER), key="dna_heat")
    with c2:
        st.markdown("**First half vs second half**")
        rows = [{"metric": r["metric"], "1st half": r["first_half"], "2nd half": r["second_half"], "change": r["change"]}
                for r in d["period_comparison"]]
        C.table(pd.DataFrame(rows), height=330)
        df = d["defensive"]
        st.markdown(
            f"**Defensive breakdowns:** {df['defensive_third_turnovers']} turnovers in the own defensive third; "
            f"{df['followed_by_opponent_shot_60s']} of them were followed by an opponent shot within 60 s "
            f"(*association only*).")

    # ---- rate over time -------------------------------------------------------------------------------------
    fig = go.Figure()
    for tid2, col in ((h, C.CYAN), (a, C.AMBER)):
        xs, ys = zip(*windowed_counts(ctx.events, tid2, "turnover", 5))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=f"{m.team_name(tid2)} turnovers", line=dict(color=col)))
        xs, ys = zip(*windowed_counts(ctx.events, tid2, "shot", 5))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=f"{m.team_name(tid2)} shots",
                                 line=dict(color=col, dash="dot")))
    fig.update_layout(title="Turnovers and shots per 5 minutes", height=300, xaxis_title="minute")
    C.chart(fig, key="dna_rate")

    st.subheader("Notable differences")
    for n in res["notes"]:
        st.markdown(f"- {n}")
    st.caption("Rule-based statements about counts and shares. They describe what happened, not why.")

    with st.expander("How each metric is calculated (formula, data needed, limitations)", expanded=ctx.mode == "analyst"):
        C.table(pd.DataFrame(METRIC_DEFINITIONS), height=420)
    C.disclaimer_footer()
