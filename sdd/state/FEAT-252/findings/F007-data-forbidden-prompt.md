---
id: F007
query_id: Q007
type: grep
intent: Locate the bots/data.py forbidden-pattern list to promote (Q4)
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F007 — bots/data.py forbidden patterns are prompt-layer prose (promotable)

## Summary
The forbidden data-IO patterns the brainstorm wants promoted (Q4) live as
**prose inside a system-prompt string** in `bots/data.py` (~lines 296-300):
`pd.read_csv/read_excel/read_json/read_parquet`, `open(...)`,
`pathlib.Path().read_*`, `glob`, `os.listdir`, etc. They are guidance only — not
deterministically enforced. (`pd.read_csv` at line 2960 is the catalog loader
itself, the sanctioned path.)

## Citations
- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 296-300
  symbol: `forbidden-patterns (system prompt prose)`
  excerpt: |
    The following patterns are **forbidden** — even if they look ...
    • pd.read_csv / read_excel / read_json / read_parquet / ...
    • open(...), pathlib.Path(...).read_*, glob, os.listdir, ...

## Notes
Confirms Q4: promotion target exists and is prompt-only today. The committed
denylist (F002) covers some of these via BLOCKED_NAMES (open) but not the
pandas read_* family.
