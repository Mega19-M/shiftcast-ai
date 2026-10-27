"""Orchestrator: runs the five agents in a fixed, acyclic order and logs every handoff.

    Signal -> Context -> Scenario -> Evidence(facts) -> Story -> Evidence(story)
                                                         \\__ at most ONE local retry if the story fails verification

Design honesty: this is "five modular logical agents with a shared structured
state and explicit handoffs", not five independent autonomous LLM agents.
Four of the five are deterministic; only the Story Agent may call a language
model (optional), and whatever it writes is re-verified by the Evidence Agent.

Guarantees
----------
* No cycles: every agent runs once per insight; the only repetition is a single
  deterministic-local retry of the Story Agent.
* Bounded work: at most ``config.PIPELINE_MAX_INSIGHTS`` insights are processed.
* Every step is wrapped: an exception becomes a trace line with status "error"
  and the pipeline continues with safe defaults.
* Provenance: ``check_provenance`` verifies that every event id carried by any
  output exists in the validated source events.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import config
from src.agents.context_agent import ContextAgent
from src.agents.evidence_agent import EvidenceAgent
from src.agents.scenario_agent import ScenarioAgent
from src.agents.schemas import (ContextInput, ContextOutput, EvidenceInput, EvidenceOutput, ScenarioInput,
                                ScenarioOutput, SignalInput, SignalOutput, StoryCheckInput, StoryInput)
from src.agents.signal_agent import SignalAgent
from src.agents.story_agent import StoryAgent
from src.models import AgentTrace, Event, InsightBundle, Match, PipelineResult, StoryDoc
from src.providers import NarrativeProvider, get_provider

log = logging.getLogger("shiftcast.pipeline")


class Orchestrator:
    def __init__(self, provider: Optional[NarrativeProvider] = None):
        self.provider = provider or get_provider()
        self.signal = SignalAgent()
        self.context = ContextAgent()
        self.scenario = ScenarioAgent()
        self.evidence = EvidenceAgent()
        self.story = StoryAgent(self.provider)

    # ------------------------------------------------------------------ helpers
    def _step(self, traces: list[AgentTrace], agent: str, fn: Callable, default: Callable,
              in_sum: str, out_sum: Callable, handoff: Optional[str], n_ids: Callable = lambda o: 0):
        t0 = time.perf_counter()
        try:
            out = fn()
            traces.append(AgentTrace(agent=agent, status="ok", duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                                     input_summary=in_sum, output_summary=out_sum(out), handoff_to=handoff,
                                     source_event_ids=n_ids(out)))
            return out
        except Exception as exc:  # never crash the app because one agent failed
            log.exception("agent %s failed", agent)
            traces.append(AgentTrace(agent=agent, status="error", duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                                     input_summary=in_sum, output_summary="safe default used", handoff_to=handoff,
                                     error=f"{type(exc).__name__}: {exc}"))
            return default()

    # ------------------------------------------------------------------ main run
    def run(self, match: Match, events: list[Event], max_insights: Optional[int] = None,
            overrides: Optional[dict] = None, kinds: Optional[list[str]] = None) -> PipelineResult:
        max_insights = min(max_insights or config.PIPELINE_MAX_INSIGHTS, config.PIPELINE_MAX_INSIGHTS)
        result = PipelineResult(match_id=match.match_id, synthetic=match.synthetic, n_events=len(events))
        traces: list[AgentTrace] = result.traces  # pydantic copies lists on construction, so share the stored list

        sig = self._step(
            traces, "signal", lambda: self.signal.run(SignalInput(match=match, events=events, kinds=kinds, max_insights=max_insights)),
            lambda: SignalOutput(), f"{len(events)} events", lambda o: f"{len(o.insights)} insights", "context",
            lambda o: sum(len(i.event_ids) for i in o.insights))
        insights = sig.insights

        ctx = self._step(
            traces, "context", lambda: self.context.run(ContextInput(match=match, events=events, insights=insights)),
            lambda: ContextOutput(), f"{len(insights)} insights",
            lambda o: f"{len(o.graphs)} graphs, {sum(len(g.edges) for g in o.graphs.values())} edges", "scenario",
            lambda o: sum(len(g.nodes) for g in o.graphs.values()))

        scn = self._step(
            traces, "scenario", lambda: self.scenario.run(ScenarioInput(match=match, events=events, insights=insights,
                                                                       overrides=overrides or {})),
            lambda: ScenarioOutput(), f"{len(insights)} insights",
            lambda o: f"{sum(len(v) for v in o.scenarios.values())} scenarios", "evidence",
            lambda o: sum(len(s.evidence_event_ids) for v in o.scenarios.values() for s in v))

        for ins in insights:
            scenarios = scn.scenarios.get(ins.insight_id, [])
            ev: EvidenceOutput = self._step(
                traces, "evidence", lambda: self.evidence.run(EvidenceInput(match=match, events=events, insight=ins,
                                                                           scenarios=scenarios)),
                lambda: EvidenceOutput(), f"insight {ins.insight_id}",
                lambda o: f"{len(o.fact_sheet)} claims passed, {len(o.rejected_claim_ids)} rejected", "story",
                lambda o: sum(len(c.evidence_event_ids) for c in o.fact_sheet))
            result.bundles.append(InsightBundle(
                insight=ins, graph=ctx.graphs.get(ins.insight_id), scenarios=scenarios,
                fact_sheet=ev.fact_sheet, fact_verification=ev.results))

        result.provenance_ok, result.provenance_notes = check_provenance(result, events)
        return result

    # ------------------------------------------------------------------ stories
    def generate_story(self, result: PipelineResult, match: Match, events: list[Event], insight_id: str,
                       mode: str, language: str) -> StoryDoc:
        """Story Agent + post-verification (bounded: at most one deterministic retry)."""
        bundle = next((b for b in result.bundles if b.insight.insight_id == insight_id), None)
        if bundle is None:
            raise KeyError(f"unknown insight {insight_id}")
        key = f"{mode}|{language}"
        if key in bundle.stories:
            return bundle.stories[key]

        def attempt(force_local: bool, reason: Optional[str]) -> tuple[StoryDoc, bool, list[str]]:
            inp = StoryInput(match=match, events=events, insight=bundle.insight, fact_sheet=bundle.fact_sheet,
                             mode=mode, language=language, force_local=force_local, fallback_reason=reason)
            t0 = time.perf_counter()
            out = self.story.run(inp)
            st = "fallback" if out.story.fallback_reason else "ok"
            result.traces.append(AgentTrace(
                agent="story", status=st, duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                input_summary=f"{insight_id} {mode}/{language} via {'local' if force_local else self.provider.name}",
                output_summary=f"{len(out.story.sentences)} sentences by {out.story.provider}", handoff_to="evidence",
                error=out.story.fallback_reason, source_event_ids=len(bundle.insight.event_ids)))
            t1 = time.perf_counter()
            chk = self.evidence.verify_story(StoryCheckInput(match=match, events=events, insight=bundle.insight,
                                                             story=out.story, fact_sheet=bundle.fact_sheet))
            result.traces.append(AgentTrace(
                agent="evidence", status="ok" if chk.ok else "error", duration_ms=round((time.perf_counter() - t1) * 1000, 2),
                input_summary=f"story {mode}/{language}", output_summary=("all claims passed" if chk.ok else f"{len(chk.failures)} failures"),
                handoff_to=None, error=None if chk.ok else "; ".join(chk.failures)[:300]))
            return chk.story, chk.ok, chk.failures

        story, ok, failures = attempt(False, None)
        if not ok and story.provider != "local-templates":
            story, ok, failures = attempt(True, "verification failed for provider output: " + "; ".join(failures)[:200])
        bundle.stories[key] = story
        return story

    def generate_all_stories(self, result: PipelineResult, match: Match, events: list[Event],
                             modes=("fan", "analyst", "broadcast"), languages=("en",)) -> None:
        for b in result.bundles:
            for m in modes:
                for lg in languages:
                    self.generate_story(result, match, events, b.insight.insight_id, m, lg)


# ----------------------------------------------------------------------------
def check_provenance(result: PipelineResult, events: list[Event]) -> tuple[bool, list[str]]:
    """Every event id referenced by any agent output must exist in the source events."""
    known = {e.event_id for e in events}
    notes: list[str] = []

    def chk(where: str, ids) -> None:
        bad = sorted({i for i in ids if i not in known})
        if bad:
            notes.append(f"{where}: unknown event ids {bad[:5]}")

    for b in result.bundles:
        iid = b.insight.insight_id
        chk(f"{iid} insight", b.insight.event_ids)
        if b.graph:
            chk(f"{iid} graph nodes", [n.node_id for n in b.graph.nodes])
            chk(f"{iid} graph edges", [x for e in b.graph.edges for x in (e.source, e.target)])
        for s in b.scenarios:
            chk(f"{iid} scenario {s.scenario_id}", s.evidence_event_ids)
        for c in b.fact_sheet:
            chk(f"{iid} claim {c.claim_id}", c.evidence_event_ids)
        for st in b.stories.values():
            for c in st.claims:
                chk(f"{iid} story claim {c.claim_id}", c.evidence_event_ids)
    return (not notes), notes
