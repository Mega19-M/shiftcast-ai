"""Turning-point detector: transparent, rule-based statistical scans.

How it works
------------
For each team and each rule we slide a window (10 minutes, or 6 for the
defensive rule) across the match in 1-minute steps. For every window we
compare what happened INSIDE the window with the same team's behaviour in the
REST of the match (the baseline), and compute an exact p-value:

* rate rules (turnover spike, shot surge, defensive cluster): k events out of n opportunities,
      p = P(X >= k) with X ~ Binomial(n, baseline_rate)   (rates, not raw counts, because a team that
      loses the ball more also HAS the ball less, which would hide a spike in raw counts)
* share rules (flank overload, possession shift):
      p = P(X >= observed) with X ~ Binomial(n_in_window, baseline_share)

A window becomes a candidate only if p <= ``P_VALUE_THRESHOLD`` AND minimum
sample-size / effect-size rules are met. Overlapping candidates of the same
rule and team are merged by keeping the one with the smallest p-value.

Evidence strength  =  min(1, -log10(p) / 6)   -- a HEURISTIC 0..1 score that
makes small p-values easy to compare. It is NOT a probability and NOT calibrated.

Caveat (stated in every insight): hundreds of overlapping windows are tested and
p-values are not corrected for that; the strict threshold only reduces false
alarms, it does not remove them. Detections are leads for an analyst, not proof.
"""
from __future__ import annotations

import math
from typing import Optional

import config
from src.analytics.metrics import binom_sf, filter_events
from src.models import INSIGHT_KINDS, Event, Insight, Match

STRENGTH_FORMULA = "min(1, -log10(p_value) / 6)"


def strength_from_p(p: float) -> float:
    return round(min(1.0, -math.log10(max(p, 1e-12)) / 6.0), 3)


def match_length(events: list[Event]) -> float:
    return max(90.0, math.ceil(max((e.minute for e in events), default=0.0)))


# --------------------------------------------------------------------------
# Window evaluation (also reused by TrustTrace to re-check an insight)
# --------------------------------------------------------------------------
def evaluate_window(kind: str, events: list[Event], team_id: str, opponent_id: str,
                    start: float, end: float, lane: Optional[str] = None) -> Optional[dict]:
    """Compute observed/expected/p-value for ONE rule over [start, end].

    Returns None when the rule cannot be evaluated (e.g. no events).
    """
    def rate_rule(num_sel, den_sel) -> Optional[dict]:
        """Binomial rate test: k events of interest out of n opportunities."""
        n_in = [e for e in events if den_sel(e) and start <= e.minute <= end]
        n_out = [e for e in events if den_sel(e) and not (start <= e.minute <= end)]
        k_in = [e for e in events if num_sel(e) and start <= e.minute <= end]
        k_out = sum(1 for e in events if num_sel(e) and not (start <= e.minute <= end))
        if not n_in or not n_out:
            return None
        p0 = min(max(k_out / len(n_out), 0.02), 0.98)
        p = binom_sf(len(k_in), len(n_in), p0)
        return {"observed": float(len(k_in)), "expected": round(len(n_in) * p0, 3), "p_value": p,
                "event_ids": [e.event_id for e in k_in],
                "detail": {"n_actions": len(n_in), "rate": round(len(k_in) / len(n_in), 3),
                           "baseline_rate": round(p0, 3)}}

    def is_action(e: Event) -> bool:  # a "ball action" = a pass or a dispossession
        return e.team_id == team_id and (e.event_type == "pass" or (e.event_type == "turnover" and e.cause == "dispossessed"))

    if kind == "turnover_spike":
        return rate_rule(lambda e: e.team_id == team_id and e.event_type == "turnover", is_action)
    if kind == "shot_surge":
        return rate_rule(lambda e: e.team_id == team_id and e.event_type == "shot",
                         lambda e: e.team_id == team_id and e.event_type in ("pass", "shot") and e.x is not None and e.x >= 55)
    if kind == "defensive_cluster":
        return rate_rule(lambda e: e.team_id == team_id and e.event_type == "turnover" and e.zone == "defensive",
                         lambda e: is_action(e) and e.zone == "defensive")

    if kind == "flank_overload":
        def lane_actions(e: Event) -> bool:
            return (e.team_id == team_id and e.event_type in ("pass", "shot")
                    and e.zone == "attacking" and e.lane is not None)
        inside = [e for e in events if lane_actions(e) and start <= e.minute <= end]
        outside = [e for e in events if lane_actions(e) and not (start <= e.minute <= end)]
        n = len(inside)
        if n == 0 or not outside:
            return None
        best = None
        for ln in ([lane] if lane else ["left", "right"]):
            k = sum(1 for e in inside if e.lane == ln)
            p0 = max(sum(1 for e in outside if e.lane == ln) / len(outside), 0.05)
            p = binom_sf(k, n, p0)
            cand = {"observed": float(k), "expected": round(n * p0, 3), "p_value": p,
                    "event_ids": [e.event_id for e in inside if e.lane == ln],
                    "detail": {"lane": ln, "n_actions": n, "share": round(k / n, 3), "baseline_share": round(p0, 3)}}
            if best is None or p < best["p_value"]:
                best = cand
        return best

    if kind == "possession_shift":
        inside = [e for e in events if start <= e.minute <= end]
        outside = [e for e in events if not (start <= e.minute <= end)]
        n = len(inside)
        if n == 0 or not outside:
            return None
        k = sum(1 for e in inside if e.team_id == team_id)
        p0 = min(max(sum(1 for e in outside if e.team_id == team_id) / len(outside), 0.05), 0.95)
        share = k / n
        if share >= p0:
            p, direction = binom_sf(k, n, p0), "up"
        else:
            p, direction = binom_sf(n - k, n, 1 - p0), "down"
        return {"observed": float(k), "expected": round(n * p0, 3), "p_value": p,
                "event_ids": [e.event_id for e in inside if e.team_id == team_id],
                "detail": {"share": round(share, 3), "baseline_share": round(p0, 3), "direction": direction,
                           "n_events": n}}
    return None


# --------------------------------------------------------------------------
# Rule configuration
# --------------------------------------------------------------------------
def _passes_rule(kind: str, r: dict) -> bool:
    obs = r["observed"]
    if r["p_value"] > config.P_VALUE_THRESHOLD:
        return False
    if kind == "turnover_spike":
        return obs >= config.MIN_COUNT_TURNOVER and obs > r["expected"]
    if kind == "shot_surge":
        return obs >= config.MIN_COUNT_SHOT and obs > r["expected"]
    if kind == "defensive_cluster":
        return obs >= config.MIN_COUNT_DEFENSIVE and obs > r["expected"]
    if kind == "flank_overload":
        d = r["detail"]
        return d["n_actions"] >= config.MIN_COUNT_LANE and d["share"] >= config.LANE_SHARE_MIN
    if kind == "possession_shift":
        d = r["detail"]
        return abs(d["share"] - d["baseline_share"]) >= config.POSSESSION_DELTA_MIN and d["n_events"] >= 20
    return False


RULE_TEXT = {
    "turnover_spike": "Binomial rate test: turnovers per ball action (passes + dispossessions) in the window vs the team's "
                      "rate in the rest of the match (p <= {p}, >= {n} turnovers).",
    "shot_surge": "Binomial rate test: shots per attacking-half action (x >= 55) in the window vs the team's rate in "
                  "the rest of the match (p <= {p}, >= {n} shots).",
    "defensive_cluster": "Binomial rate test: own-defensive-third turnovers per defensive-third action in the window vs the "
                         "rest of the match (p <= {p}, >= {n} turnovers).",
    "flank_overload": "Binomial test: share of attacking-third passes/shots through one flank lane vs the team's "
                      "baseline lane share (p <= {p}, >= {n} actions, share >= {s:.0%}).",
    "possession_shift": "Binomial test: team's share of all events in window vs its share in the rest of the match "
                        "(p <= {p}, change >= {d:.0%}). Exploratory rule, not scored in evaluation.",
}


def _rule_text(kind: str) -> str:
    n = {"turnover_spike": config.MIN_COUNT_TURNOVER, "shot_surge": config.MIN_COUNT_SHOT,
         "defensive_cluster": config.MIN_COUNT_DEFENSIVE, "flank_overload": config.MIN_COUNT_LANE}.get(kind, 0)
    return RULE_TEXT[kind].format(p=config.P_VALUE_THRESHOLD, n=n, s=config.LANE_SHARE_MIN,
                                  d=config.POSSESSION_DELTA_MIN)


def _window_len(kind: str) -> int:
    return config.WINDOW_BY_KIND[kind]


def _describe(match: Match, kind: str, team_id: str, start: float, end: float, r: dict) -> tuple[str, str]:
    team = match.team_name(team_id)
    s, e = int(round(start)), int(round(end))
    obs, exp, p = int(r["observed"]), r["expected"], r["p_value"]
    d = r["detail"]
    if kind == "turnover_spike":
        return (f"{team}: turnover spike {s}'-{e}'",
                f"{team} lost possession {obs} times between minute {s} and {e}, against about {exp:.1f} "
                f"expected from their rate in the rest of the match (p = {p:.1e}).")
    if kind == "shot_surge":
        return (f"{team}: shot surge {s}'-{e}'",
                f"{team} took {obs} shots between minute {s} and {e}, against about {exp:.1f} expected "
                f"from their shot rate in the rest of the match (p = {p:.1e}).")
    if kind == "defensive_cluster":
        return (f"{team}: defensive-third turnovers {s}'-{e}'",
                f"{team} lost the ball {obs} times in their own defensive third between minute {s} and {e}, "
                f"against about {exp:.1f} expected (p = {p:.1e}).")
    if kind == "flank_overload":
        return (f"{team}: repeated attacks down the {d['lane']} flank {s}'-{e}'",
                f"{d['share']:.0%} of {team}'s {d['n_actions']} attacking-third passes and shots between minute "
                f"{s} and {e} went through the {d['lane']} lane, against a baseline of {d['baseline_share']:.0%} "
                f"(p = {p:.1e}).")
    direction = "rose" if d["direction"] == "up" else "fell"
    return (f"{team}: share of play {direction} {s}'-{e}'",
            f"{team} were involved in {d['share']:.0%} of events between minute {s} and {e}, against a baseline "
            f"of {d['baseline_share']:.0%} ({direction}; p = {p:.1e}).")


def _caveats(kind: str, r: dict, match: Match) -> list[str]:
    cv = [
        "Association in event data only: the detector does not know why behaviour changed.",
        "p-values are not corrected for the many overlapping windows tested; treat as a lead, not proof.",
        "Evidence strength is a heuristic score (-log10 p / 6), not a probability.",
    ]
    if r["observed"] < 10:
        cv.append(f"Small sample ({int(r['observed'])} events) - the estimate is unstable.")
    if kind == "possession_shift":
        cv.append("Event-share is not true possession time; it can also reflect how many events are recorded.")
    if match.synthetic:
        cv.append("Synthetic data: findings describe generated events, not real football.")
    return cv


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def detect_turning_points(events: list[Event], match: Match, kinds: Optional[list[str]] = None,
                          max_insights: Optional[int] = None) -> list[Insight]:
    """Scan the match and return insights sorted by start minute."""
    kinds = list(kinds or INSIGHT_KINDS)
    if not events:
        return []
    total = match_length(events)
    candidates: list[tuple[float, Insight]] = []

    for team in (match.home, match.away):
        opp = match.opponent_id(team.team_id)
        for kind in kinds:
            wl = _window_len(kind)
            found: list[tuple[float, float, dict]] = []
            start = 0.0
            while start + wl <= total + 1e-9:
                r = evaluate_window(kind, events, team.team_id, opp, start, start + wl)
                if r and _passes_rule(kind, r):
                    found.append((r["p_value"], start, r))
                start += 1.0
            found.sort(key=lambda t: (t[0], t[1]))
            kept: list[tuple[float, float, dict]] = []
            for p, s0, r in found:  # keep best window per overlapping cluster
                if all(s0 >= k[1] + wl or s0 + wl <= k[1] for k in kept):
                    kept.append((p, s0, r))
            for p, s0, r in kept:
                title, expl = _describe(match, kind, team.team_id, s0, s0 + wl, r)
                ins = Insight(
                    insight_id="tmp", kind=kind, title=title, team_id=team.team_id,
                    start_min=s0, end_min=s0 + wl, event_ids=r["event_ids"], rule=_rule_text(kind),
                    observed=r["observed"], expected=r["expected"], p_value=float(r["p_value"]),
                    evidence_strength=strength_from_p(r["p_value"]), strength_formula=STRENGTH_FORMULA,
                    explanation=expl, caveats=_caveats(kind, r, match), detail=r["detail"],
                    exploratory=(kind == "possession_shift"),
                )
                candidates.append((ins.evidence_strength, ins))

    cap = max_insights or config.MAX_INSIGHTS_PER_MATCH
    candidates.sort(key=lambda t: -t[0])
    # scored rules take the cap first; exploratory rules (which saturate easily) get at most 2 extra slots
    scored = [c[1] for c in candidates if not c[1].exploratory][:cap]
    explor = [c[1] for c in candidates if c[1].exploratory][:2]
    chosen = scored + explor
    chosen.sort(key=lambda i: (i.start_min, i.kind, i.team_id))
    mid = events[0].match_id
    for n, ins in enumerate(chosen, start=1):
        ins.insight_id = f"{mid}-I{n:02d}"
    return chosen


def insight_events(insight: Insight, events: list[Event]) -> list[Event]:
    ids = set(insight.event_ids)
    return [e for e in events if e.event_id in ids]


def events_in_window(events: list[Event], start: float, end: float) -> list[Event]:
    return filter_events(events, start=start, end=end)
