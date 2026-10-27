"""Scoring the detectors on synthetic matches whose correct answer is known.

A detection counts as a TRUE POSITIVE when it has the same rule kind and team as
a planted pattern and the time windows overlap by at least ``MIN_OVERLAP`` minutes.
Planted patterns that are not found are FALSE NEGATIVES; detections of scored
kinds that match nothing are FALSE POSITIVES. The exploratory ``possession_shift``
rule has no planted counterpart and is therefore reported but not scored.

HONESTY NOTE: the generator and the detectors were written by the same authors,
so a high score shows the pipeline works on its own synthetic world - it is NOT
evidence of accuracy on real football data.
"""
from __future__ import annotations

from typing import Optional

import config
from src.analytics.turning_points import detect_turning_points
from src.data.generator import generate_control_match, generate_scenario_match
from src.models import PATTERN_KINDS, Insight, Match

MIN_OVERLAP = 3.0  # minutes


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def score_match(match: Match, insights: list[Insight]) -> dict:
    scored = [i for i in insights if i.kind in PATTERN_KINDS]
    used: set[str] = set()
    tp = 0
    misses = []
    per_kind: dict[str, dict[str, int]] = {k: {"tp": 0, "fp": 0, "fn": 0} for k in PATTERN_KINDS}
    for gt in match.ground_truth:
        hit: Optional[Insight] = None
        for ins in scored:
            if ins.insight_id in used:
                continue
            if (ins.kind == gt.kind and ins.team_id == gt.team_id
                    and _overlap(ins.start_min, ins.end_min, gt.start_min, gt.end_min) >= MIN_OVERLAP):
                hit = ins
                break
        if hit:
            used.add(hit.insight_id)
            tp += 1
            per_kind[gt.kind]["tp"] += 1
        else:
            per_kind[gt.kind]["fn"] += 1
            misses.append(f"{gt.kind} {gt.team_id} {gt.start_min:.0f}-{gt.end_min:.0f}")
    fps = [i for i in scored if i.insight_id not in used]
    for i in fps:
        per_kind[i.kind]["fp"] += 1
    return {"match_id": match.match_id, "planted": len(match.ground_truth), "detected_scored": len(scored),
            "tp": tp, "fp": len(fps), "fn": len(match.ground_truth) - tp, "per_kind": per_kind,
            "missed": misses, "false_alarms": [f"{i.kind} {i.team_id} {i.start_min:.0f}-{i.end_min:.0f}" for i in fps]}


def _prf(tp: int, fp: int, fn: int) -> dict:
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if prec is not None and rec is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1}


def evaluate_detectors(seeds: tuple[int, ...] = config.HELDOUT_SEEDS,
                       control_seeds: Optional[tuple[int, ...]] = None) -> dict:
    """Run the detectors on planted-pattern matches and on pattern-free controls."""
    control_seeds = control_seeds if control_seeds is not None else tuple(s + 500 for s in seeds[:10])
    totals = {k: {"tp": 0, "fp": 0, "fn": 0} for k in PATTERN_KINDS}
    per_match = []
    for s in seeds:
        m = generate_scenario_match(s)
        res = score_match(m, detect_turning_points(m.events, m))
        per_match.append(res)
        for k, v in res["per_kind"].items():
            for key in ("tp", "fp", "fn"):
                totals[k][key] += v[key]
    overall = {"tp": sum(v["tp"] for v in totals.values()), "fp": sum(v["fp"] for v in totals.values()),
               "fn": sum(v["fn"] for v in totals.values())}

    control_fp = 0
    control_details = []
    for s in control_seeds:
        m = generate_control_match(s)
        ins = [i for i in detect_turning_points(m.events, m) if i.kind in PATTERN_KINDS]
        control_fp += len(ins)
        control_details.append({"match_id": m.match_id, "false_alarms": len(ins)})
    return {
        "seeds": list(seeds), "n_matches": len(seeds),
        "overall": _prf(**overall),
        "per_kind": {k: _prf(**v) for k, v in totals.items()},
        "per_match": per_match,
        "control": {"n_matches": len(control_seeds), "false_alarms": control_fp,
                    "false_alarms_per_match": control_fp / max(1, len(control_seeds)), "details": control_details},
        "note": "Synthetic world scored by its own authors; not evidence of accuracy on real data.",
    }


# ---------------------------------------------------------------------------
# Data-validation and TrustTrace regression sets (also shown on the Evaluation page)
# ---------------------------------------------------------------------------
def evaluate_validation(seed: int = 5) -> dict:
    """Inject known faults into a match and check that the validator finds every one."""
    from src.data.generator import inject_faults
    from src.data.validation import validate_events

    m = generate_scenario_match(seed)
    raw, manifest, wrong_score = inject_faults(m, seed)
    clean, rep = validate_events(raw, m, wrong_score)
    rows = []
    for code, ids in manifest.items():
        found = {i.event_id for i in rep.issues if i.code == code}
        rows.append({"fault": code, "injected": len(ids), "found": len(set(ids) & found),
                     "ok": set(ids) <= found})
    score_found = any(i.code == "score_mismatch" for i in rep.issues)
    rows.append({"fault": "score_mismatch", "injected": 1, "found": int(score_found), "ok": score_found})
    return {"seed": seed, "rows": rows, "all_found": all(r["ok"] for r in rows), "input": rep.total_input,
            "accepted": rep.accepted, "rejected": rep.rejected}


def evaluate_trusttrace(seed: int = 3) -> dict:
    """Author-written true and false statements about a generated match; TrustTrace must separate them."""
    from src.analytics.metrics import count_events, score_at
    from src.verification.claim_checker import check_text

    m = generate_scenario_match(seed)
    ev = m.events
    H, A = m.home, m.away
    h, a = score_at(ev, H.team_id, A.team_id)
    goals = [e for e in ev if e.event_type == "goal"]
    g = goals[0] if goals else None
    shots_h = count_events(ev, team_id=H.team_id, event_type="shot")
    tos_h = count_events(ev, team_id=H.team_id, event_type="turnover", start=10, end=30)
    invented = "Dario Quillon"
    while invented in {p.name for p in m.players().values()}:
        invented = "Aldo Varek"
    true_set = [
        f"The final score was {H.name} {h}-{a} {A.name}.",
        f"{H.name} had {shots_h} shots in the match.",
        f"{H.name} had {tos_h} turnovers between 10 and 30.",
    ]
    false_set = [
        f"The final score was {H.name} {h + 2}-{a} {A.name}.",
        f"{H.name} had {shots_h + 4} shots in the match.",
        f"{H.name} had {tos_h + 5} turnovers between 10 and 30.",
        f"{m.match_id}-E9999 was a goal at 12:00 by {H.name}.",
        f"{invented} scored for {H.name} in the first half.",
    ]
    if g:
        other = A if g.team_id == H.team_id else H
        true_set.append(f"{g.event_id} was a goal at {g.clock} by {m.team_name(g.team_id)}.")
        false_set.append(f"{g.event_id} was a goal at {g.clock} by {other.name}.")
        wrong_clock = f"{int(g.minute) + 7:02d}:{int(round((g.minute % 1) * 60)):02d}"
        false_set.append(f"{g.event_id} was a goal at {wrong_clock} by {m.team_name(g.team_id)}.")
        pl = m.players().get(g.player_id)
        if pl:
            true_set.append(f"{pl.name} scored for {m.team_name(g.team_id)}.")
            false_set.append(f"{pl.name} scored for {other.name}.")
    rows = []
    for text, truth in [(t, True) for t in true_set] + [(t, False) for t in false_set]:
        out = check_text(text, m, ev)
        rows.append({"statement": text, "truth": "true" if truth else "false", "trusttrace_ok": out["ok"],
                     "correct": out["ok"] == truth})
    n_true = sum(1 for r in rows if r["truth"] == "true")
    n_false = len(rows) - n_true
    return {"rows": rows, "false_caught": sum(1 for r in rows if r["truth"] == "false" and not r["trusttrace_ok"]),
            "n_false": n_false, "true_passed": sum(1 for r in rows if r["truth"] == "true" and r["trusttrace_ok"]),
            "n_true": n_true,
            "note": "Author-written regression statements shaped for the extractor; not a benchmark of arbitrary text."}
