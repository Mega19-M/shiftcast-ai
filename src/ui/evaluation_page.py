"""Page 6 - Evaluation & Testing: measured reliability on synthetic data with known answers."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
from src.analytics.evaluation import evaluate_detectors, evaluate_trusttrace, evaluate_validation
from src.ui import components as C
from src.ui.context import Ctx


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def render(ctx: Ctx) -> None:
    st.title("Evaluation & Testing")
    C.banner(ctx.match)
    st.markdown(
        "<div class='sc-card'><b>Read this first.</b> The synthetic generator and the detectors were written by the same "
        "people, so these scores show that the pipeline behaves as designed on <i>its own</i> synthetic world. They are "
        "<b>not</b> evidence of accuracy on real football data. Thresholds were tuned on the development seeds only; "
        "the held-out seeds were not used for tuning.</div>", unsafe_allow_html=True)

    st.subheader("1. Turning-point detection vs planted patterns")
    choice = st.radio("Seeds", ["Held-out seeds (100-119, not used for tuning)", "Development seeds (1-10, used for tuning)"],
                      key="ev_seeds")
    seeds = config.HELDOUT_SEEDS if choice.startswith("Held-out") else config.DEV_SEEDS
    store = st.session_state.setdefault("eval_cache", {})
    if st.button("Run detection evaluation", key="ev_run"):
        with st.spinner(f"Generating {len(seeds)} matches with planted patterns plus controls and scoring the detectors..."):
            store[tuple(seeds)] = evaluate_detectors(tuple(seeds))
    res = store.get(tuple(seeds))
    if res is None:
        C.empty_state("Press the button to run the evaluation (takes a few seconds per ten matches).")
    else:
        o = res["overall"]
        c = st.columns(4)
        with c[0]:
            C.kpi("Precision", _fmt(o["precision"]), f"{o['tp']} true / {o['tp'] + o['fp']} detected")
        with c[1]:
            C.kpi("Recall", _fmt(o["recall"]), f"{o['tp']} found / {o['tp'] + o['fn']} planted")
        with c[2]:
            C.kpi("F1", _fmt(o["f1"]), "harmonic mean")
        with c[3]:
            ctl = res["control"]
            C.kpi("False alarms on control matches", f"{ctl['false_alarms_per_match']:.2f} / match",
                  f"{ctl['false_alarms']} in {ctl['n_matches']} matches with no planted pattern")
        rows = [{"rule": k, **{kk: (_fmt(vv) if kk in ("precision", "recall", "f1") else vv) for kk, vv in v.items()}}
                for k, v in res["per_kind"].items()]
        C.table(pd.DataFrame(rows))
        with st.expander("Per-match results"):
            C.table(pd.DataFrame([{"match": r["match_id"], "planted": r["planted"], "tp": r["tp"], "fp": r["fp"], "fn": r["fn"],
                                   "missed": "; ".join(r["missed"]), "false alarms": "; ".join(r["false_alarms"])}
                                  for r in res["per_match"]]), height=320)
        st.caption(res["note"] + " A hit = same rule and team, windows overlapping by at least 3 minutes. "
                   "The exploratory 'possession_shift' rule has no planted counterpart and is not scored.")

    st.subheader("2. Data-validation fault injection")
    if st.button("Inject faults and check the validator", key="ev_val"):
        st.session_state["ev_val_res"] = evaluate_validation(5)
    v = st.session_state.get("ev_val_res")
    if v:
        st.markdown(f"{v['input']} raw events → accepted **{v['accepted']}**, rejected **{v['rejected']}** · "
                    f"all injected faults found: **{'yes' if v['all_found'] else 'NO'}**")
        C.table(pd.DataFrame(v["rows"]))

    st.subheader("3. TrustTrace true/false statement set")
    if st.button("Run TrustTrace regression statements", key="ev_tt"):
        st.session_state["ev_tt_res"] = evaluate_trusttrace(3)
    t = st.session_state.get("ev_tt_res")
    if t:
        st.markdown(f"False statements caught: **{t['false_caught']}/{t['n_false']}** · "
                    f"true statements accepted: **{t['true_passed']}/{t['n_true']}**")
        C.table(pd.DataFrame(t["rows"]), height=360)
        st.caption(t["note"])

    st.subheader("4. Automated tests")
    st.markdown("Run these in a terminal inside the project folder (see README):")
    st.code("python -m pytest -q\npython scripts/run_checks.py", language="powershell")
    st.caption("`run_checks.py` needs no extra packages: it compiles every file, imports every module and runs an end-to-end "
               "pipeline smoke test.")

    st.subheader("Thresholds in use")
    C.table(pd.DataFrame([{"setting": k, "value": str(v)} for k, v in {
        "window minutes per rule": config.WINDOW_BY_KIND, "p-value threshold": config.P_VALUE_THRESHOLD,
        "min turnovers": config.MIN_COUNT_TURNOVER, "min shots": config.MIN_COUNT_SHOT,
        "min flank actions": config.MIN_COUNT_LANE, "min defensive-third turnovers": config.MIN_COUNT_DEFENSIVE,
        "min lane share": config.LANE_SHARE_MIN}.items()]))
    C.disclaimer_footer()
