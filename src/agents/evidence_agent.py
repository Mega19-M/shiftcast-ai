"""EVIDENCE AGENT - the TrustTrace gatekeeper. It runs TWICE per insight (bounded, no loop):

  1. ``run``          BEFORE the story: build the fact sheet, verify every claim against the
                      event data, and pass on only the claims that are verified or
                      correctly labelled (interpretation / hypothetical).
  2. ``verify_story`` AFTER the story: re-verify the claims the story relies on, run the free-text
                      checker on the English text, and look for numbers / ids / names in the text
                      that exist in none of the verified facts (invented details).

Input/Output: see ``agents/schemas.py``.
"""
from __future__ import annotations

from src.agents.schemas import EvidenceInput, EvidenceOutput, StoryCheckInput, StoryCheckOutput
from src.models import ClaimResult
from src.storytelling.narratives import build_fact_sheet
from src.verification.claim_checker import check_text, foreign_tokens, verify_claim, verify_claims
from src.verification.evidence import EvidenceIndex


class EvidenceAgent:
    name = "evidence"

    # ---- pass 1: facts ---------------------------------------------------------
    def run(self, inp: EvidenceInput) -> EvidenceOutput:
        idx = EvidenceIndex(inp.match, inp.events)
        claims = build_fact_sheet(inp.insight, inp.scenarios, inp.match, inp.events)
        results = verify_claims(claims, idx)
        keep, rejected = [], []
        for c, r in zip(claims, results):
            (keep if r.passed else rejected).append(c if r.passed else c.claim_id)
        return EvidenceOutput(fact_sheet=keep, results=results, rejected_claim_ids=rejected)

    # ---- pass 2: the finished story ---------------------------------------------
    def verify_story(self, inp: StoryCheckInput) -> StoryCheckOutput:
        idx = EvidenceIndex(inp.match, inp.events)
        story = inp.story
        by_id = {c.claim_id: c for c in inp.fact_sheet}
        results: list[ClaimResult] = []
        failures: list[str] = []

        # (a) every claim the story cites must exist in the verified fact sheet and still verify
        cited = []
        for s in story.sentences:
            for cid in s.claim_ids:
                if cid != "meta" and cid not in cited:
                    cited.append(cid)
        for cid in cited:
            c = by_id.get(cid)
            if c is None:
                results.append(ClaimResult(claim_id=cid, claim_text=f"(cited claim {cid})", claim_type="factual",
                                           status="unsupported", evidence="fact sheet",
                                           explanation=f"Story cites {cid}, which is not in the verified fact sheet."))
                continue
            results.append(verify_claim(c, idx))

        # (b) free-text check of the English text (contradicted / unsupported statements)
        if story.language == "en":
            # trusted template boilerplate ("meta" lines) is covered by the token check below
            trusted = story.provider == "local-templates"
            checked = "\n".join(s.text for s in story.sentences if not (trusted and "meta" in s.claim_ids))
            ft = check_text(checked, inp.match, inp.events)
            for r in ft["results"]:
                results.append(r.model_copy(update={"claim_id": f"text:{r.claim_id}"}))

        # (c) invented numbers / ids / names in ANY language
        allowed = []
        for c in inp.fact_sheet:
            allowed += [c.text_en, c.text_ta]
        ins = inp.insight
        allowed += [ins.title, ins.rule, ins.explanation, *ins.caveats, ", ".join(ins.event_ids),
                    f"{ins.evidence_strength:.2f}", f"{ins.p_value:.1e}", ins.strength_formula]
        for k, tok in enumerate(foreign_tokens(story.text, allowed, inp.match), start=1):
            results.append(ClaimResult(
                claim_id=f"token:{k}", claim_text=tok, claim_type="factual", status="unsupported",
                evidence="verified fact sheet",
                explanation=f"'{tok}' appears in the story but in none of the verified facts."))

        for r in results:
            if r.status in ("contradicted", "unsupported"):
                failures.append(f"{r.claim_id}: {r.explanation}")
        ok = not failures
        story = story.model_copy(update={"verification": results, "all_verified": ok})
        return StoryCheckOutput(story=story, ok=ok, failures=failures)
