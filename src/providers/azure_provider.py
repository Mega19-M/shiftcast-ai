"""Optional Azure OpenAI / Microsoft Foundry narrative provider.

STATUS: written against the documented ``openai`` Python package
(``AzureOpenAI`` client, chat completions API) but NOT tested against a live
Azure resource in this project (no credentials were available while building
it). It is only used when ALL of these environment variables are set and the
``openai`` package is installed::

    AZURE_OPENAI_ENDPOINT      e.g. https://<your-resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY       your key (never commit it)
    AZURE_OPENAI_DEPLOYMENT    the *deployment name* of your chat model
    AZURE_OPENAI_API_VERSION   optional, default 2024-10-21

If anything is missing or a call fails, ``ProviderError`` is raised and the
Story Agent falls back to the deterministic local provider. The model only
ever receives VERIFIED facts, and its answer is re-verified by TrustTrace.
"""
from __future__ import annotations

import json
import os

import config
from src.providers.base import NarrativeProvider, ProviderError, StoryRequest

SYSTEM_PROMPT = (
    "You are a football match storyteller. Write ONLY from the numbered FACTS you are given. "
    "Do not add any number, name, score, minute or event that is not in the facts. "
    "Keep team and player names exactly as written. Interpretations must be hedged "
    "(may / suggests). Hypothetical statements must be clearly labelled as hypothetical. "
    "Reply with JSON only: {\"sentences\": [{\"text\": \"...\", \"claim_ids\": [\"F1\"]}]}."
)

STYLE = {
    "fan": "2-3 short, friendly sentences for a casual fan. No statistics jargon.",
    "analyst": "A detailed tactical explanation: metrics, event ids, limitations. 6-9 sentences.",
    "broadcast": "3-4 punchy commentary lines, each starting with the match minute, suitable for TV.",
}
LANG = {"en": "English", "ta": "Tamil (தமிழ்). Keep names, numbers, event ids and scores in Latin digits/letters exactly as given."}


class AzureProvider(NarrativeProvider):
    name = "azure-openai"

    def __init__(self) -> None:
        self.endpoint = config.AZURE_OPENAI_ENDPOINT or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.key = config.AZURE_OPENAI_API_KEY or os.getenv("AZURE_OPENAI_API_KEY", "")
        self.deployment = config.AZURE_OPENAI_DEPLOYMENT or os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
        self.api_version = config.AZURE_OPENAI_API_VERSION

    def available(self) -> bool:
        if not (self.endpoint and self.key and self.deployment):
            return False
        try:
            import openai  # noqa: F401
        except Exception:
            return False
        return True

    def complete(self, request: StoryRequest) -> str:
        if not self.available():
            raise ProviderError("Azure provider not configured (missing env vars or 'openai' package).")
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(azure_endpoint=self.endpoint, api_key=self.key, api_version=self.api_version)
            facts = [{"id": c.claim_id, "type": c.claim_type,
                      "text": c.text_en} for c in request.claims]
            user = (
                f"Mode: {request.mode} - {STYLE.get(request.mode, '')}\n"
                f"Language: {LANG.get(request.language, 'English')}\n"
                f"Match: {request.match_title}\n"
                f"FACTS (JSON): {json.dumps(facts, ensure_ascii=False)}"
            )
            resp = client.chat.completions.create(
                model=self.deployment,  # for Azure this is the deployment name
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                temperature=0.3,
                response_format={"type": "json_object"},
                timeout=30,
            )
            content = resp.choices[0].message.content
            if not content:
                raise ProviderError("Azure returned an empty message.")
            return content
        except ProviderError:
            raise
        except Exception as exc:  # network, auth, quota ... -> fall back safely
            raise ProviderError(f"Azure call failed: {type(exc).__name__}: {exc}") from exc
