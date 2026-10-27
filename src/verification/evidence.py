"""Evidence index: the single place where claims are checked against source data.

Every number a claim can cite is produced by one of the DOCUMENTED aggregate
calculations in ``AGGREGATES`` (shown to the user in the claim audit panel).
"""
from __future__ import annotations

from typing import Optional

from src.analytics.metrics import KNOWN_METRICS, compute_metric, count_events, score_at
from src.analytics.turning_points import evaluate_window
from src.models import Event, Match

AGGREGATES: dict[str, str] = {
    "event_exists": "Look up the event id in the validated event table and compare minute (+-10 s), team, player, "
                    "type and outcome with the claim.",
    "count": "Count validated events matching team / type / zone / lane / outcome / cause inside "
             "[start_minute, end_minute] (inclusive).",
    "score": "Count 'goal' events per team up to the stated minute (or full time if none is stated).",
    "metric": "Recompute a named metric (" + ", ".join(KNOWN_METRICS) + ") over [start_minute, end_minute].",
    "window_stat": "Re-run the turning-point rule on the claimed window and compare observed count and p-value.",
    "player_team": "Check the player is on the stated team's roster.",
}

MINUTE_TOLERANCE = 10 / 60  # 10 seconds, in minutes


class EvidenceIndex:
    def __init__(self, match: Match, events: list[Event]):
        self.match = match
        self.events = events
        self.by_id = {e.event_id: e for e in events}
        self.home = match.home.team_id
        self.away = match.away.team_id

    # ---- lookups --------------------------------------------------------
    def event(self, event_id: str) -> Optional[Event]:
        return self.by_id.get(event_id)

    def missing_ids(self, ids: list[str]) -> list[str]:
        return [i for i in ids if i not in self.by_id]

    def count(self, **kw) -> int:
        return count_events(self.events, **kw)

    def score(self, minute: Optional[float] = None) -> tuple[int, int]:
        return score_at(self.events, self.home, self.away, minute)

    def metric(self, name: str, team_id: str, start=None, end=None) -> Optional[float]:
        return compute_metric(name, self.events, team_id, start, end)

    def window_stat(self, kind: str, team_id: str, start: float, end: float, lane: Optional[str] = None):
        return evaluate_window(kind, self.events, team_id, self.match.opponent_id(team_id), start, end, lane)

    # ---- data-quality contradictions ------------------------------------
    def score_contradiction(self) -> Optional[str]:
        """If the match carries an external scoreboard that disagrees with the goal events, say so."""
        rs = self.match.reported_score
        if rs is None:
            return None
        derived = self.score()
        if tuple(rs) != derived:
            return f"reported score {rs[0]}-{rs[1]} contradicts goal events {derived[0]}-{derived[1]}"
        return None
