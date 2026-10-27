"""Downloadable exports: JSON report, CSV events, plain-text summary, overlay cues, WebVTT.

OVERLAY CUE FORMAT ``shiftcast-overlay-cues/1.0`` (documented in docs/OVERLAY_FORMAT.md):
    {"format": "shiftcast-overlay-cues/1.0", "match_id": "...", "synthetic": true,
     "cues": [{"cue_id", "type": "lower_third|stat_card|pitch_overlay", "start_min",
               "duration_s" | "end_min", "title", "text", "stats"?, "overlay"?, "event_ids": [...]}]}
Minutes are decimal match minutes since kick-off.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional

import config
from src.models import Event, Match, PipelineResult, StoryDoc, ValidationReport

REPORT_FORMAT = "shiftcast-report/1.0"
CUE_FORMAT = "shiftcast-overlay-cues/1.0"


def events_to_csv(events: list[Event]) -> str:
    buf = io.StringIO()
    fields = list(Event.model_fields.keys())
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for e in events:
        w.writerow(e.model_dump())
    return buf.getvalue()


def _stories(result: PipelineResult) -> list[StoryDoc]:
    return [s for b in result.bundles for s in b.stories.values()]


def build_report(match: Match, events: list[Event], result: PipelineResult, recap: Optional[StoryDoc] = None,
                 validation: Optional[ValidationReport] = None, generated_at: Optional[str] = None) -> dict:
    """Plain dict, JSON-serialisable. ``generated_at`` can be fixed for reproducible output."""
    goals = [e for e in events if e.event_type == "goal"]
    h = sum(1 for g in goals if g.team_id == match.home.team_id)
    a = sum(1 for g in goals if g.team_id == match.away.team_id)
    return {
        "format": REPORT_FORMAT,
        "disclaimer": config.DISCLAIMER,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match": {"match_id": match.match_id, "title": match.title, "home": match.home.name, "away": match.away.name,
                  "seed": match.seed, "synthetic": match.synthetic, "score": {"home": h, "away": a},
                  "n_events": len(events)},
        "validation": validation.model_dump(mode="json") if validation else None,
        "turning_points": [{
            "insight": b.insight.model_dump(mode="json"),
            "graph": b.graph.model_dump(mode="json") if b.graph else None,
            "scenarios": [s.model_dump(mode="json") for s in b.scenarios],
            "fact_sheet": [c.model_dump(mode="json") for c in b.fact_sheet],
            "fact_verification": [r.model_dump(mode="json") for r in b.fact_verification],
            "stories": {k: s.model_dump(mode="json") for k, s in b.stories.items()},
        } for b in result.bundles],
        "recap": recap.model_dump(mode="json") if recap else None,
        "agent_trace": [t.model_dump(mode="json") for t in result.traces],
        "provenance_ok": result.provenance_ok,
        "provenance_notes": result.provenance_notes,
    }


def report_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def summary_text(match: Match, events: list[Event], result: PipelineResult, recap: Optional[StoryDoc] = None) -> str:
    lines = [config.APP_NAME + " - match summary", "=" * 60, config.DISCLAIMER, "",
             f"Match: {match.title}", f"Events analysed: {len(events)}", ""]
    if recap:
        lines += ["RECAP", "-----", recap.text, ""]
    lines += ["KEY TURNING POINTS", "------------------"]
    if not result.bundles:
        lines.append("No statistically notable turning points were detected.")
    for b in result.bundles:
        i = b.insight
        lines += [f"* {i.title} [{i.start_min:.0f}'-{i.end_min:.0f}']",
                  f"  {i.explanation}",
                  f"  Evidence strength (heuristic, not a probability): {i.evidence_strength:.2f}",
                  f"  Supporting events: {', '.join(i.event_ids[:6])}{' ...' if len(i.event_ids) > 6 else ''}"]
        for sc in b.scenarios:
            lines.append(f"  [HYPOTHETICAL] {sc.name}")
        for key, s in b.stories.items():
            lines.append(f"  [{key}] ({'verified' if s.all_verified else 'NOT fully verified'}) " + s.text.replace("\n", " | "))
        lines.append("")
    lines.append(f"Provenance check (all event ids exist): {'PASS' if result.provenance_ok else 'FAIL'}")
    return "\n".join(lines)


def overlay_cues(match: Match, result: PipelineResult) -> dict:
    cues = []
    for b in result.bundles:
        for s in b.stories.values():
            if s.mode == "broadcast" and s.language == "en":
                cues.extend(s.overlay_cues)
    return {"format": CUE_FORMAT, "match_id": match.match_id, "synthetic": match.synthetic, "cues": cues}


def overlay_cues_json(match: Match, result: PipelineResult) -> str:
    return json.dumps(overlay_cues(match, result), indent=2, ensure_ascii=False)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def webvtt(match: Match, result: PipelineResult) -> str:
    """Subtitle-style cues (WebVTT). Times are match time, not video time."""
    out = ["WEBVTT", "", "NOTE SHIFTCAST AI - synthetic data demo; times are match minutes converted to mm:ss", ""]
    n = 0
    for c in overlay_cues(match, result)["cues"]:
        if c["type"] not in ("lower_third", "stat_card"):
            continue
        n += 1
        start = c["start_min"] * 60
        end = start + c.get("duration_s", 6)
        out += [str(n), f"{_ts(start)} --> {_ts(end)}", f"{c['title']}: {c['text']}", ""]
    return "\n".join(out)
