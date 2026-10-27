"""Session state and shared data for the Streamlit pages.

All pages receive one ``Ctx`` object, so they never re-implement loading,
validation or pipeline caching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import streamlit as st

import config
from src.agents.orchestrator import Orchestrator
from src.data.generator import (PRESETS, drop_events, generate_match, inject_faults, load_preset)
from src.data.validation import validate_events
from src.models import Event, Match, PipelineResult, ValidationReport
from src.providers import AzureProvider, LocalProvider, get_provider


@dataclass
class Ctx:
    match: Match
    all_events: list[Event]  # validated events of the whole match
    events: list[Event]  # events used for analysis (all, or only those revealed so far)
    validation: ValidationReport
    cursor: int
    mode: str  # fan / analyst / broadcast
    lang: str  # en / ta
    orch: Orchestrator
    provider_name: str
    use_revealed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def pipeline(self) -> PipelineResult:
        return get_pipeline(self)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------
def match_options() -> list[str]:
    return list(PRESETS) + list(st.session_state.get("custom_matches", {}))


def _load(key: str) -> tuple[Match, list[dict], Optional[tuple[int, int]]]:
    """Return (match, raw event dicts, reported score) for a preset or a custom match."""
    custom = st.session_state.get("custom_matches", {})
    if key in custom:
        c = custom[key]
        return c["match"], c["raw"], c.get("reported")
    m = load_preset(key)
    return m, [e.model_dump() for e in m.events], None


@st.cache_data(show_spinner=False)
def _cached_preset(key: str):
    m = load_preset(key)
    clean, rep = validate_events([e.model_dump() for e in m.events], m)
    return m, clean, rep


def create_custom_match(seed: int, home: str, away: str, patterns: list[dict], drop_shots: float,
                        faults: bool) -> str:
    """Generate a custom synthetic match and register it in the session."""
    m = generate_match(int(seed), home, away, patterns, match_id=f"X{int(seed):04d}",
                       title=f"Custom synthetic match (seed {int(seed)})")
    raw_events = m.events
    if drop_shots > 0:
        raw_events = drop_events(m.events, drop_shots, int(seed), ("shot",))
    raw = [e.model_dump() for e in raw_events]
    reported = None
    if faults:
        m2 = m.model_copy(update={"events": raw_events})
        raw, _manifest, reported = inject_faults(m2, int(seed))
    key = f"custom-{int(seed)}"
    st.session_state.setdefault("custom_matches", {})[key] = {"match": m, "raw": raw, "reported": reported}
    return key


# ---------------------------------------------------------------------------
# Pipeline cache
# ---------------------------------------------------------------------------
def get_pipeline(ctx: Ctx) -> PipelineResult:
    cache = st.session_state.setdefault("pipelines", {})
    sig = tuple((g.kind, g.team_id, g.start_min, g.end_min) for g in ctx.match.ground_truth)
    key = (ctx.match.match_id, ctx.match.seed, sig, len(ctx.all_events), ctx.validation.rejected,
           len(ctx.events), ctx.provider_name)
    if key not in cache:
        with st.spinner("Running the five-agent pipeline on synthetic events..."):
            cache[key] = ctx.orch.run(ctx.match, ctx.events)
    return cache[key]


def build_context(match_key: str, mode: str, lang: str, use_azure: bool, use_revealed: bool) -> Ctx:
    custom = st.session_state.get("custom_matches", {})
    if match_key in custom:
        match, raw, reported = _load(match_key)
        clean, report = validate_events(raw, match, reported)
    else:
        match, clean, report = _cached_preset(match_key)
    total = len(clean)
    ckey = f"cursor::{match.match_id}"
    if ckey not in st.session_state:
        st.session_state[ckey] = total  # default: whole match visible
    cursor = max(0, min(int(st.session_state[ckey]), total))
    events = clean[:cursor] if use_revealed else clean
    provider = get_provider(use_azure)
    orchs = st.session_state.setdefault("orchestrators", {})
    if provider.name not in orchs:
        orchs[provider.name] = Orchestrator(provider)
    return Ctx(match=match, all_events=clean, events=events, validation=report, cursor=cursor, mode=mode, lang=lang,
               orch=orchs[provider.name], provider_name=provider.name, use_revealed=use_revealed)


def azure_available() -> bool:
    return AzureProvider().available()


def local_name() -> str:
    return LocalProvider.name
