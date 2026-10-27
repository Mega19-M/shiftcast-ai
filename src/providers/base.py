"""Provider interface for narrative generation.

A provider receives a ``StoryRequest`` (verified facts + the desired mode and
language) and returns a JSON *string* with this shape::

    {"sentences": [{"text": "...", "claim_ids": ["F1", "F3"]}, ...]}

Returning a string (not an object) is deliberate: it is how a real language
model answers, and it lets the Story Agent practise the same parsing and
safety checks for every provider, including malformed output.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from src.models import Claim, Insight


class ProviderError(Exception):
    """Raised when a provider is unavailable or fails."""


class StoryRequest(BaseModel):
    mode: str  # fan / analyst / broadcast
    language: str  # en / ta
    insight: Insight
    claims: list[Claim] = Field(default_factory=list)  # the verified fact sheet
    team_name: str = ""
    opponent_name: str = ""
    match_title: str = ""


class NarrativeProvider(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True if this provider can be used right now."""

    @abstractmethod
    def complete(self, request: StoryRequest) -> str:
        """Return the story as a JSON string (see module docstring)."""
