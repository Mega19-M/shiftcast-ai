"""Page 1 - Match Center: simulated live feed, filters, scoreboard, pitch, timeline, Synthetic Match Lab."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analytics.metrics import (filter_events, pass_completion, possession_share, score_at, shot_summary)
from src.data.generator import TEAM_POOL
from src.data.validation import summarise_report
from src.models import EVENT_TYPES, PATTERN_KINDS
from src.reporting.exports import events_to_csv
from src.ui import components as C
from src.ui.context import Ctx, create_custom_match


# ----------------------------------------------------------------------------- callbacks
def _toggle_play(pkey: str, ckey: str, total: int) -> None:
    if not st.session_state.get(pkey, False) and st.session_state.get(ckey, 0) >= total:
        st.session_state[ckey] = 0  # restart from the beginning when pressing play at full time
    st.session_state[pkey] = not st.session_state.get(pkey, False)


def _step(ckey: str, total: int, n: int, pkey: str) -> None:
    st.session_state[pkey] = False
    st.session_state[ckey] = max(0, min(total, st.session_state.get(ckey, 0) + n))


def _step_minute(ckey: str, events: list, pkey: str) -> None:
    st.session_state[pkey] = False
    cur = st.session_state.get(ckey, 0)
    t = events[cur - 1].minute if cur > 0 else 0.0
    nxt = cur
    while nxt < len(events) and events[nxt].minute <= t + 1.0:
        nxt += 1
    st.session_state[ckey] = nxt


def _set(ckey: str, value: int, pkey: str) -> None:
    st.session_state[pkey] = False
    st.session_state[ckey] = value


def _jump(ckey: str, events: list, pkey: str, minute_key: str) -> None:
    st.session_state[pkey] = False
    minute = float(st.session_state.get(minute_key, 0))
    st.session_state[ckey] = sum(1 for e in events if e.minute <= minute)


def _generate_custom() -> None:
    ss = st.session_state
    patterns = []
    for i in (1, 2, 3):
        if ss.get(f"lab_on_{i}"):
            start = int(ss.get(f"lab_start_{i}", 20))
            length = config.WINDOW_BY_KIND[ss.get(f"lab_kind_{i}", "flank_overload")]
            p = {"kind": ss.get(f"lab_kind_{i}"), "side": ss.get(f"lab_side_{i}", "home"), "start": start,
                 "end": min(89, start + length)}
            if p["kind"] == "flank_overload":
                p["lane"] = ss.get(f"lab_lane_{i}", "left")
            patterns.append(p)
    home, away = ss.get("lab_home", "HBC"), ss.get("lab_away", "NGU")
    if home == away:
        ss["lab_error"] = "Choose two different teams."
        return
    ss["lab_error"] = ""
    key = create_custom_match(ss.get("lab_seed", 7), home, away, patterns, float(ss.get("lab_drop", 0.0)),
                              bool(ss.get("lab_faults", False)))
    ss["match_choice"] = key


# ----------------------------------------------------------------------------- page
def render(ctx: Ctx) -> None:
    m = ctx.match
    st.title("Match Center")
    C.banner(m)
    st.caption(f"{m.title} · seed {m.seed} · {len(ctx.all_events)} validated events")

    total = len(ctx.all_events)
    ckey, pkey = f"cursor::{m.match_id}", f"playing::{m.match_id}"
    skey, mkey = f"speed::{m.match_id}", f"jump::{m.match_id}"
    playing = bool(st.session_state.get(pkey, False))

    # ---- controls ------------------------------------------------------------------------
    c = st.columns([1.2, 1, 1, 1, 1, 1, 2])
    c[0].button("⏸ Pause" if playing else "▶ Play", on_click=_toggle_play, args=(pkey, ckey, total), key=f"play_{m.match_id}")
    c[1].button("Step +1", on_click=_step, args=(ckey, total, 1, pkey), key=f"s1_{m.match_id}")
    c[2].button("Step +10", on_click=_step, args=(ckey, total, 10, pkey), key=f"s10_{m.match_id}")
    c[3].button("+1 minute", on_click=_step_minute, args=(ckey, ctx.all_events, pkey), key=f"sm_{m.match_id}")
    c[4].button("Reset", on_click=_set, args=(ckey, 0, pkey), key=f"rs_{m.match_id}")
    c[5].button("Full time", on_click=_set, args=(ckey, total, pkey), key=f"ft_{m.match_id}")
    speed = c[6].select_slider("Play speed (events per second)", options=[2, 5, 10, 20, 40], value=10, key=skey)
    j = st.columns([1, 1, 4])
    j[0].number_input("Jump to minute", min_value=0, max_value=90, value=45, step=1, key=mkey)
    j[1].button("Go", on_click=_jump, args=(ckey, ctx.all_events, pkey, mkey), key=f"go_{m.match_id}")

    # ---- filters ---------------------------------------------------------------------------
    f = st.columns(4)
    teams = f[0].multiselect("Team", [m.home.name, m.away.name], default=[m.home.name, m.away.name], key="f_team")
    roster = {p.name: p.player_id for t in (m.home, m.away) for p in t.players}
    player = f[1].selectbox("Player", ["All players"] + sorted(roster), key="f_player")
    types = f[2].multiselect("Event type", list(EVENT_TYPES), default=list(EVENT_TYPES), key="f_types")
    period = f[3].radio("Period", ["Both", "1st half", "2nd half"], horizontal=True, key="f_period")
    team_ids = {m.home.name: m.home.team_id, m.away.name: m.away.team_id}
    sel_teams = {team_ids[t] for t in teams}
    pid = None if player == "All players" else roster[player]
    per = {"Both": None, "1st half": 1, "2nd half": 2}[period]

    def apply_filters(events: list) -> list:
        out = [e for e in events if e.team_id in sel_teams and e.event_type in types]
        if pid:
            out = [e for e in out if e.player_id == pid]
        if per:
            out = [e for e in out if e.period == per]
        return out

    # ---- live area (a fragment so Play can refresh it every second) ---------------------------
    def live() -> None:
        cur = int(st.session_state.get(ckey, total))
        if st.session_state.get(pkey, False):
            cur = min(total, cur + int(st.session_state.get(skey, speed)))
            st.session_state[ckey] = cur
            if cur >= total:
                st.session_state[pkey] = False
                st.rerun()
        _draw_live(ctx, cur, apply_filters)

    frag = st.fragment(live, run_every=1.0 if playing else None)
    frag()

    # ---- data tools -----------------------------------------------------------------------------
    st.divider()
    t1, t2 = st.columns(2)
    with t1:
        with st.expander("Data validation report", expanded=ctx.validation.rejected > 0 or bool(ctx.validation.issues)):
            v = ctx.validation
            st.write(f"Input events: **{v.total_input}** · accepted: **{v.accepted}** · rejected: **{v.rejected}**")
            if not v.issues:
                st.success("No data-quality issues found.")
            else:
                st.dataframe(pd.DataFrame([{"code": k, "count": n} for k, n in summarise_report(v).items()]),
                             hide_index=True)
                C.table(pd.DataFrame([i.model_dump() for i in v.issues][:200]), height=240)
        C.download("Download events (CSV)", events_to_csv(ctx.all_events), f"{m.match_id}_events.csv", "text/csv", "dl_events")
    with t2:
        with st.expander("Synthetic Match Lab - generate your own match"):
            _lab_form()
    C.disclaimer_footer()


def _draw_live(ctx: Ctx, cur: int, apply_filters) -> None:
    m = ctx.match
    shown = ctx.all_events[:cur]
    h, a = score_at(shown, m.home.team_id, m.away.team_id)
    minute = shown[-1].minute if shown else 0.0

    s = st.columns([3, 2, 3])
    s[0].markdown(f"<div class='sc-team' style='color:{C.CYAN}'>{m.home.name}</div>", unsafe_allow_html=True)
    s[1].markdown(f"<div class='sc-score'>{h} – {a}</div><div class='sc-note' style='text-align:center'>"
                  f"minute {minute:.0f}' · event {cur}/{len(ctx.all_events)}</div>", unsafe_allow_html=True)
    s[2].markdown(f"<div class='sc-team' style='color:{C.AMBER}'>{m.away.name}</div>", unsafe_allow_html=True)
    st.progress(cur / max(1, len(ctx.all_events)))

    if not shown:
        C.empty_state("Kick-off! Press Play, or use Step / Jump to reveal events. All analytics update with the feed.")
        return

    filt = apply_filters(shown)
    left, right = st.columns([2, 1])
    with left:
        if filt:
            C.chart(C.pitch_figure(filt, m, "Latest events (home attacks right, away attacks left)"), key="pitch_live")
        else:
            C.empty_state("No events match the current filters.")
    with right:
        for team in (m.home, m.away):
            ss = shot_summary(shown, team.team_id)
            pc = pass_completion(shown, team.team_id)["rate"]
            poss = possession_share(shown, team.team_id)
            tos = len(filter_events(shown, team_id=team.team_id, event_type="turnover"))
            sub = f"on target {ss['on_target']} · turnovers {tos}"
            if pc is not None:
                sub += f" · pass completion {pc:.0%}"
            if poss is not None:
                sub += f" · possession {poss:.0%}"
            C.kpi(team.name, f"{ss['shots']} shots · {ss['goals']} goals", sub)

    # activity timeline: events per 5 minutes per team, goals marked
    fig = go.Figure()
    bins = list(range(0, 90, 5))
    for team, col in ((m.home, C.CYAN), (m.away, C.AMBER)):
        ys = [sum(1 for e in shown if e.team_id == team.team_id and b <= e.minute < b + 5) for b in bins]
        fig.add_trace(go.Scatter(x=bins, y=ys, mode="lines+markers", name=team.name, line=dict(color=col)))
    for g in [e for e in shown if e.event_type == "goal"]:
        fig.add_vline(x=g.minute, line=dict(color=C.GREEN, dash="dot"), annotation_text="goal")
    fig.update_layout(title="Match timeline: events per 5 minutes", height=240, xaxis_title="minute")
    C.chart(fig, key="timeline_live")

    st.subheader("Event feed")
    rows = [{"clock": e.clock, "team": m.team_name(e.team_id), "player": m.player_name(e.player_id),
             "type": e.event_type, "detail": e.outcome or e.cause or "", "id": e.event_id}
            for e in reversed(filt[-60:])]
    if rows:
        C.table(pd.DataFrame(rows), height=260)


def _lab_form() -> None:
    names = sorted(TEAM_POOL)
    st.caption("Same seed + same settings = exactly the same match. Planted patterns become the 'known answer' "
               "that the Evaluation page scores.")
    a, b, c = st.columns(3)
    a.number_input("Random seed", min_value=1, max_value=99999, value=7, step=1, key="lab_seed")
    b.selectbox("Home team", names, index=0, format_func=lambda k: TEAM_POOL[k], key="lab_home")
    c.selectbox("Away team", names, index=1, format_func=lambda k: TEAM_POOL[k], key="lab_away")
    for i in (1, 2, 3):
        r = st.columns([0.6, 1.6, 1, 1, 1])
        r[0].checkbox(f"#{i}", value=(i == 1), key=f"lab_on_{i}")
        r[1].selectbox("Pattern", list(PATTERN_KINDS), index=min(i - 1, 3), key=f"lab_kind_{i}", label_visibility="collapsed")
        r[2].selectbox("Team", ["home", "away"], key=f"lab_side_{i}", label_visibility="collapsed")
        r[3].slider("Start minute", 3, 70, 10 + 25 * (i - 1), key=f"lab_start_{i}", label_visibility="collapsed")
        r[4].selectbox("Lane", ["left", "right"], key=f"lab_lane_{i}", label_visibility="collapsed")
    st.slider("Remove this share of shot records (missing-event test)", 0.0, 0.8, 0.0, 0.05, key="lab_drop")
    st.checkbox("Inject data faults (duplicates, bad minutes, unknown ids, wrong scoreboard...)", key="lab_faults")
    st.button("Generate match", on_click=_generate_custom, key="lab_go")
    if st.session_state.get("lab_error"):
        st.error(st.session_state["lab_error"])
