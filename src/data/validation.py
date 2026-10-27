"""Event validation: turn raw (possibly dirty) event dicts into clean ``Event`` objects.

Why this exists
---------------
Real event feeds contain duplicates, missing fields, wrong team ids, clock
errors and contradictions. Every analytic in SHIFTCAST AI only sees events that
have passed through :func:`validate_events`, and every problem found is
reported in a :class:`ValidationReport` (nothing is silently dropped).

Severity rules
--------------
* ``error``   -> the event is rejected (or, for match-level problems, flagged loudly)
* ``warning`` -> the event is kept, sometimes with a field repaired or cleared
"""
from __future__ import annotations

from typing import Any, Optional

from src.models import EVENT_TYPES, Event, Match, ValidationIssue, ValidationReport

MAX_MINUTE = 130.0  # allows stoppage/extra time, rejects obvious clock errors
SPATIAL_TYPES = {"pass", "shot", "turnover", "interception", "tackle"}
REQUIRED = ("event_id", "event_type", "team_id", "minute", "period")


def _same_content(a: dict, b: dict) -> bool:
    keys = set(a) | set(b)
    return all(a.get(k) == b.get(k) for k in keys)


def validate_events(
    raw_events: list[dict[str, Any]],
    match: Match,
    reported_score: Optional[tuple[int, int]] = None,
) -> tuple[list[Event], ValidationReport]:
    """Validate raw event dicts against the match roster.

    Returns ``(clean_events_sorted_by_time, report)``.
    """
    issues: list[ValidationIssue] = []
    report = ValidationReport(total_input=len(raw_events))

    def add(code: str, sev: str, eid: Optional[str], msg: str) -> None:
        issues.append(ValidationIssue(code=code, severity=sev, event_id=eid, message=msg))

    if not raw_events:
        add("empty_input", "error", None, "No events were supplied.")
        report.issues = issues
        return [], report

    roster = match.players()
    teams = match.team_ids()
    seen: dict[str, dict] = {}
    accepted: list[tuple[int, dict]] = []
    running_max = 0.0

    for idx, raw in enumerate(raw_events):
        ev = dict(raw)
        eid = ev.get("event_id")
        label = str(eid) if eid else f"<row {idx}>"

        # 1. required fields -------------------------------------------------
        missing = [k for k in REQUIRED if ev.get(k) in (None, "")]
        if missing:
            add("missing_field", "error", label, f"Missing required field(s): {', '.join(missing)}.")
            continue

        # 2. event type ------------------------------------------------------
        if ev["event_type"] not in EVENT_TYPES:
            add("unknown_event_type", "error", label, f"Unknown event type {ev['event_type']!r}.")
            continue

        # 3. duplicates ------------------------------------------------------
        if eid in seen:
            if _same_content(seen[eid], ev):
                add("duplicate_event_id", "warning", label, "Exact duplicate record ignored.")
            else:
                add("contradictory_duplicate", "error", label,
                    "Same event_id appears with different content; the first record is kept, this one rejected.")
            continue

        # 4. minute ----------------------------------------------------------
        try:
            minute = float(ev["minute"])
        except (TypeError, ValueError):
            add("invalid_minute", "error", label, f"Minute {ev['minute']!r} is not a number.")
            continue
        if not (0.0 <= minute <= MAX_MINUTE) or minute != minute:
            add("invalid_minute", "error", label, f"Minute {minute} is outside 0-{MAX_MINUTE:.0f}.")
            continue
        ev["minute"] = minute

        # 5. team ------------------------------------------------------------
        if ev["team_id"] not in teams:
            add("unknown_team", "error", label, f"Team id {ev['team_id']!r} is not in this match.")
            continue

        # 6. period ----------------------------------------------------------
        if ev["period"] not in (1, 2):
            add("invalid_period", "error", label, f"Period {ev['period']!r} must be 1 or 2.")
            continue
        expected_period = 1 if minute < 45 else 2
        if ev["period"] != expected_period:
            add("period_mismatch", "warning", label,
                f"Period {ev['period']} disagrees with minute {minute:.1f}; period repaired to {expected_period}.")
            ev["period"] = expected_period

        # 7. player ----------------------------------------------------------
        pid = ev.get("player_id")
        if pid is not None and (pid not in roster or roster[pid].team_id != ev["team_id"]):
            add("unknown_player", "warning", label,
                f"Player id {pid!r} is not on team {ev['team_id']}; player cleared, event kept.")
            ev["player_id"] = None

        # 8. coordinates -----------------------------------------------------
        for c in ("x", "y", "end_x", "end_y"):
            v = ev.get(c)
            if v is not None and not (0.0 <= float(v) <= 100.0):
                add("coordinate_out_of_range", "warning", label, f"{c}={v} outside 0-100; coordinate cleared.")
                ev[c] = None
        if ev["event_type"] in SPATIAL_TYPES and (ev.get("x") is None or ev.get("y") is None):
            add("missing_coordinates", "warning", label,
                "Event has no usable position; it is kept for counts but excluded from zone/lane metrics.")

        # 9. chronological order --------------------------------------------
        if minute < running_max - 0.5:
            add("out_of_order", "warning", label,
                f"Event at minute {minute:.1f} appears after minute {running_max:.1f}; events will be re-sorted.")
        running_max = max(running_max, minute)

        seen[eid] = ev
        accepted.append((idx, ev))

    # Build typed events -------------------------------------------------------
    clean: list[Event] = []
    for idx, ev in accepted:
        try:
            clean.append(Event(**ev))
        except Exception as exc:  # pydantic validation error -> reject, never crash
            add("schema_error", "error", str(ev.get("event_id")), f"Event failed schema check: {exc}")
    order = {e.event_id: i for i, e in enumerate(clean)}
    clean.sort(key=lambda e: (e.minute, order[e.event_id]))

    # Cross-event checks ---------------------------------------------------------
    by_id = {e.event_id: e for e in clean}
    for e in clean:
        if e.event_type != "goal":
            continue
        rel = by_id.get(e.related_event_id) if e.related_event_id else None
        if rel is None:
            add("goal_without_shot", "warning", e.event_id,
                "Goal has no matching shot record in the data (missing event).")
        elif rel.event_type != "shot" or rel.team_id != e.team_id or rel.minute > e.minute + 0.02:
            add("goal_shot_mismatch", "warning", e.event_id,
                f"Goal references {rel.event_id}, which is not an earlier shot by the same team.")

    if reported_score is not None:
        home = sum(1 for e in clean if e.event_type == "goal" and e.team_id == match.home.team_id)
        away = sum(1 for e in clean if e.event_type == "goal" and e.team_id == match.away.team_id)
        if (home, away) != tuple(reported_score):
            add("score_mismatch", "error", None,
                f"Reported score {reported_score[0]}-{reported_score[1]} contradicts goal events {home}-{away}.")

    report.issues = issues
    report.accepted = len(clean)
    report.rejected = report.total_input - len(clean)
    return clean, report


def summarise_report(report: ValidationReport) -> dict[str, int]:
    """Count issues per code (handy for tables in the UI)."""
    out: dict[str, int] = {}
    for i in report.issues:
        out[i.code] = out.get(i.code, 0) + 1
    return out
