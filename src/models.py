"""Shared data models for SHIFTCAST AI.

Everything that moves between modules (events, insights, graph data, claims,
scenarios, agent traces, stories) is defined here as a pydantic model, so the
agents exchange *typed, structured* objects rather than loose dictionaries.

COORDINATE SYSTEM (important for beginners)
-------------------------------------------
Every event uses TEAM-RELATIVE coordinates on a 0-100 x 0-100 pitch:
  * x = 0   is the team's OWN goal line, x = 100 is the OPPONENT goal line.
    So every team always "attacks towards x = 100".
  * y = 0..33 is the "left" lane, 33..67 "center", 67..100 "right"
    (left/right are from the team's own attacking direction).
For drawing both teams on one pitch the UI mirrors the away team
(see ``to_pitch`` in ``src/ui/components.py``).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
EVENT_TYPES = ("pass", "interception", "tackle", "turnover", "shot", "goal")
SHOT_OUTCOMES = ("goal", "saved", "off_target", "blocked")
PASS_OUTCOMES = ("success", "fail")
TURNOVER_CAUSES = ("failed_pass", "dispossessed")
PATTERN_KINDS = ("turnover_spike", "flank_overload", "shot_surge", "defensive_cluster")
INSIGHT_KINDS = PATTERN_KINDS + ("possession_shift",)

ZONES = ("defensive", "middle", "attacking")
LANES = ("left", "center", "right")


def zone_of(x: Optional[float]) -> Optional[str]:
    """Pitch third from a team-relative x coordinate."""
    if x is None:
        return None
    if x < 100 / 3:
        return "defensive"
    if x < 200 / 3:
        return "middle"
    return "attacking"


def lane_of(y: Optional[float]) -> Optional[str]:
    """Pitch lane (left / center / right) from a team-relative y coordinate."""
    if y is None:
        return None
    if y < 100 / 3:
        return "left"
    if y < 200 / 3:
        return "center"
    return "right"


# --------------------------------------------------------------------------
# Teams, players, events, matches
# --------------------------------------------------------------------------
class Player(BaseModel):
    player_id: str
    name: str
    team_id: str
    role: str = "MF"  # GK / DF / MF / FW


class Team(BaseModel):
    team_id: str
    name: str
    players: list[Player] = Field(default_factory=list)


class Event(BaseModel):
    event_id: str
    match_id: str
    minute: float  # decimal minutes since kick-off (e.g. 23.5 = 23:30)
    period: int  # 1 or 2
    team_id: str
    player_id: Optional[str] = None
    event_type: str
    x: Optional[float] = None
    y: Optional[float] = None
    end_x: Optional[float] = None
    end_y: Optional[float] = None
    outcome: Optional[str] = None  # pass: success/fail ; shot: goal/saved/off_target/blocked
    cause: Optional[str] = None  # turnover: failed_pass / dispossessed
    related_event_id: Optional[str] = None  # explicit link recorded in the data

    @property
    def zone(self) -> Optional[str]:
        return zone_of(self.x)

    @property
    def lane(self) -> Optional[str]:
        return lane_of(self.y)

    @property
    def clock(self) -> str:
        """Human readable match clock, e.g. ``23:41``."""
        total = int(round(self.minute * 60))
        return f"{total // 60:02d}:{total % 60:02d}"


class GroundTruthPattern(BaseModel):
    """A tactical pattern that the generator deliberately planted."""

    kind: str
    team_id: str
    start_min: float
    end_min: float
    lane: Optional[str] = None  # for flank_overload


class Match(BaseModel):
    match_id: str
    title: str
    home: Team
    away: Team
    seed: int
    events: list[Event] = Field(default_factory=list)
    synthetic: bool = True
    reported_score: Optional[tuple[int, int]] = None  # optional external scoreboard
    ground_truth: list[GroundTruthPattern] = Field(default_factory=list)
    notes: str = ""

    def team(self, team_id: str) -> Optional[Team]:
        for t in (self.home, self.away):
            if t.team_id == team_id:
                return t
        return None

    def team_name(self, team_id: str) -> str:
        t = self.team(team_id)
        return t.name if t else f"<unknown team {team_id}>"

    def opponent_id(self, team_id: str) -> str:
        return self.away.team_id if team_id == self.home.team_id else self.home.team_id

    def players(self) -> dict[str, Player]:
        return {p.player_id: p for t in (self.home, self.away) for p in t.players}

    def player_name(self, player_id: Optional[str]) -> str:
        if not player_id:
            return "unknown player"
        p = self.players().get(player_id)
        return p.name if p else f"<unknown player {player_id}>"

    def team_ids(self) -> set[str]:
        return {self.home.team_id, self.away.team_id}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
class ValidationIssue(BaseModel):
    code: str  # e.g. duplicate_id, invalid_minute, unknown_team ...
    severity: Literal["error", "warning"]
    event_id: Optional[str] = None
    message: str


class ValidationReport(BaseModel):
    total_input: int = 0
    accepted: int = 0
    rejected: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


# --------------------------------------------------------------------------
# Insights (turning points)
# --------------------------------------------------------------------------
class Insight(BaseModel):
    insight_id: str
    kind: str  # one of INSIGHT_KINDS
    title: str
    team_id: str
    start_min: float
    end_min: float
    event_ids: list[str]  # supporting events (source references)
    rule: str  # the rule / metric that triggered detection
    observed: float
    expected: float
    p_value: float
    evidence_strength: float  # heuristic 0..1 -- NOT a probability
    strength_formula: str = "min(1, -log10(p_value) / 6)"
    explanation: str
    caveats: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)  # e.g. {"lane": "left"}
    exploratory: bool = False  # True for detectors that are not scored in evaluation


# --------------------------------------------------------------------------
# Impact graph
# --------------------------------------------------------------------------
RelationType = Literal["temporal", "statistical", "recorded_outcome"]


class GraphNode(BaseModel):
    node_id: str  # same as event_id
    label: str
    minute: float
    team_id: str
    event_type: str
    in_pattern: bool = False  # True if the event supports the insight
    x: float = 0.0  # layout position (minute)
    y: float = 0.0  # layout track


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: RelationType
    label: str
    reason: str  # why this connection was created
    strength: Optional[float] = None  # only for statistical edges
    caveat: str = ""


class GraphData(BaseModel):
    insight_id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    chain: list[str] = Field(default_factory=list)  # chronological node ids
    association: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Claims and verification (TrustTrace)
# --------------------------------------------------------------------------
ClaimType = Literal["factual", "interpretation", "prediction", "hypothetical"]
VerificationStatus = Literal[
    "verified",  # recomputed from source data and matches
    "contradicted",  # recomputed from source data and does NOT match
    "unsupported",  # refers to something that does not exist in the data
    "unverifiable",  # cannot be checked automatically -> flagged
    "labelled",  # interpretation / prediction / hypothetical, evidence references valid
]


class Claim(BaseModel):
    claim_id: str
    claim_type: ClaimType = "factual"
    check: Optional[str] = None  # event_exists / count / score / window_stat / metric
    params: dict[str, Any] = Field(default_factory=dict)
    evidence_event_ids: list[str] = Field(default_factory=list)
    text_en: str = ""
    text_ta: str = ""


class ClaimResult(BaseModel):
    claim_id: str
    claim_text: str
    claim_type: ClaimType
    status: VerificationStatus
    evidence: str  # what was compared (event ids or aggregate calculation)
    explanation: str
    evidence_event_ids: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status in ("verified", "labelled")


# --------------------------------------------------------------------------
# Scenarios (What-If Lab)
# --------------------------------------------------------------------------
class ScenarioParam(BaseModel):
    key: str
    label: str
    value: float
    minimum: float
    maximum: float
    step: float
    help: str = ""


class ScenarioMetric(BaseModel):
    metric: str
    actual: Optional[float] = None  # MEASURED from the event data (None if n/a)
    low: Optional[float] = None  # HYPOTHETICAL lower estimate
    high: Optional[float] = None  # HYPOTHETICAL upper estimate
    basis: str = ""  # formula / how the estimate was built


class ScenarioResult(BaseModel):
    scenario_id: str
    insight_id: str
    name: str
    action: str
    label: str = "HEURISTIC SCENARIO ANALYSIS - not a prediction of what would have happened"
    assumptions: list[str] = Field(default_factory=list)
    benefit: str = ""
    trade_off: str = ""
    metrics: list[ScenarioMetric] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    params: list[ScenarioParam] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Stories and pipeline
# --------------------------------------------------------------------------
class StorySentence(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class StoryDoc(BaseModel):
    insight_id: str
    mode: str  # fan / analyst / broadcast
    language: str  # en / ta
    text: str
    sentences: list[StorySentence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    verification: list[ClaimResult] = Field(default_factory=list)
    provider: str = "local"
    fallback_reason: Optional[str] = None
    graphics: list[str] = Field(default_factory=list)  # broadcast mode suggestions
    overlay_cues: list[dict[str, Any]] = Field(default_factory=list)
    all_verified: bool = True


class AgentTrace(BaseModel):
    """One log line of the agent pipeline: who ran, what came in, what went out."""

    agent: str
    status: Literal["ok", "fallback", "error"]
    duration_ms: float
    input_summary: str
    output_summary: str
    handoff_to: Optional[str] = None
    error: Optional[str] = None
    source_event_ids: int = 0  # number of source event ids carried by the output


class InsightBundle(BaseModel):
    """Everything the pipeline knows about ONE insight (the shared structured state)."""

    insight: Insight
    graph: Optional[GraphData] = None
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    fact_sheet: list[Claim] = Field(default_factory=list)
    fact_verification: list[ClaimResult] = Field(default_factory=list)
    stories: dict[str, StoryDoc] = Field(default_factory=dict)  # key "mode|lang"


class PipelineResult(BaseModel):
    match_id: str
    synthetic: bool = True
    n_events: int = 0
    bundles: list[InsightBundle] = Field(default_factory=list)
    traces: list[AgentTrace] = Field(default_factory=list)
    provenance_ok: bool = True
    provenance_notes: list[str] = Field(default_factory=list)
