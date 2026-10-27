"""Match recap generator (first half, second half or full match).

Every number in the recap comes from a structured, verified claim (score,
shot and turnover counts, goal events, detected key moments).
"""
from __future__ import annotations

from src.models import Claim, Event, Insight, Match, StorySentence, StoryDoc
from src.storytelling.translation import period_word, tr
from src.verification.claim_checker import verify_claims
from src.verification.evidence import EvidenceIndex

PERIODS = ("first_half", "second_half", "full")
_BOUNDS = {"first_half": (0.0, 44.999), "second_half": (45.0, 400.0), "full": (0.0, 400.0)}


def build_recap(match: Match, events: list[Event], insights: list[Insight], period: str = "full",
                lang: str = "en") -> StoryDoc:
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    lo, hi = _BOUNDS[period]
    pw = period_word(lang, period)
    sentences: list[StorySentence] = []
    claims: list[Claim] = []
    n = 0

    def add(check: str, params: dict, text_en: str, text_ta: str, ids: list[str] | None = None) -> Claim:
        nonlocal n
        n += 1
        c = Claim(claim_id=f"R{n}", claim_type="factual", check=check, params=params,
                  evidence_event_ids=ids or [], text_en=text_en, text_ta=text_ta)
        claims.append(c)
        sentences.append(StorySentence(text=text_ta if lang == "ta" else text_en, claim_ids=[c.claim_id]))
        return c

    if not events:
        txt = "No events available." if lang == "en" else "நிகழ்வுகள் இல்லை."
        return StoryDoc(insight_id=f"recap-{period}", mode="recap", language=lang, text=txt,
                        sentences=[StorySentence(text=txt)], provider="local-templates")

    # score at the end of the period
    end_min = None if period != "first_half" else 44.999
    h = sum(1 for e in events if e.event_type == "goal" and e.team_id == match.home.team_id and e.minute <= (end_min or 400))
    a = sum(1 for e in events if e.event_type == "goal" and e.team_id == match.away.team_id and e.minute <= (end_min or 400))
    kw = dict(period=period_word("en", period), home=match.home.name, away=match.away.name, a=h, b=a)
    kw_ta = dict(kw, period=period_word("ta", period))
    add("score", {"minute": end_min, "home": h, "away": a}, tr("en", "rc_score", **kw), tr("ta", "rc_score", **kw_ta))

    for team in (match.home, match.away):
        shots = sum(1 for e in events if e.team_id == team.team_id and e.event_type == "shot" and lo <= e.minute <= hi)
        tos = sum(1 for e in events if e.team_id == team.team_id and e.event_type == "turnover" and lo <= e.minute <= hi)
        k_en = dict(team=team.name, shots=shots, turnovers=tos, period=period_word("en", period))
        k_ta = dict(k_en, period=period_word("ta", period))
        add("count", {"team_id": team.team_id, "event_type": "shot", "start": lo, "end": hi, "expected": shots},
            tr("en", "rc_stats", **k_en), tr("ta", "rc_stats", **k_ta))
        # the turnover count is checked by a second claim bound to the same sentence
        c2 = Claim(claim_id=f"R{n}b", claim_type="factual", check="count",
                   params={"team_id": team.team_id, "event_type": "turnover", "start": lo, "end": hi, "expected": tos},
                   text_en=tr("en", "rc_stats", **k_en), text_ta=tr("ta", "rc_stats", **k_ta))
        claims.append(c2)
        sentences[-1].claim_ids.append(c2.claim_id)

    for g in [e for e in events if e.event_type == "goal" and lo <= e.minute <= hi]:
        kw = dict(player=match.player_name(g.player_id), team=match.team_name(g.team_id), clock=g.clock, event_id=g.event_id)
        add("event_exists", {"event_id": g.event_id, "minute": g.minute, "team_id": g.team_id, "player_id": g.player_id,
                             "event_type": "goal"}, tr("en", "goal", **kw), tr("ta", "goal", **kw), [g.event_id])

    moments = [i for i in insights if not i.exploratory and i.end_min >= lo and i.start_min <= hi]
    if not moments:
        sentences.append(StorySentence(text=tr(lang, "rc_none", period=pw)))
    for ins in moments[:4]:
        add("window_stat", {"kind": ins.kind, "team_id": ins.team_id, "start": ins.start_min, "end": ins.end_min,
                            "observed": ins.observed, "p_value": ins.p_value, "lane": ins.detail.get("lane")},
            tr("en", "rc_moment", title=ins.title), tr("ta", "rc_moment", title=ins.title), ins.event_ids[:10])

    idx = EvidenceIndex(match, events)
    results = verify_claims(claims, idx)
    ok = all(r.status in ("verified", "labelled") for r in results)
    return StoryDoc(insight_id=f"recap-{period}", mode="recap", language=lang,
                    text="\n".join(s.text for s in sentences), sentences=sentences, claims=claims,
                    verification=results, provider="local-templates", all_verified=ok)
