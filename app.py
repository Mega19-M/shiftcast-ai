"""SHIFTCAST AI - Streamlit entry point.

Run with:   streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import config

st.set_page_config(page_title="SHIFTCAST AI", page_icon="⚽", layout="wide", initial_sidebar_state="expanded")

from src.data.generator import PRESETS  # noqa: E402  (after set_page_config on purpose)
from src.storytelling.narratives import MODE_LABEL, MODES  # noqa: E402
from src.storytelling.translation import LANGUAGES  # noqa: E402
from src.ui import (components as C, evaluation_page, impact_graph_page, match_center, match_dna_page,  # noqa: E402
                    story_studio_page, what_if_page)
from src.ui.context import azure_available, build_context, match_options  # noqa: E402

PAGES = {
    "Match Center": match_center,
    "Match DNA": match_dna_page,
    "Impact Graph": impact_graph_page,
    "What-If Lab": what_if_page,
    "Story Studio": story_studio_page,
    "Evaluation & Testing": evaluation_page,
}


def main() -> None:
    C.inject_css()
    with st.sidebar:
        st.markdown(f"## ⚽ {config.APP_NAME}")
        st.caption(config.TAGLINE)
        st.markdown('<span class="sc-pill">DEMO / SYNTHETIC DATA</span>', unsafe_allow_html=True)
        page = st.radio("Page", list(PAGES), key="page")
        st.divider()
        options = match_options()
        if st.session_state.get("match_choice") not in options:
            st.session_state["match_choice"] = list(PRESETS)[0]
        match_key = st.selectbox("Match", options, key="match_choice")
        mode = st.radio("Audience mode", list(MODES), format_func=lambda x: MODE_LABEL[x], key="mode")
        lang = st.selectbox("Language", list(LANGUAGES), format_func=lambda x: LANGUAGES[x], key="lang")
        revealed = st.checkbox("Analyse only events revealed so far", value=False, key="use_revealed",
                               help="When ticked, every page analyses only what the simulated feed has shown.")
        az = azure_available()
        use_azure = st.checkbox("Use Azure AI for story text", value=False, disabled=not az, key="use_azure",
                                help="Needs AZURE_OPENAI_* environment variables (see README). Falls back to local templates "
                                     "if unavailable or if the output fails verification.")
        if not az:
            st.caption("Azure AI not configured - using the built-in local provider.")
        st.divider()
        st.caption("Not an official Premier League product. All data is fictional.")

    try:
        ctx = build_context(match_key, mode, lang, use_azure and az, revealed)
        PAGES[page].render(ctx)
    except Exception as exc:  # last-resort guard: show a friendly message instead of a stack trace wall
        st.error(f"Something went wrong while showing this page: {type(exc).__name__}: {exc}")
        with st.expander("Technical details"):
            st.exception(exc)


main()
