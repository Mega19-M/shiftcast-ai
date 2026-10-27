"""Narrative providers: a deterministic local one and an optional Azure one."""
from __future__ import annotations

import config
from src.providers.azure_provider import AzureProvider
from src.providers.base import NarrativeProvider, ProviderError, StoryRequest
from src.providers.local_provider import LocalProvider

__all__ = ["NarrativeProvider", "ProviderError", "StoryRequest", "LocalProvider", "AzureProvider", "get_provider"]


def get_provider(prefer_azure: bool | None = None) -> NarrativeProvider:
    """Return Azure only if explicitly requested AND fully configured; otherwise local."""
    want = config.USE_AZURE if prefer_azure is None else prefer_azure
    if want:
        az = AzureProvider()
        if az.available():
            return az
    return LocalProvider()
