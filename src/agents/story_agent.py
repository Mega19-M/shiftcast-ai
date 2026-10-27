"""STORY AGENT - writes the audience-specific narrative from VERIFIED facts only.

Input  -> StoryInput(insight, fact_sheet, mode, language, [force_local])
Output -> StoryOutput(story)

Safety behaviour
----------------
* The provider (Azure or local) only sees the verified fact sheet.
* If the provider is unavailable, raises, or returns malformed JSON, the agent
  falls back to the deterministic local provider and records ``fallback_reason``.
* Cited claim ids that do not exist in the fact sheet are treated as malformed output.
"""
from __future__ import annotations

import logging
from typing import Optional

from src.agents.schemas import StoryInput, StoryOutput
from src.models import StoryDoc
from src.providers import LocalProvider, NarrativeProvider, ProviderError, StoryRequest
from src.storytelling.narratives import broadcast_assets, parse_story_json

log = logging.getLogger("shiftcast.story")


class StoryAgent:
    name = "story"

    def __init__(self, provider: Optional[NarrativeProvider] = None):
        self.provider = provider or LocalProvider()
        self.local = LocalProvider()

    def run(self, inp: StoryInput) -> StoryOutput:
        ids = {c.claim_id for c in inp.fact_sheet}
        req = StoryRequest(mode=inp.mode, language=inp.language, insight=inp.insight, claims=inp.fact_sheet,
                           team_name=inp.match.team_name(inp.insight.team_id),
                           opponent_name=inp.match.team_name(inp.match.opponent_id(inp.insight.team_id)),
                           match_title=inp.match.title)
        provider = self.local if inp.force_local else self.provider
        fallback = inp.fallback_reason
        sentences = None
        try:
            raw = provider.complete(req)
            sentences = parse_story_json(raw)
            allowed = ids | ({"meta"} if provider.name == self.local.name else set())  # 'meta' = trusted template boilerplate
            unknown = sorted({cid for s in sentences for cid in s.claim_ids if cid not in allowed})
            if unknown:
                raise ValueError(f"story cites unknown claim ids {unknown}")
        except (ProviderError, ValueError) as exc:
            log.warning("provider %s failed (%s); using local fallback", provider.name, exc)
            fallback = f"{provider.name}: {exc}"
            provider = self.local
            sentences = parse_story_json(self.local.complete(req))

        joiner = " " if inp.mode == "fan" else "\n"
        text = joiner.join(s.text for s in sentences)
        graphics, cues = ([], [])
        if inp.mode == "broadcast":
            graphics, cues = broadcast_assets(inp.insight, inp.fact_sheet, inp.match, inp.events)
        used = {cid for s in sentences for cid in s.claim_ids if cid != "meta"}
        story = StoryDoc(
            insight_id=inp.insight.insight_id, mode=inp.mode, language=inp.language, text=text, sentences=sentences,
            claims=[c for c in inp.fact_sheet if c.claim_id in used], provider=provider.name,
            fallback_reason=fallback, graphics=graphics, overlay_cues=cues)
        return StoryOutput(story=story)
