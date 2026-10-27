"""Beginner-friendly health check. Needs NO extra packages beyond requirements.txt.

    python scripts/run_checks.py

It (1) compiles every Python file, (2) imports every module (UI modules are
skipped with a note if Streamlit/Plotly are not installed), (3) runs the whole
five-agent pipeline on every example match and (4) runs the validation and
TrustTrace regression sets. Exit code 0 = everything passed.
"""
from __future__ import annotations

import compileall
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


def main() -> int:
    # 1. syntax ---------------------------------------------------------------------
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1) and compileall.compile_file(str(ROOT / "app.py"), quiet=1) \
        and compileall.compile_file(str(ROOT / "config.py"), quiet=1)
    check("python syntax (compileall)", bool(ok))

    # 2. imports ----------------------------------------------------------------------
    ui_ok = True
    try:
        import streamlit, plotly  # noqa: F401
    except Exception:
        ui_ok = False
    for path in sorted((ROOT / "src").rglob("*.py")):
        mod = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        if mod.startswith("src.ui") and not ui_ok:
            print(f"[SKIP] import {mod} (streamlit/plotly not installed)")
            continue
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as exc:
            check(f"import {mod}", False, f"{type(exc).__name__}: {exc}")

    # 3. pipeline smoke test -------------------------------------------------------------
    from src.agents.orchestrator import Orchestrator
    from src.data.generator import PRESETS, load_preset
    from src.data.validation import validate_events

    orch = Orchestrator()
    for name in PRESETS:
        m = load_preset(name)
        events, rep = validate_events([e.model_dump() for e in m.events], m)
        res = orch.run(m, events)
        orch.generate_all_stories(res, m, events, languages=("en", "ta"))
        stories = [s for b in res.bundles for s in b.stories.values()]
        bad = [s for s in stories if not s.all_verified]
        check(f"pipeline on {name}", rep.ok and res.provenance_ok and not bad and
              not any(t.status == "error" and t.agent != "evidence" for t in res.traces),
              f"{len(res.bundles)} insights, {len(stories)} stories, {len(bad)} failed verification")

    # 4. regression sets ---------------------------------------------------------------------
    from src.analytics.evaluation import evaluate_trusttrace, evaluate_validation

    v = evaluate_validation(5)
    check("validator finds every injected fault", v["all_found"])
    t = evaluate_trusttrace(3)
    check("TrustTrace catches all false statements", t["false_caught"] == t["n_false"] and t["true_passed"] == t["n_true"],
          f"{t['false_caught']}/{t['n_false']} false caught, {t['true_passed']}/{t['n_true']} true accepted")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
