"""Reproducible synthetic match-event generator.

IMPORTANT: everything produced here is FICTIONAL. Teams, players and events are
randomly generated from a seed. Nothing here is real Premier League data.

How it works (simple version)
-----------------------------
We simulate a possession-based game as a tiny state machine:

  * one team has the ball at a team-relative position (x, y);
  * each step it passes, shoots (only near the opponent goal), or loses the ball;
  * losing the ball produces a "turnover" event for the loser followed by a
    recovery event ("interception" or "tackle") for the opponent;
  * a shot may become a "goal" event.

On top of this baseline we can plant TACTICAL PATTERNS inside a time window
(e.g. "Team A attacks mostly down the left flank between minute 30 and 40").
The planted patterns are stored in ``Match.ground_truth`` so the detectors can
be scored later (precision / recall) on data where the right answer is known.

The same seed always gives exactly the same match (Python's ``random.Random``
is deterministic for a given seed).
"""
from __future__ import annotations

import random
from typing import Optional

import config
from src.models import Event, GroundTruthPattern, Match, Player, Team

# --------------------------------------------------------------------------
# Fictional teams and players
# --------------------------------------------------------------------------
TEAM_POOL = {
    "HBC": "Harbour City",
    "NGU": "Northgate United",
    "RSR": "Riverside Rovers",
    "CPK": "Castle Park FC",
}

_FIRST = [
    "Aldo", "Bram", "Cael", "Dario", "Emre", "Finn", "Goran", "Hale", "Ivo", "Jonas", "Kian",
    "Lars", "Milo", "Niko", "Orin", "Pavel", "Quin", "Rafa", "Soren", "Tomas", "Ugo", "Vik",
    "Wren", "Xavi", "Yann", "Zane", "Arlo", "Beck", "Cory", "Dane", "Eero", "Fabi", "Gus",
    "Hugo", "Ilan", "Joss", "Kemal", "Leif", "Marek", "Nils", "Otto", "Pepe", "Remy", "Sven",
]
_LAST = [
    "Varek", "Moltane", "Brissot", "Haldane", "Quillon", "Dravic", "Ostrand", "Peveril", "Karsten",
    "Lindqvist", "Marrow", "Nevison", "Okoro-Vale", "Pryce", "Rennick", "Saltoun", "Thorne",
    "Umbra", "Vasseur", "Wexley", "Yardley", "Zeller", "Ashby", "Bexley", "Corrin", "Delmar",
    "Esker", "Farrow", "Gaunt", "Hollin", "Isler", "Jarrow", "Kestrel", "Lorne", "Mercer",
    "Norwin", "Ormond", "Pallis", "Roake", "Stenner", "Tarrant", "Ulven", "Voss", "Wrenfield",
]
_ROLES = ["GK", "DF", "DF", "DF", "DF", "MF", "MF", "MF", "MF", "FW", "FW"]

# How likely each role is to be involved when the ball is in a pitch third.
_ROLE_WEIGHTS = {
    "defensive": {"GK": 1.0, "DF": 6.0, "MF": 2.0, "FW": 0.2},
    "middle": {"GK": 0.05, "DF": 1.5, "MF": 6.0, "FW": 1.5},
    "attacking": {"GK": 0.0, "DF": 0.3, "MF": 2.0, "FW": 6.0},
}


def build_team(key: str) -> Team:
    """Create a fictional team with 11 stable players (same every call)."""
    if key not in TEAM_POOL:
        raise ValueError(f"Unknown team key {key!r}. Choose from {sorted(TEAM_POOL)}")
    k = sorted(TEAM_POOL).index(key)
    players = []
    for i, role in enumerate(_ROLES):
        idx = k * 11 + i
        players.append(
            Player(
                player_id=f"{key}_{i + 1:02d}",
                name=f"{_FIRST[idx % len(_FIRST)]} {_LAST[idx % len(_LAST)]}",
                team_id=key,
                role=role,
            )
        )
    return Team(team_id=key, name=TEAM_POOL[key], players=players)


# --------------------------------------------------------------------------
# Seeded example matches shown in the app
# --------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "demo-1": {
        "title": "Harbour City vs Northgate United (synthetic demo 1)",
        "seed": 11, "home": "HBC", "away": "NGU",
        "patterns": [
            {"kind": "flank_overload", "side": "home", "start": 28, "end": 38, "lane": "left"},
            {"kind": "turnover_spike", "side": "away", "start": 52, "end": 67},
            {"kind": "shot_surge", "side": "home", "start": 70, "end": 85},
        ],
    },
    "demo-2": {
        "title": "Riverside Rovers vs Castle Park FC (synthetic demo 2)",
        "seed": 23, "home": "RSR", "away": "CPK",
        "patterns": [
            {"kind": "defensive_cluster", "side": "home", "start": 15, "end": 27},
            {"kind": "flank_overload", "side": "away", "start": 48, "end": 58, "lane": "right"},
            {"kind": "turnover_spike", "side": "home", "start": 72, "end": 87},
        ],
    },
    "demo-3": {
        "title": "Northgate United vs Riverside Rovers (synthetic demo 3)",
        "seed": 37, "home": "NGU", "away": "RSR",
        "patterns": [
            {"kind": "shot_surge", "side": "away", "start": 20, "end": 35},
            {"kind": "defensive_cluster", "side": "away", "start": 58, "end": 70},
        ],
    },
    "control-1": {
        "title": "Castle Park FC vs Harbour City (synthetic control: no planted pattern)",
        "seed": 41, "home": "CPK", "away": "HBC",
        "patterns": [],
    },
}

# Effect sizes of planted patterns (used by the generator only).
FLANK_PROB = 0.80  # share of final-half passes sent into the chosen flank
TURNOVER_BOOST = 0.32  # added to the base probability of losing the ball
DEFENSIVE_BOOST = 0.45  # added in own defensive third
SHOT_PROB_SURGE = 0.45  # shot probability per action in the attacking half
BASE_LOSS = 0.15
BASE_SHOT = 0.085
MATCH_SECONDS = 90 * 60


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _active(patterns: list[dict], side_idx: int, minute: float, kind: str) -> Optional[dict]:
    """Return the planted pattern of ``kind`` active for this team at this minute."""
    for p in patterns:
        if p["kind"] == kind and p["side_idx"] == side_idx and p["start"] <= minute < p["end"]:
            return p
    return None


def generate_match(
    seed: int,
    home: str = "HBC",
    away: str = "NGU",
    patterns: Optional[list[dict]] = None,
    match_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Match:
    """Generate one full synthetic 90-minute match.

    ``patterns`` is a list of dicts like
    ``{"kind": "flank_overload", "side": "home", "start": 28, "end": 38, "lane": "left"}``.
    """
    rng = random.Random(seed)
    teams = [build_team(home), build_team(away)]
    match_id = match_id or f"M{seed:04d}"
    title = title or f"{teams[0].name} vs {teams[1].name} (synthetic, seed {seed})"
    pats = []
    for p in patterns or []:
        q = dict(p)
        q["side_idx"] = 0 if p["side"] == "home" else 1
        pats.append(q)

    events: list[Event] = []
    state = {"t": 0.0, "n": 0}

    def emit(side: int, etype: str, x, y, end_x=None, end_y=None, outcome=None,
             cause=None, related=None, player=None, gap=True) -> Optional[Event]:
        if gap:
            state["t"] += rng.uniform(2.0, 9.0)
        if state["t"] >= MATCH_SECONDS:
            return None
        state["n"] += 1
        minute = round(state["t"] / 60.0, 3)
        ev = Event(
            event_id=f"{match_id}-E{state['n']:04d}",
            match_id=match_id,
            minute=minute,
            period=1 if minute < 45 else 2,
            team_id=teams[side].team_id,
            player_id=player,
            event_type=etype,
            x=None if x is None else round(x, 1),
            y=None if y is None else round(y, 1),
            end_x=None if end_x is None else round(end_x, 1),
            end_y=None if end_y is None else round(end_y, 1),
            outcome=outcome,
            cause=cause,
            related_event_id=related,
        )
        events.append(ev)
        return ev

    def pick_player(side: int, x: float) -> str:
        zone = "defensive" if x < 33.3 else ("middle" if x < 66.7 else "attacking")
        w = _ROLE_WEIGHTS[zone]
        pl = teams[side].players
        return rng.choices(pl, weights=[w[p.role] + 1e-6 for p in pl], k=1)[0].player_id

    side = 0  # team in possession (0 = home, 1 = away)
    x, y = 50.0, 50.0
    safety = 0
    while state["t"] < MATCH_SECONDS and safety < 20000:
        safety += 1
        minute = state["t"] / 60.0
        spike = _active(pats, side, minute, "turnover_spike")
        dcl = _active(pats, side, minute, "defensive_cluster")
        flank = _active(pats, side, minute, "flank_overload")
        surge = _active(pats, side, minute, "shot_surge")

        # ---- shot? ------------------------------------------------------
        shot_zone = 55.0 if surge else 70.0
        p_shot = SHOT_PROB_SURGE if surge else BASE_SHOT
        if x >= shot_zone and rng.random() < p_shot:
            pl = pick_player(side, x)
            shot = emit(side, "shot", x, y, 100.0, rng.uniform(38, 62), player=pl,
                        outcome=None)
            if shot is None:
                break
            r = rng.random()
            outcome = "goal" if r < 0.12 else "saved" if r < 0.42 else "off_target" if r < 0.77 else "blocked"
            shot.outcome = outcome
            if outcome == "goal":
                emit(side, "goal", 100.0, shot.end_y, outcome="goal", related=shot.event_id,
                     player=pl, gap=True)
                side = 1 - side
                x, y = 50.0, 50.0  # kick-off for the conceding team
            else:
                side = 1 - side
                x, y = (8.0, 50.0) if outcome == "saved" else (6.0, 50.0) if outcome == "off_target" else (22.0, rng.uniform(20, 80))
            continue

        # ---- losing the ball? --------------------------------------------
        p_loss = BASE_LOSS
        if spike:
            p_loss += TURNOVER_BOOST
        if dcl and x < 33.3:
            p_loss += DEFENSIVE_BOOST
        if rng.random() < p_loss:
            pl = pick_player(side, x)
            if rng.random() < 0.7:  # failed pass
                ex = _clamp(x + rng.gauss(8, 10))
                ey = _clamp(y + rng.gauss(0, 18))
                ps = emit(side, "pass", x, y, ex, ey, outcome="fail", player=pl)
                if ps is None:
                    break
                to = emit(side, "turnover", x, y, cause="failed_pass", related=ps.event_id, player=pl, gap=True)
                if to is None:
                    break
                opp = 1 - side
                ox, oy = _clamp(100 - ex), _clamp(100 - ey)
                emit(opp, "interception", ox, oy, related=to.event_id, player=pick_player(opp, ox))
                side, x, y = opp, ox, oy
            else:  # dispossessed
                to = emit(side, "turnover", x, y, cause="dispossessed", player=pl)
                if to is None:
                    break
                opp = 1 - side
                ox, oy = _clamp(100 - x), _clamp(100 - y)
                emit(opp, "tackle", ox, oy, related=to.event_id, player=pick_player(opp, ox))
                side, x, y = opp, ox, oy
            continue

        # ---- successful pass ---------------------------------------------
        nx = _clamp(x + rng.gauss(6, 10))
        if flank and x >= 45 and rng.random() < FLANK_PROB:
            lane = flank.get("lane", "left")
            ny = rng.uniform(4, 28) if lane == "left" else rng.uniform(72, 96)
        else:
            ny = _clamp(y + rng.gauss(0, 20) - 0.35 * (y - 50.0))  # mean-reverting so play spreads across lanes
        # tiny pull back towards the centre so the ball does not stick in a corner
        if rng.random() < 0.08:
            nx = _clamp(nx - rng.uniform(10, 25))
        emit(side, "pass", x, y, nx, ny, outcome="success", player=pick_player(side, x))
        x, y = nx, ny

    return Match(
        match_id=match_id,
        title=title,
        home=teams[0],
        away=teams[1],
        seed=seed,
        events=events,
        synthetic=True,
        ground_truth=[
            GroundTruthPattern(
                kind=p["kind"], team_id=teams[p["side_idx"]].team_id,
                start_min=float(p["start"]), end_min=float(p["end"]), lane=p.get("lane"),
            )
            for p in pats
        ],
        notes="Synthetic data generated from a seed. Fictional teams and players.",
    )


def load_preset(name: str) -> Match:
    """Build one of the seeded example matches (``demo-1`` ... ``control-1``)."""
    if name not in PRESETS:
        raise KeyError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    p = PRESETS[name]
    return generate_match(p["seed"], p["home"], p["away"], p["patterns"], match_id=name.upper().replace("-", ""), title=p["title"])


# --------------------------------------------------------------------------
# Evaluation helpers: random planted patterns and control matches
# --------------------------------------------------------------------------
def random_patterns(seed: int, n: int = 3) -> list[dict]:
    """Choose ``n`` non-overlapping planted patterns for a seed (deterministic)."""
    rng = random.Random(seed * 7919 + 13)
    kinds = ["flank_overload", "turnover_spike", "shot_surge", "defensive_cluster"]
    out: list[dict] = []
    tries = 0
    while len(out) < n and tries < 200:
        tries += 1
        kind = rng.choice(kinds)
        side = rng.choice(["home", "away"])
        length = config.WINDOW_BY_KIND[kind]
        start = rng.randint(4, 90 - length - 4)
        end = start + length
        # keep windows far apart so detections are not ambiguous
        if any(abs(start - o["start"]) < 16 for o in out):
            continue
        item = {"kind": kind, "side": side, "start": start, "end": end}
        if kind == "flank_overload":
            item["lane"] = rng.choice(["left", "right"])
        out.append(item)
    return out


def generate_scenario_match(seed: int, patterns: Optional[list[dict]] = None) -> Match:
    """A match with KNOWN planted patterns (known answer) for scoring detectors."""
    pats = patterns if patterns is not None else random_patterns(seed)
    keys = sorted(TEAM_POOL)
    home, away = keys[seed % 4], keys[(seed + 1) % 4]
    return generate_match(seed, home, away, pats, match_id=f"S{seed:04d}")


def generate_control_match(seed: int) -> Match:
    """A match with NO planted pattern: every detection here is a false alarm."""
    keys = sorted(TEAM_POOL)
    return generate_match(seed, keys[seed % 4], keys[(seed + 2) % 4], [], match_id=f"C{seed:04d}")


# --------------------------------------------------------------------------
# Fault injection (for testing validation / TrustTrace robustness)
# --------------------------------------------------------------------------
def drop_events(events: list[Event], fraction: float, seed: int, types: tuple[str, ...] = ("shot",)) -> list[Event]:
    """Randomly remove a fraction of events of the given types (missing-event test case).

    Dropping a *shot* leaves its *goal* event pointing at a missing record.
    """
    rng = random.Random(seed)
    return [e for e in events if not (e.event_type in types and rng.random() < fraction)]


def inject_faults(match: Match, seed: int = 0) -> tuple[list[dict], dict[str, list[str]], Optional[tuple[int, int]]]:
    """Return (raw event dicts with deliberate faults, manifest of faults, wrong score).

    The manifest maps a validation issue code to the event ids that were broken,
    so tests can check that the validator really found every injected fault.
    """
    rng = random.Random(seed)
    raw = [e.model_dump() for e in match.events]
    manifest: dict[str, list[str]] = {}
    n = len(raw)
    if n < 60:
        return raw, manifest, None

    def mark(code: str, eid: str) -> None:
        manifest.setdefault(code, []).append(eid)

    idx = rng.sample(range(5, n - 5), 12)

    raw[idx[0]]["minute"] = -3.0
    mark("invalid_minute", raw[idx[0]]["event_id"])
    raw[idx[1]]["minute"] = 140.0
    mark("invalid_minute", raw[idx[1]]["event_id"])
    raw[idx[2]]["team_id"] = "ZZZ"
    mark("unknown_team", raw[idx[2]]["event_id"])
    raw[idx[3]]["player_id"] = "ZZZ_99"
    mark("unknown_player", raw[idx[3]]["event_id"])
    raw[idx[4]]["event_type"] = None
    mark("missing_field", raw[idx[4]]["event_id"])
    raw[idx[5]]["x"] = 140.0
    mark("coordinate_out_of_range", raw[idx[5]]["event_id"])
    raw[idx[6]]["x"] = None
    raw[idx[6]]["y"] = None
    raw[idx[6]]["event_type"] = "pass"
    mark("missing_coordinates", raw[idx[6]]["event_id"])
    raw[idx[7]]["period"] = 1 if raw[idx[7]]["minute"] >= 45 else 2
    mark("period_mismatch", raw[idx[7]]["event_id"])
    raw[idx[8]]["event_type"] = "dribble"
    mark("unknown_event_type", raw[idx[8]]["event_id"])

    # identical duplicate (harmless) and contradictory duplicate (same id, different content)
    dup = dict(raw[idx[9]])
    raw.append(dup)
    mark("duplicate_event_id", dup["event_id"])
    contra = dict(raw[idx[10]])
    contra["team_id"] = match.opponent_id(contra["team_id"]) if contra["team_id"] in match.team_ids() else contra["team_id"]
    contra["minute"] = round(contra["minute"] + 1.0, 3)
    raw.append(contra)
    mark("contradictory_duplicate", contra["event_id"])

    # a goal whose shot record is missing
    raw.append({
        "event_id": f"{match.match_id}-E9999", "match_id": match.match_id, "minute": 50.0, "period": 2,
        "team_id": match.home.team_id, "player_id": match.home.players[9].player_id, "event_type": "goal",
        "x": 100.0, "y": 50.0, "outcome": "goal", "related_event_id": f"{match.match_id}-E8888",
    })
    mark("goal_without_shot", f"{match.match_id}-E9999")

    # an event out of chronological order
    j = idx[11]
    raw[j]["minute"] = max(0.0, raw[j]["minute"] - 12.0)
    raw[j]["period"] = 1 if raw[j]["minute"] < 45 else 2
    mark("out_of_order", raw[j]["event_id"])

    goals = [e for e in match.events if e.event_type == "goal"]
    h = sum(1 for g in goals if g.team_id == match.home.team_id)
    a = len(goals) - h
    wrong_score = (h + 2, a)  # the scoreboard disagrees with the events
    return raw, manifest, wrong_score
