# FEAT-633 readiness checkpoint — 2026-10-19

**Feature**: FEAT-633 `parrot-installer` · **Spec**: `sdd/specs/parrot-installer.spec.md` rev 0.4 (approved)
**Verified against**: `origin/dev` `9f51c7735` (refreshed to `dac9766b7` for the edits)
**Index**: `sdd/tasks/index/parrot-installer.json`: 33 tasks (32 pending, TASK-4334 done);
`check_task_graph` exits 0 with 8 waves and one expected warning (TASK-4299's validation file is created by its dependency TASK-4298).

## Verdict

- **The spec is still a sound basis.** Nothing merged on `dev` since rev 0.4 conflicts with
  M0–M5, M7 or M8. A **rev 0.5** is needed before the M6 chain (SDD packaging) starts. The rev 0.5
  items are listed below.
- **Every pending task was refreshed** against `dev`: line anchors, counts, file rows,
  validation commands, stale claims, and the folding-in of approved amendments C16/C17 that had not
  reached the task files. Each touched task has a `## Readiness review — 2026-10-19` section that
  states what changed and any **open decision**. Implementers must not build the part an open
  decision covers until it is resolved.
- **Two new tasks** (ids reserved in `dac9766b7`):
  - **TASK-4508 — helpers move D.** The shipped markdown calls four helpers that no move task
    covered: `cache_test_contract`, `test_report`, `check_e2e_closeout` and
    `close_resolved_issues`. TASK-4089 now depends on it.
  - **TASK-4509 — launcher fast path for `parrot sdd run worktree_environment --hook`.** This is
    rev 0.3 C16, split out of TASK-4072 so the launcher does not wait on `parrot.sdd`.

## How this was verified

1. A mechanical drift scan: for every path a task references, commits on `dev` since the task was
   last touched, plus CREATE targets that already exist and MODIFY targets that are missing.
2. Seven independent read-only reviews, one per area (launcher/bootstrap, toolkits/self, hosts,
   wiki store, SDD helper moves, SDD markdown/assets) plus one for the spec. Each checked Files
   tables, Codebase Contracts and `file:line` anchors against `dev` and read the relevant diffs.
3. The same reviewers applied only the findings that needed no decision. Escalations were recorded
   as open decisions, not applied. Key claims were re-verified independently: C16 was never folded
   into its tasks (commit `63f40570e` touched only the spec and proposal), the four uncovered
   helpers are real, `_lazy_commands` has 25 entries, and the C16 `test_scope` lookup hazard is
   real.

## What changed on `dev` that matters to FEAT-633

| Change | Effect on FEAT-633 |
|---|---|
| FEAT-699 tests-optimization (`cache_test_contract`, `test_report`, `select_tests` 130→359 lines, `test_scope/{baseline,green_cache}`) | New helpers to move (TASK-4508); C7/Validation Contract question (D2) |
| FEAT-703 E2E closeout gate (`check_e2e_closeout`, `/sdd-done` rewired) | Helper to move (TASK-4508); the Google twin has no gate (D9) |
| `close_resolved_issues` (2026-10-16, missed by rev 0.3/0.4) | Helper to move (TASK-4508) |
| FEAT-694 shared ledger event log (managed git hooks, `.gitattributes merge=union`) | Hosts: new hook emitters (TASK-4081); foreign repos get neither (D5) |
| FEAT-698 `/sdd-brief` (rev 0.4 C17) | `brief_meta` fold-in completed in TASK-4085/4299 |
| wiki tools moved to `parrot_tools.wiki.tools` (`fae0b33b9`, `4bef2a3c8`) | `wikitoolkit mcp` needs ai-parrot-tools (D1) |
| graphindex `WikiBackendSpec` (`6791d81ce`) | `store.py` anchors moved +144 (TASK-4092/4093) |
| FEAT-569 `--remote` in the Claude/Codex installers (`6b30156ad`, `a6340733f`) | TASK-4082/4083 blueprints now keep `remote=` (they would have regressed it) |

## Task status

| Task | Verdict | Open decisions |
|---|---|---|
| 4068 S1 smoke + matrix | updated | D1 |
| 4069 S3 host env probe | updated (anchors) | — |
| 4070 S5 asset audit | updated (helper map regenerated) | D11 |
| 4071 launcher core | updated | D14 |
| 4072 launcher re-exec | current (C16 split to 4509) | — |
| 4073 parrot_home consolidation | updated (anchors) | — |
| 4074 / 4075 bootstrap sh / ps1 | updated / current | D1 |
| 4076 bootstrap CI | current | — |
| 4077 template install metadata | updated (anchors) | D12 |
| 4078 toolkits hint | current | — |
| 4079 self components | updated (pyvenv, kept user data) | — |
| 4080 self CLI + doctor | updated (`_check_python` accepts `3.12`) | D13 |
| 4081 Claude emitters | updated (false Windows claim removed) | D6 |
| 4082 Claude installer | updated (keeps `remote=`) | D6, D7 |
| 4083 Codex | updated (keeps `remote=`) | D7, D16 |
| 4084 Google | current | — |
| 4085 helpers move A | updated (C17 completed, C16 folded and gated) | D4 |
| 4086 / 4087 / 4088 helpers move B1/B2/C | updated | — |
| 4089 markdown rewrite | updated (+4508 dep, C16, rule 6 → 13 one-liners, counts 56 files / 216) | D2, D3, D9, D18 |
| 4090 asset packaging | updated (81 assets, C16 gate) | D3 |
| 4091 `parrot sdd` CLI | updated (scenarios, invocation parsing, C16 test) | D2, D5 |
| 4092 / 4093 wiki store | updated (+144 anchors) | D8 |
| 4094 core wheel matrix | updated | D1, D15 |
| 4095 docs | updated | D2 (do not document `test_command` yet) |
| 4298 branch policy | updated | — |
| 4299 `sdd/config.json` | updated | D10 |
| **4508** move D | **new** | — |
| **4509** hook fast path | **new** | D4 (hook command form), D17 |
| 4334 spec_tools | done (on `dev`) | — |

## Decision register

Recommendations are the reviewer's, for the owner (Jesus) to confirm or replace.

| # | Decision | Evidence | Affects | Blocks | Recommendation |
|---|---|---|---|---|---|
| D1 | `wikitoolkit mcp` needs ai-parrot-tools; core-only installs fail the MCP handshake | `parrot_tools.wiki.tools` (`wiki/tools.py:69-76`); `mcp_server.py:348-362,525-545`; the SDK fallback crashes on `mcp` 2.x (`:471`) | 4068, 4074, 4075, 4094 | S1 spike outcome, bootstrap install spec | Fix core: `auto` falls back cleanly when `parrot_tools` is missing (ledger bug). Until then, install `ai-parrot-tools` with the same pin |
| D2 | FEAT-699 vs C7: FEAT-633's spec has no Validation Contract; how the cache/select/report steps behave in a foreign repo; the `test_command` override | `cache_test_contract --check` exits 2 on this spec; `sdd-task.md:365-375`; C7 has no owner | 4089, 4091, 4095 | M6 | Add §4 Validation Contract (`none — fallback` allowed). C7 clause: when `test_command` is set, skip the three steps. Owner TASK-4089 |
| D3 | The C16 widened test vs ~33 `packages/` lines in 20 shipped files, `sdd-worker-format.sh:76`, and 4 `tests/sdd_scripts` refs | TASK-4089/4090 readiness sections | 4089, 4090 | M6 (C16 gate stays red) | Decide per file: rewrite to `parrot sdd run`/prose, or allowlist with a reason |
| D4 | C16 move mechanics: `_load_guard_bash` relative `test_scope` import breaks after the move and `_scope_guard` fails **open**; a by-path shim needs bare `python3` to work; the programmatic hook command form | `worktree_environment.py:294-307,336-340`; `dispatchers/claude.py:625`; `test_worktree_environment.py:273-295` | 4085, 4509 | the C16 rows of 4085; 4509 | Package-relative kernel path (as 4086/4088 do). Keep the old path runnable by path. Programmatic hook: `sys.executable -m parrot.sdd.scripts.worktree_environment --hook` |
| D5 | Foreign repos get no `.gitattributes merge=union` and no ledger hooks | only `parrot claude install` writes the hooks (`installer.py:973`) | 4091, 4080 | — | `parrot sdd install` writes a marker-block `.gitattributes`, records it in the receipt, ensures the ledger hooks; `doctor --sdd` checks both |
| D6 | Windows: hook bodies interpolate an unquoted path into `#!/bin/sh`; `_is_wikitoolkit_entry` treats `.exe` as foreign | `claude_code/assets.py:206-207,236`; `installer.py:762` | 4081, 4082 | the M5 Windows ACs | Extend 4081/4082 (quote and use forward slashes; match on the basename) |
| D7 | `--remote` × `--portable`: an http/url entry is read as "baked", so portable mode is lost | `claude_code/assets.py:134`; `codex/assets.py:111-118` | 4082, 4083 | sticky-portable AC | `--remote` decides only the `wikitoolkit` key; infer the mode from the managed `parrot-*` entries |
| D8 | Wiki store: stamp in `_ensure_schema` and/or refuse a downgrade; `SourceRegistry` bypasses the gate; lock/backup in an unwritable directory | `store.py:1300-1303,1585`; `sources.py:795-810,983-1003`; `store.py:1377-1379` | 4092, 4093 | M7 | Stamp at creation **and** refuse stored version > `SCHEMA_VERSION`. A clear error in an unwritable directory. `SourceRegistry` as an explicit follow-up |
| D9 | The Google `/sdd-done` twin has no E2E gate | FEAT-703 covered two twins (`fixgroup-603217cacd87.spec.md:142,279`) | 4089 | — | Port it during the rewrite |
| D10 | `brief_meta` / `ensure_worktree` hard-code the branch policy and ignore `sdd/config.json` | `brief_meta.py:28,45-55,98,166`; `ensure_worktree.py:304,318` | 4299 | — | Extend 4299 (it already owns the residual literals) |
| D11 | The S5 scanner scans only `.claude/`, but `.agents/skills` and `.agent/workflows` also ship | TASK-4070 | 4070 | — | Widen the default globs |
| D12 | `bounded-source.yaml` / `targeted-writer.yaml` load ai-parrot-tools without `requires_dist` | TASK-4077 | 4077 | — | Add to 4077's scope |
| D13 | doctor ignores Gemini's repo-local `mcp_config.json` | `google/installer.py:142-152,175-200` | 4080 | — | Check both files; keep the collision check on the user-global one |
| D14 | Launcher `.git` walk-up should stop at the system temp dir | `7e961b885`, `project.py:1011-1031` | 4071 | — | Mirror `_is_temp_root` with stdlib `tempfile` |
| D15 | No linux-aarch64 install-matrix leg | TASK-4094 | 4094 | — | Add the leg, or record the gap |
| D16 | `mcp/local_cli.py` is in scope in Files/AC but excluded in NOT-in-scope | TASK-4083 (already the case at baseline) | 4083 | — | Keep it in scope (it is the majority intent); drop the exclusions |
| D17 | Latency budget for the `--hook` fast path | C16 "Open" | 4509 | — | Reuse the S4 targets (≤ 5 ms non-managed, ≤ 50 ms managed) |
| D18 | Navconfig `python -c` lines keep `sdd-done`/`sdd-tojira` out of the inline-python ban | `sdd-done.md:781`, `sdd-tojira.md:66`, `sdd-fromjira.md:55` | 4089 | — | Move them behind a `parrot sdd run` helper, or allowlist them |

### Spec rev 0.5 (needed before the M6 chain)

- M6 helper list: every moving module, which is 26 plus `__init__` (adds `review_checkpoint`,
  `spec_tools`, `prune_intake`, `brief_meta`, `worktree_environment` and the four TASK-4508
  helpers), and "every `_KERNEL_PARENT` path loader becomes package-relative". The C12 premise is
  stale.
- D2 (Validation Contract + C7 owner), D3, D4, D5 and D6 as clauses.
- Counts: 13 templates (not 14); `scripts/sdd/` has 31 Python helpers, 2 `.sh`, 2 baseline JSON;
  `[project.scripts]` has 4 entries (`parrot-graphindex` stays outside the launcher, per
  TASK-4072); `_lazy_commands` has 25 entries.
- §6 anchor refresh (`store.py` +144, `project.py`, `claude_code/*`, `codex/*`, `pyproject.toml`).

## What can start now

Wave 1 (no dependencies):
- **Clean:** TASK-4069 (S3) and TASK-4298 (branch policy).
- **Startable; their open decision is low-impact and can be settled at pickup:** TASK-4070
  (D11), TASK-4071 (D14), TASK-4077 (D12).
- **Decide first:** TASK-4068 (D1 changes what S1 expects) and TASK-4092 (D8 changes the stamping
  design).

Blocked on spec rev 0.5: the M6 chain, TASK-4085 → 4508/4086/4087/4088 → 4089 → 4090 → 4091.
TASK-4085's C17 part and its non-C16 moves are otherwise ready, but its C16 rows are gated on D4.

## Environment notes

- `ensure_worktree` creates `feat-FEAT-633-parrot-installer` from `origin/dev` on a machine with no
  local branch of that name. The remote branch of that name is fully merged (0 ahead, 159 behind
  `dev`), so the push is a fast-forward. On a machine that still has the old local worktree, merge
  `origin/dev` into it first.
- Package-level tests do not collect from a fresh worktree using `PYTHONPATH` alone: the Cython
  module `parrot.utils.types` is not built there. Root `tests/` suites run.
- The id reservation commit `dac9766b7` is unsigned (`reserve_ids` makes its own commit).

## Ledger follow-ups (unrelated to the task content)

- The 15 FEAT-649 issues restored in PR #1738 exist only as snapshot rows until the `revbot`
  machine runs `wikitoolkit ledger import-log && wikitoolkit ledger export-log`.
- `issue:792b6e2a8f25` has a claim conflict in the shared log (`agent:sdd-brief` vs `agent:sdd-fix`).
- `issue:1752eb466e1e` (CI guard against snapshot row removal) is open.
