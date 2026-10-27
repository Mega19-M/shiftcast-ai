# Architecture
Layers: `src/data` (generate, load, validate) → `src/analytics` (metrics, detectors, graph, DNA, evaluation) → `src/scenarios` → `src/verification` (evidence index, claim checker) → `src/storytelling` (fact sheet, templates EN/TA, recap) → `src/providers` (local, Azure) → `src/agents` (five agents + orchestrator) → `src/reporting` (exports) → `src/ui` + `app.py`.
Key contracts: Pydantic models in `src/models.py`; claims carry `evidence_event_ids`; stories cite claim ids; `check_provenance` ensures every output id exists in the source events.
Failure policy: validation drops/flags bad rows; agent exceptions become error traces; provider errors/malformed/unverified output fall back to local templates with `fallback_reason`.
