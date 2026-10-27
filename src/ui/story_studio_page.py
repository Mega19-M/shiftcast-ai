"""Page 5 - Story Studio: one verified insight, three audiences, two languages; recap; TrustTrace sandbox; exports."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src.models import StoryDoc
from src.reporting.exports import (build_report, events_to_csv, overlay_cues_json, report_json, summary_text, webvtt)
from src.storytelling.narratives import MODE_LABEL, MODES
from src.storytelling.recap import PERIODS, build_recap
from src.storytelling.translation import LANGUAGES, period_word
from src.ui import components as C
from src.ui.context import Ctx, azure_available
from src.verification.claim_checker import check_text


def _show_story(story: StoryDoc) -> None:
    if story.all_verified:
        st.markdown(C.chip("verified") + " <span class='sc-note'>every checked claim passed TrustTrace</span>",
                    unsafe_allow_html=True)
    else:
        st.markdown(C.chip("contradicted") + " <span class='sc-note'>some claims failed - see the audit panel</span>",
                    unsafe_allow_html=True)
    C.story_box(story.text)
    st.caption(f"Provider: {story.provider}" + (f" · fallback used: {story.fallback_reason}" if story.fallback_reason else ""))
    if story.mode == "broadcast" and story.graphics:
        st.markdown("**Suggested on-screen graphics**")
        for g in story.graphics:
            st.markdown(f"- {g}")
    with st.expander("Claim audit panel (claim · evidence · result · why)", expanded=story.mode == "analyst"):
        C.audit_panel(story.verification)


def _fill_example(text: str) -> None:
    st.session_state["tt_text"] = text


def render(ctx: Ctx) -> None:
    m = ctx.match
    st.title("Story Studio")
    C.banner(m)
    st.caption("One verified insight → three audiences. Stories are written ONLY from facts that passed TrustTrace, "
               "then checked again after writing.")
    az = azure_available()
    st.markdown(f"Narrative provider: **{ctx.provider_name}** · Azure AI configured: **{'yes' if az else 'no (local templates are used)'}**")
    if not ctx.events:
        C.empty_state("No events yet. Press Play in the Match Center or analyse the full match.")
        return
    pipe = ctx.pipeline
    tabs = st.tabs(["Insight stories", "Match recap", "TrustTrace sandbox", "Agent pipeline", "Export"])

    # ------------------------------------------------------------------ tab 1
    with tabs[0]:
        if not pipe.bundles:
            C.empty_state("No turning point was detected, so there is no insight to narrate. Try the recap tab.")
        else:
            labels = {b.insight.insight_id: b.insight.title for b in pipe.bundles}
            sel = st.selectbox("Insight", list(labels), format_func=lambda k: labels[k], key="ss_insight")
            c = st.columns([2, 1, 1])
            mode = c[0].radio("Audience", list(MODES), index=list(MODES).index(ctx.mode), horizontal=True,
                              format_func=lambda x: MODE_LABEL[x], key="ss_mode")
            lang = c[1].selectbox("Language", list(LANGUAGES), index=list(LANGUAGES).index(ctx.lang),
                                  format_func=lambda x: LANGUAGES[x], key="ss_lang")
            both = c[2].checkbox("Show all three audiences", value=False, key="ss_all")
            if lang == "ta":
                st.info("Tamil text comes from reviewed-by-code templates: names, numbers and scores are inserted unchanged. "
                        "A native speaker should review the wording before a public demo.")
            todo = list(MODES) if both else [mode]
            if st.button("Generate story", key="ss_go") or all(f"{x}|{lang}" in
                                                           next(b for b in pipe.bundles if b.insight.insight_id == sel).stories
                                                           for x in todo):
                for md in todo:
                    with st.spinner(f"Writing {MODE_LABEL[md]} and verifying every claim..."):
                        story = ctx.orch.generate_story(pipe, m, ctx.events, sel, md, lang)
                    if both:
                        st.subheader(MODE_LABEL[md])
                    _show_story(story)
            else:
                st.info("Press **Generate story** to write and verify the narrative.")

    # ------------------------------------------------------------------ tab 2
    with tabs[1]:
        c = st.columns(2)
        period = c[0].radio("Period", list(PERIODS), index=2, horizontal=True,
                            format_func=lambda p: period_word("en", p), key="rc_period")
        lang = c[1].selectbox("Language", list(LANGUAGES), format_func=lambda x: LANGUAGES[x], key="rc_lang")
        recap = build_recap(m, ctx.events, [b.insight for b in pipe.bundles], period, lang)
        C.story_box(recap.text)
        st.markdown(C.chip("verified" if recap.all_verified else "contradicted"), unsafe_allow_html=True)
        with st.expander("Claim audit panel", expanded=False):
            C.audit_panel(recap.verification)
        C.download("Download recap (txt)", recap.text, f"{m.match_id}_recap_{period}_{lang}.txt", "text/plain", f"dl_recap_{period}_{lang}")

    # ------------------------------------------------------------------ tab 3
    with tabs[2]:
        st.markdown("Paste any match text (for example from a chatbot). TrustTrace extracts event ids, scores, counts, "
                    "clock times and player/team facts, **recomputes each from the events**, and rewrites the text without "
                    "unsupported statements.")
        goals = [e for e in ctx.events if e.event_type == "goal"]
        h = sum(1 for g in goals if g.team_id == m.home.team_id)
        a = len(goals) - h
        example = (f"The final score was {m.home.name} {h}-{a} {m.away.name}. "
                   f"{m.home.name} scored {h + 4} goals in total. "
                   + (f"{goals[0].event_id} was a goal at {goals[0].clock} by {m.team_name(goals[0].team_id)}. " if goals else "")
                   + "Dario Quillon scored a late winner. The pressure may have forced errors. They will win next week.")
        st.button("Load an example with deliberate errors", on_click=_fill_example, args=(example,), key="tt_example")
        text = st.text_area("Text to verify", height=150, key="tt_text")
        if st.button("Verify with TrustTrace", key="tt_go"):
            out = check_text(text, m, ctx.events)
            if not out["results"]:
                st.info("Nothing to check - paste some text first.")
            else:
                st.markdown(C.chip("verified" if out["ok"] else "contradicted"), unsafe_allow_html=True)
                C.audit_panel(out["results"])
                st.markdown("**Revised text (unsupported statements removed, uncheckable ones flagged)**")
                C.story_box(out["revised_text"])

    # ------------------------------------------------------------------ tab 4
    with tabs[3]:
        st.markdown(f"Provenance check - every event id carried by any agent exists in the source data: "
                    f"**{'PASS' if pipe.provenance_ok else 'FAIL'}**")
        for n in pipe.provenance_notes:
            st.warning(n)
        rows = [{"agent": t.agent, "status": t.status, "ms": t.duration_ms, "input": t.input_summary,
                 "output": t.output_summary, "hands off to": t.handoff_to or "-", "event ids carried": t.source_event_ids,
                 "error": t.error or ""} for t in pipe.traces]
        C.table(pd.DataFrame(rows), height=340)
        if pipe.bundles:
            sel = st.selectbox("Inspect the structured handoffs for", [b.insight.insight_id for b in pipe.bundles], key="ap_sel")
            b = next(x for x in pipe.bundles if x.insight.insight_id == sel)
            with st.expander("1. Signal Agent output → Insight"):
                st.json(b.insight.model_dump(mode="json"))
            with st.expander("2. Context Agent output → GraphData (nodes/edges summary)"):
                if b.graph:
                    st.json({"nodes": len(b.graph.nodes), "edges": len(b.graph.edges), "chain": b.graph.chain[:10],
                             "association": b.graph.association})
            with st.expander("3. Scenario Agent output → ScenarioResult[]"):
                st.json([s.model_dump(mode="json") for s in b.scenarios])
            with st.expander("4. Evidence Agent output → verified fact sheet"):
                st.json([c.model_dump(mode="json") for c in b.fact_sheet])
            with st.expander("5. Story Agent output → StoryDoc (after Evidence post-check)"):
                st.json({k: v.model_dump(mode="json") for k, v in b.stories.items()} or {"info": "generate a story first"})

    # ------------------------------------------------------------------ tab 5
    with tabs[4]:
        st.markdown("Exports contain everything shown in the app: turning points with event ids, scenarios, verified "
                    "facts, stories (generated so far) and the agent trace.")
        if st.button("Generate all stories (3 audiences × English + Tamil) for the export", key="ex_gen"):
            with st.spinner("Writing and verifying all stories..."):
                ctx.orch.generate_all_stories(pipe, m, ctx.events, languages=("en", "ta"))
            st.success("Done.")
        recap = build_recap(m, ctx.events, [b.insight for b in pipe.bundles], "full", "en")
        report = build_report(m, ctx.events, pipe, recap, ctx.validation)
        c = st.columns(3)
        with c[0]:
            C.download("Download report (JSON)", report_json(report), f"{m.match_id}_report.json", "application/json", "dl_json")
            C.download("Download events (CSV)", events_to_csv(ctx.events), f"{m.match_id}_events.csv", "text/csv", "dl_csv")
        with c[1]:
            C.download("Download match summary (TXT)", summary_text(m, ctx.events, pipe, recap), f"{m.match_id}_summary.txt",
                       "text/plain", "dl_txt")
        with c[2]:
            C.download("Download overlay cues (JSON)", overlay_cues_json(m, pipe), f"{m.match_id}_overlay_cues.json",
                       "application/json", "dl_cues")
            C.download("Download subtitles (WebVTT)", webvtt(m, pipe), f"{m.match_id}_cues.vtt", "text/vtt", "dl_vtt")
        st.caption("Overlay cues exist only for broadcast-mode English stories you have generated. "
                   "Format: shiftcast-overlay-cues/1.0 (see docs/OVERLAY_FORMAT.md).")
    C.disclaimer_footer()
