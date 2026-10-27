"""SIGNAL AGENT - finds the moments worth explaining.

Deterministic: wraps the statistical turning-point detector. No language model.
Input  -> SignalInput(match, events)
Output -> SignalOutput(insights)   (each insight carries supporting event ids)
"""
from __future__ import annotations

from src.agents.schemas import SignalInput, SignalOutput
from src.analytics.turning_points import detect_turning_points


class SignalAgent:
    name = "signal"

    def run(self, inp: SignalInput) -> SignalOutput:
        insights = detect_turning_points(inp.events, inp.match, kinds=inp.kinds)
        # the hard cap keeps the pipeline bounded: strongest evidence first
        # scored rules first, exploratory ones only if there is room; strongest evidence first
        insights = sorted(insights, key=lambda i: (i.exploratory, -i.evidence_strength))[: max(0, inp.max_insights)]
        insights.sort(key=lambda i: i.start_min)
        return SignalOutput(insights=insights)
