---
id: F007
query: "G7 — Hygiene batch (drift, hard-coded transition, revision QA, dead schema)"
type: code_review
verdict: CONFIRMED
---

## G7: Hygiene issues — all confirmed

### G7a: Subagent dual-sourcing drift — CONFIRMED

- **`_subagent_defs.py:15-22`** docstring advertises repo + package sourcing
- **`_subagent_defs.py:64-88`** (`load_subagent_definition`) only reads from
  `_subagent_data/` via `importlib.resources`. No repo fallback.
- Line counts: sdd-research 99 vs 80, sdd-worker 328 vs 274
- Drift is substantive: repo copies have FEAT-145 per-spec index + wiki-first;
  package copies retain monolithic index, no wiki.
- No CI parity checks exist.

### G7b: FailureHandlerNode hard-codes transition — CONFIRMED

- **`failure_handler.py:87-89`** — calls `jira_transition_issue(transition="Needs Human Review")`
- `nodes/base.py:53` has `transition_issue_with_candidates` helper (synonym fallback)
- `deployment_handoff.py:204,397` and `close.py:78` use the helper. Only
  `failure_handler` bypasses it.

### G7c: Revision QA is lint-only — CONFIRMED

- **`models.py:283-305`** (`RevisionBrief`) — no `acceptance_criteria` field.
- **`runner.py:653-673`** — comment: "criteria are not carried on RevisionBrief,
  so QA re-runs a lint gate by default." Synthesizes minimal `WorkBrief` with
  single `ShellCriterion(name="lint", command="ruff check .")`.
- Original feature criteria lost on revision runs.

### G7d: Dead JSON-schema path — PARTIALLY_TRUE

- Claude dispatcher: `json_schema_path` pinned `None` (`dispatcher.py:315`),
  `_materialize_json_schema` exists but never called.
- Codex dispatcher: has its own `_materialize_json_schema` at line 1006, actively used.
- Dead only in Claude dispatcher, not universally.
