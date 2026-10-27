"""Fact sheets and story composition.

Flow for one insight:
  1. ``build_fact_sheet``  turns the insight + scenarios into structured ``Claim``s
     (each carries its own check parameters and bilingual text).
  2. The Evidence Agent verifies the fact sheet.
  3. A provider turns the VERIFIED facts into sentences for a mode (fan /
     analyst / broadcast) and language (en / ta).
  4. ``parse_story_json`` safely reads the provider answer.
  5. The Evidence Agent verifies the story again (structured + free text).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from src.analytics.impact_graph import describe_event
from src.models import Claim, Event, Insight, Match, ScenarioResult, StorySentence
from src.storytelling.translation import lane_word, tr

MODES = ("fan", "analyst", "broadcast")
MODE_LABEL = {"fan": "FAN MODE", "analyst": "ANALYST MODE", "broadcast": "BROADCAST MODE"}
SUPPORT_NOUN = {"turnover_spike": "turnovers", "defensive_cluster": "turnovers in their own defensive third",
                "shot_surge": "shots", "flank_overload": "shots", "possession_shift": "shots"}


# --------------------------------------------------------------------------
# Fact sheet
# --------------------------------------------------------------------------
def _vars(insight: Insight, match: Match) -> dict:
    d = insight.detail
    v = {
        "team": match.team_name(insight.team_id), "s": int(round(insight.start_min)), "e": int(round(insight.end_min)),
        "n": int(insight.observed), "exp": f"{insight.expected:.1f}", "p": f"{insight.p_value:.1e}",
        "lane": d.get("lane", ""),
    }
    if "share" in d:
        v["share"] = f"{d['share']:.0%}"
        v["base"] = f"{d.get('baseline_share', 0):.0%}"
        v["tot"] = d.get("n_actions", d.get("n_events", 0))
    return v


def _render(lang: str, key: str, v: dict) -> str:
    vv = dict(v)
    if vv.get("lane"):
        vv["lane"] = lane_word(lang, vv["lane"])
    return tr(lang, key, **vv)


def build_fact_sheet(insight: Insight, scenarios: list[ScenarioResult], match: Match, events: list[Event]) -> list[Claim]:
    """Create the structured claims that every story is allowed to use."""
    v = _vars(insight, match)
    T = insight.team_id
    s, e = insight.start_min, insight.end_min
    claims: list[Claim] = []
    ids = insight.event_ids[:25]

    # F1 headline - re-runs the detection rule
    claims.append(Claim(
        claim_id="F1", claim_type="factual", check="window_stat",
        params={"kind": insight.kind, "team_id": T, "start": s, "end": e, "observed": insight.observed,
                "p_value": insight.p_value, "lane": insight.detail.get("lane"), "_role": "headline", "_vars": v},
        evidence_event_ids=ids,
        text_en=_render("en", f"hl_{insight.kind}", v), text_ta=_render("ta", f"hl_{insight.kind}", v)))

    # F2 support count - a plain count of events
    if insight.kind == "turnover_spike":
        cp = {"event_type": "turnover"}
    elif insight.kind == "defensive_cluster":
        cp = {"event_type": "turnover", "zone": "defensive"}
    else:
        cp = {"event_type": "shot"}
    n_sup = sum(1 for x in events if x.team_id == T and s <= x.minute <= e and x.event_type == cp["event_type"]
                and (cp.get("zone") is None or x.zone == cp["zone"]))
    noun = SUPPORT_NOUN[insight.kind]
    claims.append(Claim(
        claim_id="F2", claim_type="factual", check="count",
        params={"team_id": T, "start": s, "end": e, "expected": n_sup, "op": "==", **cp, "_role": "support"},
        text_en=(f"{v['team']} lost the ball {n_sup} times in their own defensive third between {v['s']}' and {v['e']}'."
                 if insight.kind == "defensive_cluster"
                 else f"{v['team']} had {n_sup} {noun} between {v['s']}' and {v['e']}'."),
        text_ta=f"{v['s']}' முதல் {v['e']}' வரை {v['team']} அணிக்கு {n_sup} பதிவுகள் ({noun})."))

    # F3 score at the end of the window
    h, a = _score(events, match, e)
    claims.append(Claim(
        claim_id="F3", claim_type="factual", check="score",
        params={"minute": e, "home": h, "away": a, "_role": "score"},
        text_en=tr("en", "score", m=v["e"], home=match.home.name, away=match.away.name, a=h, b=a),
        text_ta=tr("ta", "score", m=v["e"], home=match.home.name, away=match.away.name, a=h, b=a)))

    # F4.. goals inside the window
    n = 4
    for g in [x for x in events if x.event_type == "goal" and s <= x.minute <= e][:2]:
        kw = dict(player=match.player_name(g.player_id), team=match.team_name(g.team_id), clock=g.clock, event_id=g.event_id)
        claims.append(Claim(
            claim_id=f"F{n}", claim_type="factual", check="event_exists",
            params={"event_id": g.event_id, "minute": g.minute, "team_id": g.team_id, "player_id": g.player_id,
                    "event_type": "goal", "_role": "goal"},
            evidence_event_ids=[g.event_id], text_en=tr("en", "goal", **kw), text_ta=tr("ta", "goal", **kw)))
        n += 1

    # interpretation (hedged)
    claims.append(Claim(
        claim_id=f"F{n}", claim_type="interpretation", evidence_event_ids=ids[:5],
        params={"_role": "interpretation"},
        text_en=_render("en", f"interp_{insight.kind}", v), text_ta=_render("ta", f"interp_{insight.kind}", v)))
    n += 1

    # hypothetical statements from the What-If lab
    for letter, sc in zip("AB", scenarios):
        m = next((x for x in sc.metrics if x.low is not None and x.high is not None and x.actual is not None), None)
        if m is None:
            continue
        kw = dict(letter=letter, metric=m.metric, low=f"{min(m.low, m.high):.1f}", high=f"{max(m.low, m.high):.1f}",
                  actual=f"{m.actual:.1f}")
        claims.append(Claim(
            claim_id=f"F{n}", claim_type="hypothetical", evidence_event_ids=sc.evidence_event_ids[:5],
            params={"_role": "hypothetical", "scenario": sc.scenario_id},
            text_en=tr("en", "hyp", **kw), text_ta=tr("ta", "hyp", **kw)))
        n += 1

    claims.append(Claim(claim_id=f"F{n}", claim_type="interpretation", params={"_role": "caveat"},
                        text_en=tr("en", "caveat"), text_ta=tr("ta", "caveat")))
    return claims


def _score(events: list[Event], match: Match, minute: float) -> tuple[int, int]:
    h = sum(1 for x in events if x.event_type == "goal" and x.team_id == match.home.team_id and x.minute <= minute)
    a = sum(1 for x in events if x.event_type == "goal" and x.team_id == match.away.team_id and x.minute <= minute)
    return h, a


# --------------------------------------------------------------------------
# Composition (used by the local provider)
# --------------------------------------------------------------------------
def _by_role(claims: list[Claim]) -> dict[str, list[Claim]]:
    out: dict[str, list[Claim]] = {}
    for c in claims:
        out.setdefault(c.params.get("_role", "other"), []).append(c)
    return out


def _text(c: Claim, lang: str) -> str:
    return (c.text_ta if lang == "ta" and c.text_ta else c.text_en)


def compose_sentences(mode: str, lang: str, insight: Insight, claims: list[Claim]) -> list[StorySentence]:
    """Deterministic, template-based story. Every sentence lists the claims it relies on."""
    r = _by_role(claims)
    head = (r.get("headline") or [None])[0]
    if head is None:  # the headline fact failed verification: say so instead of inventing text
        msg = ("No verified facts were available for this insight." if lang == "en"
               else "இந்த நுண்ணறிவுக்கு சரிபார்க்கப்பட்ட தகவல்கள் இல்லை.")
        return [StorySentence(text=msg, claim_ids=[])]
    v = dict(head.params["_vars"])
    out: list[StorySentence] = []

    def add(text: str, *cs: Optional[Claim]) -> None:
        out.append(StorySentence(text=text, claim_ids=[c.claim_id for c in cs if c is not None]))

    def meta(text: str) -> None:  # boilerplate line (rule, strength, ids, caveats); checked by the token check
        out.append(StorySentence(text=text, claim_ids=["meta"]))

    score = (r.get("score") or [None])[0]
    goals = r.get("goal") or []
    interp = (r.get("interpretation") or [None])[0]
    hyps = r.get("hypothetical") or []
    caveat = (r.get("caveat") or [None])[0]
    support = (r.get("support") or [None])[0]

    if mode == "fan":
        add(_render(lang, f"fan_{insight.kind}", v), head)
        if goals:
            add(_text(goals[0], lang), goals[0])
        elif score:
            add(_text(score, lang), score)
        if interp:
            add(_text(interp, lang), interp)
    elif mode == "broadcast":
        add(_render(lang, f"bc_{insight.kind}", v), head)
        if goals:
            add(_text(goals[0], lang), goals[0])
        if score:
            add(_text(score, lang), score)
    else:  # analyst
        if head:
            add(_text(head, lang), head)
        if support:
            add(_text(support, lang), support)
        meta(tr(lang, "strength_line", strength=f"{insight.evidence_strength:.2f}"))
        meta(tr(lang, "rule_line", rule=insight.rule))
        meta(tr(lang, "evidence_line", ids=", ".join(insight.event_ids[:5])))
        if score:
            add(_text(score, lang), score)
        for g in goals:
            add(_text(g, lang), g)
        if interp:
            add(_text(interp, lang), interp)
        for h in hyps:
            add(_text(h, lang), h)
        if caveat:
            add(_text(caveat, lang), caveat)
        for cv in insight.caveats[:2]:
            meta(cv if cv.endswith(".") else cv + ".")
    return out


def broadcast_assets(insight: Insight, claims: list[Claim], match: Match, events: list[Event]) -> tuple[list[str], list[dict]]:
    """Suggested on-screen graphics and machine-readable overlay cues (format documented in docs/)."""
    team = match.team_name(insight.team_id)
    s, e = insight.start_min, insight.end_min
    ids = insight.event_ids
    graphics = {
        "turnover_spike": [f"Pitch map: {team} turnovers {s:.0f}'-{e:.0f}'", f"Stat card: {int(insight.observed)} turnovers vs {insight.expected:.1f} expected",
                           "Timeline marker with turnover ticks"],
        "shot_surge": [f"Shot map: {team} shots {s:.0f}'-{e:.0f}'", f"Stat card: {int(insight.observed)} shots vs {insight.expected:.1f} expected",
                       "Momentum bar over the window"],
        "defensive_cluster": [f"Defensive-third zone highlight for {team}", f"Stat card: {int(insight.observed)} turnovers in own third",
                              "Replay carousel of the turnovers"],
        "flank_overload": [f"Arrow map: {team} attacks down the {insight.detail.get('lane', '')} flank",
                           f"Lane split donut: {insight.detail.get('share', 0):.0%} vs {insight.detail.get('baseline_share', 0):.0%} baseline",
                           "Pass network on that flank"],
        "possession_shift": [f"Share-of-play line chart for {team}", "Before/after share bar", "Timeline marker at the shift"],
    }[insight.kind]
    cues = [
        {"cue_id": f"{insight.insight_id}-C1", "type": "lower_third", "start_min": round(s, 2), "duration_s": 8,
         "title": insight.title, "text": _text((_by_role(claims).get("headline") or [Claim(claim_id="x")])[0], "en")[:140],
         "event_ids": ids[:3]},
        {"cue_id": f"{insight.insight_id}-C2", "type": "stat_card", "start_min": round(e, 2), "duration_s": 8,
         "title": "Observed vs expected", "stats": {"observed": insight.observed, "expected": insight.expected,
                                                   "p_value": insight.p_value, "evidence_strength": insight.evidence_strength},
         "text": "Heuristic evidence strength, not a probability.", "event_ids": ids[:3]},
        {"cue_id": f"{insight.insight_id}-C3", "type": "pitch_overlay", "start_min": round(s, 2), "end_min": round(e, 2),
         "title": "Supporting events", "overlay": "event_markers", "event_ids": ids[:25]},
    ]
    return graphics, cues


# --------------------------------------------------------------------------
# Provider output parsing (robust against malformed model answers)
# --------------------------------------------------------------------------
def parse_story_json(raw: object) -> list[StorySentence]:
    """Parse a provider answer. Raises ``ValueError`` for anything malformed."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty provider answer")
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.I)
    try:
        data = json.loads(txt)
    except json.JSONDecodeError as exc:
        raise ValueError(f"answer is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sentences"), list) or not data["sentences"]:
        raise ValueError("JSON has no non-empty 'sentences' list")
    out: list[StorySentence] = []
    for item in data["sentences"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("a sentence entry has no text")
        cids = item.get("claim_ids", [])
        if not isinstance(cids, list) or not all(isinstance(c, str) for c in cids):
            raise ValueError("claim_ids must be a list of strings")
        out.append(StorySentence(text=item["text"].strip(), claim_ids=cids))
    return out
