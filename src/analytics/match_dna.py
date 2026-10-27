"""Match DNA: a behavioural fingerprint of each team plus plain-English differences.

Only event-based, explainable metrics are used (see ``metrics.METRIC_DEFINITIONS``).
Nothing here infers fatigue, emotion or physical condition.
"""
from __future__ import annotations

from src.analytics.metrics import team_dna
from src.models import Event, Match


def compare_teams(events: list[Event], match: Match) -> dict:
    """Return both fingerprints and rule-based, factual 'notable differences'."""
    h, a = match.home.team_id, match.away.team_id
    dna = {h: team_dna(events, h, a), a: team_dna(events, a, h)}
    notes: list[str] = []
    for tid, oid in ((h, a), (a, h)):
        name = match.team_name(tid)
        d, o = dna[tid], dna[oid]
        for lane in ("left", "right"):
            share, oshare = d["lane_share"][lane], o["lane_share"][lane]
            if d["lane_counts"][lane] >= 10 and share - oshare >= 0.10:
                notes.append(f"{name} attack through the {lane} lane in {share:.0%} of their final-third actions "
                             f"({match.team_name(oid)}: {oshare:.0%}).")
        zt, zo = d["turnovers_by_zone"], o["turnovers_by_zone"]
        if sum(zt.values()) >= 10 and zt["defensive"] / max(1, sum(zt.values())) >= 0.30:
            notes.append(f"{name} lost {zt['defensive']} of {sum(zt.values())} turnovers in their own defensive third.")
        for row in d["period_comparison"]:
            if row["metric"] == "Turnovers" and row["first_half"] and row["second_half"] is not None:
                if row["second_half"] >= 1.4 * row["first_half"] and row["second_half"] - row["first_half"] >= 5:
                    notes.append(f"{name} had {row['second_half']} turnovers in the 2nd half vs {row['first_half']} in the 1st.")
    if not notes:
        notes.append("No large behavioural differences were found with these simple rules.")
    return {"dna": dna, "notes": notes}
