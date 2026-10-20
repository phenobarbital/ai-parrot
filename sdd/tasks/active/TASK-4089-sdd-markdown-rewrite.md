# TASK-4089: Rewrite SDD markdown to parrot sdd run <name>

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070, TASK-4086, TASK-4087, TASK-4088, TASK-4299, TASK-4334, TASK-4508
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
  was failing on `dev` then (on `9f51c7735` all 8 copies are byte-identical again) and C2 retires it.

---

## Amendments — spec rev 0.4 (2026-10-18)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C17 (decision by
Jesus Lara, 2026-10-18). Every section below is already edited to match.

- **C17 — `/sdd-brief` (FEAT-698) joins the rewrite.** The enumeration above was made on
  `6c4ca5482`, before FEAT-698 merged (2026-10-17). Three more shipped files reference moved
  helpers (verified on `925b0f1a2`): `.claude/commands/sdd-brief.md` (`:18`, `:132`
  `python -m scripts.sdd.ensure_worktree`; `:151` the prose
  `scripts.sdd.brief_meta.write_brief_index`; `:154` `python -m scripts.sdd.check_task_graph`),
  its Codex twin `.agents/skills/sdd-brief/SKILL.md` (`:39-40`), and the Google twin
  `.agent/workflows/sdd-brief.md`, which **does not exist yet** — FEAT-698 shipped Claude +
  Codex only. This task creates it the way every other Google twin is built (`---\n`
  `description: <the command's one-line purpose>` `\n---\n\n` + the byte-identical body of
  the Claude command) *before* running the rewrite, so the twin parity test
  (`.claude/commands` ↔ `.agent/workflows`) holds for `sdd-brief` too. `brief_meta` is the
  21st moved name (TASK-4085 moves it, TASK-4299 adds `plan` / `write-index`): add it to the
  rewrite script's and the regression test's name list; rule 5a covers the `python -m`
  forms, and the prose symbol reference is a hand edit (rule 6) to
  `parrot sdd run brief_meta write-index <brief.md> --tasks <tasks.json> --worktree-root <wt>`.
  No `python -c` block is involved (`test_shipped_commands_have_no_inline_python` already
  passes over `sdd-brief.md`).

---

## Amendments — spec rev 0.3 C16 (folded in 2026-10-19)

From `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C16 (approved by Jesus Lara,
2026-10-17; spec rev 0.3 lists TASK-4089 as amended). Every section below is edited to match.

- **C16 — no shipped monorepo source path.** `.claude/agents/sdd-coder.md:21` and
  `.claude/agents/sdd-worker.md:32` run the shared-environment guard as
  `python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook || exit 2`.
  This task rewrites both frontmatter hooks by hand (rule 7) to
  `parrot sdd run worktree_environment --hook || exit 2` (the module itself is relocated to
  `parrot/sdd/scripts/` with a re-export shim — proposal C16 step 1; the launcher fast path is
  TASK-4509). `worktree_environment` joins the name lists, and `test_no_repo_script_refs` is
  widened past `scripts/sdd` to ANY monorepo source path in a shipped file — `packages/`,
  `scripts/`, `$CLAUDE_PROJECT_DIR/…` (historical `sdd/specs/` and `sdd/tasks/` excluded). This
  reverses the NOT-in-scope clause that the substitution table "matches the 19 moved names only,
  by construction".

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: TASK-4508's four helpers (`cache_test_contract`, `test_report`, `check_e2e_closeout`, `close_resolved_issues`) and C16's `worktree_environment` join the name lists (26) and Depends-on; Files table re-enumerated (56 files, dry run `total=216 residual=0`; + both `sdd-research/agent.md`, the `sdd-coder` hook, 5 more test files incl. `test_command_twin_parity.py`); rule 6 covers all 13 `sdd_meta` one-liners; name regexes `[a-z0-9_]+`; stale inline-python residual list, line anchors and the `test_prompt_parity` note corrected; C16 folded in.
- FEAT-708 drift (merged on `dev` 2026-10-20, after this review's baseline): it added the Claude-only
  `.claude/agents/sdd-contract-probe.md` (10 Claude agents). `/sdd-task`, `/sdd-brainstorm` and
  `/sdd-proposal` and their twins call it. FEAT-708 also inserted lines into those three commands
  (+41/+39/+153, e.g. `cache_test_contract` `sdd-task.md:369` → `:410`), so anchors in those files
  must be re-located by `grep` at pickup.
- Resolved by spec rev 0.5 (2026-10-20):
  - C22 (C16 widened test vs existing paths) — categories A–E are applied to all twins in this task's single pass (Scope, "C21 / C22 / C24 hand edits"); `_C16_ALLOWLIST` holds only `.claude/hooks/sdd-worker-format.sh:76`; both gate patterns are in `test_no_repo_script_refs.py`; `/sdd-insight` left the rewrite and shipped sets (53 files, dry run `total=206 residual=0`); both `codebase-conventions.md` twins added as MODIFY rows.
  - C21 (FEAT-699 vs C7) — `test_command` prose rules added for `/sdd-done`'s feature tier, sdd-worker's merge step, qa-runner, sdd-autopilot, `/sdd-task` and the `/sdd-spec` hint; `sdd/templates/spec.md` added (MODIFY).
  - C24 (Google `/sdd-done` E2E gate) — the Claude §4.6 gate is ported into `.agent/workflows/sdd-done.md` during the rewrite.
  - C22 E (navconfig one-liners) — they become an env-var precondition; the `sdd-done` / `sdd-tojira` twins join `_SHIPPED_WITH_INLINE_PYTHON_BAN`.

## Scope

- Rewrite every reference to a moved helper in the 53 files listed below (+ the Google
  `sdd-brief` twin this task creates; rev 0.5 C22: the three `/sdd-insight` files left the set), using EXACTLY the
  substitution table in the Implementation Blueprint (applied by the one-off script, never by
  hand-editing individual occurrences). The invocation form is `parrot sdd run <name>` (Q1).
- Rewrite the two `scripts.sdd.review_checkpoint` invocations in `.claude/agents/sdd-worker.md`
  (lines 607 and 626) the same way (C12 — `review_checkpoint` is moved by TASK-4086).
- *(C16)* Rewrite the `PreToolUse` hook in the frontmatter of `.claude/agents/sdd-coder.md:21`
  and `.claude/agents/sdd-worker.md:32` to `parrot sdd run worktree_environment --hook || exit 2`
  (rule 7, by hand).
- Keep every command twin byte-identical: the `.claude/commands/` ↔ `.agent/workflows/`
  command twins (`_TWINNED` = sdd-next, sdd-spec, sdd-status, sdd-task, plus sdd-brief added by
  this task — frontmatter + one tolerated line excepted, see
  `tests/sdd_scripts/test_command_twin_parity.py`). (`_subagent_data/` copies are retired by
  TASK-4090 / C2 and are not twins of this task.)
- Apply the C11b / C6 / C9 text edits to every file in TASK-4090's shipped set (the 14
  `.claude/commands/sdd-*.md`, 10 `.claude/agents/sdd-*.md` (incl. FEAT-708's `sdd-contract-probe`), 14 `.agents/skills/sdd-*/SKILL.md` — no `sdd-insight`, C22,
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
  - the 13 inline `sdd_meta` one-liners → `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`
    (rule 6; see Amendments, Q1, and the rule-6 row of the substitution table).
  The exact line set is produced by the TASK-4070 scanner (`org-data`, `claude-md-ref`,
  `branch-literal` kinds) — regenerate it at run time; never hand-enumerate.
- *(rev 0.5 C21)* `test_command` prose, in the same pass and on every twin (rules in the blueprint,
  "C21 / C22 / C24 hand edits"): `/sdd-done`'s feature tier (`.claude/commands/sdd-done.md` §4.5
  `:184-187`, §4.7 `:245-278` + twins), sdd-worker's merge step (`.claude/agents/sdd-worker.md:556`,
  `.agent/agents/sdd-worker/agent.md:289`), qa-runner (`.claude/agents/qa-runner.md:69`), sdd-autopilot
  (`.claude/agents/sdd-autopilot.md:567`, `.agent/agents/sdd-autopilot/agent.md:574`), `/sdd-task`'s
  cache step (`.claude/commands/sdd-task.md:364-373` + twins) and the `/sdd-spec` hint
  (`.claude/commands/sdd-spec.md:541-546` + twins), plus `sdd/templates/spec.md` (§4 Validation
  Contract, `:147-158`).
- *(rev 0.5 C22)* Apply categories A–E to every shipped twin in the same pass; ai-parrot's own
  layout/environment rules move to `.claude/rules/codebase-conventions.md` and its twin
  `.agent/rules/codebase-conventions.md` (not shipped). `/sdd-insight` (all hosts) is neither
  rewritten nor shipped.
- *(rev 0.5 C24)* Port `/sdd-done`'s E2E closeout gate (Claude `.claude/commands/sdd-done.md` §4.6,
  `:193-243`, and its `E2E:` lines in Step 5 / Step 12, `:296`, `:899`, `:915`) into the Google twin `.agent/workflows/sdd-done.md` (between §4.5 `:126` and §4.7 `:158`).
- Update the eight existing tests that assert the OLD literal string in markdown, plus
  `test_command_twin_parity.py` (its tolerated-delta anchors and `_TWINNED`).
- Create `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (C12 sweep, widened by C16 and C22).

**NOT in scope**:
- Implementing `parrot sdd run` (TASK-4091) and the wheel-only foreign-repo test (C3, TASK-4091).
- `sdd/config.json` itself, its Pydantic model and ai-parrot's own config (TASK-4299 / C6);
  the scanner kinds `org-data` / `claude-md-ref` / `branch-literal` (TASK-4070).
- References to non-moved, non-shipped helpers in files TASK-4090 does not package:
  `codex_hook` (`.codex/hooks.json:9` — the hooks file is not an asset),
  `regen_core_paths`, `calibrate_rlimit_as`, `profile_execution`, `tag_yaml_fixtures` (verified
  2026-10-14: zero references in the shipped set). The substitution table matches the 26 names
  in `MOVED` only; the extended regression test (C12, widened by C16) proves nothing else is left.
- Moving `cache_test_contract`, `test_report`, `check_e2e_closeout`, `close_resolved_issues`
  into `parrot.sdd.scripts` (TASK-4508); relocating `worktree_environment` (proposal C16 step 1)
  and its launcher fast path (TASK-4509). This task only rewrites the markdown that invokes them.
- `/sdd-insight` on any host (rev 0.5 C22: not shipped in v1 — it depends on unshipped
  `reference/sdd-insight/` and `.claude/workflows/sdd-insight.js`); its three files keep calling
  `scripts/sdd/insight.py` through the monorepo shim and are excluded from this task's gates.
- A foreign-repo validation phase (rev 0.5 C21: deferred to v1.1); `cache_test_contract` itself stays
  strict; `test_command` semantics and `SddConfig.projects` (TASK-4299).
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
**Re-enumerated on `dev` @ `9f51c7735`** (readiness review, same grep over the 26 `MOVED`
names): 56 files, 215 lines — the per-row counts below; a read-only dry run of the blueprint
script reports `total=216 residual=0`. Rows marked *(C16)* carry the hand-rewritten hook.
**Rev 0.5 (2026-10-20, dev `0263f0724`)**: the three `/sdd-insight` rows are gone (C22) — 53 files,
205 lines, dry run `total=206 residual=0`. Rows tagged *(C21)* / *(C24)* carry those hand edits; the
C22 category edits (A–E) touch a superset of the shipped files, produced at run time by
`test_no_monorepo_source_paths_in_shipped_files` (not enumerated here).

| File | Action | Description |
|---|---|---|
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | Rewrite 1 line(s): select_tests; *(C21)* `:574` |
| `.agent/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/agents/sdd-research/agent.md` | MODIFY | Rewrite 1 line(s): ensure_worktree (`:61`, synced by 542fdbc08) |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Rewrite 6 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests; *(C21)* merge step `:289` |
| `.agents/agents/sdd-ideation/agent.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/agents/sdd-research/agent.md` | MODIFY | Rewrite 1 line(s): ensure_worktree (`:61`, synced by 542fdbc08) |
| `.agents/agents/sdd-worker/agent.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,sdd_meta |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,sdd_meta |
| `.agents/skills/sdd-brainstorm/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-brief/SKILL.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,brief_meta,check_task_graph (rev 0.4 C17) |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Rewrite 12 line(s): check_e2e_closeout,close_resolved_issues,close_task,heal_orphans,sdd_meta,select_tests,test_report; *(C21)* `:94`, `:131-134` |
| `.agents/skills/sdd-fix/SKILL.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agents/skills/sdd-fromjira/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Rewrite 4 line(s): reserve_ids,sdd_meta; *(C21)* hint `:133` |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Rewrite 6 line(s): ensure_worktree,finalize_task |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Rewrite 7 line(s): cache_test_contract,check_task_graph,reserve_ids,sdd_meta; *(C21)* `:110` |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-brief.md` | CREATE | Google twin of `.claude/commands/sdd-brief.md` (`description:` frontmatter + byte-identical body), created BEFORE the rewrite so it is rewritten like the Claude copy (rev 0.4 C17) |
| `.claude/commands/sdd-brief.md` | MODIFY | Rewrite 4 line(s): ensure_worktree ×2, brief_meta (prose `write_brief_index` → `parrot sdd run brief_meta write-index …`), check_task_graph (rev 0.4 C17) |
| `.agent/workflows/sdd-done.md` | MODIFY | Rewrite 12 line(s): check_task_state,close_resolved_issues,close_task,heal_orphans,sdd_meta,select_tests,test_report; *(C24)* new §4.6 E2E gate between `:126` and `:158` + `E2E:` report lines; *(C21)* `:150`, `:158-191`; *(C22 E)* navconfig `:664` |
| `.agent/workflows/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.agent/workflows/sdd-next.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.agent/workflows/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.agent/workflows/sdd-spec.md` | MODIFY | Rewrite 13 line(s): reserve_ids,sdd_meta,spec_tools; *(C21)* hint `:545-550` |
| `.agent/workflows/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.agent/workflows/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.agent/workflows/sdd-task.md` | MODIFY | Rewrite 6 line(s): cache_test_contract,check_task_graph,reserve_ids,sdd_meta; *(C21)* `:361-370` |
| `.agent/workflows/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/qa-runner.md` | MODIFY | Rewrite 1 line(s): select_tests; *(C21)* `:69` |
| `.claude/agents/sdd-contract-probe.md` | MODIFY | *(C22, FEAT-708)* `:19`, `:84` example paths → category A placeholders; `:62` `packages/*/src/` resolution rule → category B (the repo's source roots per `sdd/CONVENTIONS.md` § Repository layout); re-locate by `grep` |
| `.claude/agents/sdd-autopilot.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,select_tests; *(C21)* `:567` |
| `.claude/agents/sdd-coder.md` | MODIFY | *(C16)* hook `:21` → `parrot sdd run worktree_environment --hook \|\| exit 2` (rule 7); C10 pointer `:157` |
| `.claude/agents/sdd-ideation.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/agents/sdd-planner.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,sdd_meta |
| `.claude/agents/sdd-research.md` | MODIFY | Rewrite 1 line(s): ensure_worktree |
| `.claude/agents/sdd-worker.md` | MODIFY | Rewrite 8 line(s): close_task,ensure_worktree,finalize_task,sdd_meta,select_tests + review_checkpoint (:607, :626 — C12); *(C16)* hook `:32` (rule 7); C10 pointer `:537`; *(C21)* merge step `:556` |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-done.md` | MODIFY | Rewrite 14 line(s): check_e2e_closeout,check_task_state,close_resolved_issues,close_task,heal_orphans,sdd_meta,select_tests,test_report; *(C21)* `:184-187`, `:245-278`; *(C22 C/E)* `:239`, navconfig `:781` |
| `.claude/commands/sdd-fix.md` | MODIFY | Rewrite 2 line(s): ensure_worktree,reserve_ids |
| `.claude/commands/sdd-next.md` | MODIFY | Rewrite 2 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-proposal.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `.claude/commands/sdd-spec.md` | MODIFY | Rewrite 13 line(s): reserve_ids,sdd_meta,spec_tools; *(C21)* hint `:541-546` |
| `.claude/commands/sdd-start.md` | MODIFY | Rewrite 5 line(s): close_task,ensure_worktree,finalize_task,sdd_meta |
| `.claude/commands/sdd-status.md` | MODIFY | Rewrite 4 line(s): doc_taxonomy,worktree_status |
| `.claude/commands/sdd-task.md` | MODIFY | Rewrite 6 line(s): cache_test_contract,check_task_graph,reserve_ids,sdd_meta; *(C21)* `:364-373` |
| `.claude/commands/sdd-tojira.md` | MODIFY | Rewrite 1 line(s): sdd_meta |
| `CLAUDE.md` | MODIFY | Rewrite 3 line(s): ensure_worktree,migrate_index,reserve_ids |
| `.claude/rules/worktree-management.md` | MODIFY | Rewrite 4 line(s): ensure_worktree,sdd_meta; *(C22 B)* `PYTHONPATH=` / shared-venv rule `:52` moves to `codebase-conventions.md` |
| `.claude/rules/codebase-conventions.md` | MODIFY | *(C22 B)* receives ai-parrot's own layout / environment rules removed from shipped files (not shipped) |
| `.agent/rules/codebase-conventions.md` | MODIFY | *(C22 B)* byte twin of the row above (`test_rules_parity.py::test_claude_rules_twin_is_identical`) |
| `packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md` | MODIFY | *(C22 B, PR #1746 review)* third byte twin (`test_package_rules_copy_is_identical`; `_rules_data` ≤ 8,000 bytes) |
| `.codex/agents/sdd-worker.toml` | MODIFY | Rewrite 3 line(s): finalize_task,sdd_meta |
| `docs/sdd/WORKFLOW.md` | MODIFY | Rewrite 4 line(s): close_task,ensure_worktree,reserve_ids,select_tests |
| `sdd/templates/intake.procedure.md` | MODIFY | Rewrite 1 line(s): reserve_ids |
| `sdd/templates/task.md` | MODIFY | Rewrite 2 line(s): close_task,ensure_worktree |
| `sdd/templates/spec.md` | MODIFY | *(C21)* §4 Validation Contract hint "repos with `test_command` set: write `none — fallback`" (`:147-158`); *(C22 A)* example operands `:157-158` → placeholders |
| `sdd/WORKFLOW.md` | MODIFY | Rewrite 12 line(s): backfill_taxonomy,check_id_collisions,close_task,doc_taxonomy,ensure_worktree,id_ledger,install_hooks,migrate_index,reserve_ids |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | `ensure_worktree` contract asserts `parrot sdd run ensure_worktree`; `_SHIPPED_WITH_INLINE_PYTHON_BAN` widened to the sdd-worker agent copies (rule 6) and the `sdd-done` / `sdd-tojira` twins (C22 E) |
| `tests/sdd_scripts/test_command_twin_parity.py` | MODIFY | `_TWINNED` gains `"sdd-brief"`; `_SUBSTITUTIONS` anchors follow the C11b `CLAUDE.md`-pointer edits |
| `tests/sdd_scripts/test_sdd_brief_command_contract.py` | MODIFY | `:18` asserts `parrot sdd run ensure_worktree` |
| `tests/sdd_scripts/test_sdd_brief_twin_contract.py` | MODIFY | `_SHARED_TOKENS` `:12` → `"parrot sdd run ensure_worktree"` |
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | MODIFY | `:440` asserts `parrot sdd run check_e2e_closeout`; `_DOC_SURFACES` (`:56`) gains `.agent/workflows/sdd-done.md` (C24, PR #1746 review) |
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | `:129` asserts `parrot sdd run close_resolved_issues` |
| `tests/sdd/test_codex_sdd_sync.py` | MODIFY | Codex worker TOML asserts `parrot sdd run finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Orchestrator-loop assert uses `parrot sdd run finalize_task` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py` | MODIFY | Closure-block markers: new finalize_task / close_task module form |
| `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` | CREATE | Regression: zero `repo-script` findings of ANY kind, zero `org-data` / `claude-md-ref` / `branch-literal` findings, no monorepo source path (C16) and no `python -c` importing `parrot.sdd.scripts`, across the shipped set |

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
# Created by TASK-4085..4088 (+ TASK-4086 for review_checkpoint, C12; TASK-4334 spec_tools; TASK-4508 for
# cache_test_contract / test_report / check_e2e_closeout / close_resolved_issues; worktree_environment per C16
# step 1) — every rewritten reference must resolve as a MODULE (importlib.util.find_spec):
#   parrot.sdd.scripts.<name>   for each of the 26 names in MOVED (blueprint)
# Created by TASK-4299 (C6) — the field names the rewritten text cites must exist on the model:
from parrot.sdd.config import SddConfig, load_sdd_config    # fields: base_branch, staging_branch, hotfix_base,
#   issue_tracker, jira_host, reviewer, test_command — verify in parrot/sdd/config.py before writing prose
```

### Existing Signatures to Use
```python
# tests/sdd_scripts/test_command_contracts.py   (line numbers re-verified on 9f51c7735)
_CREATORS: dict[str, bool] = {...}                              # line 24 (7 command/agent files, incl. sdd-brief.md)
def test_no_command_hand_rolls_a_worktree(rel: str) -> None:    # line 45; message line 48 names the CLI
def test_every_creator_calls_ensure_worktree(rel: str) -> None: # line 53; `assert "scripts.sdd.ensure_worktree" in _read(` line 55
#   module docstring line 7 also names `scripts.sdd.ensure_worktree`; grep -c 'scripts.sdd.ensure_worktree' == 4
_SHIPPED_WITH_INLINE_PYTHON_BAN = (...)                         # lines 102-108 (sdd-spec ×2, sdd-task ×3)
def test_shipped_commands_have_no_inline_python(rel: str) -> None:  # line 115; sdd_meta allowance lines 125-126

# tests/sdd_scripts/test_command_twin_parity.py
_TWINNED = ("sdd-next", "sdd-spec", "sdd-status", "sdd-task")  # line 22
_SUBSTITUTIONS: dict[str, tuple[str, str]] = {...}             # lines 29-42 — anchors pin `CLAUDE.md` lines:
#   sdd-next.md:155 / sdd-spec.md:654 `- Worktree policy: `CLAUDE.md` (section "Worktree Policy")`,
#   sdd-task.md:65 `(sub-features extend a parent feature branch — see `CLAUDE.md`).`; each asserted to occur once
def test_command_twin_parity(name: str) -> None:               # line 73

# tests/sdd_scripts/test_sdd_brief_command_contract.py
def test_provisions_through_ensure_worktree_brief_key() -> None:  # line 15; `assert "python -m scripts.sdd.ensure_worktree" in text` line 18
# tests/sdd_scripts/test_sdd_brief_twin_contract.py
_SHARED_TOKENS = (...)                                          # line 10; `"scripts.sdd.ensure_worktree",` line 12
# tests/sdd_scripts/test_e2e_closeout_contract.py
def test_each_surface_invokes_the_gate_script(path: Path) -> None:  # line 437; `assert "scripts.sdd.check_e2e_closeout" in text` line 440
# tests/sdd/test_ledger_workflow_twins.py
class TestDoneTwins:                                            # line 87
    def test_closes_issues_resolved_by_verified_tasks(self):    # line 125; `assert "scripts.sdd.close_resolved_issues" in content, path` line 129

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

# Twin-parity tests that MUST stay green after the rewrite:
# tests/sdd_scripts/test_command_twin_parity.py::test_command_twin_parity     line 73 — MODIFIED by this task
#   (see above), no longer read-only: the C11b `CLAUDE.md`-pointer edits change its anchors
# tests/sdd/test_ledger_workflow_twins.py  — asserts "reserve_ids"/"ensure_worktree" substrings (lines 179, 257-258):
#   still satisfied by the new form (substring of `parrot sdd run reserve_ids`); its line 129 is MODIFIED (above)
# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:187,197 — assert the substrings
#   "review_checkpoint prepare" / "review_checkpoint validate": still satisfied by `parrot sdd run review_checkpoint prepare`
# NOT in this task's gate any more (C2 — retired by TASK-4090; on 9f51c7735 all 8 `_subagent_data` copies are
# byte-identical to `.claude/agents/`, so test_prompt_parity no longer fails there):
#   packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py::test_prompt_parity
#   packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin

# rev 0.5 C22 — anchors verified on dev 0263f0724:
# .claude/hooks/sdd-worker-format.sh:76 — the ONE C16 allowlisted line (category D; the target repo's own venv):
#   for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \
# packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py (FEAT-553) — THREE byte twins of codebase-conventions.md:
def test_claude_rules_twin_is_identical(name: str) -> None:    # .claude/rules ↔ .agent/rules
def test_package_rules_copy_is_identical(name: str) -> None:   # parrot/flows/_rules_data ↔ .agent/rules
def test_coder_rules_fit_the_prompt_budget() -> None:          # sum of _rules_data/*.md <= 8_000 bytes (5_642 today)
# .agents/skills/sdd-start/SKILL.md:132-133 — the evidence reference C22 E inlines:
#   "read `TaskCompletionEvidence` in `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py`"
# scripts/sdd/cache_test_contract.py:17,46 — prints `fallback` (exit 0) for `none — fallback`; exit 2 on a missing or
#   malformed section (C21: "cache_test_contract stays strict")
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
  `flows/_rules_data/`~~ — verified zero hits; do not touch them for the helper rewrite (C22 B
  edits the three `codebase-conventions.md` twins, `_rules_data` included, for a different reason).
- ~~`SddConfig.projects`~~ on `dev` today — added by TASK-4299 (C22 B: replaces `KNOWN_PROJECTS`
  when set). Prose may cite it only once it exists in `parrot/sdd/config.py`.
- ~~`parrot.sdd.scripts.lint_new` / `token_audit` / `codex_hook`~~ — not moved and (verified
  2026-10-14) referenced by no shipped file; nothing to rewrite. `review_checkpoint` IS moved
  (TASK-4086, C12) and IS rewritten.
- ~~`parrot.sdd.scripts.{cache_test_contract,test_report,check_e2e_closeout,close_resolved_issues}`
  on `dev` today~~ — created by TASK-4508 (a dependency). On `9f51c7735`,
  `scripts/sdd/test_report.py:17` and `scripts/sdd/cache_test_contract.py:14` still load
  `test_scope` through a monorepo path; do not start before TASK-4508 is `done`.
- ~~`parrot.sdd.scripts.worktree_environment` on `dev` today~~ — relocated per C16 step 1 (the
  proposal assigns it to TASK-4085); the frontmatter hook (rule 7) must not be rewritten before
  the module resolves.
- ~~a substitution rule that matches the C16 hook~~ — the hook names
  `$CLAUDE_PROJECT_DIR/packages/…/worktree_environment.py`, which no `scripts/sdd` regex matches;
  rule 7 is a hand edit.

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
      "path": ".claude/agents/sdd-contract-probe.md",
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
      "path": "sdd/templates/spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/codebase-conventions.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/rules/codebase-conventions.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md",
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
      "path": ".agent/agents/sdd-research/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/agents/sdd-research/agent.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-brief/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-brief.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-brief.md",
      "action": "CREATE"
    },
    {
      "path": ".claude/agents/sdd-coder.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_command_twin_parity.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_sdd_brief_command_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_sdd_brief_twin_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_e2e_closeout_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd/test_ledger_workflow_twins.py",
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
    "sym:tests/sdd_scripts/test_command_twin_parity.py#test_command_twin_parity",
    "sym:tests/sdd_scripts/test_command_contracts.py#test_shipped_commands_have_no_inline_python",
    "sym:tests/sdd_scripts/test_sdd_brief_command_contract.py#test_provisions_through_ensure_worktree_brief_key",
    "sym:tests/sdd_scripts/test_sdd_brief_twin_contract.py#test_shared_tokens_in_both_twins",
    "sym:tests/sdd_scripts/test_e2e_closeout_contract.py#test_each_surface_invokes_the_gate_script",
    "sym:tests/sdd/test_ledger_workflow_twins.py#TestDoneTwins.test_closes_issues_resolved_by_verified_tasks",
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py#test_claude_rules_twin_is_identical"
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
  `python -m scripts.sdd.insight` both become `parrot sdd run insight` (rule illustration only — rev 0.5
  C22 keeps the `/sdd-insight` files that carry these forms out of the rewrite); `bash ` prefixes are
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
   `python -m parrot.sdd.scripts.<n> --help` for each name in `MOVED` (incl. `review_checkpoint`
   and TASK-4508's four; `worktree_environment` only needs `importlib.util.find_spec` to resolve),
   and that `parrot.sdd.audit.KINDS` contains `org-data`, `claude-md-ref`, `branch-literal` —
   *why*: rewriting to a module that does not resolve breaks every SDD command; the new tests
   filter on those kind strings.
2. Regenerate the file list with the grep in "Files to Create / Modify" and diff it against the
   table — *why*: other features may have touched these files since `9f51c7735` (last
   re-enumeration); a new hit file means STOP and update this task's table first.
3. Save the one-off script below OUTSIDE the repo (scratchpad), run it without `--write`
   (dry run), then with `--write` — *why*: deterministic and idempotent; never committed.
4. Review `git diff --stat` and spot-check every `close_task`/`heal_orphans` line (per-file
   checklist) — *why*: these change shape (`.sh` → `python -m`), not just a prefix.
5. Apply rule 6 by hand (the 13 `sdd_meta` one-liners → `parrot sdd run sdd_meta …`; the
   `parse` output is still `<type> <base_branch>`, so `sdd-task.md:56-57`'s `awk` lines stay),
   rule 7 (the two C16 frontmatter hooks)
   and the C11b / C6 / C9 / C10 text edits (Scope), driven by
   `python -m parrot.sdd.audit <shipped files>` until the three new kinds report zero — *why*:
   these are prose edits the mechanical script cannot make; the scanner is the oracle.
   Then run `pytest tests/sdd_scripts/test_command_contracts.py::test_shipped_commands_have_no_inline_python -q`
   and confirm its `sdd_meta` allowance is no longer exercised — *why*: TASK-4334 banned inline
   Python in shipped commands; rule 6 retires the last allowed cases.
5b. *(rev 0.5)* Apply the C21 / C22 / C24 hand edits (subsection below) to every twin in the same
   pass, re-running `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q` until the
   C16/C22 gate passes with the single allowlisted line — *why*: one pass keeps the twins
   byte-identical; the gate is the oracle for C22 (its line set is not hand-enumerated).
6. Apply the nine test edits, create `test_no_repo_script_refs.py`, run the Validation
   Commands — *why*: parity + contract tests prove twins and pins are intact.

### Substitution table (old → new; 26 names `N` only; order matters — 5a before 5b)

| # | Old (regex, `[ \t]` = same line) | New |
|---|---|---|
| 1 | `(bash\|sh)[ \t]+(./)?scripts/sdd/<N>.sh` | `parrot sdd run <N>` |
| 2 | `(python\|python3)[ \t]+(./)?scripts/sdd/<N>.py` | `parrot sdd run <N>` |
| 3 | `(./)?scripts/sdd/<N>.sh` (bare, invoked or named) | `parrot sdd run <N>` |
| 4 | `scripts/sdd/<N>.py` (bare prose file reference) | `parrot.sdd.scripts.<N>` |
| 5a | `(python\|python3)[ \t]+-m[ \t]+scripts.sdd.<N>` (invocation) | `parrot sdd run <N>` |
| 5b | `scripts.sdd.<N>` (remaining: `from … import`, `…sdd_meta.plan_worktree` prose) | `parrot.sdd.scripts.<N>` |
| 6 (hand) | `python -c "… from scripts.sdd.sdd_meta import parse\|parse_taxonomy\|resolve_flow …"` — 13 invocations (re-verified on `9f51c7735`): `parse` ×7 — `.claude/commands/sdd-task.md:55`, `.agent/workflows/sdd-task.md:51`, `.claude/commands/sdd-done.md:71`, `.agent/workflows/sdd-done.md:68`, `.claude/agents/sdd-worker.md:152`, `.agent/agents/sdd-worker/agent.md:101`, `.agents/agents/sdd-worker/agent.md:101`; `resolve_flow` ×2 (multi-line) — `.claude/commands/sdd-spec.md:173-180`, `.agent/workflows/sdd-spec.md:177`; `parse_taxonomy` ×4 — `.claude/commands/sdd-spec.md:523`, `.agent/workflows/sdd-spec.md:527`, `.claude/commands/sdd-tojira.md:145`, `.agent/workflows/sdd-tojira.md:145`. (`.agents/skills/sdd-task/SKILL.md:45` is prose → rule 5b, not rule 6.) | `parrot sdd run sdd_meta parse <doc>` / `taxonomy <doc>` / `resolve-flow [--kind K] [--doc PATH] [--type T] [--base B]` — applied AFTER the script, by hand (multi-line shapes); keep the surrounding `$(…)` / `awk` lines working; where the old one-liner printed a different shape than the CLI (`resolve_flow` printed `<type> <base_branch>`, `sdd-tojira.md:145` printed the space-joined projects+tags set) adapt the consumer to the TASK-4299 output, never re-embed Python |
| 7 (hand, C16) | `command: 'python3 "$CLAUDE_PROJECT_DIR/packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py" --hook \|\| exit 2'` (`.claude/agents/sdd-coder.md:21`, `.claude/agents/sdd-worker.md:32`) | `command: 'parrot sdd run worktree_environment --hook \|\| exit 2'` — frontmatter only, byte-identical in both files |

### C21 / C22 / C24 hand edits (rev 0.5 — spec M6 "Rev 0.5 amendments", proposal §3; every twin, same pass)

**C21 — `sdd/config.json` `test_command` is the switch** (semantics — shell string, cwd = repo root,
non-blank — owned by TASK-4299). Sites: the rows tagged *(C21)* in the Files table.
1. When it is set, the shipped `/sdd-done` feature tier, sdd-worker's merge step, qa-runner and
   sdd-autopilot run it once from the repo root instead of `select_tests` / `test_report`. They record
   the command, exit code and output tail; a non-zero exit blocks the merge.
2. When it is null (ai-parrot), the FEAT-699 path is unchanged — the rewritten `parrot sdd run
   select_tests …` / `parrot sdd run test_report …` lines are that branch.
3. A tier that ran no tests is reported "⚠️ not run — no tests selected", never ✅.
4. `sdd/templates/spec.md` §4 and the `/sdd-spec` hint (+ twins) say: "repos with `test_command` set:
   write `none — fallback`".
5. `/sdd-task` continues past a missing Validation Contract section only when `test_command` is set;
   `cache_test_contract` stays strict.

Resolved (PR #1746 review, 2026-10-20): `.claude/agents/qa-runner.md` is not in TASK-4090's asset mapping (`.claude/agents/sdd-*.md`), so it does not ship. Edit it anyway, because C21 names it and ai-parrot's own qa-runner follows the same `test_command` rule. No asset or count change follows.
Resolved (PR #1746 review, 2026-10-20): on both paths the shipped reporting prose owns item 3. When the selected run executed **zero** tests (no `pytest` invocation, or 0 collected), the report line is "⚠️ not run — no tests selected", even when `test_report render` prints its ✅ gate line. `report.py` is unchanged; its own zero-test gate is v1.1 (`issue:dee91130fa06`).

**C22 — monorepo-specific text** (oracle: `test_no_monorepo_source_paths_in_shipped_files`, both patterns):

| Cat | Rule | Examples on dev `0263f0724` (not exhaustive) |
|---|---|---|
| A | Real paths in examples become fixed placeholders: `<src>/<pkg>/module.py`, `<tests>/test_module.py::test_case`, `sym:<src>/<pkg>/module.py#ClassName`. Nothing in A is allowlisted. | `sdd/templates/spec.md:157-158`; `.claude/commands/sdd-task.md:381-416` + twins (`.agents/skills/sdd-task/SKILL.md:141,154`); `.claude/agents/sdd-autopilot.md:663-664` + twins |
| B | Layout, venv activation, `PYTHONPATH` and the `projects` vocabulary point to `sdd/CONVENTIONS.md` (seed sections `## Repository layout`, `## Project areas` — TASK-4090); ai-parrot's own rules move to `.claude/rules/codebase-conventions.md` + `.agent/rules/codebase-conventions.md` (not shipped); `SddConfig.projects` replaces `KNOWN_PROJECTS` when set, unknown values warn and never fail (TASK-4299). | `.claude/rules/worktree-management.md:52`; `KNOWN_PROJECTS` prose (`.claude/commands/sdd-brainstorm.md:188-192` + twins, `sdd-proposal.md:385`, `sdd-spec.md:465`); `sdd/WORKFLOW.md:135`; `sdd/templates/{brainstorm,proposal,spec}.md` (`:7`, `:16`, `:7`) |
| C | This repo's tests or CI cited as evidence: delete the citation, keep the behaviour statement; CI facts become conditions ("if your repo runs a sync-down Action…"). | `.claude/commands/sdd-done.md:239`; `.claude/commands/sdd-task.md:386` + `.agent/workflows/sdd-task.md:382`; `sdd/templates/task.md:281`; `sync-down.yml` (`sdd-done.md:51,676`, `sdd-brainstorm.md:67`, `sdd/WORKFLOW.md:88,93,121`); "the nightly workflow" (`sdd-spec.md:545`, `sdd/templates/spec.md:151`) |
| D | Portable: allowlisted with a reason. Only `.claude/hooks/sdd-worker-format.sh:76` (`${CLAUDE_PROJECT_DIR:-}/.venv/bin`, the target repo's own venv). | `_C16_ALLOWLIST` |
| E | Repo code through `python`: navconfig one-liners become a precondition ("export `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`; see `sdd/CONVENTIONS.md`"); the `sdd-start` evidence reference lists its fields inline. | `.claude/commands/sdd-done.md:781`, `.agent/workflows/sdd-done.md:664`, `sdd-tojira.md:66` + twin, `sdd-fromjira.md:55` + twin; `.agents/skills/sdd-start/SKILL.md:132-133` (`TaskCompletionEvidence`) |

`/sdd-insight` (all hosts) is excluded: not rewritten, not shipped, not scanned.
Resolved (PR #1746 review, 2026-10-20): edit all **three** byte twins identically, including `packages/ai-parrot/src/parrot/flows/_rules_data/codebase-conventions.md`. The dev-loop coder seats load that copy, and they work in ai-parrot worktrees where the moved rules (worktree `PYTHONPATH` prefix, no `uv sync` in a worktree, venv activation) apply. Put the rules as 2–3 lines under the existing `## Repository layout` / `## Tooling` sections (~400 bytes). `test_rules_parity.py` enforces byte identity and the 8,000-byte `_rules_data` budget (5,642 today). If the addition would exceed the budget, STOP and report; do not trim other rules.

**C24 — E2E gate on the Google `/sdd-done` twin.** Port the Claude §4.6 "Verify E2E Evidence"
(`.claude/commands/sdd-done.md:193-243`, as rewritten — `parrot sdd run check_e2e_closeout …`, with the
C22 C citation dropped) into `.agent/workflows/sdd-done.md` between §4.5 (`:126`) and §4.7 (`:158`),
and its `E2E:` lines into that twin's Step 5 report and Step 12 output (Claude `:296`, `:899`, `:915`).
Resolved (PR #1746 review, 2026-10-20): `tests/sdd_scripts/test_e2e_closeout_contract.py::_DOC_SURFACES` (`:56`) gains the Google twin `.agent/workflows/sdd-done.md`. C24 ports the gate there, so the contract test covers all three surfaces.

### All 53 markdown / TOML targets (MODIFY — one-off script, NOT committed)
```python
# occurrences: 206 substitutions across 53 files / 205 lines (rev 0.5: re-verified on 0263f0724 by a read-only dry run
# of this script, /sdd-insight excluded; 216 / 56 on 9f51c7735; 173 / 52 on 6c4ca5482)
# REPLACE — every match of the five rules below, in every file of the table (no single anchor:
#           mechanical rewrite; per-file counts are in the Files table)
"""One-off FEAT-633 TASK-4089 rewrite (scratchpad only). Usage: python rewrite_refs.py --list files.txt [--write]"""
import re
import sys
from pathlib import Path

MOVED = (
    "sdd_meta id_ledger reserve_ids check_id_collisions ensure_worktree finalize_task check_task_state "
    "check_task_graph worktree_status close_task heal_orphans doc_taxonomy backfill_taxonomy migrate_index "
    "select_tests insight install_hooks prune_intake spec_tools review_checkpoint "  # review_checkpoint: C12 (TASK-4086); spec_tools: TASK-4334
    "brief_meta "  # rev 0.4 C17
    "cache_test_contract test_report check_e2e_closeout close_resolved_issues "  # TASK-4508
    "worktree_environment"  # rev 0.3 C16 — 0 regex hits; the hook is rule 7 (hand)
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
`total=206 residual=0` on `0263f0724`, second run `total=0 residual=0`). Write `files.txt` with the 53
MODIFY paths of the table that carry a `scripts/sdd` reference — plus the Google `sdd-brief`
twin once created (one per line); you may append any `_subagent_data/*.md` copy that still
exists (C2 ordering note in Amendments) — it is not asserted.

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)
```python
# occurrences: 4 (verified: grep -c 'scripts.sdd.ensure_worktree' tests/sdd_scripts/test_command_contracts.py)
# REPLACE — all 4 lines (docstring :7, message :48, assert :55, message :57)
#   `scripts.sdd.ensure_worktree` → `parrot sdd run ensure_worktree`
# e.g. line 55 becomes:
    assert "parrot sdd run ensure_worktree" in _read(
# AFTER — `    ".agents/skills/sdd-task/SKILL.md",` inside `_SHIPPED_WITH_INLINE_PYTHON_BAN` (:107) — insert
# (rule 6 retires their only inline Python, the `sdd_meta parse` one-liner):
    ".claude/agents/sdd-worker.md",
    ".agents/agents/sdd-worker/agent.md",
    # rev 0.5 C22 E: the navconfig one-liners become an env-var precondition, so after rules 6 + E these
    # twins carry no inline Python either:
    ".claude/commands/sdd-done.md",
    ".agent/workflows/sdd-done.md",
    ".claude/commands/sdd-tojira.md",
    ".agent/workflows/sdd-tojira.md",
```
**Why**: the old substring is NOT contained in the new form (`parrot sdd run ensure_worktree`),
so the FEAT-552 contract would fail; the contract itself is unchanged. (The creator files invoke
the helper — `python -m scripts.sdd.ensure_worktree …` — so rule 5a applies, not 5b.) The ban
list grows only by files whose inline Python is retired by this task: the rule-6 one-liners and,
since rev 0.5 C22 E, the navconfig one-liners of `sdd-done` / `sdd-tojira` (the commented one in
`sdd-fromjira.md:55` is caught by the second C22 gate pattern, `\bfrom navconfig\b`).

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

### Four more pinned tests (MODIFY — readiness review 2026-10-19)
```python
# tests/sdd_scripts/test_sdd_brief_command_contract.py — REPLACE :18
    assert "parrot sdd run ensure_worktree" in text
# tests/sdd_scripts/test_sdd_brief_twin_contract.py — REPLACE `_SHARED_TOKENS` entry :12
    "parrot sdd run ensure_worktree",
# tests/sdd_scripts/test_e2e_closeout_contract.py — REPLACE :440
    assert "parrot sdd run check_e2e_closeout" in text
# tests/sdd/test_ledger_workflow_twins.py — REPLACE :129 (TestDoneTwins.test_closes_issues_resolved_by_verified_tasks)
            assert "parrot sdd run close_resolved_issues" in content, path
```
**Why**: each pins the old invocation as a substring that the new form does not contain. If the
C11b `branch-literal` edit changes `sdd-brief.md:58`'s refusal text, update its two pins with it
(`test_sdd_brief_command_contract.py:24`, `test_sdd_brief_twin_contract.py:13`). Code-level
imports such as `test_e2e_closeout_contract.py:52` (`from scripts.sdd.check_e2e_closeout import …`)
keep working through the TASK-4508 shim and are not touched.

### `tests/sdd_scripts/test_command_twin_parity.py` (MODIFY)
```python
# REPLACE — :22
_TWINNED = ("sdd-brief", "sdd-next", "sdd-spec", "sdd-status", "sdd-task")
# REPLACE — each `_SUBSTITUTIONS` anchor (:29-42) that the C11b `claude-md-ref` edit changes
#   (sdd-next.md:155, sdd-spec.md:654, sdd-task.md:65 name `CLAUDE.md` today) with the post-edit line, or
#   DELETE the entry when the two twins become byte-identical (modulo frontmatter).
# FILL IN: the post-edit anchor text — bounded by `count == 1` in `_apply_expected_substitution`.
```
**Why**: the C11b edits remove the `CLAUDE.md` lines the tolerated-delta anchors assert exactly
once, so the test is no longer read-only for this task; `sdd-brief` joins `_TWINNED` so the C17
claim that the parity test covers the new Google twin is actually enforced.

### `packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py` (CREATE)
```python
"""FEAT-633 M6 (rev 0.2): no shipped SDD asset references ``scripts/sdd`` at all, and none carries
org data, a ``CLAUDE.md`` pointer or a hardcoded flow base.

Every helper listed in ``_MOVED`` lives in ``parrot.sdd.scripts`` (TASK-4085..4088, C12) and is
invoked as ``parrot sdd run <name>`` (Q1). An installed asset that still says
``python -m scripts.sdd.<name>`` / ``scripts/sdd/<name>.py`` — moved helper or not — is broken in
any repository that is not this monorepo (C12). Shipped files must also be free of
``org-data`` / ``claude-md-ref`` / ``branch-literal`` findings (C11) and of any monorepo source
path — ``packages/``, ``scripts/``, ``$CLAUDE_PROJECT_DIR/…`` (C16) — or other monorepo-specific
text — ``tests/sdd_scripts/``, ``from navconfig``, ``PYTHONPATH=``, ``reference/sdd-insight/`` (C22);
``CLAUDE.md``, ``AGENTS.md`` and ``docs/sdd/WORKFLOW.md`` are repo-only and exempt from those gates,
and ``/sdd-insight`` (all hosts) is neither shipped nor rewritten (C22).
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
    "spec_tools",  # TASK-4334
    "brief_meta",  # rev 0.4 C17
    "cache_test_contract", "test_report", "check_e2e_closeout", "close_resolved_issues",  # TASK-4508
    "worktree_environment",  # rev 0.3 C16
)
_ASSET_GLOBS: tuple[str, ...] = (
    ".claude/commands/*.md", ".claude/agents/*.md", ".claude/rules/*.md", ".claude/skills/**/*.md",
    ".agent/**/*.md", ".agents/**/*.md", ".codex/agents/*.toml",
    "sdd/WORKFLOW.md", "docs/sdd/WORKFLOW.md", "CLAUDE.md", "AGENTS.md", "sdd/templates/*.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/*.md",
)
# The files TASK-4090 actually ships (its Implementation Notes › Asset mapping); the C11 and C16
# gates apply to these only. `_ASSET_GLOBS` above is wider (non-SDD commands/agents/skills, the
# rulebooks, CLAUDE.md / AGENTS.md / docs/sdd/WORKFLOW.md), none of which ships.
_SHIPPED_GLOBS: tuple[str, ...] = (
    ".claude/commands/sdd-*.md", ".claude/agents/sdd-*.md", ".claude/hooks/sdd-worker-format.sh",
    ".claude/rules/worktree-management.md", ".claude/skills/second-opinion/SKILL.md",
    ".agents/skills/sdd-*/SKILL.md", ".codex/agents/sdd-worker.toml", ".agent/workflows/sdd-*.md",
    ".agents/agents/sdd-*/agent.md", "sdd/templates/*", "sdd/WORKFLOW.md", "sdd/CONVENTIONS.md",
)
_C11_KINDS: tuple[str, ...] = ("org-data", "claude-md-ref", "branch-literal")  # FILL IN: verify against parrot.sdd.audit.KINDS
# C16: a monorepo source path — `packages/…`, `scripts/…`, `$CLAUDE_PROJECT_DIR/…` / `${CLAUDE_PROJECT_DIR…}/…`.
_MONOREPO_PATH = re.compile(r"(?<![\w./-])(?:packages|scripts)/|\$\{?CLAUDE_PROJECT_DIR\b[^/\s]*/")
# C22: the second pattern both C16 gates add (this test and TASK-4090's --check / --wheel).
_MONOREPO_TEXT = re.compile(r"tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/")
# (posix path, stripped line) pairs exempted from both patterns — C22 category D: the ONLY entry. Its reason:
# `${CLAUDE_PROJECT_DIR:-}/.venv/bin` is the target repo's own venv, not a monorepo path.
_C16_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    (".claude/hooks/sdd-worker-format.sh", 'for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \\'),
})
# C22: /sdd-insight (all hosts) does not ship and is not rewritten — excluded from every gate here.
_NOT_SHIPPED_PREFIX = "sdd-insight"


def _glob_files(globs: tuple[str, ...]) -> list[Path]:
    """Files matching ``globs`` in the checkout (``.claude/worktrees/`` and ``/sdd-insight`` excluded)."""
    if not (_REPO_ROOT / ".claude").is_dir():
        pytest.skip("not a repo checkout (installed package)")
    files = {p for g in globs for p in _REPO_ROOT.glob(g) if p.is_file()}
    return sorted(
        p for p in files
        if "worktrees" not in p.parts and not any(part.startswith(_NOT_SHIPPED_PREFIX) for part in p.parts)
    )


def _asset_files() -> list[Path]:
    """Every SDD asset in the checkout (``.claude/worktrees/`` excluded)."""
    return _glob_files(_ASSET_GLOBS)


def _shipped_files() -> list[Path]:
    """TASK-4090's shipped set (the C11 publication gate and the C16 path gate apply to these only)."""
    return _glob_files(_SHIPPED_GLOBS)


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
    pattern = re.compile(r"parrot\.sdd\.scripts\.([a-z0-9_]+)")  # digits: check_e2e_closeout
    names = {m for p in _asset_files() for m in pattern.findall(p.read_text(encoding="utf-8"))}
    missing = sorted(n for n in names if importlib.util.find_spec(f"parrot.sdd.scripts.{n}") is None)
    assert not missing, f"unresolvable parrot.sdd.scripts modules referenced: {missing}"


def test_no_inline_python_imports_parrot() -> None:
    """Rule 6: no ``python -c`` in an asset imports ``parrot.sdd.scripts`` (a global-only install's python cannot)."""
    bad = re.compile(r"python3?\s+-c\s+\"[^\"]*parrot\.sdd\.scripts")  # [^"] spans the multi-line resolve_flow block
    offenders = [p for p in _asset_files() if bad.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"inline python still imports a helper (use `parrot sdd run sdd_meta …`): {offenders}"


def test_no_monorepo_source_paths_in_shipped_files() -> None:
    """C16 + C22: no shipped file names ``packages/``, ``scripts/``, ``$CLAUDE_PROJECT_DIR/…`` or other
    monorepo-specific text, except the single category-D line in ``_C16_ALLOWLIST``."""
    offenders = []
    for p in _shipped_files():
        rel = p.relative_to(_REPO_ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            hit = _MONOREPO_PATH.search(line) or _MONOREPO_TEXT.search(line)
            if hit and (rel, line.strip()) not in _C16_ALLOWLIST:
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, "\n".join(offenders)
```
**Why this shape**: the first test is the spec-mandated S5-scanner gate, now over every
`scripts/sdd` reference (C12); the second is the C11 publication gate over shipped files only;
the third pins the Q1 invocation form; the fourth proves each dotted module name an asset still
cites (rules 4 / 5b) actually resolves (spec §5); the fifth proves rule 6 retired all 13
`sdd_meta` one-liners (rule 5b alone would leave them as `python -c "from parrot.sdd.scripts…"`);
the sixth is C16's widened gate ("fails on any monorepo source path in a shipped file") plus C22's
second pattern. On `9f51c7735` it flagged, besides the two hooks rule 7 fixes and the `scripts/sdd`
lines the rewrite removes, 33 more `packages/` lines in 20 shipped files and
`.claude/hooks/sdd-worker-format.sh:76`; rev 0.5 C22 resolves them — categories A, B, C and E rewrite
every line, and D allowlists only the hook line (spec "done when": both C16 gates pass with the single
allowlisted line). `parents[4]`
mirrors `tests/sdd_scripts/test_command_twin_parity.py`'s fixed-depth root.

### Per-file checklist (after `--write`)
- [ ] `git diff --stat` lists the 53 markdown/TOML files of the table (+ the created Google
      `sdd-brief` twin, `.claude/agents/sdd-coder.md`, `sdd/templates/spec.md` and the two
      `codebase-conventions.md` twins), the shipped files touched by the C11b / C6 / C9 / C21 / C22
      hand edits, and the 10 test files — nothing else (no `sdd-insight` file).
- [ ] `.claude/commands/sdd-done.md` / `.agent/workflows/sdd-done.md` / `.agents/skills/sdd-done/SKILL.md`:
      `(cd "$WORKTREE_PATH" && parrot sdd run close_task "$TASK_ID" …)` and the
      `heal_orphans` lines keep their arguments; the ```` ```bash ```` fence lines are intact.
- [ ] `sdd-start` (3 hosts) + `sdd-worker` (3 host copies): `close_task` / `finalize_task` lines read naturally.
- [ ] `sdd-insight` (3 hosts): untouched — not rewritten, not shipped (rev 0.5 C22).
- [ ] *(C21)* every `/sdd-done` feature-tier, sdd-worker merge, qa-runner and sdd-autopilot test step
      reads: `test_command` set → run it once from the repo root, record command / exit code / output
      tail, non-zero blocks the merge; null → the `parrot sdd run select_tests` / `test_report` path;
      zero tests → "⚠️ not run — no tests selected"; `/sdd-task` continues past a missing Validation
      Contract only when `test_command` is set; the spec template and `/sdd-spec` hint carry "repos with
      `test_command` set: write `none — fallback`".
- [ ] *(C22)* categories A–E applied on every twin; `test_no_monorepo_source_paths_in_shipped_files`
      reports nothing beyond the single allowlisted hook line; ai-parrot's moved rules sit in both
      `codebase-conventions.md` twins (and `test_rules_parity.py` still passes).
- [ ] *(C24)* `.agent/workflows/sdd-done.md` has §4.6 (`parrot sdd run check_e2e_closeout …`) between
      §4.5 and §4.7, and `E2E:` lines in its Step 5 report and Step 12 output.
- [ ] `sdd-spec`/`sdd-task`/`sdd-done`/`sdd-tojira` + the three `sdd-worker` copies: the 13 `sdd_meta`
      one-liners now read `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`
      (rule 6); no `from parrot.sdd.scripts.sdd_meta import` remains inside a `python -c` string.
- [ ] *(C16)* `.claude/agents/sdd-coder.md:21` / `sdd-worker.md:32` frontmatter hooks read
      `parrot sdd run worktree_environment --hook || exit 2` (rule 7); YAML quoting intact.
- [ ] *(TASK-4508 helpers)* `sdd-done` (3 hosts): `check_e2e_closeout` (Claude + Codex only),
      `test_report decide-rerun|render` and `close_resolved_issues` lines keep their flags and `\`
      continuations; `sdd-task` (3 hosts): `parrot sdd run cache_test_contract --spec … --index …`.
- [ ] *(rev 0.4 C17)* `sdd-brief` (3 hosts; the Google twin is created first): the two
      `python -m scripts.sdd.ensure_worktree … --brief-key …` lines read `parrot sdd run ensure_worktree …`,
      the prose `scripts.sdd.brief_meta.write_brief_index` reads `parrot sdd run brief_meta write-index …`,
      `python -m scripts.sdd.check_task_graph` reads `parrot sdd run check_task_graph`; the twin parity
      test covers `sdd-brief` (`.claude/commands` ↔ `.agent/workflows`).
- [ ] No inline `python -c` block remains in `sdd-spec` / `sdd-task` (TASK-4334 retired the former
      `sdd-spec.md:290,362,381,393,542,666` blocks into `spec_tools`; on `9f51c7735` only the rule-6
      one-liners `:173` and `:523` were left); the `sdd_meta` allowance of
      `test_shipped_commands_have_no_inline_python` is exercised zero times.
- [ ] `.claude/agents/sdd-coder.md` / `sdd-worker.md` point at `sdd/CONVENTIONS.md` (C10);
      `.claude/skills/second-opinion/SKILL.md` has no `CLAUDE.md` pointer and no `agy` text (C9).
- [ ] `sdd/templates/task.md` lines 329 and 344 now name `parrot sdd run ensure_worktree`
      / `parrot sdd run close_task`.
- [ ] `.claude/agents/sdd-worker.md:607,626` now read `parrot sdd run review_checkpoint prepare …` /
      `… validate …` with their flags intact (C12).
- [ ] No shipped file contains `trocglobal`, a `NAV-<n>` key, the string `agy`, or `CLAUDE.md`
      (C11b); `sdd-codereview` / `sdd-secondopinion` reference `second-opinion` conditionally (C9);
      flow bases are cited through `sdd/config.json` (C6).

### FILL IN checklist
- [ ] Confirm `parrot.sdd.scripts.prune_intake` exists (TASK-4088) before running; it has 0 markdown hits today.
- [ ] Confirm TASK-4508's four modules and `parrot.sdd.scripts.worktree_environment` (C16) resolve before
      running rule 7 / the script.
- [ ] `test_command_twin_parity.py` `_SUBSTITUTIONS` — the post-C11b anchor text, or delete the entry;
      bounded by `count == 1`.
- [ ] `_C16_ALLOWLIST` — fixed by rev 0.5 C22 D: exactly the one `sdd-worker-format.sh:76` entry; add nothing else.
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
- [ ] `.claude/agents/sdd-worker.md:607,626` invoke `parrot sdd run review_checkpoint` (C12).
- [ ] *(C16)* `.claude/agents/sdd-coder.md:21` and `.claude/agents/sdd-worker.md:32` run
      `parrot sdd run worktree_environment --hook || exit 2`; no shipped file names a monorepo source
      path (`test_no_monorepo_source_paths_in_shipped_files`).
- [ ] *(rev 0.5 C22)* Both gate patterns pass over the shipped set with the single allowlisted line
      (`.claude/hooks/sdd-worker-format.sh:76`); categories A–E applied to every twin; ai-parrot's own
      layout / environment rules live in `.claude/rules/codebase-conventions.md` and
      `.agent/rules/codebase-conventions.md` (byte-identical); `/sdd-insight` is untouched.
- [ ] *(rev 0.5 C21)* In every shipped test step named by C21, `test_command` set → run once from the
      repo root (command, exit code, output tail recorded; non-zero blocks the merge), null → FEAT-699
      path unchanged; zero tests is "⚠️ not run — no tests selected", never ✅; `/sdd-task` continues
      past a missing Validation Contract only when `test_command` is set; `sdd/templates/spec.md` and
      the `/sdd-spec` hint say "repos with `test_command` set: write `none — fallback`".
- [ ] *(rev 0.5 C24)* The Google `.agent/workflows/sdd-done.md` runs the E2E closeout gate
      (`parrot sdd run check_e2e_closeout …`) before any stamp/push/merge/cleanup step, like its
      Claude and Codex twins.
- [ ] No shipped file carries an `org-data`, `claude-md-ref` or `branch-literal` finding (C11b/C6);
      `CLAUDE.md` / `AGENTS.md` / `docs/sdd/WORKFLOW.md` are exempt (repo-only).
- [ ] `second-opinion` references in shipped files are conditional on `reviewer: codex` in
      `sdd/config.json` (C9).
- [ ] The command twin parity test passes (`.claude/commands` ↔ `.agent/workflows`, `_TWINNED`
      incl. `sdd-brief`); no `_subagent_data` parity is asserted (C2).
- [ ] The eight updated contract tests pass against the rewritten assets.
- [ ] `test_no_repo_script_refs.py` passes (all six tests).
- [ ] The 13 `sdd_meta` one-liners invoke `parrot sdd run sdd_meta parse|taxonomy|resolve-flow`
      (rule 6) and `sdd-task`'s `TYPE=`/`BASE=` `awk` split still works on `parse`'s output;
      `test_no_inline_python_imports_parrot` passes.
- [ ] No inline `python -c` block remains in `sdd-spec` / `sdd-task` (TASK-4334 retired the former
      residual list); the `sdd_meta` allowance of `test_shipped_commands_have_no_inline_python` is
      exercised zero times; after C22 E no navconfig one-liner remains, and the widened ban list
      (sdd-worker copies, `sdd-done` / `sdd-tojira` twins) passes.
- [ ] No shipped file references `codebase-conventions.md`; the two former references point at
      `sdd/CONVENTIONS.md` (C10).
- [ ] Re-running the rewrite script reports `total=0 residual=0` (idempotent).
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py`
      and the nine modified test files.

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
- `pytest tests/sdd_scripts/test_sdd_brief_command_contract.py tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py — see the CREATE block above:
#   test_no_repo_script_findings_at_all              (S5 scanner gate, any scripts/sdd ref — C12)
#   test_no_publication_findings_in_shipped_files    (org-data / claude-md-ref / branch-literal — C11)
#   test_every_invocation_uses_parrot_sdd_run        (Q1 form)
#   test_every_rewritten_reference_resolves          (dotted module names import)
#   test_no_inline_python_imports_parrot             (rule 6 — all 13 sdd_meta one-liners retired)
#   test_no_monorepo_source_paths_in_shipped_files   (C16 + C22 second pattern; one allowlisted line)
# Existing tests updated (assert the new form; intent unchanged):
#   tests/sdd_scripts/test_command_contracts.py::test_every_creator_calls_ensure_worktree
#   tests/sdd_scripts/test_command_contracts.py::test_shipped_commands_have_no_inline_python (ban list widened)
#   tests/sdd/test_codex_sdd_sync.py::test_worker_uses_deterministic_finalization_and_scoped_force_add
#   packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py::
#       test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop
#   packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py::
#       test_start_twins_preserve_semantic_gates
#   tests/sdd_scripts/test_sdd_brief_command_contract.py::test_provisions_through_ensure_worktree_brief_key
#   tests/sdd_scripts/test_sdd_brief_twin_contract.py::test_shared_tokens_in_both_twins
#   tests/sdd_scripts/test_e2e_closeout_contract.py::test_each_surface_invokes_the_gate_script
#   tests/sdd/test_ledger_workflow_twins.py::TestDoneTwins::test_closes_issues_resolved_by_verified_tasks
#   tests/sdd_scripts/test_command_twin_parity.py::test_command_twin_parity (`_TWINNED` + anchors)
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
