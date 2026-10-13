---
id: F011
query_id: Q005
type: git_log
intent: Recent commits on the planogram package (30 days)
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F011 — FEAT-645/646 landed 2026-10-08/09; presence.py untouched since TASK-4169

## Summary

25 commits in the last 30 days on `planogram/`, all by Jesus Lara / engine coder seats. Theme: ink wall. FEAT-645 (slot presence, 2026-10-08, TASK-4166..4171 + two fixes), FEAT-646 (ink-wall registration & completeness, 2026-10-09, TASK-4174..4178), then `42a93f350 fix(planogram): skip reference images for types that do not use them` and `b12e115c3 wip planogram compliance ink wall` (neighbour spill: identification/spill.py, types/ink_wall.py, test_neighbour_spill.py) + `747009334` test fix. `comparison/presence.py` was only touched by TASK-4169 (181e04cfa, 7894b710d). Nothing on the endcap types in this window.

## Citations

- commit: `b12e115c3` 2026-10-09 "wip planogram compliance ink wall" — identification/identify.py, identification/spill.py (new), types/ink_wall.py, tests/planogram_cycle/test_neighbour_spill.py
- commit: `42a93f350` 2026-10-09 "fix(planogram): skip reference images for types that do not use them"
- commit: `7093cb88c` 2026-10-08 "fix(planogram-ink-wall-slot-presence): accept integral float SKUs, document reporting-meta error boundary"
- commit: `3721eaba0` 2026-10-08 "fix(planogram-ink-wall-slot-presence): fall back to facing label when product is None" — comparison/projection.py
- commit: `181e04cfa` 2026-10-08 "TASK-4169" — comparison/presence.py (creation)
- commit: `3e446e87b`..`5aafa2f79` 2026-10-08 — FEAT-645 TASK-4166..4171
- commit: `1cdc894a4`..`4e44ccad5` 2026-10-09 — FEAT-646 TASK-4174..4178
