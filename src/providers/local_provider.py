"""Deterministic local provider: always available, no network, no keys.

It writes the story from templates (see ``storytelling.narratives``) and
returns it as a JSON string, so it goes through exactly the same parsing and
verification path as a cloud language model would.
"""
from __future__ import annotations

import json

from src.providers.base import NarrativeProvider, StoryRequest
from src.storytelling.narratives import compose_sentences


class LocalProvider(NarrativeProvider):
    name = "local-templates"

    def available(self) -> bool:
        return True

    def complete(self, request: StoryRequest) -> str:
        sentences = compose_sentences(request.mode, request.language, request.insight, request.claims)
        return json.dumps({"sentences": [s.model_dump() for s in sentences]}, ensure_ascii=False)
