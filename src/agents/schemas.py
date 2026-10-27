"""Structured input/output schemas for the five agents (the 'handoff contracts').

Each agent takes exactly one input model and returns exactly one output model.
The orchestrator moves data from one agent to the next by building the next
agent's input from the previous agent's output - nothing is passed implicitly.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.models import (Claim, ClaimResult, Event, GraphData, Insight, Match, ScenarioResult, StoryDoc)


class _Base(BaseModel):
    model_config = {"arbitrary_types_allowed": True}


# 1. Signal Agent --------------------------------------------------------------
class SignalInput(_Base):
    match: Match
    events: list[Event]
    kinds: Optional[list[str]] = None
    max_insights: int = 5


class SignalOutput(_Base):
    insights: list[Insight] = Field(default_factory=list)


# 2. Context Agent -------------------------------------------------------------
class ContextInput(_Base):
    match: Match
    events: list[Event]
    insights: list[Insight]


class ContextOutput(_Base):
    graphs: dict[str, GraphData] = Field(default_factory=dict)  # insight_id -> graph


# 3. Scenario Agent ------------------------------------------------------------
class ScenarioInput(_Base):
    match: Match
    events: list[Event]
    insights: list[Insight]
    overrides: dict[str, dict[str, float]] = Field(default_factory=dict)


class ScenarioOutput(_Base):
    scenarios: dict[str, list[ScenarioResult]] = Field(default_factory=dict)


# 4. Evidence Agent (two jobs: verify facts BEFORE the story, verify the story AFTER) ---
class EvidenceInput(_Base):
    match: Match
    events: list[Event]
    insight: Insight
    scenarios: list[ScenarioResult] = Field(default_factory=list)


class EvidenceOutput(_Base):
    fact_sheet: list[Claim] = Field(default_factory=list)  # only claims that passed
    results: list[ClaimResult] = Field(default_factory=list)
    rejected_claim_ids: list[str] = Field(default_factory=list)


class StoryCheckInput(_Base):
    match: Match
    events: list[Event]
    insight: Insight
    story: StoryDoc
    fact_sheet: list[Claim]


class StoryCheckOutput(_Base):
    story: StoryDoc
    ok: bool = True
    failures: list[str] = Field(default_factory=list)


# 5. Story Agent ---------------------------------------------------------------
class StoryInput(_Base):
    match: Match
    events: list[Event]
    insight: Insight
    fact_sheet: list[Claim]
    mode: str = "fan"
    language: str = "en"
    force_local: bool = False
    fallback_reason: Optional[str] = None


class StoryOutput(_Base):
    story: StoryDoc
