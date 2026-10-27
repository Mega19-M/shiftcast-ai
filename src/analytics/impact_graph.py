"""Match Impact Graph: connect related events and say WHY they are connected.

Three kinds of connection are kept strictly separate (an honest graph never
turns "A happened before B" into "A caused B"):

* ``recorded_outcome`` - the data itself links the two events through
  ``related_event_id`` (e.g. a goal that references its shot, an interception
  that references the turnover it followed). This is a *recorded fact*.
* ``temporal``         - B is the next selected event after A in time. Order only.
* ``statistical``      - B (a shot) happened within 60 s after a pattern event A,
  and shots in the insight window follow such events more often than shots
  elsewhere in the match. This is an *association*, never proof of causation.
"""
from __future__ import annotations

from typing import Callable, Optional

from src.analytics.metrics import filter_events
from src.models import Event, GraphData, GraphEdge, GraphNode, Insight, Match

MAX_NODES = 40
TEMPORAL_GAP_SECONDS = 120
SHOT_FOLLOW_SECONDS = 60

_ROW = {"pass": 0, "turnover": 1, "interception": 2, "tackle": 2, "shot": 3, "goal": 4}
ROW_LABELS = {0: "pass", 1: "turnover", 2: "recovery", 3: "shot", 4: "goal"}


def describe_event(match: Match, e: Event) -> str:
    """Short human readable label, e.g. ``23:41 turnover - Varek (Harbour City)``."""
    who = match.player_name(e.player_id).split(" ")[-1] if e.player_id else "?"
    extra = ""
    if e.event_type == "shot" and e.outcome:
        extra = f" [{e.outcome}]"
    elif e.event_type == "pass" and e.outcome == "fail":
        extra = " [failed]"
    elif e.event_type == "turnover" and e.cause:
        extra = f" [{e.cause.replace('_', ' ')}]"
    return f"{e.clock} {e.event_type}{extra} - {who} ({match.team_name(e.team_id)})"


def support_selector(insight: Insight) -> Callable[[Event], bool]:
    """Predicate for 'pattern' events of an insight (same logic as the detector)."""
    t = insight.team_id
    k = insight.kind
    if k == "turnover_spike":
        return lambda e: e.team_id == t and e.event_type == "turnover"
    if k == "defensive_cluster":
        return lambda e: e.team_id == t and e.event_type == "turnover" and e.zone == "defensive"
    if k == "flank_overload":
        lane = insight.detail.get("lane")
        return lambda e: (e.team_id == t and e.event_type in ("pass", "shot") and e.zone == "attacking"
                          and e.lane == lane)
    if k == "shot_surge":
        return lambda e: e.team_id == t and e.event_type in ("pass", "shot") and e.x is not None and e.x >= 55
    return lambda e: e.team_id == t


def target_team(insight: Insight, match: Match) -> str:
    """Whose shots do we associate with the pattern? The opponent's after our turnovers."""
    if insight.kind in ("turnover_spike", "defensive_cluster"):
        return match.opponent_id(insight.team_id)
    return insight.team_id


def _follow_rate(events: list[Event], sel: Callable[[Event], bool], team: str, start: float, end: float,
                 inside: bool) -> tuple[int, int, list[tuple[Event, Event]]]:
    """(# shots preceded by a pattern event within 60 s, # shots, pairs) inside/outside the window."""
    shots = [e for e in events if e.team_id == team and e.event_type == "shot"
             and ((start <= e.minute <= end) == inside)]
    pairs: list[tuple[Event, Event]] = []
    prior = [e for e in events if sel(e)]
    for s in shots:
        cands = [p for p in prior if 0 < (s.minute - p.minute) * 60 <= SHOT_FOLLOW_SECONDS and p.event_id != s.event_id]
        if cands:
            pairs.append((cands[-1], s))
    return len(pairs), len(shots), pairs


def build_impact_graph(insight: Insight, events: list[Event], match: Match, max_nodes: int = MAX_NODES) -> GraphData:
    """Build the graph for one insight (pure function, deterministic)."""
    by_id = {e.event_id: e for e in events}
    support_ids = [i for i in insight.event_ids if i in by_id]
    sel = support_selector(insight)
    tgt = target_team(insight, match)

    # ---- choose nodes ------------------------------------------------------
    key_events = [e for e in events if insight.start_min <= e.minute <= insight.end_min + 1.5
                  and e.event_type in ("shot", "goal")]
    chosen: dict[str, Event] = {i: by_id[i] for i in support_ids}
    for e in key_events:
        chosen[e.event_id] = e
    # pull in events that the chosen ones explicitly reference (so recorded links are visible)
    for e in list(chosen.values()):
        rid = e.related_event_id
        if rid and rid in by_id:
            chosen.setdefault(rid, by_id[rid])
    nodes_ev = sorted(chosen.values(), key=lambda e: (e.minute, e.event_id))
    if len(nodes_ev) > max_nodes:
        must = [e for e in nodes_ev if e.event_type in ("shot", "goal")]
        rest = [e for e in nodes_ev if e.event_type not in ("shot", "goal")]
        room = max(0, max_nodes - len(must))
        if room and rest:
            step = max(1, len(rest) // room)
            rest = rest[::step][:room]
        else:
            rest = []
        nodes_ev = sorted(must[:max_nodes] + rest, key=lambda e: (e.minute, e.event_id))
    keep = {e.event_id for e in nodes_ev}

    nodes = [
        GraphNode(
            node_id=e.event_id, label=describe_event(match, e), minute=e.minute, team_id=e.team_id,
            event_type=e.event_type, in_pattern=e.event_id in set(support_ids), x=e.minute,
            y=float(_ROW.get(e.event_type, 0) + (0 if e.team_id == insight.team_id else 6)),
        )
        for e in nodes_ev
    ]

    edges: list[GraphEdge] = []
    linked: set[tuple[str, str]] = set()

    # ---- recorded outcome edges -------------------------------------------
    for e in nodes_ev:
        rid = e.related_event_id
        if rid and rid in keep:
            src = by_id[rid]
            label = {
                ("shot", "goal"): "shot scored (recorded)",
                ("turnover", "interception"): "ball won by interception (recorded)",
                ("turnover", "tackle"): "ball won by tackle (recorded)",
                ("pass", "turnover"): "failed pass became turnover (recorded)",
            }.get((src.event_type, e.event_type), "recorded link")
            edges.append(GraphEdge(
                source=src.event_id, target=e.event_id, relation="recorded_outcome", label=label,
                reason=f"The data itself links {e.event_id} to {src.event_id} through related_event_id.",
                caveat="A recorded link states what the data says followed; it does not explain tactical cause.",
            ))
            linked.add((src.event_id, e.event_id))

    # ---- temporal edges ----------------------------------------------------
    for a, b in zip(nodes_ev, nodes_ev[1:]):
        dt = (b.minute - a.minute) * 60
        if (a.event_id, b.event_id) in linked or dt > TEMPORAL_GAP_SECONDS:
            continue
        edges.append(GraphEdge(
            source=a.event_id, target=b.event_id, relation="temporal", label=f"+{dt:.0f}s",
            reason=f"{b.event_id} is the next selected event, {dt:.0f} seconds after {a.event_id}.",
            caveat="Time order only. Coming first does not mean causing.",
        ))

    # ---- statistical edges ---------------------------------------------------
    k_in, n_in, pairs_in = _follow_rate(events, sel, tgt, insight.start_min, insight.end_min, True)
    k_out, n_out, _ = _follow_rate(events, sel, tgt, insight.start_min, insight.end_min, False)
    rate_in = (k_in / n_in) if n_in else None
    rate_out = (k_out / n_out) if n_out else None
    diff = (rate_in - rate_out) if (rate_in is not None and rate_out is not None) else None
    association = {
        "target_team": tgt,
        "shots_in_window": n_in, "shots_in_window_following_pattern_event": k_in,
        "shots_outside_window": n_out, "shots_outside_following_pattern_event": k_out,
        "rate_in_window": rate_in, "rate_outside_window": rate_out, "difference": diff,
        "definition": f"A shot 'follows' a pattern event if it occurs 1-{SHOT_FOLLOW_SECONDS}s after one.",
        "note": "Association only. Small counts; no control for shot quality, opponent or match state.",
    }
    for src, dst in pairs_in:
        if src.event_id in keep and dst.event_id in keep:
            edges.append(GraphEdge(
                source=src.event_id, target=dst.event_id, relation="statistical",
                label="pattern -> shot (association)",
                reason=(f"{dst.event_id} is a shot by {match.team_name(tgt)} {(dst.minute - src.minute) * 60:.0f}s after a "
                        f"pattern event. In the window {k_in}/{n_in} such shots follow a pattern event vs "
                        f"{k_out}/{n_out} elsewhere."),
                strength=diff,
                caveat="Statistical association, not proven causation.",
            ))

    return GraphData(insight_id=insight.insight_id, nodes=nodes, edges=edges,
                     chain=[n.node_id for n in nodes], association=association)


def chain_table(graph: GraphData, events: list[Event], match: Match) -> list[dict]:
    """Chronological rows for the UI table."""
    by_id = {e.event_id: e for e in events}
    rows = []
    for nid in graph.chain:
        e = by_id.get(nid)
        if e:
            rows.append({"event_id": nid, "clock": e.clock, "team": match.team_name(e.team_id),
                         "type": e.event_type, "player": match.player_name(e.player_id),
                         "detail": e.outcome or e.cause or ""})
    return rows
