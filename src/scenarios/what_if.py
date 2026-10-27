"""What-If Match Lab: transparent, rule-based scenario comparison.

This module does NOT simulate football and does NOT claim to know what would
have happened. For each detected turning point it builds two alternative
decisions, and for each alternative it:

  1. states its assumptions (as adjustable numeric parameters),
  2. reports MEASURED quantities from the real (synthetic) event data
     ("actual" column), and
  3. reports HYPOTHETICAL ranges built with a simple, printed formula from
     other measured rates in the same match ("low"/"high" columns). Ranges come
     from 95% Wilson intervals of the measured rates, so small samples give
     wide ranges.

Every result is labelled ``HEURISTIC SCENARIO ANALYSIS``. Data that would be
needed for a validated simulation (player positions, defenders, pressure,
shot quality, opponent reaction) is listed in ``missing_data``.
"""
from __future__ import annotations

from typing import Optional

from src.analytics.impact_graph import SHOT_FOLLOW_SECONDS
from src.analytics.metrics import filter_events, wilson_interval
from src.models import Event, Insight, Match, ScenarioMetric, ScenarioParam, ScenarioResult

STANDARD_MISSING = [
    "Player and defender positions (tracking data)",
    "Pressure on the ball and passing options available at that moment",
    "Opponent reaction to the changed decision",
    "Shot quality (no expected-goals model in this dataset)",
    "Physical or fatigue data (never inferred from event counts)",
]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _param(overrides: Optional[dict], key: str, label: str, default: float, lo: float, hi: float,
           step: float, help_: str) -> ScenarioParam:
    v = _clamp(float((overrides or {}).get(key, default)), lo, hi)
    return ScenarioParam(key=key, label=label, value=v, minimum=lo, maximum=hi, step=step, help=help_)


def _inside(e: Event, s: float, t: float) -> bool:
    return s <= e.minute <= t


# --------------------------------------------------------------------------
# Measured facts about the actual sequence
# --------------------------------------------------------------------------
def actual_summary(insight: Insight, events: list[Event], match: Match) -> dict:
    """Measured facts for the 'Actual' column of the What-If Lab."""
    T, O = insight.team_id, match.opponent_id(insight.team_id)
    s, e = insight.start_min, insight.end_min
    win = [x for x in events if _inside(x, s, e)]
    tos = [x for x in win if x.team_id == T and x.event_type == "turnover"]
    opp_shots_after = _shots_after(events, tos, O)
    return {
        "window": f"{s:.0f}'-{e:.0f}'",
        "team": match.team_name(T),
        "turnovers": len(tos),
        "failed_pass_turnovers": sum(1 for x in tos if x.cause == "failed_pass"),
        "shots": sum(1 for x in win if x.team_id == T and x.event_type == "shot"),
        "goals": sum(1 for x in win if x.team_id == T and x.event_type == "goal"),
        "opponent_shots": sum(1 for x in win if x.team_id == O and x.event_type == "shot"),
        "opponent_shots_within_60s_after_turnover": len(opp_shots_after),
        "pass_attempts": sum(1 for x in win if x.team_id == T and x.event_type == "pass"),
        "evidence_event_ids": list(insight.event_ids),
    }


def _shots_after(events: list[Event], anchors: list[Event], team: str) -> list[Event]:
    """Shots by ``team`` that happen 1-60 s after at least one anchor event."""
    out = []
    for sh in events:
        if sh.team_id != team or sh.event_type != "shot":
            continue
        if any(0 < (sh.minute - a.minute) * 60 <= SHOT_FOLLOW_SECONDS for a in anchors):
            out.append(sh)
    return out


def _forward_gain(passes: list[Event]) -> list[float]:
    return [p.end_x - p.x for p in passes if p.outcome == "success" and p.x is not None and p.end_x is not None]


def _mean(v: list[float]) -> Optional[float]:
    return sum(v) / len(v) if v else None


def _follow_rate(events: list[Event], actions: list[Event], team: str) -> tuple[int, int]:
    """(# actions followed by a shot of ``team`` within 60 s, # actions)."""
    shots = [e for e in events if e.team_id == team and e.event_type == "shot"]
    k = sum(1 for a in actions if any(0 < (sh.minute - a.minute) * 60 <= SHOT_FOLLOW_SECONDS for sh in shots))
    return k, len(actions)


# --------------------------------------------------------------------------
# Scenario templates
# --------------------------------------------------------------------------
def _wide_outlet(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    T, O = ins.team_id, match.opponent_id(ins.team_id)
    s, e = ins.start_min, ins.end_min
    w = _param(ov, "w", "Share of central passes redirected wide", 0.5, 0.0, 1.0, 0.05,
               "Fraction of central pass attempts that the alternative decision plays to a flank instead.")
    passes_in = [p for p in filter_events(events, team_id=T, event_type="pass") if _inside(p, s, e) and p.lane]
    central = [p for p in passes_in if p.lane == "center"]
    a_c = len(central)
    f_c = sum(1 for p in central if p.outcome == "fail")
    q_c = (1 - f_c / a_c) if a_c else None
    wide_out = [p for p in filter_events(events, team_id=T, event_type="pass")
                if not _inside(p, s, e) and p.lane in ("left", "right")]
    ok_w = sum(1 for p in wide_out if p.outcome == "success")
    q_w = ok_w / len(wide_out) if wide_out else None
    lo_w, hi_w = wilson_interval(ok_w, len(wide_out))
    warnings = []
    metrics: list[ScenarioMetric] = []
    if a_c < 8:
        warnings.append(f"Only {a_c} central pass attempts in the window - results are unstable.")
    if len(wide_out) < 30:
        warnings.append(f"Only {len(wide_out)} wide passes elsewhere in the match to estimate completion.")
    if a_c and q_c is not None and q_w is not None:
        wv = w.value
        base = a_c * (1 - wv) * (1 - q_c)
        hyp_mid = base + a_c * wv * (1 - q_w)
        hyp_low = base + a_c * wv * (1 - hi_w)
        hyp_high = base + a_c * wv * (1 - lo_w)
        metrics.append(ScenarioMetric(
            metric="Failed central passes (-> turnovers)", actual=float(f_c), low=round(hyp_low, 2), high=round(hyp_high, 2),
            basis="a_c*(1-w)*(1-q_c) + a_c*w*(1-q_wide); q_wide = this team's wide-pass completion outside the window "
                  f"({q_w:.0%}, 95% CI {lo_w:.0%}-{hi_w:.0%}); a_c={a_c}, q_c={q_c:.0%}, w={wv:.2f}"))
        tos = [x for x in events if _inside(x, s, e) and x.team_id == T and x.event_type == "turnover"]
        shots_after = len(_shots_after(events, tos, O))
        ratio_lo, ratio_hi = (hyp_low / f_c, hyp_high / f_c) if f_c else (1.0, 1.0)
        metrics.append(ScenarioMetric(
            metric="Opponent shots within 60s after our turnovers", actual=float(shots_after),
            low=round(shots_after * min(ratio_lo, 1.0), 2), high=round(shots_after * max(ratio_hi, 0.0), 2),
            basis="measured shots x (hypothetical failed passes / actual failed passes); assumes opponent shots scale "
                  "in proportion to turnovers (an assumption, not a finding)"))
        gain_c = _mean(_forward_gain(central))
        gain_w = _mean(_forward_gain([p for p in wide_out]))
        if gain_c is not None and gain_w is not None:
            metrics.append(ScenarioMetric(
                metric="Average forward ground per completed pass (x units)", actual=round(gain_c, 2),
                low=round(min((1 - wv) * gain_c + wv * gain_w, gain_c), 2),
                high=round(max((1 - wv) * gain_c + wv * gain_w, gain_c), 2),
                basis="blend of central passes in window and wide passes elsewhere, weighted by w (trade-off view)"))
    else:
        warnings.append("Not enough passes to compute this scenario.")
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-wide", insight_id=ins.insight_id,
        name="Alternative A: play wide instead of through the centre",
        action="Redirect a share of central pass attempts to a wide player.",
        assumptions=[
            "Wide passes would have the same completion rate as this team's wide passes elsewhere in the match.",
            "Opponent shots after turnovers scale in proportion to the number of turnovers.",
            "The wide option was actually available at those moments (not verifiable).",
        ],
        benefit="Fewer risky central turnovers and fewer fast counter-attacks starting in the middle.",
        trade_off="Wide passes usually gain less ground and can slow the attack; a predictable pattern is easier to defend.",
        metrics=metrics, missing_data=STANDARD_MISSING, params=[w], warnings=warnings,
        evidence_event_ids=[p.event_id for p in central][:30])


def _retain_possession(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    T, O = ins.team_id, match.opponent_id(ins.team_id)
    s, e = ins.start_min, ins.end_min
    r = _param(ov, "r", "Share of failed-pass turnovers retained", 0.4, 0.0, 1.0, 0.05,
               "Fraction of failed-pass turnovers where a safer pass is played and possession is kept.")
    tos = [x for x in events if _inside(x, s, e) and x.team_id == T and x.event_type == "turnover"]
    fp = [x for x in tos if x.cause == "failed_pass"]
    n_to, n_fp = len(tos), len(fp)
    shots_after = len(_shots_after(events, tos, O))
    metrics: list[ScenarioMetric] = []
    warnings = []
    if n_to < 5:
        warnings.append(f"Only {n_to} turnovers in the window - results are unstable.")
    if n_to:
        rv = r.value
        mid = n_to - rv * n_fp
        spread = 0.5  # +-50% of the assumed retained share, shown as the range
        lo_v = n_to - min(1.0, rv * (1 + spread)) * n_fp
        hi_v = n_to - rv * (1 - spread) * n_fp
        metrics.append(ScenarioMetric(
            metric="Turnovers in window", actual=float(n_to), low=round(min(lo_v, hi_v), 2), high=round(max(lo_v, hi_v), 2),
            basis=f"n_turnovers - r * n_failed_pass (r={rv:.2f}, n_failed_pass={n_fp}); range = r +/-50%"))
        scale_lo, scale_hi = min(lo_v, hi_v) / n_to, max(lo_v, hi_v) / n_to
        metrics.append(ScenarioMetric(
            metric="Opponent shots within 60s after our turnovers", actual=float(shots_after),
            low=round(shots_after * scale_lo, 2), high=round(shots_after * scale_hi, 2),
            basis="measured shots x (hypothetical turnovers / actual turnovers); proportionality is an assumption"))
        safe = [p for p in filter_events(events, team_id=T, event_type="pass")
                if _inside(p, s, e) and p.outcome == "success" and p.x is not None and p.end_x is not None
                and -5 <= (p.end_x - p.x) <= 5]
        g_safe = _mean([p.end_x - p.x for p in safe])
        all_gain = sum(_forward_gain([p for p in filter_events(events, team_id=T, event_type="pass") if _inside(p, s, e)]))
        if g_safe is not None:
            add = rv * n_fp * g_safe
            ends = (all_gain + add * (1 - spread), all_gain + add * (1 + spread))
            metrics.append(ScenarioMetric(
                metric="Total forward ground gained by completed passes (x units)", actual=round(all_gain, 1),
                low=round(min(ends), 1), high=round(max(ends), 1),
                basis="actual + r * n_failed_pass * (average gain of 'safe' completed passes, those moving the ball "
                      "between -5 and +5 units, in the window); can be negative net ground"))
    else:
        warnings.append("No turnovers in the window.")
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-retain", insight_id=ins.insight_id,
        name="Alternative B: keep the ball with a safer pass",
        action="Replace a share of risky failed passes with a safe pass that keeps possession.",
        assumptions=[
            "A safe option existed for the retained share of failed passes (not verifiable from event data).",
            "Retained possessions do not change the opponent's behaviour.",
            "Opponent shots scale in proportion to turnovers.",
        ],
        benefit="Fewer giveaways and fewer opponent transitions that start from our mistakes.",
        trade_off="Safe passes usually gain little ground, so the team progresses less and may create fewer chances.",
        metrics=metrics, missing_data=STANDARD_MISSING, params=[r], warnings=warnings,
        evidence_event_ids=[x.event_id for x in fp][:30])


def _lane_actions(events: list[Event], team: str, lane: str, inside: bool, s: float, t: float) -> list[Event]:
    return [x for x in events if x.team_id == team and x.event_type in ("pass", "shot") and x.zone == "attacking"
            and x.lane == lane and (_inside(x, s, t) == inside)]


def _flank_core(ins: Insight, events: list[Event]) -> dict:
    T = ins.team_id
    L = ins.detail.get("lane", "left")
    other = "right" if L == "left" else "left"
    in_L = _lane_actions(events, T, L, True, ins.start_min, ins.end_min)
    out_O = _lane_actions(events, T, other, False, ins.start_min, ins.end_min)
    k_L, n_L = _follow_rate(events, in_L, T)
    k_O, n_O = _follow_rate(events, out_O, T)
    return {"L": L, "other": other, "k_L": k_L, "n_L": n_L, "k_O": k_O, "n_O": n_O, "in_L": in_L}


def _switch_flank(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    c = _flank_core(ins, events)
    sh = _param(ov, "s", "Share of attacks moved to the opposite flank", 1.0, 0.0, 1.0, 0.05,
                "Fraction of the window's flank actions played down the opposite flank instead.")
    lo, hi = wilson_interval(c["k_O"], c["n_O"])
    warnings = []
    metrics = []
    if c["n_L"] < 8:
        warnings.append(f"Only {c['n_L']} actions through the {c['L']} flank in the window.")
    if c["n_O"] < 15:
        warnings.append(f"Only {c['n_O']} actions through the {c['other']} flank elsewhere - the rate is very uncertain.")
    if c["n_L"] and c["n_O"]:
        rate_L = c["k_L"] / c["n_L"]
        rate_O = c["k_O"] / c["n_O"]
        sv = sh.value
        mid = c["n_L"] * ((1 - sv) * rate_L + sv * rate_O)
        low = c["n_L"] * ((1 - sv) * rate_L + sv * lo)
        high = c["n_L"] * ((1 - sv) * rate_L + sv * hi)
        metrics.append(ScenarioMetric(
            metric=f"Flank actions followed by our own shot within 60s (of {c['n_L']} actions)", actual=float(c["k_L"]),
            low=round(min(low, high), 2), high=round(max(low, high), 2),
            basis=f"n * ((1-s)*rate_{c['L']} + s*rate_{c['other']}); rate_{c['other']} measured outside the window = "
                  f"{c['k_O']}/{c['n_O']} ({rate_O:.0%}, 95% CI {lo:.0%}-{hi:.0%}); s={sv:.2f}"))
        metrics.append(ScenarioMetric(
            metric=f"Shot follow-up rate per action ({c['L']} in window vs {c['other']} elsewhere)",
            actual=round(rate_L, 3), low=round(lo, 3), high=round(hi, 3),
            basis="measured rate in window (actual) vs 95% Wilson interval of the opposite flank rate (hypothetical)"))
    else:
        warnings.append("Not enough flank actions to compute this scenario.")
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-switch", insight_id=ins.insight_id,
        name=f"Alternative A: switch the attack to the {c['other']} flank",
        action=f"Play the {c['L']}-flank actions down the {c['other']} flank instead.",
        assumptions=[
            f"The {c['other']} flank would convert actions into shots at its measured rate elsewhere in the match.",
            "Opponent defenders would not adapt to the switch.",
            "The same players could attack the other flank with the same effectiveness.",
        ],
        benefit="Attacks the side the opponent may be weaker on, and makes the pattern less predictable.",
        trade_off="Gives up whatever advantage the original flank was producing; the other flank may be weaker.",
        metrics=metrics, missing_data=STANDARD_MISSING, params=[sh], warnings=warnings,
        evidence_event_ids=[x.event_id for x in c["in_L"]][:30])


def _split_flanks(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    c = _flank_core(ins, events)
    mix = _param(ov, "mix", "Share of attacks sent to the opposite flank", 0.5, 0.0, 1.0, 0.05,
                 "Fraction of attacks moved to the other flank (0.5 = an even split).")
    lo, hi = wilson_interval(c["k_O"], c["n_O"])
    warnings, metrics = [], []
    if c["n_O"] < 15:
        warnings.append(f"Only {c['n_O']} actions through the {c['other']} flank elsewhere - the rate is very uncertain.")
    if c["n_L"] and c["n_O"]:
        rate_L = c["k_L"] / c["n_L"]
        m = mix.value
        low = c["n_L"] * ((1 - m) * rate_L + m * lo)
        high = c["n_L"] * ((1 - m) * rate_L + m * hi)
        metrics.append(ScenarioMetric(
            metric=f"Flank actions followed by our own shot within 60s (of {c['n_L']} actions)", actual=float(c["k_L"]),
            low=round(min(low, high), 2), high=round(max(low, high), 2),
            basis=f"n * ((1-m)*rate_{c['L']} + m*rate_{c['other']}) with m={m:.2f}; rates measured as in Alternative A"))
        metrics.append(ScenarioMetric(
            metric="Share of attacks through one flank (predictability)", actual=round(1.0, 2),
            low=round(max(1 - m, m), 2), high=round(max(1 - m, m), 2),
            basis="max(1-m, m): a lower number means a less one-sided (less predictable) attack"))
    else:
        warnings.append("Not enough flank actions to compute this scenario.")
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-split", insight_id=ins.insight_id,
        name="Alternative B: split attacks between both flanks",
        action=f"Send part of the {c['L']}-flank actions down the {c['other']} flank.",
        assumptions=["Both flanks keep their measured shot follow-up rates.",
                     "Splitting does not reduce the quality of either flank's attacks."],
        benefit="Stretches the defence and reduces predictability.",
        trade_off="Dilutes the pressure on the flank that was working.",
        metrics=metrics, missing_data=STANDARD_MISSING, params=[mix], warnings=warnings,
        evidence_event_ids=[x.event_id for x in c["in_L"]][:30])


def _match_conversion(events: list[Event], team: str) -> tuple[int, int]:
    shots = filter_events(events, team_id=team, event_type="shot")
    return sum(1 for x in shots if x.outcome == "goal"), len(shots)


def _shot_sustain(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    T = ins.team_id
    extra = _param(ov, "extra", "Extra minutes at the same shot rate", 10.0, 1.0, 30.0, 1.0,
                   "How many more minutes the team keeps the same shot volume.")
    win = ins.end_min - ins.start_min
    shots_in = [x for x in filter_events(events, team_id=T, event_type="shot") if _inside(x, ins.start_min, ins.end_min)]
    g, n = _match_conversion(events, T)
    lo, hi = wilson_interval(g, n)
    rate = len(shots_in) / win if win else 0.0
    add_shots = rate * extra.value
    metrics = [
        ScenarioMetric(metric="Shots in window", actual=float(len(shots_in)), basis="measured"),
        ScenarioMetric(
            metric=f"Extra shots if the rate continues for {extra.value:.0f} more minutes", actual=None,
            low=round(add_shots, 2), high=round(add_shots, 2),
            basis=f"shots_in_window / window_minutes * extra_minutes = {len(shots_in)}/{win:.0f}*{extra.value:.0f}"),
        ScenarioMetric(
            metric="Goals implied by this team's whole-match conversion", actual=float(sum(1 for x in shots_in if x.outcome == 'goal')),
            low=round(add_shots * lo, 2), high=round(add_shots * hi, 2),
            basis=f"extra shots x Wilson 95% CI of match conversion ({g}/{n}); actual = goals measured in the window"),
    ]
    warnings = []
    if n < 10:
        warnings.append(f"Only {n} shots in the match - the conversion interval is very wide.")
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-sustain", insight_id=ins.insight_id,
        name="Alternative A: keep shooting at the same rate",
        action="Sustain the high shot volume for more minutes.",
        assumptions=["Shot rate stays constant.", "Shots convert at the team's whole-match rate (shot quality is unknown)."],
        benefit="More chances while the opponent is under pressure.",
        trade_off="Low-quality shots waste possession and invite counter-attacks; the rate is unlikely to stay constant.",
        metrics=metrics, missing_data=STANDARD_MISSING, params=[extra], warnings=warnings,
        evidence_event_ids=[x.event_id for x in shots_in])


def _shot_reduce(ins: Insight, events: list[Event], match: Match, ov: Optional[dict]) -> ScenarioResult:
    T = ins.team_id
    f = _param(ov, "f", "Share of shots replaced by keeping the ball", 0.5, 0.0, 1.0, 0.05,
               "Fraction of the window's shots where the team recycles possession instead of shooting.")
    shots_in = [x for x in filter_events(events, team_id=T, event_type="shot") if _inside(x, ins.start_min, ins.end_min)]
    g, n = _match_conversion(events, T)
    lo, hi = wilson_interval(g, n)
    keep = len(shots_in) * (1 - f.value)
    goals_actual = sum(1 for x in shots_in if x.outcome == "goal")
    metrics = [
        ScenarioMetric(metric="Shots in window", actual=float(len(shots_in)), low=round(keep, 2), high=round(keep, 2),
                       basis="shots * (1 - f)"),
        ScenarioMetric(metric="Goals implied by whole-match conversion", actual=float(goals_actual),
                       low=round(keep * lo, 2), high=round(keep * hi, 2),
                       basis=f"remaining shots x Wilson 95% CI of match conversion ({g}/{n})"),
        ScenarioMetric(metric="Shots replaced by recycled possession", actual=0.0,
                       low=round(len(shots_in) * f.value, 2), high=round(len(shots_in) * f.value, 2),
                       basis="shots * f - what happens to those possessions is NOT modelled"),
    ]
    return ScenarioResult(
        scenario_id=f"{ins.insight_id}-reduce", insight_id=ins.insight_id,
        name="Alternative B: recycle possession instead of shooting",
        action="Turn a share of shots into patient possession.",
        assumptions=["Removed shots would not have scored differently from average shots.",
                     "What the recycled possessions would have produced is unknown and not modelled."],
        benefit="Better shot selection and fewer wasted possessions.",
        trade_off="Fewer chances; opponents get time to reorganise.",
        metrics=metrics, missing_data=STANDARD_MISSING + ["What a recycled possession would produce"],
        params=[f], warnings=[], evidence_event_ids=[x.event_id for x in shots_in])


_BUILDERS = {
    "wide": _wide_outlet, "retain": _retain_possession, "switch": _switch_flank, "split": _split_flanks,
    "sustain": _shot_sustain, "reduce": _shot_reduce,
}
_PLAN = {
    "turnover_spike": ("wide", "retain"),
    "defensive_cluster": ("wide", "retain"),
    "possession_shift": ("wide", "retain"),
    "flank_overload": ("switch", "split"),
    "shot_surge": ("sustain", "reduce"),
}


def build_scenarios(insight: Insight, events: list[Event], match: Match,
                    overrides: Optional[dict[str, dict[str, float]]] = None) -> list[ScenarioResult]:
    """Return the two alternatives for an insight.

    ``overrides`` maps a scenario key (``wide`` / ``retain`` / ``switch`` / ``split`` /
    ``sustain`` / ``reduce``) to parameter values chosen by the user.
    """
    overrides = overrides or {}
    out = []
    for key in _PLAN.get(insight.kind, ("wide", "retain")):
        out.append(_BUILDERS[key](insight, events, match, overrides.get(key)))
    return out


def scenario_key(scenario: ScenarioResult) -> str:
    return scenario.scenario_id.rsplit("-", 1)[-1]
