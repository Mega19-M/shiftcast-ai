"""Central configuration for SHIFTCAST AI.

Values come from environment variables (optionally loaded from a local ``.env``
file) so that no secret is ever written in the source code.
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional at runtime; the app works without it
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv missing is fine
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

APP_NAME = "SHIFTCAST AI"
APP_FULL_NAME = "Explainable Football Intelligence & Storytelling Engine"
TAGLINE = "Every event has a story. Every decision changes the game."
DISCLAIMER = (
    "DEMO / SYNTHETIC DATA - all matches, teams and players are fictional and "
    "randomly generated. This is not an official Premier League product and "
    "contains no real Premier League data."
)

# --- Optional Azure / Microsoft Foundry provider (all optional) ---------------
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
USE_AZURE = os.getenv("SHIFTCAST_USE_AZURE", "false").strip().lower() in {"1", "true", "yes"}

# --- Detection thresholds (documented in README, section "Turning points") ----
# Sliding-window length (minutes) per rule. Rate tests need enough opportunities to be
# powerful, so the rules that depend on rarer events use longer windows.
WINDOW_BY_KIND = {
    "turnover_spike": 15,
    "shot_surge": 15,
    "defensive_cluster": 15,
    "flank_overload": 10,
    "possession_shift": 10,
}
P_VALUE_THRESHOLD = 1e-3  # strict because many overlapping windows are tested
MIN_COUNT_TURNOVER = 8
MIN_COUNT_SHOT = 4
MIN_COUNT_LANE = 8
MIN_COUNT_DEFENSIVE = 4
LANE_SHARE_MIN = 0.55
POSSESSION_DELTA_MIN = 0.12
MAX_INSIGHTS_PER_MATCH = 8
PIPELINE_MAX_INSIGHTS = 5  # hard bound on how many insights the agents process

# Seeds: DEV seeds were used while tuning thresholds, HELD-OUT seeds were not.
DEV_SEEDS = tuple(range(1, 11))
HELDOUT_SEEDS = tuple(range(100, 120))
