# Demo script (about 4 minutes)
1. **Match Center** (0:00) — pick *demo-1*; point at the DEMO / SYNTHETIC DATA badge; press Play, then Pause and Step.
2. **Turning points** (0:40) — open the first insight: rule, observed vs expected, p-value, strength labelled heuristic, caveats, evidence ids.
3. **Impact Graph** (1:10) — show the three edge types; say clearly it never claims causation.
4. **What-If Lab** (1:40) — two alternatives; note "heuristic" label and the measured vs hypothetical columns.
5. **Story Studio** (2:10) — FAN, then ANALYST, then BROADCAST; switch to Tamil; show the verification table (every claim passed).
6. **TrustTrace** (3:00) — paste a false sentence ("… scored 9 goals"); it is rejected with the reason.
7. **Evaluation** (3:20) — run held-out evaluation; be upfront: ~0.53 precision / 0.73 recall on synthetic data.
8. **Export** (3:45) — download the JSON report and overlay cues.
Fallback if the UI misbehaves: `python scripts/run_checks.py` and show `data/sample_summary_demo-1.txt`.
