# data/

Everything in this folder is **synthetic**. Teams, players and events are fictional and generated from a random seed
by `src/data/generator.py`. No real Premier League data is included or used.

Regenerate the files below with `python scripts/generate_demo_data.py`:

| File | What it is |
|------|-----------|
| `demo-1.json`, `demo-2.json`, `demo-3.json`, `control-1.json` | The four seeded example matches (full `Match` objects, including the planted-pattern ground truth) |
| `*_events.csv` | The same events as flat CSV (you can open them in Excel) |
| `sample_report_demo-1.json` | A sample exported report (format `shiftcast-report/1.0`) |
| `sample_summary_demo-1.txt` | The matching plain-text match summary |
| `sample_overlay_cues_demo-1.json` | Broadcast overlay cues (format `shiftcast-overlay-cues/1.0`) |
