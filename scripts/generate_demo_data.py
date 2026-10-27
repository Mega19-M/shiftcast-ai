"""Regenerate the synthetic demo data and the sample exported report.

Usage (from the project folder):
    python scripts/generate_demo_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.orchestrator import Orchestrator  # noqa: E402
from src.data.generator import PRESETS, load_preset  # noqa: E402
from src.data.loader import save_events_csv, save_match_json  # noqa: E402
from src.providers import LocalProvider  # noqa: E402
from src.reporting.exports import (build_report, overlay_cues_json, report_json, summary_text)  # noqa: E402
from src.storytelling.recap import build_recap  # noqa: E402


def main() -> None:
    data = ROOT / "data"
    for name in PRESETS:
        m = load_preset(name)
        save_match_json(m, data / f"{name}.json")
        save_events_csv(m.events, data / f"{name}_events.csv")
        print(f"wrote {name}: {len(m.events)} events")

    # sample report for demo-1 (local provider only, fixed timestamp so the file is reproducible)
    m = load_preset("demo-1")
    orch = Orchestrator(LocalProvider())
    res = orch.run(m, m.events)
    orch.generate_all_stories(res, m, m.events, languages=("en", "ta"))
    recap = build_recap(m, m.events, [b.insight for b in res.bundles], "full", "en")
    report = build_report(m, m.events, res, recap, generated_at="2026-01-01T00:00:00+00:00")
    (data / "sample_report_demo-1.json").write_text(report_json(report), encoding="utf-8")
    (data / "sample_summary_demo-1.txt").write_text(summary_text(m, m.events, res, recap), encoding="utf-8")
    (data / "sample_overlay_cues_demo-1.json").write_text(overlay_cues_json(m, res), encoding="utf-8")
    print("wrote sample report, summary and overlay cues for demo-1")


if __name__ == "__main__":
    main()
