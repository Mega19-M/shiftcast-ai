"""TrustTrace: claim verification that really executes against the event data.

Two entry points
----------------
1. ``verify_claim(s)``  - STRUCTURED claims (``Claim`` objects with a ``check``
   type and parameters). Used for everything the app generates itself and for
   claims extracted from text. The check recomputes the number / lookup from
   the validated events and compares it with what the claim says.

2. ``check_text``      - FREE TEXT (e.g. written by a language model or pasted by
   a user). Sentences are scanned for checkable facts (event ids, scores,
   counts, clock times, player/team consistency); each fact becomes a
   structured claim and goes through ``verify_claim``. Sentences that contain
   a contradicted or unsupported fact are removed from the "revised text";
   sentences with nothing checkable are flagged ``unverifiable``.

Statuses: verified | contradicted | unsupported | unverifiable | labelled.
"""
from __future__ import annotations

import re
from typing import Optional

from src.data.generator import _FIRST as KNOWN_FIRST_NAMES
from src.models import Claim, ClaimResult, Event, Match
from src.verification.evidence import AGGREGATES, MINUTE_TOLERANCE, EvidenceIndex

NON_FACTUAL = ("interpretation", "prediction", "hypothetical")


def _res(claim: Claim, status: str, evidence: str, explanation: str) -> ClaimResult:
    return ClaimResult(claim_id=claim.claim_id, claim_text=claim.text_en or claim.claim_id,
                       claim_type=claim.claim_type, status=status, evidence=evidence,
                       explanation=explanation, evidence_event_ids=list(claim.evidence_event_ids))


# --------------------------------------------------------------------------
# Structured claim verification
# --------------------------------------------------------------------------
def verify_claim(claim: Claim, idx: EvidenceIndex) -> ClaimResult:
    """Verify ONE structured claim. Never raises: failures become ``unverifiable``."""
    try:
        return _verify(claim, idx)
    except Exception as exc:  # defensive: a broken claim must not crash the pipeline
        return _res(claim, "unverifiable", "n/a", f"Verification error: {exc}")


def _verify(claim: Claim, idx: EvidenceIndex) -> ClaimResult:
    missing = idx.missing_ids(claim.evidence_event_ids)
    if missing:
        return _res(claim, "unsupported", f"event ids {missing}",
                    f"Cited event id(s) {missing} do not exist in the validated data.")

    if claim.claim_type in NON_FACTUAL:
        cited = (f"{len(claim.evidence_event_ids)} cited event(s)" if claim.evidence_event_ids
                 else "no event ids cited")
        return _res(claim, "labelled", cited,
                    f"Labelled as {claim.claim_type}; not presented as fact. All cited event ids exist.")

    check = claim.check
    p = claim.params
    if check is None:
        return _res(claim, "unverifiable", "none",
                    "Factual statement without a check type or evidence: cannot be verified automatically.")

    if check == "event_exists":
        e = idx.event(p.get("event_id", ""))
        if e is None:
            return _res(claim, "unsupported", f"event {p.get('event_id')}", "No such event in the data.")
        problems, compared = [], []
        if "minute" in p:
            compared.append("minute")
            if abs(float(p["minute"]) - e.minute) > MINUTE_TOLERANCE:
                problems.append(f"minute {p['minute']:.2f} vs {e.minute:.2f}")
        for key, actual in (("team_id", e.team_id), ("player_id", e.player_id),
                            ("event_type", e.event_type), ("outcome", e.outcome)):
            if key in p and p[key] is not None:
                compared.append(key)
                if p[key] != actual:
                    problems.append(f"{key} {p[key]!r} vs {actual!r}")
        ev = f"{e.event_id}: {e.clock} {e.event_type} by {e.team_id}/{e.player_id}"
        if problems:
            return _res(claim, "contradicted", ev, "Mismatch: " + "; ".join(problems) + ".")
        return _res(claim, "verified", ev, f"Matches the source event on: {', '.join(compared) or 'existence'}.")

    if check == "count":
        kw = {k: p[k] for k in ("team_id", "event_type", "zone", "lane", "outcome", "cause", "start", "end")
              if p.get(k) is not None}
        actual = idx.count(**kw)
        want = p.get("expected")
        op = p.get("op", "==")
        ok = {"==": actual == want, ">=": actual >= want, "<=": actual <= want,
              "approx": abs(actual - want) <= p.get("tol", 1)}.get(op, False)
        ev = f"count({kw}) = {actual}  [{AGGREGATES['count']}]"
        if ok:
            return _res(claim, "verified", ev, f"Recomputed {actual}; claim says {op} {want}.")
        return _res(claim, "contradicted", ev, f"Recomputed {actual}; claim says {op} {want}.")

    if check == "score":
        minute = p.get("minute")
        h, a = idx.score(minute)
        ev = f"score at {'full time' if minute is None else str(round(minute, 1)) + chr(39)} = {h}-{a}"
        contradiction = idx.score_contradiction() if minute is None else None
        if contradiction:
            return _res(claim, "unverifiable", ev, f"Source data contradicts itself: {contradiction}.")
        if (h, a) == (p.get("home"), p.get("away")):
            return _res(claim, "verified", ev, "Score recomputed from goal events matches.")
        return _res(claim, "contradicted", ev,
                    f"Goal events give {h}-{a}; claim says {p.get('home')}-{p.get('away')}.")

    if check == "metric":
        val = idx.metric(p.get("name", ""), p.get("team_id", ""), p.get("start"), p.get("end"))
        if val is None:
            return _res(claim, "unverifiable", f"metric {p.get('name')}", "Unknown or incomputable metric.")
        tol = p.get("tol", 0.01)
        ev = f"{p['name']}({p.get('team_id')}, {p.get('start')}-{p.get('end')}) = {val:.3f}  [{AGGREGATES['metric']}]"
        if abs(val - float(p["expected"])) <= tol:
            return _res(claim, "verified", ev, f"Recomputed {val:.3f}; claim says {p['expected']}.")
        return _res(claim, "contradicted", ev, f"Recomputed {val:.3f}; claim says {p['expected']}.")

    if check == "window_stat":
        r = idx.window_stat(p["kind"], p["team_id"], p["start"], p["end"], p.get("lane"))
        if r is None:
            return _res(claim, "unsupported", f"{p['kind']} {p['start']}-{p['end']}", "Rule cannot be evaluated here.")
        ev = f"{p['kind']}: observed={r['observed']:.0f}, expected={r['expected']:.2f}, p={r['p_value']:.2e}"
        obs_ok = int(r["observed"]) == int(p["observed"])
        import math
        p_ok = True
        if "p_value" in p and r["p_value"] > 0 and p["p_value"] > 0:
            p_ok = abs(math.log10(r["p_value"]) - math.log10(p["p_value"])) < 0.05
        if obs_ok and p_ok:
            return _res(claim, "verified", ev, "Re-running the detection rule reproduces the observed count and p-value.")
        return _res(claim, "contradicted", ev, "Re-running the detection rule gives a different count or p-value.")

    if check == "player_team":
        pl = idx.match.players().get(p.get("player_id", ""))
        ev = f"roster lookup {p.get('player_id')}"
        if pl is None:
            return _res(claim, "unsupported", ev, "Player is not on either roster.")
        if pl.team_id == p.get("team_id"):
            return _res(claim, "verified", ev, f"{pl.name} is on {idx.match.team_name(pl.team_id)}.")
        return _res(claim, "contradicted", ev,
                    f"{pl.name} plays for {idx.match.team_name(pl.team_id)}, not {idx.match.team_name(p.get('team_id', ''))}.")

    return _res(claim, "unverifiable", f"check={check}", "Unknown check type.")


def verify_claims(claims: list[Claim], idx: EvidenceIndex) -> list[ClaimResult]:
    return [verify_claim(c, idx) for c in claims]


def all_passed(results: list[ClaimResult]) -> bool:
    return all(r.passed for r in results)


# --------------------------------------------------------------------------
# Free-text extraction and checking
# --------------------------------------------------------------------------
_EVENT_ID = re.compile(r"\b[A-Z0-9]+-E\d{4}\b")
_CLOCK = re.compile(r"\b(\d{1,3}):(\d{2})\b")
_MIN = re.compile(r"(?:minute\s+|at\s+|in\s+the\s+)(\d{1,3})(?:'|th|st|nd|rd)?\b|(\d{1,3})'")
_SCORE = re.compile(r"\b(\d{1,2})\s*[-–:]\s*(\d{1,2})\b")
_SCORE_WORDS = re.compile(r"\b(score|scoreline|scored|lead|leads|led|ahead|behind|level|win|won|draw|final|result)\b", re.I)
_COUNT = re.compile(r"\b(\d+)\s+(turnovers?|shots?|goals?|passes|interceptions?|tackles?)\b", re.I)
_RANGE = re.compile(r"(?:between|from)\s+(?:minute\s+)?(\d{1,3})'?\s*(?:and|to|-|–)\s*(?:minute\s+)?(\d{1,3})'?", re.I)
_RANGE2 = re.compile(r"\b(\d{1,3})'\s*[-–]\s*(\d{1,3})'")
_HEDGE = re.compile(r"\b(may|might|could|likely|suggests?|perhaps|probably|possibly|seems?|appears?)\b", re.I)
_HYPO = re.compile(r"\b(would|if|had .* instead|what-if|hypothetical|alternative)\b", re.I)
_PREDICT = re.compile(r"\b(will|expect(?:ed)?|forecast|predict(?:ed)?|going to)\b", re.I)
_APPROX = re.compile(r"\b(about|around|roughly|approximately|nearly|almost)\s*$", re.I)
_ATLEAST = re.compile(r"\b(at least|more than|over)\s*$", re.I)

_TYPE_MAP = {"turnover": "turnover", "shot": "shot", "goal": "goal", "pass": "pass",
             "passes": "pass", "interception": "interception", "tackle": "tackle"}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _teams_in(sentence: str, match: Match) -> list[str]:
    found = []
    low = sentence.lower()
    for t in (match.home, match.away):
        if t.name.lower() in low:
            found.append(t.team_id)
    return found


def extract_claims_from_sentence(sentence: str, match: Match, sid: str) -> list[Claim]:
    """Turn the checkable facts of ONE sentence into structured claims."""
    claims: list[Claim] = []
    teams = _teams_in(sentence, match)
    n = 0

    def new(**kw) -> Claim:
        nonlocal n
        n += 1
        return Claim(claim_id=f"{sid}.{n}", text_en=sentence, **kw)

    # 1. event ids (+ optional clock time, team, player)
    ids = _EVENT_ID.findall(sentence)
    clock = _CLOCK.search(sentence)
    for eid in ids:
        params: dict = {"event_id": eid}
        if clock and len(ids) == 1:
            params["minute"] = int(clock.group(1)) + int(clock.group(2)) / 60.0
        if len(teams) == 1 and len(ids) == 1:
            params["team_id"] = teams[0]
        claims.append(new(check="event_exists", params=params, evidence_event_ids=[]))

    # 2. players: roster consistency and invented names
    roster = match.players()
    for pl in roster.values():
        if pl.name in sentence and len(teams) == 1:
            claims.append(new(check="player_team", params={"player_id": pl.player_id, "team_id": teams[0]}))
    known_names = {pl.name for pl in roster.values()}
    for m in re.finditer(r"\b([A-Z][a-z]+) ([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", sentence):
        if m.group(1) in KNOWN_FIRST_NAMES and m.group(0) not in known_names:
            claims.append(new(check="player_team", params={"player_id": f"UNKNOWN::{m.group(0)}", "team_id": ""}))

    # 3. score
    if _SCORE_WORDS.search(sentence):
        stripped = _CLOCK.sub("", _RANGE2.sub("", sentence))
        sm = _SCORE.search(stripped)
        if sm and int(sm.group(1)) <= 12 and int(sm.group(2)) <= 12:
            minute = None
            mm = _CLOCK.search(sentence)
            if mm:
                minute = int(mm.group(1)) + int(mm.group(2)) / 60.0
            else:
                m2 = re.search(r"(?:minute\s+|\bat\s+|\bby\s+)(\d{1,3})\b|\b(\d{1,3})'(?!\s*[-–])", sentence, re.I)
                if m2:
                    minute = float(m2.group(1) or m2.group(2))
            a, b = int(sm.group(1)), int(sm.group(2))
            # orientation: if away team name appears before home team name, swap
            low = sentence.lower()
            hi, ai = low.find(match.home.name.lower()), low.find(match.away.name.lower())
            if hi >= 0 and ai >= 0 and ai < hi:
                a, b = b, a
            claims.append(new(check="score", params={"minute": minute, "home": a, "away": b}))

    # 4. counts
    rng = _RANGE.search(sentence) or _RANGE2.search(sentence)
    for cm in _COUNT.finditer(sentence):
        word = cm.group(2).lower().rstrip("s") if cm.group(2).lower() != "passes" else "pass"
        etype = _TYPE_MAP.get(word) or _TYPE_MAP.get(cm.group(2).lower())
        if etype is None:
            continue
        prefix = sentence[: cm.start()]
        op = "approx" if _APPROX.search(prefix) else (">=" if _ATLEAST.search(prefix) else "==")
        params = {"event_type": etype, "expected": int(cm.group(1)), "op": op, "tol": 1}
        if len(teams) == 1:
            params["team_id"] = teams[0]
        elif len(teams) > 1:
            continue  # ambiguous: leave as unverifiable
        if rng:
            params["start"], params["end"] = float(rng.group(1)), float(rng.group(2))
        claims.append(new(check="count", params=params))

    # 5. non-factual labels
    if not claims:
        if _HYPO.search(sentence):
            claims.append(new(claim_type="hypothetical"))
        elif _PREDICT.search(sentence):
            claims.append(new(claim_type="prediction"))
        elif _HEDGE.search(sentence):
            claims.append(new(claim_type="interpretation"))
        else:
            claims.append(new(claim_type="factual", check=None))
    return claims


def extract_claims_from_text(text: str, match: Match) -> list[tuple[str, list[Claim]]]:
    return [(s, extract_claims_from_sentence(s, match, f"T{i + 1}")) for i, s in enumerate(_split_sentences(text))]


def check_text(text: str, match: Match, events: list[Event]) -> dict:
    """Verify free text. Returns results per claim, a revised text and a summary."""
    idx = EvidenceIndex(match, events)
    if not text or not text.strip():
        return {"results": [], "revised_text": "", "summary": {"total": 0}, "ok": True, "sentences": []}
    results: list[ClaimResult] = []
    revised: list[str] = []
    per_sentence = []
    for sentence, claims in extract_claims_from_text(text, match):
        rs = [verify_claim(c, idx) for c in claims]
        results.extend(rs)
        bad = [r for r in rs if r.status in ("contradicted", "unsupported")]
        unver = [r for r in rs if r.status == "unverifiable"]
        if bad:
            revised.append("[removed by TrustTrace: " + "; ".join(r.explanation for r in bad)[:160] + "]")
            state = "removed"
        elif unver:
            revised.append(sentence + " [unverified]")
            state = "flagged"
        else:
            revised.append(sentence)
            state = "kept"
        per_sentence.append({"sentence": sentence, "state": state, "claim_ids": [c.claim_id for c in claims]})
    summary = {"total": len(results)}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    return {"results": results, "revised_text": " ".join(revised), "summary": summary,
            "ok": all_passed(results), "sentences": per_sentence}


# --------------------------------------------------------------------------
# Token preservation (used for translations)
# --------------------------------------------------------------------------
def protected_tokens(text: str, match: Match) -> set[str]:
    """Numbers, event ids and names that must survive translation unchanged."""
    toks = set(re.findall(r"\d+(?::\d{2})?", text))
    toks |= set(_EVENT_ID.findall(text))
    for t in (match.home, match.away):
        if t.name in text:
            toks.add(t.name)
        for pl in t.players:
            if pl.name in text:
                toks.add(pl.name)
    return toks


def preserved(source: str, translated: str, match: Match) -> tuple[bool, list[str]]:
    """True if every protected token of ``source`` also appears in ``translated``."""
    numbers_in_translation = set(re.findall(r"\d+(?::\d{2})?", translated))
    missing = []
    for t in sorted(protected_tokens(source, match)):
        if re.fullmatch(r"\d+(?::\d{2})?", t):
            if t not in numbers_in_translation:  # whole-number comparison, not substring
                missing.append(t)
        elif t not in translated:
            missing.append(t)
    return (not missing, missing)


_NUMBER = re.compile(r"\d+(?:[.:]\d+)*(?:e-?\d+)?")


def foreign_tokens(story_text: str, allowed_texts: list[str], match: Match) -> list[str]:
    """Numbers, event ids and roster names in the story that appear in NONE of the verified texts.

    This catches invented numbers/ids/names in any language (including translations),
    without requiring a model to repeat every fact.
    """
    corpus = " ".join(allowed_texts)
    allowed_numbers = set(_NUMBER.findall(corpus))
    bad: list[str] = []
    for tok in _EVENT_ID.findall(story_text):
        if tok not in corpus:
            bad.append(tok)
    ids_removed = _EVENT_ID.sub(" ", story_text)
    for tok in _NUMBER.findall(ids_removed):
        if tok not in allowed_numbers and tok not in bad:
            bad.append(tok)
    known = {pl.name for t in (match.home, match.away) for pl in t.players}
    for m in re.finditer(r"\b([A-Z][a-z]+) ([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", story_text):
        if m.group(1) in KNOWN_FIRST_NAMES and m.group(0) not in known:
            bad.append(m.group(0))
    for name in known:
        if name in story_text and name not in corpus:
            bad.append(name)
    return bad
