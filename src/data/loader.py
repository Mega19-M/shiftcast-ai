"""Load and save matches (JSON) and raw events (CSV)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.models import Event, Match

CSV_FIELDS = list(Event.model_fields.keys())
_FLOAT = {"minute", "x", "y", "end_x", "end_y"}
_INT = {"period"}


def save_match_json(match: Match, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(match.model_dump_json(indent=1), encoding="utf-8")
    return path


def load_match_json(path: str | Path) -> Match:
    return Match.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_events_csv(events: list[Event], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for e in events:
            w.writerow(e.model_dump())
    return path


def raw_events_from_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read a CSV into raw dicts (empty cells -> None). Validation happens later."""
    rows: list[dict[str, Any]] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            row: dict[str, Any] = {}
            for k, v in r.items():
                if v in ("", None):
                    row[k] = None
                elif k in _FLOAT:
                    try:
                        row[k] = float(v)
                    except ValueError:
                        row[k] = v  # kept as text so validation can report it
                elif k in _INT:
                    try:
                        row[k] = int(float(v))
                    except ValueError:
                        row[k] = v
                else:
                    row[k] = v
            rows.append(row)
    return rows
