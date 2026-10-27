"""SCENARIO AGENT - evaluates two alternative decisions per insight.

Rule-based and transparent (see ``scenarios/what_if.py``). It states assumptions,
trade-offs and missing data, and labels everything as heuristic.

Input  -> ScenarioInput(match, events, insights, overrides)
Output -> ScenarioOutput(scenarios)   (insight_id -> [Alternative A, Alternative B])
"""
from __future__ import annotations

from src.agents.schemas import ScenarioInput, ScenarioOutput
from src.scenarios.what_if import build_scenarios


class ScenarioAgent:
    name = "scenario"

    def run(self, inp: ScenarioInput) -> ScenarioOutput:
        out = {}
        for ins in inp.insights:
            out[ins.insight_id] = build_scenarios(ins, inp.events, inp.match, inp.overrides)
        return ScenarioOutput(scenarios=out)
