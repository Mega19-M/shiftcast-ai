"""Transparent, reproducible match metrics.

All functions are plain Python on lists of ``Event`` objects, so they are easy
to read, test and verify. Windows are INCLUSIVE: ``start <= minute <= end``.

The dictionary ``METRIC_DEFINITIONS`` documents every derived metric (formula,
data requirements, limitations) and is shown in the Match DNA page.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from src.models import LANES, ZONES, Event

# --------------------------------------------------------------------------
# Documentation of every derived metric (displayed in the UI)
# --------------------------------------------------------------------------
METRIC_DEFINITIONS: list[dict[str, str]] = [
    {
        "metric": "Possession changes",
        "formula": "number of times the team of consecutive events changes (A..A, B..B = 1 change)",
        "requires": "events ordered by time with a team_id",
        "limitations": "Event-based, not tracking-based: 'possession' only exists when an event is recorded. "
        "A change is counted even if the ball was only briefly contested.",
    },
    {
        "metric": "Possession share (time)",
        "formula": "sum of durations of the team's possession sequences / total sequence time. "
        "A sequence lasts from its first event to the first event of the next sequence.",
        "requires": "event minutes and team ids",
        "limitations": "Approximation from sparse events; with missing events the share is biased.",
    },
    {
        "metric": "Turnovers by zone",
        "formula": "count of 'turnover' events by the team, grouped by the pitch third of event x "
        "(defensive x<33.3, middle, attacking x>=66.7, team-relative)",
        "requires": "turnover events with x coordinate",
        "limitations": "Turnovers without coordinates are excluded from the zone split but still counted in totals.",
    },
    {
        "metric": "Attacking direction",
        "formula": "of the team's passes and shots that START in the attacking third, the share per lane "
        "(left y<33.3, center, right y>=66.7)",
        "requires": "pass/shot events with x and y",
        "limitations": "Uses the start position of the action; says where the team attacks, not why.",
    },
    {
        "metric": "Shot and chance creation",
        "formula": "shots; shots on target = goal+saved; conversion = goals / shots; "
        "shot rate = shots per 10 minutes",
        "requires": "shot events with outcome",
        "limitations": "No expected-goals value: shot quality, defenders and goalkeeper position are not in the data. "
        "Small counts => wide uncertainty (Wilson interval is shown).",
    },
    {
        "metric": "Defensive breakdowns",
        "formula": "turnovers by the team inside its own defensive third (x<33.3), and the opponent's "
        "shots within 60 seconds after them",
        "requires": "turnover + shot events with coordinates and time",
        "limitations": "A temporal association only: a shot after a turnover is not proof the turnover caused it.",
    },
    {
        "metric": "Pass completion",
        "formula": "successful passes / pass attempts",
        "requires": "pass events with outcome",
        "limitations": "Does not weight pass difficulty or direction.",
    },
    {
        "metric": "Period comparison",
        "formula": "metric in the 2nd half minus the same metric in the 1st half",
        "requires": "period (derived from the minute)",
        "limitations": "Halves may contain different match states (e.g. a goal changes behaviour); "
        "no stoppage-time normalisation.",
    },
    {
        "metric": "Not computed (by design)",
        "formula": "fatigue, intent, emotion, pressure, expected goals",
        "requires": "tracking, physical or video data that this dataset does not contain",
        "limitations": "SHIFTCAST AI never infers these from event counts alone.",
    },
]


# --------------------------------------------------------------------------
# Small statistics helpers
# --------------------------------------------------------------------------
def poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam). Exact sum, no external libraries."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # P(X >= k) = 1 - sum_{i<k} P(i); sum in log space for stability
    cdf = 0.0
    term = math.exp(-lam)
    cdf += term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Exact sum."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    p = min(max(p, 1e-9), 1 - 1e-9)
    total = 0.0
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i))
    return max(0.0, min(1.0, total))


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (robust for small n)."""
    if n <= 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# --------------------------------------------------------------------------
# Filtering / counting
# --------------------------------------------------------------------------
def filter_events(
    events: list[Event],
    team_id: Optional[str] = None,
    event_type: Optional[str] = None,
    start: Optional[float] = None,
    end: Optional[float] = None,
    zone: Optional[str] = None,
    lane: Optional[str] = None,
    outcome: Optional[str] = None,
    cause: Optional[str] = None,
    player_id: Optional[str] = None,
    period: Optional[int] = None,
) -> list[Event]:
    out = []
    for e in events:
        if team_id is not None and e.team_id != team_id:
            continue
        if event_type is not None and e.event_type != event_type:
            continue
        if start is not None and e.minute < start:
            continue
        if end is not None and e.minute > end:
            continue
        if zone is not None and e.zone != zone:
            continue
        if lane is not None and e.lane != lane:
            continue
        if outcome is not None and e.outcome != outcome:
            continue
        if cause is not None and e.cause != cause:
            continue
        if player_id is not None and e.player_id != player_id:
            continue
        if period is not None and e.period != period:
            continue
        out.append(e)
    return out


def count_events(events: list[Event], **kwargs) -> int:
    return len(filter_events(events, **kwargs))


def score_at(events: list[Event], home_id: str, away_id: str, minute: Optional[float] = None) -> tuple[int, int]:
    """Score from 'goal' events up to and including ``minute`` (None = full time)."""
    h = a = 0
    for e in events:
        if e.event_type != "goal":
            continue
        if minute is not None and e.minute > minute:
            continue
        if e.team_id == home_id:
            h += 1
        elif e.team_id == away_id:
            a += 1
    return h, a


# --------------------------------------------------------------------------
# Possession
# --------------------------------------------------------------------------
def possession_sequences(events: list[Event]) -> list[dict]:
    """Group consecutive events by the same team into sequences."""
    seqs: list[dict] = []
    for e in events:
        if seqs and seqs[-1]["team_id"] == e.team_id:
            seqs[-1]["end_min"] = e.minute
            seqs[-1]["n_events"] += 1
            seqs[-1]["event_ids"].append(e.event_id)
        else:
            seqs.append({"team_id": e.team_id, "start_min": e.minute, "end_min": e.minute,
                         "n_events": 1, "event_ids": [e.event_id]})
    for i in range(len(seqs) - 1):  # a sequence lasts until the next one starts
        seqs[i]["end_min"] = seqs[i + 1]["start_min"]
    return seqs


def possession_changes(events: list[Event]) -> int:
    return max(0, len(possession_sequences(events)) - 1)


def possession_share(events: list[Event], team_id: str) -> Optional[float]:
    seqs = possession_sequences(events)
    total = sum(s["end_min"] - s["start_min"] for s in seqs)
    if total <= 0:
        return None
    mine = sum(s["end_min"] - s["start_min"] for s in seqs if s["team_id"] == team_id)
    return mine / total


# --------------------------------------------------------------------------
# Team behaviour metrics
# --------------------------------------------------------------------------
def turnovers_by_zone(events: list[Event], team_id: str, start=None, end=None) -> dict[str, int]:
    out = {z: 0 for z in ZONES}
    for e in filter_events(events, team_id=team_id, event_type="turnover", start=start, end=end):
        if e.zone:
            out[e.zone] += 1
    return out


def attacking_lane_profile(events: list[Event], team_id: str, start=None, end=None) -> dict[str, int]:
    """Counts of passes/shots that START in the attacking third, per lane."""
    out = {ln: 0 for ln in LANES}
    for e in filter_events(events, team_id=team_id, start=start, end=end):
        if e.event_type in ("pass", "shot") and e.zone == "attacking" and e.lane:
            out[e.lane] += 1
    return out


def shot_summary(events: list[Event], team_id: str, start=None, end=None) -> dict:
    shots = filter_events(events, team_id=team_id, event_type="shot", start=start, end=end)
    goals = sum(1 for s in shots if s.outcome == "goal")
    on_target = sum(1 for s in shots if s.outcome in ("goal", "saved"))
    lo, hi = wilson_interval(goals, len(shots))
    return {"shots": len(shots), "on_target": on_target, "goals": goals,
            "conversion": (goals / len(shots)) if shots else None,
            "conversion_ci95": (lo, hi) if shots else None}


def pass_completion(events: list[Event], team_id: str, start=None, end=None, lane: Optional[str] = None) -> dict:
    ps = filter_events(events, team_id=team_id, event_type="pass", start=start, end=end, lane=lane)
    ok = sum(1 for p in ps if p.outcome == "success")
    return {"attempts": len(ps), "completed": ok, "rate": (ok / len(ps)) if ps else None}


def defensive_breakdowns(events: list[Event], team_id: str, opponent_id: str, start=None, end=None) -> dict:
    """Own-third turnovers and opponent shots within 60 s after them (association only)."""
    tos = [e for e in filter_events(events, team_id=team_id, event_type="turnover", start=start, end=end)
           if e.zone == "defensive"]
    opp_shots = filter_events(events, team_id=opponent_id, event_type="shot")
    followed = 0
    for t in tos:
        if any(0 <= (s.minute - t.minute) * 60 <= 60 for s in opp_shots):
            followed += 1
    return {"defensive_third_turnovers": len(tos), "followed_by_opponent_shot_60s": followed,
            "event_ids": [t.event_id for t in tos]}


def windowed_counts(events: list[Event], team_id: str, event_type: str, bin_minutes: int = 5,
                    total_minutes: int = 90) -> list[tuple[int, int]]:
    """[(bin_start_minute, count), ...] for line charts."""
    out = []
    for s in range(0, total_minutes, bin_minutes):
        n = sum(1 for e in events if e.team_id == team_id and e.event_type == event_type
                and s <= e.minute < s + bin_minutes)
        out.append((s, n))
    return out


def period_comparison(events: list[Event], team_id: str, opponent_id: str) -> list[dict]:
    """First half vs second half for the main metrics."""
    rows = []
    for label, fn in _PERIOD_METRICS.items():
        a = fn([e for e in events if e.period == 1], team_id, opponent_id)
        b = fn([e for e in events if e.period == 2], team_id, opponent_id)
        rows.append({"metric": label, "first_half": a, "second_half": b,
                     "change": (None if a is None or b is None else round(b - a, 3))})
    return rows


def _share(events, team_id, opponent_id):
    return possession_share(events, team_id)


_PERIOD_METRICS: dict[str, Callable] = {
    "Turnovers": lambda ev, t, o: count_events(ev, team_id=t, event_type="turnover"),
    "Defensive-third turnovers": lambda ev, t, o: sum(
        1 for e in filter_events(ev, team_id=t, event_type="turnover") if e.zone == "defensive"),
    "Shots": lambda ev, t, o: count_events(ev, team_id=t, event_type="shot"),
    "Goals": lambda ev, t, o: count_events(ev, team_id=t, event_type="goal"),
    "Pass completion": lambda ev, t, o: (lambda r: None if r is None else round(r, 3))(
        pass_completion(ev, t)["rate"]),
    "Possession share": lambda ev, t, o: (lambda r: None if r is None else round(r, 3))(_share(ev, t, o)),
    "Attacks via left lane": lambda ev, t, o: attacking_lane_profile(ev, t)["left"],
    "Attacks via right lane": lambda ev, t, o: attacking_lane_profile(ev, t)["right"],
}


# --------------------------------------------------------------------------
# Named metric registry (used by TrustTrace "metric" claims)
# --------------------------------------------------------------------------
def compute_metric(name: str, events: list[Event], team_id: str, start=None, end=None) -> Optional[float]:
    """Recompute a named metric over a window. Returns None for an unknown metric."""
    if name == "turnovers":
        return float(count_events(events, team_id=team_id, event_type="turnover", start=start, end=end))
    if name == "shots":
        return float(count_events(events, team_id=team_id, event_type="shot", start=start, end=end))
    if name == "goals":
        return float(count_events(events, team_id=team_id, event_type="goal", start=start, end=end))
    if name == "passes":
        return float(count_events(events, team_id=team_id, event_type="pass", start=start, end=end))
    if name == "pass_completion":
        r = pass_completion(events, team_id, start, end)["rate"]
        return None if r is None else float(r)
    if name == "defensive_third_turnovers":
        return float(sum(1 for e in filter_events(events, team_id=team_id, event_type="turnover", start=start, end=end)
                         if e.zone == "defensive"))
    if name == "possession_changes":
        return float(possession_changes(filter_events(events, start=start, end=end)))
    return None


KNOWN_METRICS = ("turnovers", "shots", "goals", "passes", "pass_completion",
                 "defensive_third_turnovers", "possession_changes")


def team_dna(events: list[Event], team_id: str, opponent_id: str) -> dict:
    """Bundle of all fingerprint metrics for one team (used by the Match DNA page)."""
    lanes = attacking_lane_profile(events, team_id)
    total_lane = sum(lanes.values()) or 1
    return {
        "possession_changes_total": possession_changes(events),
        "possession_share": possession_share(events, team_id),
        "turnovers_by_zone": turnovers_by_zone(events, team_id),
        "lane_counts": lanes,
        "lane_share": {k: v / total_lane for k, v in lanes.items()},
        "shots": shot_summary(events, team_id),
        "pass_completion": pass_completion(events, team_id),
        "defensive": defensive_breakdowns(events, team_id, opponent_id),
        "period_comparison": period_comparison(events, team_id, opponent_id),
    }
