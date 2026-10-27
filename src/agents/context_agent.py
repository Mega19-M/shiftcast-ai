"""CONTEXT AGENT - connects events into the Match Impact Graph.

Input  -> ContextInput(match, events, insights)   (the Signal Agent's insights)
Output -> ContextOutput(graphs)                   (one graph per insight id)
Every graph node keeps its original event id, so the chain can be traced back.
"""
from __future__ import annotations

from src.agents.schemas import ContextInput, ContextOutput
from src.analytics.impact_graph import build_impact_graph


class ContextAgent:
    name = "context"

    def run(self, inp: ContextInput) -> ContextOutput:
        graphs = {}
        for ins in inp.insights:
            graphs[ins.insight_id] = build_impact_graph(ins, inp.events, inp.match)
        return ContextOutput(graphs=graphs)
