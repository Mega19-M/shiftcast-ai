"""Page 4 - What-If Match Lab: actual sequence vs two heuristic alternatives."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.scenarios.what_if import actual_summary, build_scenarios, scenario_key
from src.ui import components as C
from src.ui.context import Ctx


def _metric_figure(sc) -> go.Figure | None:
    ms = [x for x in sc.metrics if x.low is not None and x.high is not None]
    if not ms:
        return None
    names = [x.metric[:38] + ("…" if len(x.metric) > 38 else "") for x in ms]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="MEASURED (actual)", x=names, y=[x.actual if x.actual is not None else 0 for x in ms],
                         marker_color=C.CYAN))
    mid = [(x.low + x.high) / 2 for x in ms]
    fig.add_trace(go.Bar(name="HYPOTHETICAL (midpoint, bar = range)", x=names, y=mid, marker_color=C.AMBER,
                         marker_pattern_shape="/",
                         error_y=dict(type="data", array=[(x.high - x.low) / 2 for x in ms], visible=True)))
    fig.update_layout(barmode="group", height=300, legend=dict(orientation="h", y=-0.35))
    return fig


def render(ctx: Ctx) -> None:
    m = ctx.match
    st.title("What-If Match Lab")
    C.banner(m)
    st.markdown(
        "<div class='sc-card sc-hyp'><b>HEURISTIC SCENARIO ANALYSIS.</b> The alternatives below are built from simple "
        "formulas using rates measured in this same match. They are <b>not predictions</b> of what would have happened. "
        "Change the assumptions and watch the ranges move.</div>", unsafe_allow_html=True)
    if not ctx.events:
        C.empty_state("No events yet. Press Play in the Match Center or analyse the full match.")
        return
    pipe = ctx.pipeline
    if not pipe.bundles:
        C.empty_state("No turning point was detected in this match, so there is nothing to explore.")
        return
    labels = {b.insight.insight_id: b.insight.title for b in pipe.bundles}
    sel = st.selectbox("Turning point", list(labels), format_func=lambda k: labels[k], key="wi_insight")
    ins = next(b.insight for b in pipe.bundles if b.insight.insight_id == sel)

    # first pass: defaults, to know which parameters exist; second pass: with the user's slider values
    defaults = build_scenarios(ins, ctx.events, m)
    overrides: dict[str, dict[str, float]] = {}
    cols = st.columns(3)
    with cols[0]:
        st.markdown("### Actual\n**MEASURED from the event data**")
        a = actual_summary(ins, ctx.events, m)
        rows = [("Window", a["window"]), ("Team", a["team"]), ("Turnovers", a["turnovers"]),
                ("…of which failed passes", a["failed_pass_turnovers"]), ("Shots", a["shots"]), ("Goals", a["goals"]),
                ("Opponent shots", a["opponent_shots"]),
                ("Opponent shots ≤60 s after our turnovers", a["opponent_shots_within_60s_after_turnover"])]
        C.table(pd.DataFrame(rows, columns=["measured fact", "value"]))
        st.caption(f"{len(ins.event_ids)} supporting events: " + ", ".join(ins.event_ids[:4]) + (" …" if len(ins.event_ids) > 4 else ""))
        st.caption(ins.explanation)
    for col, sc0 in zip(cols[1:], defaults):
        key = scenario_key(sc0)
        with col:
            st.markdown(f"### {sc0.name.split(':')[0]}\n**HYPOTHETICAL - {sc0.name.split(': ', 1)[-1]}**")
            ov = {}
            for p in sc0.params:
                ov[p.key] = st.slider(p.label, float(p.minimum), float(p.maximum), float(p.value), float(p.step),
                                      help=p.help, key=f"wi::{sel}::{key}::{p.key}")
            overrides[key] = ov
    scenarios = build_scenarios(ins, ctx.events, m, overrides)

    for col, sc in zip(cols[1:], scenarios):
        with col:
            st.markdown(f"<div class='sc-card sc-hyp'><b>{sc.action}</b><br><span class='sc-note'>{sc.label}</span></div>",
                        unsafe_allow_html=True)
            st.markdown(f"**Intended benefit:** {sc.benefit}")
            st.markdown(f"**Trade-off:** {sc.trade_off}")
            for w in sc.warnings:
                st.warning(w)
            if sc.metrics:
                df = pd.DataFrame([{"metric": x.metric, "MEASURED": x.actual,
                                    "HYPOTHETICAL low": x.low, "HYPOTHETICAL high": x.high} for x in sc.metrics])
                C.table(df, height=min(300, 60 + 35 * len(df)))
                fig = _metric_figure(sc)
                if fig:
                    C.chart(fig, key=f"wi_fig::{sel}::{sc.scenario_id}")
            with st.expander("Assumptions, formulas and missing data", expanded=ctx.mode == "analyst"):
                st.markdown("**Assumptions**")
                for x in sc.assumptions:
                    st.markdown(f"- {x}")
                st.markdown("**How each hypothetical number is built**")
                for x in sc.metrics:
                    st.markdown(f"- *{x.metric}*: {x.basis}")
                st.markdown("**Data we do not have (so this cannot be a validated simulation)**")
                for x in sc.missing_data:
                    st.markdown(f"- {x}")
    st.caption("Ranges come from 95% Wilson intervals of rates measured in this match, so small samples give wide ranges. "
               "Measured numbers are facts about the synthetic events; hypothetical numbers are assumption-based estimates.")
    C.disclaimer_footer()
