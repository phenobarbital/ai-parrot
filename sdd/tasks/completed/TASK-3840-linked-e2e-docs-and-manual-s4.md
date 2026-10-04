# TASK-3840: Linked E2E README, docs "E2E validation" section and manual S4 checklist

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3839, TASK-3836
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 10. It documents how to run the FEAT-611 E2E harness:
- the staging seed from TASK-3832;
- `server.py` and `run_e2e.py` from TASK-3839;
- the offline and staging pytest tiers from TASK-3839;
- the golden/parity harness from TASK-3838.

It also adds the **manual S4** checklist: a real agent chat with `output_mode=a2ui` opens a canvas tab,
renders in `A2UISurface`, the FilterBar re-queries, and Refresh uses the server lane. That checklist
exercises the canvas wiring from TASK-3836.

S4 is `exploratory` and is never required (spec §4 E2E table). Its recorded outcome goes into this task's
Completion Note (spec §5).

Why each dependency:
- TASK-3839 provides the commands, flags (`--guard-mode`, `--deny-base-url`, `--noguard-base-url`,
  `--via-agent`) and env vars that the README documents.
- TASK-3836 provides the `isLinkedSurface` tab opening and the `persistedSurfaceId` pass-through, which
  the S4 checklist verifies.

---

## Scope

- Create `examples/agents/a2ui/linked_e2e/README.md` with these sections:
  - requirements;
  - layout of the directory;
  - seed;
  - server;
  - runner;
  - pytest tiers;
  - golden/parity;
  - manual S4 checklist with expected observations;
  - known gotchas.
- Append an "E2E validation" section (§8) to `docs/outputs/a2ui-linked-surfaces.md`. It links the README
  and summarizes the tiers.
- Run the manual S4 checklist once if an admin UI and staging are available, and record the result in
  the Completion Note. Otherwise record "not run: <reason>".

**NOT in scope**: any code change, any change to the harness, and editing other docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/linked_e2e/README.md` | CREATE | How to run FEAT-611 E2E + manual S4 checklist |
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | Append "## 8. E2E validation" section |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation-only task
```

### Existing Signatures to Use
```text
docs/outputs/a2ui-linked-surfaces.md — 90 lines; sections "## 1." … "## 7. Share-token viewers" (:83);
  last line :90 "This ensures that share recipients see consistent data without inadvertently executing queries
  on their behalf." — the file has NO trailing newline (verified with od -c).
.gitignore:20 ignores examples/**/*.py and :31 re-includes examples/agents/a2ui/**/*.py; README.md is NOT
  ignored (git check-ignore returned nothing for examples/agents/a2ui/linked_e2e/README.md).
examples/agents/a2ui/README.md — the tone/structure reference (intro paragraph + bash block + "## Files").

Commands/flags documented (created by TASK-3839 / TASK-3832 — re-read those files before writing):
  ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py              (TASK-3832; refuses non-staging)
  ENV=staging python examples/agents/a2ui/linked_e2e/server.py --port 5000 [--guard-mode policy|deny|none]
  ENV=staging E2E_USER=… E2E_PASSWORD=… python examples/agents/a2ui/linked_e2e/run_e2e.py --base-url … \
      [--deny-base-url …] [--noguard-base-url …] [--via-agent] [--scenarios s1,s2,s3,s5]
  optional E2E_SHARE_USER / E2E_SHARE_PASSWORD (share bearer), AUTH_USERNAME_ATTRIBUTE (login field)
  pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py            (deterministic)
  ENV=staging pytest -m staging packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py
  pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py
  pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py
  pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py              (Node >= 24, pnpm)
  PARROT_REGEN_GOLDEN=1 regenerates linked_epson_dashboard.json (TASK-3838)
Admin UI: A2UI is on unless PUBLIC_AGENTCHAT_A2UI=false|0 (ui/src/lib/features.ts:31); agent chat route
  /api/v1/agents/chat/{agent_id} (manager.py:2312), agent name "epson_linked" (TASK-3839 agent.py).
```

### Does NOT Exist
- ~~An admin page listing persisted surfaces~~ (spec Non-Goals). The S4 checklist must not tell the user to find one.
- ~~Anonymous share-token viewing~~. The bearer must be logged in (spec §7).
- ~~Persisted `/refresh` params~~. A refresh with `{}` reverts to the stored placeholders (spec §7). Document this as a gotcha.
- ~~`package-lock.json` / npm~~. The UI is pnpm-only (`pnpm-lock.yaml`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/agents/a2ui/linked_e2e/README.md", "action": "CREATE"},
    {"path": "docs/outputs/a2ui-linked-surfaces.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Every command in the README must match the flags and env vars that TASK-3839/TASK-3832 actually ship.
  Re-read `server.py`, `run_e2e.py` and `seed_staging.py` before writing, and fix the README (not the code) if they differ.
- State plainly:
  - staging only; never production (spec §5);
  - SKIP is not PASS;
  - the offline tier is the deterministic verdict, and staging is a live check (§9 S9).
- Write English prose, with short paragraphs and no marketing tone.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read `examples/agents/a2ui/linked_e2e/{server,run_e2e,seed_staging,agent,dashboard_tool}.py`. The README documents what exists, not what the spec imagined.
2. Write README block 1 (intro → pytest tiers), then append block 2 (golden/parity → S4 → gotchas).
3. Append the docs section to `docs/outputs/a2ui-linked-surfaces.md`.
4. If possible, run S4 by hand and record each checklist line as observed / not observed in the Completion Note.
5. Run the validation command. It is a cheap sanity check that the documented offline command works.

### `examples/agents/a2ui/linked_e2e/README.md` (CREATE) — block 1
````markdown
# Linked surfaces end to end (FEAT-611)

This directory is an asserting end-to-end harness for **linked A2UI surfaces** (FEAT-598) over the Epson
slugs `epson_field_activity` and `epson_program_targets`, plus the seeded multiquery
`epson_activity_vs_targets_mq`. It is meant to run against **staging** with **querysource ≥ 5.1.2**.
Nothing here writes to production: every script refuses to run unless `ENV=staging`.

| Scenario | What it proves |
|---|---|
| S1 | Server lane: publish, GET json/html, refresh with params, share token, bearer refresh; 403/409/warnings |
| S2 | Dashboard TOOL: join + `transform.ops` + FilterBar `param` + local FilterBar; Python↔TS parity |
| S3 | Multiquery: `multi_output`, `result` fallback, missing/ambiguous → error |
| S5 | Tenant route: `tenant="public"` via `/api/v1/public/queries/{slug}` and via `/refresh` |
| S4 | Manual: a real agent chat renders and refreshes the surface in the admin UI |

## Requirements

- FILL IN: bullets — `ENV=staging` + staging DB/credentials; querysource >= 5.1.2 (TASK-3831 pin);
  navigator-auth installed (the guard fails open without it — docs §6); an E2E user (E2E_USER/E2E_PASSWORD) and
  optionally a second share user; Node >= 24 + pnpm 9.15.9 for the vitest parity leg; the demo policy
  `policies/source-epson.yaml` — bounded by spec §7 External Dependencies

## Files

- FILL IN: one line each for dashboard_tool.py, agent.py, server.py, run_e2e.py, seed_staging.py,
  policies/source-epson.yaml — bounded by what exists in this directory

## 1. Seed staging (once)

```bash
ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py
```
FILL IN: what it does (describe slugs read-only, upsert the multiquery, prove the policy allow/deny) and that
it refuses unless the DB name contains "staging" — bounded by TASK-3832's seed_staging.py

## 2. Start the server

```bash
ENV=staging python examples/agents/a2ui/linked_e2e/server.py --port 5000
ENV=staging python examples/agents/a2ui/linked_e2e/server.py --port 5001 --guard-mode deny   # optional: S1 403 (policy)
ENV=staging python examples/agents/a2ui/linked_e2e/server.py --port 5002 --guard-mode none   # optional: S1 403 (no guard)
```
FILL IN: mount order (QuerySource → guard → BotManager + EpsonLinkedAgent → AuthHandler/BasicAuth) and why the
agent is registered before startup (the guard is injected only into bots present at startup)

## 3. Run the scenarios

```bash
ENV=staging E2E_USER=… E2E_PASSWORD=… \
  python examples/agents/a2ui/linked_e2e/run_e2e.py --base-url http://127.0.0.1:5000 \
  --deny-base-url http://127.0.0.1:5001 --noguard-base-url http://127.0.0.1:5002
```
FILL IN: the PASS/FAIL/SKIP table, exit codes (0 only when every non-skipped check passed; 2 when not staging),
`--via-agent` (needs an LLM key; exercises the chat → envelope lift), E2E_SHARE_USER/E2E_SHARE_PASSWORD

## 4. Pytest tiers

```bash
pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py            # deterministic, no DB
ENV=staging pytest -m staging packages/ai-parrot-server/tests/integration/test_linked_e2e_staging.py
```
FILL IN: the offline tier is the verdict; the staging tier is live, skipped without ENV=staging, querysource
>= 5.1.2 and E2E_USER/E2E_PASSWORD, and needs a running server at E2E_BASE_URL — bounded by §9 S9
````
**Why**: the section order follows the spec §3 M10 list (requirements → seed → server → runner → pytest → S4).
Replace every `FILL IN:` line with prose. None may remain in the committed file.

### `examples/agents/a2ui/linked_e2e/README.md` (CREATE) — block 2 (append)
````markdown
## 5. Golden and parity (S2)

```bash
pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py
pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_parity.py
pytest packages/ai-parrot-server/tests/ui/test_vitest_a2ui_linked_parity.py   # Node >= 24; skipped without pnpm/node_modules
```
FILL IN: one fixture (`contract/fixtures/parity/epson_dashboard_params.json`) pins conditions (declared, undeclared,
locked) and rows for both lanes; `PARROT_REGEN_GOLDEN=1` regenerates the golden envelope; a vitest skip is not a pass

## 6. Manual S4 — admin chat (exploratory, never required)

1. FILL IN: start server.py (policy mode) and the admin UI against it; log in as the E2E user.
2. FILL IN: open agent `epson_linked`, set output mode to A2UI, ask for the Epson activity dashboard for a range with data.
3. Expected: a canvas tab opens (linked Column root) and `A2UISurface` renders KPIs, the bar chart and the attainment table.
4. Expected: changing "From"/"To" in the date FilterBar re-queries the chart (browser lane, `parrot_param`).
5. Expected: the "Program" FilterBar filters rows locally, with no network request.
6. Expected: after publishing, Refresh uses `POST /api/v1/ui/surfaces/{id}/refresh`, and "data as of" updates.
7. Record each line as observed / not observed in TASK-3840's Completion Note.

## Known gotchas

- FILL IN: startup needs a real Postgres (QS 5.1.x `initialize_tenants`); an empty date range is a 502
  `data_stage` (pick ranges with data); `/refresh` params are not persisted (a later `{}` refresh reverts);
  the date FilterBar re-queries only `activity` in the browser lane but the server refresh broadcasts to every
  source; the "stale refresh" 409 against staging depends on winning a race (SKIP when it does not); share
  bearers must be logged in — bounded by spec §7 Known Risks and TASK-3838's dashboard_tool docstring
````
**Why**: every S4 step states an observable expectation, so the manual run is falsifiable (spec §5 AC:
"S4 manual checklist, recorded").

### `docs/outputs/a2ui-linked-surfaces.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'This ensures that share recipients see consistent data' docs/outputs/a2ui-linked-surfaces.md)
# AFTER — insert below `This ensures that share recipients see consistent data without inadvertently executing queries on their behalf.` (verified: docs/outputs/a2ui-linked-surfaces.md:90)
# NOTE: the file has no trailing newline — add "\n\n" before the new heading.

## 8. E2E validation

FEAT-611 validates linked surfaces end to end against staging (querysource ≥ 5.1.2). The harness lives in
[`examples/agents/a2ui/linked_e2e/`](../../examples/agents/a2ui/linked_e2e/README.md).

FILL IN: 4-6 lines — the three tiers (offline pytest = deterministic verdict; `pytest -m staging` and
`run_e2e.py` = live, staging only; manual S4 in the admin UI = exploratory), the Python↔TS parity fixture
(`contract/fixtures/parity/epson_dashboard_params.json`), and that SKIP never counts as PASS — bounded by spec §4 E2E table
```
**Why**:
- Append a new numbered section after §7, so no existing anchor or heading changes.
- Use a relative link from `docs/outputs/`, so it resolves in the repository browser.

### FILL IN checklist
- [ ] `README.md` block 1 — requirements, files, seed/server/runner/pytest prose. Bounded by the files TASK-3832/3839 actually ship.
- [ ] `README.md` block 2 — the golden/parity prose, S4 steps 1-2, and gotchas. Bounded by spec §7 and TASK-3838.
- [ ] `a2ui-linked-surfaces.md` §8 — the tier summary. Bounded by the spec §4 E2E table.
- [ ] Completion Note — the S4 observations (or "not run: <reason>"). Bounded by spec §5.

---

## Acceptance Criteria

- [ ] `examples/agents/a2ui/linked_e2e/README.md` exists. It contains requirements, seed, server, runner, both pytest tiers, golden/parity, the manual S4 checklist with expected observations, and gotchas. No `FILL IN` remains.
- [ ] `docs/outputs/a2ui-linked-surfaces.md` ends with a `## 8. E2E validation` section that links the README. Sections 1-7 are unchanged.
- [ ] Every documented command or flag exists in the shipped scripts.
- [ ] The Completion Note records the S4 run (observed / not observed per line) or the reason it was not run.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py -q`

---

## Test Specification

This task is docs only and adds no tests. The validation command re-runs TASK-3839's offline tier, so the
documented deterministic command is known to work.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`).
2. **Read the spec**: §3 M10, §4 E2E table and §7 gotchas.
3. **Check dependencies**. TASK-3839 and TASK-3836 must be `"done"`.
4. **Verify** the commands and flags against the shipped scripts before writing.
5. **Update status** to `"in-progress"`, and commit only the index file.
6. **Implement** from the blueprint, and complete every `FILL IN`.
7. **Verify** by running the validation command.
8. **Commit** only the two files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3840 a2ui-linked-e2e-parallel verified`.
10. **Fill in the Completion Note**, including the S4 record.

---

## Completion Note

**Completed by**: SDD sub-agent (session_01CFWijXsJLATx5g6k94o1EP), feature worktree (commit 11bb5dad1)
**Date**: 2026-09-29
**Verification**: partial. The docs are complete and were checked against the shipped scripts. The manual S4 was not run, because staging Postgres is unreachable from this workstation.

**Notes**:
- **README** (`examples/agents/a2ui/linked_e2e/README.md`) covers:
  - the purpose and the table of scenarios S1/S2/S3/S5/S4;
  - the requirements: querysource ≥5.1.2, the `ENV=staging` selector, running from the main checkout root, staging network access, Node 24 + pnpm 9.15.9, and the demo policy;
  - the seed order;
  - the three server guard modes;
  - the `run_e2e.py` flags, env vars and exit codes;
  - the pytest tiers;
  - the golden, parity and vitest wrappers;
  - the manual S4 checklist (a–g);
  - the known gotchas and follow-ups.
- **Docs**: appended "## 8. E2E validation" to `docs/outputs/a2ui-linked-surfaces.md`.
- Every command, flag and env var was checked against the `argparse` definitions and `os.environ` reads.
- `test_linked_e2e_offline.py`: 4 passed.

**Deviations from spec**:
- The README states that linked saves fail closed with a 403 when there is no PBAC guard, per docs §6. The blueprint had said the guard "fails open".
- The offline section also lists `test_seed_staging_guard.py` and all six vitest wrappers.


**Live update (2026-09-29)**: the automated live tier (S1/S2/S3/S5) passed on the dev env: runner 32/32, pytest 4/4 (F020). The manual S4 is still NOT run. Reasons:
- The LLM client registry does not resolve provider `google` in this venv. `ai-parrot-client-google` is not installed as a distribution, and putting it on PYTHONPATH does not register its entry point.
- The admin UI `dist/` is not built.

So this task remains done-with-issues.
