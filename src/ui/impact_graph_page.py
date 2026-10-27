"""Page 3 - Impact Graph: related events, with the reason for every connection."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.impact_graph import ROW_LABELS, chain_table
from src.models import GraphData, Insight, Match
from src.ui import components as C
from src.ui.context import Ctx

REL_STYLE = {
    "recorded_outcome": dict(color=C.GREEN, dash="solid", width=2.5, name="Recorded outcome (stated by the data)"),
    "temporal": dict(color="#6B7C99", dash="dot", width=1.2, name="Temporal order only"),
    "statistical": dict(color=C.AMBER, dash="dash", width=2, name="Statistical association (not causation)"),
}
SYMBOL = {"pass": "circle", "turnover": "x", "interception": "diamond", "tackle": "square", "shot": "star",
          "goal": "star-diamond"}


def graph_figure(g: GraphData, match: Match, insight: Insight, selected: str | None) -> go.Figure:
    pos = {n.node_id: (n.x, n.y) for n in g.nodes}
    fig = go.Figure()
    for rel, st_ in REL_STYLE.items():
        es = [e for e in g.edges if e.relation == rel and e.source in pos and e.target in pos]
        if not es:
            continue
        xs, ys = [], []
        for e in es:
            xs += [pos[e.source][0], pos[e.target][0], None]
            ys += [pos[e.source][1], pos[e.target][1], None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=st_["name"], hoverinfo="skip",
                                 line=dict(color=st_["color"], dash=st_["dash"], width=st_["width"])))
        # invisible midpoints carry the hover text that explains each connection
        fig.add_trace(go.Scatter(
            x=[(pos[e.source][0] + pos[e.target][0]) / 2 for e in es], y=[(pos[e.source][1] + pos[e.target][1]) / 2 for e in es],
            mode="markers", marker=dict(size=9, color=st_["color"], opacity=0.01), showlegend=False,
            text=[f"<b>{e.label}</b><br>{e.reason}<br><i>{e.caveat}</i>" for e in es], hoverinfo="text"))
        if rel != "temporal":
            for e in es:
                fig.add_annotation(x=pos[e.target][0], y=pos[e.target][1], ax=pos[e.source][0], ay=pos[e.source][1],
                                   xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.1,
                                   arrowwidth=1.6, arrowcolor=st_["color"], opacity=0.8)
    for team, col in ((match.home.team_id, C.CYAN), (match.away.team_id, C.AMBER)):
        for etype, sym in SYMBOL.items():
            ns = [n for n in g.nodes if n.team_id == team and n.event_type == etype]
            if not ns:
                continue
            fig.add_trace(go.Scatter(
                x=[n.x for n in ns], y=[n.y for n in ns], mode="markers", name=f"{match.team_name(team)} {etype}",
                marker=dict(symbol=sym, size=[17 if n.in_pattern else 11 for n in ns], color=col,
                            line=dict(width=[2 if n.in_pattern else 0.5 for n in ns], color="#FFFFFF")),
                customdata=[n.node_id for n in ns], text=[n.label + ("<br><b>supports the insight</b>" if n.in_pattern else "")
                                                         for n in ns], hoverinfo="text", showlegend=False))
    if selected and selected in pos:
        fig.add_trace(go.Scatter(x=[pos[selected][0]], y=[pos[selected][1]], mode="markers", hoverinfo="skip",
                                 marker=dict(size=30, symbol="circle-open", color=C.GREEN, line=dict(width=3)),
                                 showlegend=False))
    focal = insight.team_id
    rows = list(ROW_LABELS.items())
    tickvals = [k for k, _ in rows] + [k + 6 for k, _ in rows]
    ticktext = [f"{v} ({focal})" for _, v in rows] + [f"{v} (opp.)" for _, v in rows]
    fig.update_layout(height=520, xaxis_title="match minute", yaxis=dict(tickvals=tickvals, ticktext=ticktext, autorange="reversed"),
                      title="Event graph - click a node to inspect it", legend=dict(orientation="h", y=-0.2))
    return fig


def render(ctx: Ctx) -> None:
    m = ctx.match
    st.title("Impact Graph")
    C.banner(m)
    st.caption("Three kinds of line are kept apart on purpose: what the data RECORDS, what merely FOLLOWS in time, "
               "and what is only STATISTICALLY ASSOCIATED. None of them proves cause and effect.")
    if not ctx.events:
        C.empty_state("No events yet. Press Play in the Match Center or analyse the full match.")
        return
    pipe = ctx.pipeline
    bundles = [b for b in pipe.bundles if b.graph is not None]
    if not bundles:
        C.empty_state("No statistically notable turning point was found, so there is nothing to connect. "
                      "Try another match or generate one with planted patterns in the Synthetic Match Lab.")
        return
    labels = {b.insight.insight_id: f"{b.insight.title} (strength {b.insight.evidence_strength:.2f})" for b in bundles}
    sel_id = st.selectbox("Turning point", list(labels), format_func=lambda k: labels[k], key="ig_insight")
    bundle = next(b for b in bundles if b.insight.insight_id == sel_id)
    g, ins = bundle.graph, bundle.insight
    st.markdown(f"**{ins.explanation}**")

    by_id = {e.event_id: e for e in ctx.events}
    node_ids = [n.node_id for n in g.nodes]
    sel_key = f"ig_sel::{sel_id}"
    clicked = C.chart_select(graph_figure(g, m, ins, st.session_state.get(sel_key)), key=f"ig_chart::{sel_id}")
    if clicked and clicked in node_ids:
        st.session_state[sel_key] = clicked
    # fallback / precise selector (always works, also on older Streamlit versions)
    default = st.session_state.get(sel_key, node_ids[0] if node_ids else None)
    chosen = st.selectbox("Inspect an event", node_ids, index=node_ids.index(default) if default in node_ids else 0,
                          format_func=lambda i: next(n.label for n in g.nodes if n.node_id == i), key=f"ig_pick::{sel_id}")
    st.session_state[sel_key] = chosen

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Source event")
        e = by_id.get(chosen)
        if e:
            st.json({**e.model_dump(), "clock": e.clock, "team": m.team_name(e.team_id), "player": m.player_name(e.player_id),
                     "zone": e.zone, "lane": e.lane})
            incoming = [x for x in g.edges if x.target == chosen]
            outgoing = [x for x in g.edges if x.source == chosen]
            st.caption(f"{len(incoming)} incoming and {len(outgoing)} outgoing connections in this graph.")
    with c2:
        st.subheader("Association check")
        a = g.association
        if a.get("rate_in_window") is None or a.get("rate_outside_window") is None:
            st.write("Not enough shots to compare the window with the rest of the match.")
        else:
            st.write(f"Shots by **{m.team_name(a['target_team'])}** that follow a pattern event within 60 s: "
                     f"**{a['shots_in_window_following_pattern_event']}/{a['shots_in_window']}** in the window vs "
                     f"**{a['shots_outside_following_pattern_event']}/{a['shots_outside_window']}** elsewhere.")
        st.caption(a.get("note", ""))
        st.caption(a.get("definition", ""))

    st.subheader("Chronological event chain")
    C.table(pd.DataFrame(chain_table(g, ctx.events, m)), height=260)

    st.subheader("Why each connection exists")
    rel_filter = st.multiselect("Show connection types", ["recorded_outcome", "temporal", "statistical"],
                                default=["recorded_outcome", "statistical"], key="ig_rel")
    rows = [{"type": e.relation, "from": e.source, "to": e.target, "label": e.label, "why": e.reason, "caveat": e.caveat}
            for e in g.edges if e.relation in rel_filter]
    if rows:
        C.table(pd.DataFrame(rows), height=300)
    else:
        st.info("No connections of the selected types in this graph.")
    C.disclaimer_footer()
