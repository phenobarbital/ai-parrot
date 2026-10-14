# TASK-4089: Rewrite SDD markdown to parrot sdd run <name>

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070, TASK-4086, TASK-4087, TASK-4088, TASK-4299, TASK-4334
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (rev 0.2) moves the doc-referenced SDD helpers into the core package as
`parrot.sdd.scripts.<name>` (TASK-4085 / TASK-4086 / TASK-4087 / TASK-4088) and requires that
**ALL markdown — installed AND monorepo — invokes them through the single form
`parrot sdd run <name> [args…]`** (Q1 of the amendments), otherwise the byte-equality sync
between `.claude/` and the packaged `_assets/` (TASK-4090) can never pass (spec §7
"Byte-equality sync vs path rewrite"). An SDD flow installed into a foreign repository
(TASK-4091) has no `scripts/sdd/` directory, and in a global-only install the `python` on PATH
cannot import `parrot`, so both the old repo-relative path and a bare
`python -m parrot.sdd.scripts.<name>` are broken instructions there. `parrot sdd run` enters
through the launcher (spec M1) and therefore runs in whatever venv `parrot` itself resolved.

This task performs that rewrite across every SDD markdown/agent asset (and the Codex TOML
agent), keeps every command twin byte-identical, replaces org-specific data and `CLAUDE.md`
pointers in shipped files with placeholders / shipped targets (C11b, C6), makes the
`second-opinion` references conditional (C9), updates the four existing contract tests that
pin the old string literally, and adds a regression test built on the spike-S5 scanner
(`parrot.sdd.audit`, TASK-4070) so no `scripts/sdd` reference of any kind, and no org-data /
`CLAUDE.md` / branch-literal finding, can come back in a shipped file.

The 19 moved helpers (spec §3 M6 + C12): `sdd_meta`, `id_ledger`, `reserve_ids`,
`check_id_collisions`, `ensure_worktree`, `finalize_task`, `check_task_state`,
`check_task_graph`, `worktree_status`, `close_task`, `heal_orphans`, `doc_taxonomy`,
`backfill_taxonomy`, `migrate_index`, `select_tests`, `insight`, `install_hooks`,
`review_checkpoint` (C12, moved by TASK-4086) (+ the package `__init__`) — plus `prune_intake`,
which the coordinator added to TASK-4088's move (`install_hooks`' rendered git hook runs
`python -m scripts.sdd.prune_intake`). Verified on `6c4ca5482`: no markdown/agent asset
references `prune_intake`, so it adds 0 hits; it is still in the rewrite script's and the
regression test's name list so a future reference is caught.

---

## Amendments — spec rev 0.2 (2026-10-14)

Folded from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3, §5; all decided by
Jesus Lara on 2026-10-14). Each delta below is already applied to the sections that follow;
this list is the audit trail.

- **Q1 — invocation form.** The rewrite target is `parrot sdd run <name>` (not
  `python -m parrot.sdd.scripts.<name>`). Title, substitution table (rules 1, 2, 3, 5a), the
  four test edits and the acceptance criteria changed accordingly. The `run` subcommand is
  implemented by TASK-4091 (`parrot sdd run <name> [args…]` →
  `runpy.run_module(f"parrot.sdd.scripts.{name}", run_name="__main__")`); this task only
  needs the **modules** to exist (TASK-4085..4088), so TASK-4091 is NOT a dependency. The
  form is validated end-to-end by TASK-4091's wheel-only foreign-repo test (C3), with only
  `$PARROT_HOME/bin` on PATH.
  *`sdd_meta` one-liners (resolved by TASK-4299)*: TASK-4299 gives
  `parrot/sdd/scripts/sdd_meta.py` an argparse `main()` with `parse <doc>` (prints
  `<type> <base_branch>` on one line — exactly what `sdd-task.md:55-57` awk-splits),
  `taxonomy <doc>` (JSON `{"projects": [...], "tags": [...]}`) and
  `resolve-flow [--kind K] [--doc PATH] [--type T] [--base B]` (JSON
  `{"type": …, "base_branch": …}`). Rule 6 (hand edit) rewrites the inline
  `python -c "… from scripts.sdd.sdd_meta import parse|parse_taxonomy|resolve_flow …"`
  invocations — `.claude/commands/sdd-task.md:55` (+ twins `.agent/workflows/sdd-task.md`,
  `.agents/skills/sdd-task/SKILL.md`), `.claude/commands/sdd-spec.md:173` (resolve_flow,
  multi-line) and `:590` (parse_taxonomy) (+ twin `.agent/workflows/sdd-spec.md`) — to
  `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`, e.g.
  `META=$(parrot sdd run sdd_meta parse "<spec-path>")`. Six invocations in total.
- **Q1 residual (inline python) — RETIRED by TASK-4334 (2026-10-15).** TASK-4334, now a
  dependency of this task, replaced every block listed below with a single-line
  `python -m scripts.sdd.spec_tools <sub> …` invocation, so rule 5a rewrites them once
  `spec_tools` is in `MOVED` (20 names). The Completion Note reports the
  `test_shipped_commands_have_no_inline_python` result (its `sdd_meta` allowance must be
  exercised zero times after rule 6) instead of a residual list. Historical text follows.
  The remaining inline
  `python -c` blocks in shipped files still need a `python` on PATH in a foreign repo:
  `.claude/commands/sdd-spec.md:290`, `:362`, `:381` (imports `jsonschema`), `:393`, `:666`
  (stdlib `json`/`sys`/`os` index and JSON manipulation — no helper exists for them) and
  `:542` (`from scripts.sdd.reserve_ids import existing_feature_id`), plus their
  `.agent/workflows/sdd-spec.md` twin. Verified 2026-10-14: `existing_feature_id`
  (`scripts/sdd/reserve_ids.py:420`) is NOT reachable through `reserve_ids`' CLI (its
  argparse at `:629-633` takes only `--kind/--count/--base-branch/--label/--max-retries`), and
  TASK-4085 freezes that CLI — so `:542` stays in the residual list; rule 5b only rewrites its
  import to `parrot.sdd.scripts.reserve_ids`. Scope decision (coordinator, 2026-10-14): do not
  invent new helpers in this task; write the residual list with `file:line` to the Completion
  Note so the follow-up (ledger item opened by the coordinator) can pick it up. C3's wheel-only
  test (TASK-4091) enumerates `parrot sdd run` invocations only, so these blocks do not fail it.
- **C10 — conventions seed.** Shipped files point at `sdd/CONVENTIONS.md` instead of
  `codebase-conventions.md` / `.claude/rules/codebase-conventions.md` (TASK-4090 no longer
  ships the rulebook). Verified 2026-10-14 on the shipped set: 2 references, in
  `.claude/agents/sdd-coder.md` and `.claude/agents/sdd-worker.md` (one line each).
- **C9 (cont.) — `.claude/skills/second-opinion/SKILL.md` is packaged** for the claude host by
  TASK-4090, so it is rewrite work here: line 8 ("live in `CLAUDE.md` § Adversarial Second
  Opinion") is a `claude-md-ref` finding → point at the shipped `sdd/WORKFLOW.md` reviewer
  rules; its `agy`/`codex` history (13 lines mention `agy` or `codex`) becomes the
  `reviewer: codex` conditional wording ("when `reviewer` in `sdd/config.json` is `codex` …;
  otherwise rely on a Claude subagent"), with the `agy` ban removed (it stays in `CLAUDE.md`).
- **C12 — no shipped reference to a monorepo-only helper.** `review_checkpoint` is moved by
  TASK-4086, so `.claude/agents/sdd-worker.md:588,607` are rewritten to
  `parrot sdd run review_checkpoint …` like every other helper. Verified 2026-10-14 on
  `a6e51614b`: `lint_new` and `token_audit` are referenced by **no** packaged file, and
  `codex_hook` only by `.codex/hooks.json:9`, which TASK-4090 does not package. The "non-moved
  helpers stay untouched" rule is withdrawn; `test_no_repo_script_refs.py` now fails on ANY
  `scripts.sdd.*` / `scripts/sdd/*` reference in a shipped file (historical `sdd/specs/` and
  `sdd/tasks/` excluded).
- **C11b — publication safety (text).** Shipped files use placeholders: Atlassian host →
  `https://your-org.atlassian.net`, real ticket keys (`NAV-123` style) → `PROJ-123`; the `agy`
  reviewer ban stays only in ai-parrot's `CLAUDE.md` (not shipped) and is removed from shipped
  files; hardcoded flow bases (`dev` / `staging` / `main`) become "the `base_branch` /
  `hotfix_base` in `sdd/config.json`" (C6, TASK-4299); references to `CLAUDE.md` sections in
  shipped files point at the shipped `sdd/WORKFLOW.md` or at `sdd/config.json`. The detecting
  scanner kinds `org-data`, `claude-md-ref`, `branch-literal` are added by TASK-4070; the
  regression test asserts zero findings of those kinds over the shipped set. Because of the
  byte-equality rule, the placeholders also land in ai-parrot's own `.claude/` files —
  ai-parrot's real host and keys live in its `sdd/config.json` / environment, not in command
  text. New dependency: **TASK-4299** (the config file and its field names must exist before
  the markdown refers to them).
- **C9 — `second-opinion`.** TASK-4090 packages the skill for the claude host; shipped
  references become conditional: "when `reviewer` in `sdd/config.json` is `codex` and the
  second-opinion skill is installed; otherwise rely on a Claude subagent".
- **C2 — one copy of each agent prompt.** TASK-4090 deletes the `_subagent_data/` copies of
  shipped prompts (the dev-loop loads the packaged `_assets/` copy). They are no longer rewrite
  targets or twins of this task: removed from the Files table, the complexity targets, the
  parity assertions and the Validation Commands. **Ordering**: if this task runs before
  TASK-4090, the one-off script may still include any `_subagent_data/*.md` that exists
  (harmless, keeps `test_worker_prompt_orchestrator.py` reading a rewritten copy), but nothing
  in this task asserts their parity — `test_subagent_parity.py::test_prompt_parity[sdd-worker]`
  is already failing on `dev` and C2 retires it.

---

## Scope

- Rewrite every reference to a moved helper in the 52 files listed below, using EXACTLY the
  substitution table in the Implementation Blueprint (applied by the one-off script, never by
  hand-editing individual occurrences). The invocation form is `parrot sdd run <name>` (Q1).
- Rewrite the two `scripts.sdd.review_checkpoint` invocations in `.claude/agents/sdd-worker.md`
  (lines 588 and 607) the same way (C12 — `review_checkpoint` is moved by TASK-4086).
- Keep every command twin byte-identical: the `.claude/commands/` ↔ `.agent/workflows/`
  command twins (sdd-spec, sdd-task — frontmatter + one tolerated line excepted, see
  `tests/sdd_scripts/test_command_twin_parity.py`). (`_subagent_data/` copies are retired by
  TASK-4090 / C2 and are not twins of this task.)
- Apply the C11b / C6 / C9 text edits to every file in TASK-4090's shipped set (the 14
  `.claude/commands/sdd-*.md`, 9 `.claude/agents/sdd-*.md`, 14 `.agents/skills/sdd-*/SKILL.md`,
  8 `.agents/agents/sdd-*/agent.md`, `.codex/agents/sdd-worker.toml`, the 2 rules,
  `sdd/WORKFLOW.md`, `sdd/templates/*`, plus their `.agent/workflows/` twins):
  - Atlassian hosts → `https://your-org.atlassian.net`; real ticket keys → `PROJ-123`
    (on `a6e51614b`: `sdd-proposal` 5, `sdd-done` 3, `sdd-fromjira` 7, `sdd-tojira` 27,
    `sdd-autopilot` 9 occurrences per host copy; `sdd/templates/proposal.md` 1);
  - remove the `agy` reviewer-ban paragraphs from shipped files (`sdd-codereview`,
    `sdd-spec`, both hosts) — the ban stays in ai-parrot's `CLAUDE.md`;
  - flow-base literals (`dev` / `staging` / `main` named as the base or hotfix branch) →
    "the `base_branch` / `hotfix_base` in `sdd/config.json`" (field names from TASK-4299);
  - `CLAUDE.md §…` pointers → the shipped `sdd/WORKFLOW.md` section or `sdd/config.json`
    (27 lines across commands/agents/workflows/skills/templates on `a6e51614b`);
  - `second-opinion` references (`sdd-codereview` on all hosts, `sdd-secondopinion` agents)
    → conditional on `reviewer: codex` in `sdd/config.json` and the skill being installed;
  - `.claude/skills/second-opinion/SKILL.md` (packaged, claude host): line 8 `CLAUDE.md §`
    pointer → shipped `sdd/WORKFLOW.md`; `agy` ban removed; `codex` text under the same
    `reviewer: codex` conditional (C9);
  - `codebase-conventions.md` / `.claude/rules/codebase-conventions.md` →
    `sdd/CONVENTIONS.md` (C10; 2 lines: `.claude/agents/sdd-coder.md`, `.claude/agents/sdd-worker.md`);
  - the six inline `sdd_meta` one-liners → `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`
    (rule 6; see Amendments, Q1).
  The exact line set is produced by the TASK-4070 scanner (`org-data`, `claude-md-ref`,
  `branch-literal` kinds) — regenerate it at run time; never hand-enumerate.
- Update the four existing tests that assert the OLD literal string in markdown.
- Create `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py`.

**NOT in scope**:
- Implementing `parrot sdd run` (TASK-4091) and the wheel-only foreign-repo test (C3, TASK-4091).
- `sdd/config.json` itself, its Pydantic model and ai-parrot's own config (TASK-4299 / C6);
  the scanner kinds `org-data` / `claude-md-ref` / `branch-literal` (TASK-4070).
- References to non-moved, non-shipped helpers in files TASK-4090 does not package:
  `codex_hook` (`.codex/hooks.json:9` — the hooks file is not an asset),
  `regen_core_paths`, `calibrate_rlimit_as`, `profile_execution`, `tag_yaml_fixtures` (verified
  2026-10-14: zero references in the shipped set). The substitution table matches the 19 moved
  names only, by construction; the extended regression test proves nothing else is left.
- Creating helpers for the former inline `python -c` blocks — TASK-4334 did (`spec_tools`);
  this task only rewrites their `python -m scripts.sdd.spec_tools` invocations via rule 5a.
- Giving `sdd_meta` its CLI (`parse` / `taxonomy` / `resolve-flow`) — TASK-4299; this task only
  consumes it.
- Python sources that embed `scripts.sdd.*` strings
  (`parrot/flows/dev_loop/nodes/research.py`, `nodes/base.py`, `sdd_coder/checkpoint.py`,
  `sdd_coder/background.py`) and `.github/workflows/ci.yml` (`python -m
  scripts.sdd.check_id_collisions` / `check_task_state`) — they run inside the monorepo, where
  the `scripts/sdd/*.py` shims (TASK-4085..4088) keep them working.
- `backfill_taxonomy._SDD_TOOLING_RE` (`scripts/sdd/backfill_taxonomy.py:41`,
  `re.compile(r"scripts/sdd/|\.claude/commands/|sdd/templates/")`) — it is a taxonomy heuristic that
  classifies *changed file paths*, not a reference to a helper; it still correctly matches the repo's
  `scripts/sdd/` shims. Do NOT "fix" it ad hoc in this task (or when TASK-4088 moves the module).
- Other docs under `docs/` (7 files outside `docs/sdd/WORKFLOW.md` mention moved helpers) —
  not installed assets; leave for a follow-up.
- Tests that EXECUTE the helpers via the repo path (`tests/sdd/test_close_task_ledger.py`,
  `tests/sdd/test_ledger_lifecycle_acceptance.py`, `tests/sdd_scripts/test_*.py` importing
  `scripts.sdd.*`) — the shims keep them valid; owned by the move tasks.
- Packaging the assets into `_assets/` (TASK-4090) and the installer (TASK-4091).
- `AGENTS.md`, `.claude/skills/`, `.agent/rules/` and
  `packages/ai-parrot/src/parrot/flows/_rules_data/` were searched and contain **no**
  reference to a moved helper — nothing to change there for the helper rewrite.
  `CLAUDE.md` and `AGENTS.md` are NOT shipped, so the C11b placeholders do not apply to them
  (they keep the real host, keys and the `agy` ban).
- Deleting the `_subagent_data/` prompt copies and repointing `load_subagent_definition()`
  (TASK-4090 / C2).

---

## Files to Create / Modify

Enumerated on `dev` @ `6c4ca5482` with
`grep -rlE "scripts[./]sdd[./](<19 names>)\b"` over `.claude/commands/ .claude/agents/
.claude/rules/ .claude/skills/ .agent/ .agents/ .codex/ sdd/WORKFLOW.md docs/sdd/WORKFLOW.md
CLAUDE.md AGENTS.md sdd/templates/ packages/ai-parrot/src/parrot/flows/_rules_data/`
(173 moved-helper occurrences in 52 files after removing the five `_subagent_data/` copies —
C2 — plus the 2 `review_checkpoint` lines — C12; dry run of the blueprint script leaves 0
residuals). The C11b / C6 / C9 text edits touch a superset of the shipped files; that list is
produced by the TASK-4070 scanner at run time (see Scope) and is not enumerated here.

| File | Action | Description |
|---|---|---|
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | Rewrite 1 line(s): select_tests |
| `.agent/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Rewrite 6 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests |
| `.agents/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,sdd_meta |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Rewrite 6 line(s): close_task,heal_orphans,sdd_meta,select_tests |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agents/skills/sdd-fromjira/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-insight/SKILL.md` | MODIFY | Rewrite 4 line(s): insight |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Rewrite 4 line(s): reserve_ids,sdd_meta |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Rewrite 6 line(s): ensure_worktree,finalize_task |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Rewrite 6 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-done.md` | MODIFY | Rewrite 8 line(s): check_task_state,close_task,heal_orphans,sdd_meta,select_tests |
| `.agent/workflows/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agent/workflows/sdd-insight.md` | MODIFY | Rewrite 3 line(s): insight |
| `.agent/workflows/sdd-next.md` | MODIFY | Rewrite 1 line(s): doc_taxonomy |
| `.agent/workflows/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-spec.md` | MODIFY | Rewrite 7 line(s): reserve_ids,sdd_meta |
| `.agent/workflows/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.agent/workflows/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agent/workflows/sdd-task.md` | MODIFY | Rewrite 5 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.agent/workflows/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/qa-runner.md` | MODIFY | Rewrite 1 line(s): select_tests |
| `.claude/agents/sdd-autopilot.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,select_tests |
| `.claude/agents/sdd-ideation.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/sdd-planner.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,sdd_meta |
| `.claude/agents/sdd-research.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.claude/agents/sdd-worker.md` | MODIFY | Rewrite 8 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests + review_checkpoint (:588, :607 — C12) |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-done.md` | MODIFY | Rewrite 8 line(s): check_task_state,close_task,heal_orphans,sdd_meta,select_tests |
| `.claude/commands/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.claude/commands/sdd-insight.md` | MODIFY | Rewrite 3 line(s): insight |
| `.claude/commands/sdd-next.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-spec.md` | MODIFY | Rewrite 7 line(s): reserve_ids,sdd_meta |
| `.claude/commands/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.claude/commands/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-task.md` | MODIFY | Rewrite 5 line(s): check_task_graph,reserve_ids,sdd_meta |
| `.claude/commands/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `CLAUDE.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,migrate_index,reserve_ids |
| `.claude/rules/worktree-management.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.codex/agents/sdd-worker.toml` | MODIFY | Rewrite 3 line(s): finalize_task,sdd_meta |
| `docs/sdd/WORKFLOW.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,reserve_ids,select_tests |
| `sdd/templates/intake.procedure.md` | MODIFY | Rewrite 1 line(s): reserve_ids |
| `sdd/templates/task.md` | MODIFY | Rewrite 2 line(s): close_task,ensure_worktree |
| `sdd/WORKFLOW.md` | MODIFY | Rewrite 12 line(s): backfill_taxonomy,check_id_collisions,close_task,doc_taxonomy,ensure_worktree,id_ledger,install_hooks,migrate_index,reserve_ids |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | `ensure_worktree` contract asserts `parrot sdd run ensure_worktree` |
| `tests/sdd/test_codex_sdd_sync.py` | MODIFY | Codex worker TOML asserts `parrot sdd run finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Orchestrator-loop assert uses `parrot sdd run finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` | MODIFY | Closure-block markers: new finalize_task / close_task module form |
| `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` | CREATE | Regression: zero `repo-script` findings of ANY kind, and zero `org-data` / `claude-md-ref` / `branch-literal` findings, across the shipped set |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from __future__ import annotations
from pathlib import Path          # stdlib
import pytest                     # test dependency (used by every file under tests/)
# Created by TASK-4070 (does not exist yet on dev — verify the exact names in
# packages/ai-parrot/src/parrot/sdd/audit.py before use):
from parrot.sdd.audit import AssumptionFinding, scan_paths   # AssumptionFinding(path, line, kind, snippet);
#   kinds used here: "repo-script" (original six) + "org-data", "claude-md-ref", "branch-literal" (C11a, added to
#   TASK-4070 by rev 0.2 — verify the exact kind strings in parrot/sdd/audit.py KINDS before use)
# Created by TASK-4085..4088 (+ TASK-4086 for review_checkpoint, C12) — every rewritten reference must resolve
# as a MODULE (importlib.util.find_spec):
#   parrot.sdd.scripts.<name>   for each of the 19 moved names
# Created by TASK-4299 (C6) — the field names the rewritten text cites must exist on the model:
from parrot.sdd.config import SddConfig, load_sdd_config    # fields: base_branch, staging_branch, hotfix_base,
#   issue_tracker, jira_host, reviewer, test_command — verify in parrot/sdd/config.py before writing prose
```

### Existing Signatures to Use
```python
# tests/sdd_scripts/test_command_contracts.py
_CREATORS: dict[str, bool] = {...}                              # line 23 (6 command/agent files)
def test_no_command_hand_rolls_a_worktree(rel: str) -> None:    # line 43; message line 46 names the CLI
def test_every_creator_calls_ensure_worktree(rel: str) -> None: # line 51; `assert "scripts.sdd.ensure_worktree" in _read(` line 53
#   module docstring line 7 also names `scripts.sdd.ensure_worktree`; grep -c 'scripts.sdd.ensure_worktree' == 4

# tests/sdd/test_codex_sdd_sync.py
def test_worker_uses_deterministic_finalization_and_scoped_force_add() -> None:  # line 27
#   assert "scripts.sdd.finalize_task" in worker                                   # line 33 (reads .codex/agents/sdd-worker.toml)

# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py
def test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop():  # line 208
#   docstring line 210 names `scripts.sdd.finalize_task`; assert line 214

# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py
_MARKDOWN_TWINS = (...)                                        # line 12 (.claude/commands/sdd-start.md,
                                                               #   .agent/workflows/sdd-start.md,
                                                               #   .agents/skills/sdd-start/SKILL.md,
                                                               #   .agent/agents/sdd-worker/agent.md)
def test_start_twins_preserve_semantic_gates(tmp_path: Path) -> None:  # line 30
#   marker "python -m scripts.sdd.finalize_task",              # line 43
#   assert "close_task.sh" in body, ...                         # line 59 (comment line 51)

# Twin-parity tests that MUST stay green after the rewrite (read-only for this task):
# tests/sdd_scripts/test_command_twin_parity.py::test_command_twin_parity     line 64 (sdd-spec, sdd-task)
# tests/sdd/test_ledger_workflow_twins.py  — asserts "reserve_ids"/"ensure_worktree" substrings (lines 172, 250-251):
#   still satisfied by the new form (substring of `parrot sdd run reserve_ids`)
# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:187,197 — assert the substrings
#   "review_checkpoint prepare" / "review_checkpoint validate": still satisfied by `parrot sdd run review_checkpoint prepare`
# NOT in this task's gate any more (C2 — retired by TASK-4090, and test_prompt_parity[sdd-worker] already fails on dev):
#   packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py::test_prompt_parity
#   packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin
```

### Does NOT Exist
- ~~`parrot.sdd`, `parrot.sdd.audit`, `parrot.sdd.scripts`~~ on `dev` today — created by
  TASK-4070 / TASK-4085..4088 (this task's dependencies). Do not start before they are `done`.
- ~~a sync/regeneration script for `_subagent_data/` or `_rules_data/`~~ — none exists;
  `_subagent_data/` prompt copies are deleted by TASK-4090 (C2). If they still exist when this
  task runs, the script may rewrite them too, but nothing here asserts their parity.
- ~~`parrot sdd run`~~ — the subcommand is created by TASK-4091 and is NOT required by this
  task's tests; they check module existence with `importlib.util.find_spec`, never spawn
  `parrot sdd run`. Do not add a dependency on TASK-4091.
- ~~`parrot.sdd.config` / `sdd/config.json` on `dev` today~~ — created by TASK-4299 (C6); a
  dependency of this task. Verify its field names before writing prose that cites them.
- ~~a `main()` / CLI on `sdd_meta`~~ — on `dev` today `knowledge/wiki/ledger/sdd_meta.py` has
  no `main`; TASK-4299 adds `parse <doc>`, `taxonomy <doc>`, `resolve-flow [--kind] [--doc]
  [--type] [--base]` to `parrot/sdd/scripts/sdd_meta.py`. Verify the subcommand names and
  output shapes (`parse` → `<type> <base_branch>` one line; `taxonomy` / `resolve-flow` → JSON)
  before writing rule-6 invocations.
- ~~`existing_feature_id` reachable from `reserve_ids`' CLI~~ — it is a Python function
  (`scripts/sdd/reserve_ids.py:420`) only; the CLI (`:629-633`) is frozen by TASK-4085. The
  `sdd-spec.md:542` block was rewritten by TASK-4334 to `spec_tools existing-feature-id` (rule 5a applies).
- ~~scanner kinds `org-data`, `claude-md-ref`, `branch-literal` on `dev` today~~ — added to
  `parrot.sdd.audit.KINDS` by TASK-4070 (C11a). Verify the strings before filtering on them.
- ~~`scripts/sdd/close_task.py` / `heal_orphans.py` in the repo~~ — the Python ports are
  `parrot.sdd.scripts.close_task` / `.heal_orphans` (TASK-4087); `scripts/sdd/*.sh` remain as
  wrappers. Markdown must call the module, never the `.sh`.
- ~~any reference to moved helpers in `AGENTS.md`, `.claude/skills/`, `.agent/rules/`,
  `flows/_rules_data/`~~ — verified zero hits; do not touch them.
- ~~`parrot.sdd.scripts.lint_new` / `token_audit` / `codex_hook`~~ — not moved and (verified
  2026-10-14) referenced by no shipped file; nothing to rewrite. `review_checkpoint` IS moved
  (TASK-4086, C12) and IS rewritten.

---

## Complexity Contract

> **MANDATORY.** Declares the measurable targets and contract symbols used for
> deterministic complexity routing (FEAT-561) before any coder is dispatched.
> This is a declaration, not a hand-authored score — the evaluator computes
> classification from measured evidence, never from this section's prose.

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".agent/agents/sdd-autopilot/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-ideation/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/agents/sdd-ideation/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/worktree-management/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-brainstorm/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-fix/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-fromjira/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-insight/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-next/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-proposal/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-spec/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-start/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-status/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-task/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-brainstorm.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-fix.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-insight.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-tojira.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/qa-runner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-autopilot.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-ideation.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-planner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-research.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-brainstorm.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-fix.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-insight.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-proposal.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-start.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-task.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-tojira.md",
      "action": "MODIFY"
    },
    {
      "path": "CLAUDE.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".codex/agents/sdd-worker.toml",
      "action": "MODIFY"
    },
    {
      "path": "docs/sdd/WORKFLOW.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/templates/intake.procedure.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/templates/task.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/WORKFLOW.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_command_contracts.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd/test_codex_sdd_sync.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:tests/sdd_scripts/test_command_contracts.py#test_no_command_hand_rolls_a_worktree",
    "sym:tests/sdd_scripts/test_command_contracts.py#test_every_creator_calls_ensure_worktree",
    "sym:tests/sdd/test_codex_sdd_sync.py#test_worker_uses_deterministic_finalization_and_scoped_force_add",
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py#test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop",
    "sym:packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py#test_start_twins_preserve_semantic_gates",
    "sym:tests/sdd_scripts/test_command_twin_parity.py#test_command_twin_parity"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The FEAT-553 twin discipline: one source text, copies kept byte-identical and pinned by
parity tests (`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py`,
`test_rules_parity.py`). A deterministic, idempotent substitution applied to the whole file
list preserves parity automatically — never hand-edit one side.

### Key Constraints
- The rewrite is **mechanical and idempotent**: re-running the script must report
  `total=0 residual=0`.
- `close_task.sh` / `heal_orphans.sh` invocations become `parrot sdd run close_task` /
  `parrot sdd run heal_orphans` with the **same positional arguments** (TASK-4087 preserves the
  `.sh` CLI: `<TASK-ID> <feature-slug> <verified|partial|forced>` and `<feature-slug>`). Verify
  against `parrot/sdd/scripts/close_task.py` before running; if TASK-4087 changed the argv, STOP and report.
- Interpreter tokens are DROPPED (Q1): `python3 scripts/sdd/insight.py` and
  `python -m scripts.sdd.insight` both become `parrot sdd run insight`; `bash ` prefixes are
  dropped too. Only prose / import references (rules 4 and 5b) keep the dotted module form
  `parrot.sdd.scripts.<N>`.
- The C11b / C6 / C9 text edits are NOT mechanical: apply them by hand per finding of the
  TASK-4070 scanner, re-run the scanner until it reports zero `org-data` / `claude-md-ref` /
  `branch-literal` findings over the shipped set, and keep each command twin identical.
- Never match across a newline (a fenced ```` ```bash ```` line followed by
  `scripts/sdd/heal_orphans.sh` must not become ```` ```python -m … ````) — the regexes use
  `[ \t]+`, not `\s+`.
- Do NOT rewrite `.claude/worktrees/**` (separate checkouts) — the file list excludes them.

### References in Codebase
- `scripts/sdd/sdd_meta.py` — existing re-export shim precedent (FEAT-633 brief).
- `tests/sdd_scripts/test_command_twin_parity.py` — the twin rule for commands ↔ workflows.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm dependencies landed: `python -c "import parrot.sdd.audit, parrot.sdd.scripts, parrot.sdd.config"`,
   `python -m parrot.sdd.scripts.<n> --help` for each of the 19 names (incl. `review_checkpoint`),
   and that `parrot.sdd.audit.KINDS` contains `org-data`, `claude-md-ref`, `branch-literal` —
   *why*: rewriting to a module that does not resolve breaks every SDD command; the new tests
   filter on those kind strings.
2. Regenerate the file list with the grep in "Files to Create / Modify" and diff it against the
   table — *why*: other features may have touched these files since `6c4ca5482`; a new hit file
   means STOP and update this task's table first.
3. Save the one-off script below OUTSIDE the repo (scratchpad), run it without `--write`
   (dry run), then with `--write` — *why*: deterministic and idempotent; never committed.
4. Review `git diff --stat` and spot-check every `close_task`/`heal_orphans` line (per-file
   checklist) — *why*: these change shape (`.sh` → `python -m`), not just a prefix.
5. Apply rule 6 by hand (the six `sdd_meta` one-liners → `parrot sdd run sdd_meta …`; the
   `parse` output is still `<type> <base_branch>`, so `sdd-task.md:56-57`'s `awk` lines stay)
   and the C11b / C6 / C9 / C10 text edits (Scope), driven by
   `python -m parrot.sdd.audit <shipped files>` until the three new kinds report zero — *why*:
   these are prose edits the mechanical script cannot make; the scanner is the oracle.
   Then run `pytest tests/sdd_scripts/test_command_contracts.py::test_shipped_commands_have_no_inline_python -q`
   and confirm its `sdd_meta` allowance is no longer exercised — *why*: TASK-4334 banned inline
   Python in shipped commands; rule 6 retires the last allowed cases.
6. Apply the four test edits, create `test_no_repo_script_refs.py`, run the Validation
   Commands — *why*: parity + contract tests prove twins and pins are intact.

### Substitution table (old → new; 20 names `N` only; order matters — 5a before 5b)

| # | Old (regex, `[ \t]` = same line) | New |
|---|---|---|
| 1 | `(bash\|sh)[ \t]+(./)?scripts/sdd/<N>.sh` | `parrot sdd run <N>` |
| 2 | `(python\|python3)[ \t]+(./)?scripts/sdd/<N>.py` | `parrot sdd run <N>` |
| 3 | `(./)?scripts/sdd/<N>.sh` (bare, invoked or named) | `parrot sdd run <N>` |
| 4 | `scripts/sdd/<N>.py` (bare prose file reference) | `parrot.sdd.scripts.<N>` |
| 5a | `(python\|python3)[ \t]+-m[ \t]+scripts.sdd.<N>` (invocation) | `parrot sdd run <N>` |
| 5b | `scripts.sdd.<N>` (remaining: `from … import`, `…sdd_meta.plan_worktree` prose) | `parrot.sdd.scripts.<N>` |
| 6 (hand) | `python -c "… from scripts.sdd.sdd_meta import parse\|parse_taxonomy\|resolve_flow …"` (6 invocations: `sdd-task.md:55` + 2 twins, `sdd-spec.md:173`, `:590` + twin) | `parrot sdd run sdd_meta parse <doc>` / `taxonomy <doc>` / `resolve-flow [--kind K] [--doc PATH] [--type T] [--base B]` — applied AFTER the script, by hand (multi-line shapes); keep the surrounding `$(…)` / `awk` lines working |

### All 52 markdown / TOML targets (MODIFY — one-off script, NOT committed)
```python
# occurrences: 173 across 52 files + 2 review_checkpoint lines (verified: grep -cE "scripts[./]sdd[./](<19 names>)\b" <each file>, summed)
# REPLACE — every match of the five rules below, in every file of the table (no single anchor:
#           mechanical rewrite; per-file counts are in the Files table)
"""One-off FEAT-633 TASK-4089 rewrite (scratchpad only). Usage: python rewrite_refs.py --list files.txt [--write]"""
import re
import sys
from pathlib import Path

MOVED = (
    "sdd_meta id_ledger reserve_ids check_id_collisions ensure_worktree finalize_task check_task_state "
    "check_task_graph worktree_status close_task heal_orphans doc_taxonomy backfill_taxonomy migrate_index "
    "select_tests insight install_hooks prune_intake spec_tools review_checkpoint"  # review_checkpoint: C12 (TASK-4086); spec_tools: TASK-4334
).split()
N = "|".join(MOVED)
RULES = [  # Q1: invocations become `parrot sdd run <N>`; prose/import references keep the dotted module name
    (re.compile(rf"\b(?:bash|sh)[ \t]+(?:\./)?scripts/sdd/({N})\.sh\b"), r"parrot sdd run \1"),
    (re.compile(rf"\bpython3?[ \t]+(?:\./)?scripts/sdd/({N})\.py\b"), r"parrot sdd run \1"),
    (re.compile(rf"(?<![\w/.-])(?:\./)?scripts/sdd/({N})\.sh\b"), r"parrot sdd run \1"),
    (re.compile(rf"(?<![\w/.-])scripts/sdd/({N})\.py\b"), r"parrot.sdd.scripts.\1"),
    (re.compile(rf"\bpython3?[ \t]+-m[ \t]+scripts\.sdd\.({N})\b"), r"parrot sdd run \1"),      # 5a
    (re.compile(rf"(?<![\w.])scripts\.sdd\.({N})\b"), r"parrot.sdd.scripts.\1"),                   # 5b
]
RESIDUAL = re.compile(r"scripts[./]sdd[./]\w+")  # C12: ANY scripts/sdd reference left is a residual


def main(argv: list[str]) -> int:
    write = "--write" in argv
    files = [Path(p) for p in Path(argv[argv.index("--list") + 1]).read_text().split()]
    total = leftovers = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        new, count = text, 0
        for rx, repl in RULES:
            new, n = rx.subn(repl, new)
            count += n
        rest = RESIDUAL.findall(new.replace("parrot.sdd.scripts.", "@@").replace("parrot sdd run ", "@@"))
        total, leftovers = total + count, leftovers + len(rest)
        sys.stdout.write(f"{count:3d} {path}{'  RESIDUAL ' + str(rest) if rest else ''}\n")
        if write and new != text:
            path.write_text(new, encoding="utf-8")
    sys.stdout.write(f"total={total} residual={leftovers}\n")
    return 1 if leftovers else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```
**Why this shape**: one deterministic pass over both sides of every twin is the only way to
keep byte parity; the residual count makes the run self-verifying (expected first run:
`total=175 residual=0`, second run `total=0 residual=0`). Write `files.txt` with the 52
paths of the table (one per line); you may append any `_subagent_data/*.md` copy that still
exists (C2 ordering note in Amendments) — it is not asserted.

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'scripts.sdd.ensure_worktree' tests/sdd_scripts/test_command_contracts.py)
# REPLACE — all 4 lines (docstring :7, message :46, assert :53, message :55)
#   `scripts.sdd.ensure_worktree` → `parrot sdd run ensure_worktree`
# e.g. line 53 becomes:
    assert "parrot sdd run ensure_worktree" in _read(
```
**Why**: the old substring is NOT contained in the new form (`parrot sdd run ensure_worktree`),
so the FEAT-552 contract would fail; the contract itself is unchanged. (The creator files invoke
the helper — `python -m scripts.sdd.ensure_worktree …` — so rule 5a applies, not 5b.)

### `tests/sdd/test_codex_sdd_sync.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert "scripts.sdd.finalize_task" in worker' tests/sdd/test_codex_sdd_sync.py)
# REPLACE — `    assert "scripts.sdd.finalize_task" in worker` (verified: tests/sdd/test_codex_sdd_sync.py:33)
    assert "parrot sdd run finalize_task" in worker
```
**Why**: `.codex/agents/sdd-worker.toml` is rewritten by this task (invocation → rule 5a).

### `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert "python -m scripts.sdd.finalize_task" in loop' packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py)
# REPLACE — `    assert "python -m scripts.sdd.finalize_task" in loop` (verified: test_worker_prompt_orchestrator.py:214)
    assert "parrot sdd run finalize_task" in loop
# also REPLACE the docstring mention at :210 `scripts.sdd.finalize_task` → `parrot sdd run finalize_task`
# (grep -c 'scripts.sdd.finalize_task' == 2: lines 210 and 214)
```
**Why**: `load_subagent_definition("sdd-worker")` reads the sdd-worker prompt — the packaged
`_assets/` copy after TASK-4090 (C2), or the `_subagent_data` copy if this task runs first; both
carry the rewritten form (see the C2 ordering note).

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"python -m scripts.sdd.finalize_task",' .../test_start_optimization_contract.py)
# REPLACE — `            "python -m scripts.sdd.finalize_task",` (verified: test_start_optimization_contract.py:43)
            "parrot sdd run finalize_task",
# occurrences: 1 (verified: grep -c '        assert "close_task.sh" in body, f"{rel_path} lost its close_task.sh reference"' ...)
# REPLACE — line 59 (and the comment at :51 naming close_task.sh)
        assert "parrot sdd run close_task" in body, f"{rel_path} lost its close_task reference"
```
**Why**: the closure block now calls the Python port; the AC8/AC17 intent (closure still goes
through the deterministic closer) is unchanged.

### `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (CREATE)
```python
"""FEAT-633 M6 (rev 0.2): no shipped SDD asset references ``scripts/sdd`` at all, and none carries
org data, a ``CLAUDE.md`` pointer or a hardcoded flow base.

Every helper listed in ``_MOVED`` lives in ``parrot.sdd.scripts`` (TASK-4085..4088, C12) and is
invoked as ``parrot sdd run <name>`` (Q1). An installed asset that still says
``python -m scripts.sdd.<name>`` / ``scripts/sdd/<name>.py`` — moved helper or not — is broken in
any repository that is not this monorepo (C12). Shipped files must also be free of
``org-data`` / ``claude-md-ref`` / ``branch-literal`` findings (C11); ``CLAUDE.md``, ``AGENTS.md``
and ``docs/sdd/WORKFLOW.md`` are repo-only and exempt from that second gate.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from parrot.sdd.audit import scan_paths  # created by TASK-4070

_REPO_ROOT = Path(__file__).resolve().parents[4]  # packages/ai-parrot/tests/sdd/ -> repo root
_MOVED: tuple[str, ...] = (
    "sdd_meta", "id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree", "finalize_task",
    "check_task_state", "check_task_graph", "worktree_status", "close_task", "heal_orphans",
    "doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks",
    "prune_intake",  # added to TASK-4088 by the coordinator
    "review_checkpoint",  # C12 — moved by TASK-4086
)
_ASSET_GLOBS: tuple[str, ...] = (
    ".claude/commands/*.md", ".claude/agents/*.md", ".claude/rules/*.md", ".claude/skills/**/*.md",
    ".agent/**/*.md", ".agents/**/*.md", ".codex/agents/*.toml",
    "sdd/WORKFLOW.md", "docs/sdd/WORKFLOW.md", "CLAUDE.md", "AGENTS.md", "sdd/templates/*.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/*.md",
)
# Repo-only files: never shipped by TASK-4090, so the C11 gate does not apply to them.
_REPO_ONLY: frozenset[str] = frozenset({"CLAUDE.md", "AGENTS.md", "docs/sdd/WORKFLOW.md"})
_C11_KINDS: tuple[str, ...] = ("org-data", "claude-md-ref", "branch-literal")  # FILL IN: verify against parrot.sdd.audit.KINDS


def _asset_files() -> list[Path]:
    """Every SDD asset in the checkout (``.claude/worktrees/`` excluded)."""
    if not (_REPO_ROOT / ".claude").is_dir():
        pytest.skip("not a repo checkout (installed package)")
    files = {p for g in _ASSET_GLOBS for p in _REPO_ROOT.glob(g) if p.is_file()}
    return sorted(p for p in files if "worktrees" not in p.parts)


def _shipped_files() -> list[Path]:
    """The asset set minus repo-only files (the C11 publication gate applies to these only)."""
    return [p for p in _asset_files() if p.relative_to(_REPO_ROOT).as_posix() not in _REPO_ONLY]


def test_no_repo_script_findings_at_all() -> None:
    """parrot.sdd.audit reports zero ``repo-script`` findings — moved helper or not (C12)."""
    findings = scan_paths(_asset_files())
    # FILL IN: adapt the call/filters to the exact TASK-4070 signature — bounded by
    #          AssumptionFinding(path, line, kind, snippet) and kind == "repo-script"
    offenders = [f for f in findings if f.kind == "repo-script"]
    assert not offenders, "\n".join(f"{f.path}:{f.line}: {f.snippet}" for f in offenders)


def test_no_publication_findings_in_shipped_files() -> None:
    """Zero ``org-data`` / ``claude-md-ref`` / ``branch-literal`` findings over the shipped set (C11)."""
    findings = scan_paths(_shipped_files())
    offenders = [f for f in findings if f.kind in _C11_KINDS]
    assert not offenders, "\n".join(f"{f.path}:{f.line}: [{f.kind}] {f.snippet}" for f in offenders)


def test_every_invocation_uses_parrot_sdd_run() -> None:
    """Every helper invocation in an asset is ``parrot sdd run <moved name>`` (Q1)."""
    bad = re.compile(r"python3?[ \t]+-m[ \t]+parrot\.sdd\.scripts\.")
    offenders = [p for p in _asset_files() if bad.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"assets still invoke helpers with python -m: {offenders}"


def test_every_rewritten_reference_resolves() -> None:
    """Each ``parrot.sdd.scripts.<name>`` named by an asset is an importable module."""
    pattern = re.compile(r"parrot\.sdd\.scripts\.([a-z_]+)")
    names = {m for p in _asset_files() for m in pattern.findall(p.read_text(encoding="utf-8"))}
    missing = sorted(n for n in names if importlib.util.find_spec(f"parrot.sdd.scripts.{n}") is None)
    assert not missing, f"unresolvable parrot.sdd.scripts modules referenced: {missing}"
```
**Why this shape**: the first test is the spec-mandated S5-scanner gate, now over every
`scripts/sdd` reference (C12); the second is the C11 publication gate over shipped files only;
the third pins the Q1 invocation form; the last proves each dotted module name an asset still
cites (rules 4 / 5b) actually resolves (spec §5). `parents[4]` mirrors
`tests/sdd_scripts/test_command_twin_parity.py`'s fixed-depth root.

### Per-file checklist (after `--write`)
- [ ] `git diff --stat` lists the 52 markdown/TOML files of the table, the shipped files touched
      by the C11b / C6 / C9 hand edits, and the 5 test files — nothing else.
- [ ] `.claude/commands/sdd-done.md` / `.agent/workflows/sdd-done.md` / `.agents/skills/sdd-done/SKILL.md`:
      `(cd "$WORKTREE_PATH" && parrot sdd run close_task "$TASK_ID" …)` and the
      `heal_orphans` lines keep their arguments; the ```` ```bash ```` fence lines are intact.
- [ ] `sdd-start` (3 hosts) + `sdd-worker` (3 host copies): `close_task` / `finalize_task` lines read naturally.
- [ ] `sdd-insight` (3 hosts): `parrot sdd run insight \` continuation lines intact.
- [ ] `sdd-spec`/`sdd-task`: the six `sdd_meta` one-liners now read `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`
      (rule 6); no `from parrot.sdd.scripts.sdd_meta import` remains inside a `python -c` string.
- [ ] Residual inline `python -c` blocks (`sdd-spec.md:290,362,381,393,542,666` + twin, re-verified
      line numbers) listed in the Completion Note with `file:line`; `:542` still imports
      `parrot.sdd.scripts.reserve_ids` (rule 5b) and is on that list.
- [ ] `.claude/agents/sdd-coder.md` / `sdd-worker.md` point at `sdd/CONVENTIONS.md` (C10);
      `.claude/skills/second-opinion/SKILL.md` has no `CLAUDE.md` pointer and no `agy` text (C9).
- [ ] `sdd/templates/task.md` lines 329 and 344 now name `parrot sdd run ensure_worktree`
      / `parrot sdd run close_task`.
- [ ] `.claude/agents/sdd-worker.md:588,607` now read `parrot sdd run review_checkpoint prepare …` /
      `… validate …` with their flags intact (C12).
- [ ] No shipped file contains `trocglobal`, a `NAV-<n>` key, the string `agy`, or `CLAUDE.md`
      (C11b); `sdd-codereview` / `sdd-secondopinion` reference `second-opinion` conditionally (C9);
      flow bases are cited through `sdd/config.json` (C6).

### FILL IN checklist
- [ ] Confirm `parrot.sdd.scripts.prune_intake` exists (TASK-4088) before running; it has 0 markdown hits today.
- [ ] `test_no_repo_script_refs.py::test_no_repo_script_findings_at_all` /
      `::test_no_publication_findings_in_shipped_files` — match the real `scan_paths`
      signature/return type and the exact kind strings; bounded by TASK-4070's `AssumptionFinding`
      and `KINDS` (`repo-script`, `org-data`, `claude-md-ref`, `branch-literal`).
- [ ] `SddConfig` field names cited in the rewritten prose (`base_branch`, `hotfix_base`,
      `reviewer`, …) — verify against `parrot/sdd/config.py` (TASK-4299).
- [ ] `close_task` / `heal_orphans` argv parity — confirm TASK-4087 kept the `.sh` positional CLI;
      bounded by spec §5 ("`scripts/sdd/` wrappers keep the monorepo's existing invocations working").

---

## Acceptance Criteria

- [ ] `grep -rlE "scripts[./]sdd[./]\w+"` over the shipped asset paths returns nothing (C12);
      every helper invocation in installed markdown is `parrot sdd run <name>` (Q1, spec §5 rev 0.2)
      and every dotted `parrot.sdd.scripts.<name>` still cited in prose resolves.
- [ ] `.claude/agents/sdd-worker.md:588,607` invoke `parrot sdd run review_checkpoint` (C12).
- [ ] No shipped file carries an `org-data`, `claude-md-ref` or `branch-literal` finding (C11b/C6);
      `CLAUDE.md` / `AGENTS.md` / `docs/sdd/WORKFLOW.md` are exempt (repo-only).
- [ ] `second-opinion` references in shipped files are conditional on `reviewer: codex` in
      `sdd/config.json` (C9).
- [ ] The command twin parity test passes (`.claude/commands` ↔ `.agent/workflows`); no
      `_subagent_data` parity is asserted (C2).
- [ ] The four updated contract tests pass against the rewritten assets.
- [ ] `test_no_repo_script_refs.py` passes (all four tests).
- [ ] The six `sdd_meta` one-liners invoke `parrot sdd run sdd_meta parse|taxonomy|resolve-flow`
      (rule 6) and `sdd-task`'s `TYPE=`/`BASE=` `awk` split still works on `parse`'s output.
- [ ] Completion Note lists every remaining inline `python -c` block in a shipped file as
      `file:line` (expected: `sdd-spec.md:290,362,381,393,542,666` + the `.agent/workflows` twin,
      re-verified), for the follow-up ledger item. These do not fail C3's wheel-only test, which
      enumerates `parrot sdd run` invocations only.
- [ ] No shipped file references `codebase-conventions.md`; the two former references point at
      `sdd/CONVENTIONS.md` (C10).
- [ ] Re-running the rewrite script reports `total=0 residual=0` (idempotent).
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py`
      and the four modified test files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd/test_codex_sdd_sync.py -q`
Also, outside the pytest contract: `python -m parrot.sdd.audit <every shipped asset>` reports zero `repo-script`,
`org-data`, `claude-md-ref` and `branch-literal` findings (exact CLI per TASK-4070).
- `pytest tests/sdd/test_ledger_workflow_twins.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py — see the CREATE block above:
#   test_no_repo_script_findings_at_all              (S5 scanner gate, any scripts/sdd ref — C12)
#   test_no_publication_findings_in_shipped_files    (org-data / claude-md-ref / branch-literal — C11)
#   test_every_invocation_uses_parrot_sdd_run        (Q1 form)
#   test_every_rewritten_reference_resolves          (dotted module names import)
# Existing tests updated (assert the new form; intent unchanged):
#   tests/sdd_scripts/test_command_contracts.py::test_every_creator_calls_ensure_worktree
#   tests/sdd/test_codex_sdd_sync.py::test_worker_uses_deterministic_finalization_and_scoped_force_add
#   packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py::
#       test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py::
#       test_start_twins_preserve_semantic_gates
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4089 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
