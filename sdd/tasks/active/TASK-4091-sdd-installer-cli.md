# TASK-4091: parrot sdd install|uninstall|status|run + lazy registration

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h) — was M; raised by the rev 0.2 amendments (receipt, dry-run, `run`, seeds, wheel-only test)
**Depends-on**: TASK-4070, TASK-4080, TASK-4090, TASK-4299
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview piece 4 and §3 Module 6: the SDD flow becomes installable into any repository
with `parrot sdd install [--host claude|codex|google]`, deploying the packaged assets that
TASK-4090 placed under `parrot/sdd/_assets/` (listed in `_assets/manifest.json`). The installer
follows the wiki installers' discipline — never clobber foreign content, warn-and-skip on
collisions, re-runnable, uninstall removes exactly what it installed — and, per codex S9,
**reports clearly** when an installed asset references tooling unavailable on the target
machine, using the spike-S5 scanner `parrot.sdd.audit` (TASK-4070).

The command registers lazily in `parrot/cli/__init__.py::cli._lazy_commands` (spec §6 Edit
Sites, `cli/__init__.py:109`), serialized after TASK-4080 which adds `"self"` to the same dict.

---

## Amendments — spec rev 0.4 (2026-10-18)

- **C17 — `/sdd-brief` (FEAT-698) scenarios.** The installed `sdd-brief.md` (plus its Codex
  and Google twins, the latter created by TASK-4089) carries three `parrot sdd run` forms the
  C3 test must cover with a `Scenario` each: `ensure_worktree --json --slug <slug>
  --brief-key <KEY> --base-branch <base>` (fixture repo with the bare origin; expects a
  `hotfix-<KEY>-<slug>` / `fix-<KEY>-<slug>` worktree and no upstream set),
  `brief_meta write-index <brief.md> --tasks <tasks.json> --worktree-root <wt>` (fixture brief
  rendered from `sdd/templates/brief.md`, which TASK-4090 ships; one task dict) and
  `check_task_graph <wt>/sdd/briefs/<slug>.index.json` (already a scenario for `/sdd-task`;
  reuse it with the brief index). `parrot sdd install --host google` is expected to write
  `.agent/workflows/sdd-brief.md`; `--host claude|codex|google` all write
  `sdd/templates/brief.md`. A `brief_meta` invocation with no scenario fails the test, as for
  every other helper.

## Amendments — spec rev 0.2 (2026-10-14)

- **Cross-task interface (TASK-4094)**: `test_wheel_only_foreign_repo.py` honours an optional
  `PARROT_WHEEL_PATH` environment variable — when set, it skips `uv build --wheel` and installs
  that wheel instead, so the release workflow's `smoke-sdd-foreign` job can run the same test
  against the built artifact. Unset → build locally as described below.

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3, §5; decisions by
Jesus Lara, 2026-10-14). Every section below is already rewritten to match; this list is the
delta for reviewers.

- **C4 — install receipt (reverses the "no hash manifest" wording).** The installer records
  the SHA-256 of the bytes it wrote per target, plus the ai-parrot version that wrote it, in a
  **committed** `sdd/.sdd-installed.json` (the `sdd/` tree is committed; `.parrot/` is
  gitignored at `.gitignore:411`). The conflict rule becomes receipt-driven:
  absent → write + record · matches the record → upgrade (overwrite + re-record) ·
  differs from the record → edited by the team → skip + `warning:` unless `--force` ·
  not in the record → foreign → skip + `warning:`, **never overwritten, even with `--force`**.
  Interpretation fixed here: a file not in the record but **byte-identical** to the packaged
  copy is adopted as `current` and recorded (harmless; covers installs made before the
  receipt existed). `uninstall` removes only files whose SHA matches the record.
  `parrot sdd status` classifies each manifest target as
  `missing | current | outdated | edited | foreign`.
- **C5 — `--dry-run`** on `install` and `uninstall`: prints the exact plan (one line per
  target: write / upgrade / overwrite / skip-current / skip-edited / skip-foreign / remove /
  keep-edited / keep-foreign, plus the `.gitignore` block, the ledger seed, the config seed and
  the conventions seed) and changes nothing — the test hashes every file under the repo
  before and after.
- **Q1 — `parrot sdd run <name> [ARGS]...`** joins the group. Shipped markdown (TASK-4089,
  rev 0.2) now invokes helpers as `parrot sdd run <name>`, never `python -m
  parrot.sdd.scripts.<name>`: `python -m` runs whatever `python` is first on PATH, which in a
  foreign repo has no ai-parrot; everything entering through `parrot` inherits the M1 launcher's
  venv resolution. `run` sets `sys.argv` and calls `runpy.run_module(..., run_name="__main__",
  alter_sys=True)`, propagates the helper's exit code, and lists available helpers
  (`pkgutil.iter_modules` over `parrot.sdd.scripts` — every module, `sdd_meta` included: after
  TASK-4299 it has a `main()` and shipped markdown invokes `parrot sdd run sdd_meta parse|taxonomy|resolve-flow …`) on an unknown
  name. `python -m parrot.sdd.scripts.<name>` keeps working for direct use.
- **C6 seed** — `install` seeds `sdd/config.json` from `parrot.sdd.config.default_sdd_config()`
  (TASK-4299) when absent; never overwrites it. New dependency: TASK-4299.
- **C10 seed** — `install` applies a **write-once rule to every manifest entry carrying the
  optional `"seed": true` key** (TASK-4090 rev 0.2 adds the key; manifest `schema_version`
  stays 1; a missing key means `false`). Today that is `sdd/CONVENTIONS.md`, but the installer,
  `status` and the tests are generic over the flag — never a hardcoded path. Seeds are written
  only when absent, never overwritten (not even with `--force`), never recorded in the receipt
  (team-owned), and never removed by `uninstall`; `status` reports each as `seed-present | missing`.
- **C15 hook** — `sdd_status(root)` is the public, import-cheap entry point `parrot self doctor`
  (TASK-4080) calls lazily to report whether installed SDD files are current. Nothing else in
  this task changes for TASK-4080's benefit; TASK-4080 must tolerate `parrot.sdd.installer`
  being absent.
- **Q1 residual — `spec_tools` scenarios (TASK-4334, 2026-10-15).** The wheel-only test's
  per-helper `Scenario` set must cover every `parrot sdd run spec_tools <sub>` invocation the
  installed markdown carries (`init-run`, `render-brief`, `stamp-run`, `validate-suggestions`,
  `check-path`, `existing-feature-id`, `commit-intake`): the fixture repo needs
  `sdd/templates/design_research.{prompt.md,schema.json}` (shipped by TASK-4090) and a `$DR`
  directory holding the six brief inputs plus a `suggestions.json` of the sample shape.
- **C3 — wheel-only foreign-repo test (proposal rev 0.3 wording).** New
  `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (explicit
  `pytestmark = pytest.mark.integration`, skipped unless `uv` is on PATH). It:
  1. builds the ai-parrot wheel (`uv build --wheel`);
  2. creates a temporary `PARROT_HOME` whose venv has ai-parrot installed **from that wheel
     with its declared runtime dependencies** (`uv pip install <wheel>`, non-editable, no
     monorepo path);
  3. `git init`s an unrelated, non-Python repo with one commit and a local **bare `origin`**;
  4. runs `parrot sdd install` there for all three hosts (`--host claude --host codex --host google`;
     readiness review 2026-10-19 — was `--host claude`, which left the AC's "all three hosts" unproven);
  5. runs **every helper invocation found in the installed markdown using its documented
     command and flags** — placeholders (`<FEAT-ID>`, `<slug>`, `<path>`, `TASK-<NNN>` …)
     substituted with fixture values, and each invocation's required state supplied by a
     per-helper scenario (committed ledger pushed to the bare origin, task files, index,
     evidence where needed), with isolated state per scenario (fresh clone per invocation).
     Helper implementations are **not mocked**; a helper name found in markdown with no
     scenario fails the test;
  6. uses `PATH=$PARROT_HOME/bin:<tools-dir>` where `<tools-dir>` exposes an explicit
     allowlist of system tools (`git`, plus `bash`/`jq` only when an invocation needs them);
     project/test venv bins are excluded; `PYTHONPATH`, `PYTHONHOME`, `VIRTUAL_ENV`,
     `PARROT_VENV`, `PARROT_PROJECT` and `CONDA_PREFIX` are unset; and asserts that `parrot`
     and the helper interpreter resolve to the temporary managed install (`parrot self env`
     reports the managed venv and rule `managed`).
  This is the proof of Q1: it fails by design while any shipped file still says `python -m
  parrot.sdd.scripts…`, and it proves system prerequisites remain available while ai-parrot
  loads only from the wheel. It builds a wheel (minutes), so it runs in the **merge tier only**
  (`-m integration`), never in the task-tier selector. TASK-4094 reuses it as the release smoke.
- **Effort** raised M → L. The spec §4/§5 rows this task implements are the rev 0.2 ones
  (`test_sdd_flow_in_foreign_repo` now checks the `parrot sdd run` form).

---

## Amendments — spec rev 0.3 C16 (folded in 2026-10-19)

- **C16 — cover the shared-environment hook in C3's proof** (proposal C16 step 6, approved by
  Jesus Lara 2026-10-17; spec rev 0.3 lists TASK-4091 as amended). After TASK-4089 the installed
  `sdd-coder` / `sdd-worker` frontmatter runs `parrot sdd run worktree_environment --hook || exit 2`;
  `test_wheel_only_foreign_repo.py` gains `test_installed_hook_denies_shared_environment_write` (the
  installed command, run with only `$PARROT_HOME/bin` + allowlisted tools on PATH, still denies a write
  into a shared environment), and `worktree_environment` gets a `Scenario` like every other helper
  (spec §5: "C3's foreign-repo test shows the shared-environment guard denying a write"). The launcher
  fast path is TASK-4509; this task only proves the behaviour.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: C3 `Scenario` list extended (`review_checkpoint`, `spec_tools`, `brief_meta`, `worktree_environment`, TASK-4508's `cache_test_contract` / `test_report` / `check_e2e_closeout` / `close_resolved_issues`); `INVOCATION_RE` takes digits, `\`-continuations are joined and argv is cut at shell operators (the C16 hook); the C3 test installs and scans all three hosts as the AC says; `_lazy_commands` has 25 entries; claude-installer anchors `:51` / `:72` / `:1013`; C16 hook-denial test folded in.
- FEAT-708 drift (merged on `dev` 2026-10-20, after this review's baseline): it added the Claude-only
  `.claude/agents/sdd-contract-probe.md` (10 Claude agents). `/sdd-task`, `/sdd-brainstorm` and
  `/sdd-proposal` and their twins call it. FEAT-708 also inserted lines into those three commands
  (+41/+39/+153, e.g. `cache_test_contract` `sdd-task.md:369` → `:410`), so anchors in those files
  must be re-located by `grep` at pickup.
- Resolved by spec rev 0.5 (2026-10-20):
  - C21 (FEAT-699 vs C7) — `parrot sdd install` warns when `sdd/config.json` `test_command` is null; new C3 test `test_c21_test_step_outcomes` pins the outcomes (`cache_test_contract`: `none — fallback` spec → exit 0 printing `fallback`, missing section → exit 2; `test_report decide-rerun` → `rerun`; `test_report render` → exit 0; `select_tests --tier task` with nothing selected → exit 2).
  - C23 (`.gitattributes` + ledger hooks) — `parrot sdd install` (any host) writes a marker-delimited `.gitattributes` block (`merge=union` for `sdd/ledger/events.jsonl` and `sdd/ledger/archive/*.jsonl`), records it in the receipt, `uninstall` removes it, and installs the four ledger hooks through the existing `claude_code/installer.py::_install_ledger_hooks` (`:973`); C3 asserts both after `--host codex`. FEAT-577's `install_hooks` (intake-prune hook) is not named by C23 and stays out.
  - C22 — no `/sdd-insight` scenarios (it is not shipped); counts follow TASK-4090 (14 commands per host, 79 manifest entries).

## Scope

- Implement `parrot/sdd/installer.py`: `plan_install` / `plan_uninstall` (pure: compute a
  `list[PlannedAction]`), `install_sdd_integration`, `uninstall_sdd_integration` (apply the plan
  unless `dry_run`), `sdd_status`, `classify_entry`, `load_receipt`, with the **rev 0.2
  receipt-driven conflict rule** (C4): absent → write + record; matches the receipt → upgrade;
  differs from the receipt → edited → skip + warning unless `force`; not in the receipt →
  foreign → skip + warning, never overwritten; byte-identical-but-unrecorded → adopt as
  current. `uninstall` removes only files whose SHA matches the receipt.
- Write and maintain the install receipt `sdd/.sdd-installed.json`
  (`{"schema_version": 1, "version": "<ai-parrot>", "files": {"<target>": "<sha256>"}}`), one
  write per install/uninstall, sorted keys, trailing newline.
- `--dry-run` for `install` and `uninstall` (C5): print the plan, write nothing.
- Add a managed `.gitignore` marker block ignoring `.claude/worktrees/` (own copy of the
  marker helpers — do NOT import the claude installer for them).
- *(rev 0.5 C23)* For any host, write a marker-delimited `.gitattributes` block (`merge=union` for
  `sdd/ledger/events.jsonl` and `sdd/ledger/archive/*.jsonl`), record it in the receipt (`uninstall`
  removes it), and install the four ledger hooks (`pre-commit`, `post-merge`, `post-checkout`,
  `post-rewrite`) through the existing `parrot.knowledge.wiki.claude_code.installer._install_ledger_hooks`
  — imported lazily inside that step, so module load stays free of `parrot.knowledge.wiki`.
- *(rev 0.5 C21)* After install, warn when `sdd/config.json` `test_command` is null.
- Seed `sdd/tasks/.id_ledger.json` when absent (decided below — `reserve_ids` cannot run without it).
- Seed `sdd/config.json` from `parrot.sdd.config.default_sdd_config()` when absent (C6,
  TASK-4299) and every manifest entry flagged `"seed": true` (today `sdd/CONVENTIONS.md`) when
  absent (C10, TASK-4090 rev 0.2) — generic over the flag, never a hardcoded path. Seeds: never
  overwritten, never recorded, never removed.
- After install, scan the installed files with `parrot.sdd.audit.scan_paths` +
  `missing_tools` and report unavailable tooling as warnings (codex S9).
- Implement `parrot/sdd/cli.py`: click group `sdd` with `install` / `uninstall` / `status` /
  **`run`** (Q1: `parrot sdd run <name> [ARGS]...` dispatches to `parrot.sdd.scripts.<name>` via
  `runpy.run_module`, propagating the exit code).
- Register `"sdd": "parrot.sdd.cli"` in `cli._lazy_commands`.
- Write `packages/ai-parrot/tests/sdd/test_installer.py` (incl. spec §4
  `test_sdd_install_into_empty_repo`, integration `test_sdd_flow_in_foreign_repo`, and the C4 /
  C5 / seed tests), `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (incl. the `run` tests) and
  `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (C3, `@pytest.mark.integration`;
  all three hosts; plus the C16 hook-denial check, the C21 pinned test-step outcomes and the C23
  `.gitattributes` / ledger-hook assertions after `--host codex`).

**NOT in scope**:
- Producing / syncing `_assets/` or `manifest.json`, including the `"seed": true` flag on the
  `sdd/CONVENTIONS.md` entry (TASK-4090, rev 0.2).
- `parrot/sdd/config.py` (`SddConfig`, `load_sdd_config`, `default_sdd_config`, `CONFIG_PATH`)
  — TASK-4299 creates it; this task only calls `default_sdd_config()` to seed.
- Moving helpers / rewriting markdown to the `parrot sdd run <name>` form (TASK-4085..4089).
- `parrot/sdd/__init__.py`, `parrot/sdd/audit.py`, `packages/ai-parrot/tests/sdd/__init__.py` (TASK-4070).
- The SDD readiness checks themselves (`parrot self doctor --sdd`, TASK-4080) — this task
  only exposes `sdd_status` for them.
- Registering the `sdd-worker-format.sh` hook in the target's `.claude/settings.json` — v1 copies
  the script only and prints a one-line wiring note (JSON-merge of settings is not a spec'd target).
- Committing anything in the target repo (the installer never runs `git add/commit/push`);
  the receipt and the seeds are written to disk and the action log tells the user to commit them.
- A per-file hash comment or a `.parrot/`-resident receipt — rejected in the proposal (JSON/TOML
  assets cannot carry comments; `.parrot/` is gitignored).
- `parrot self doctor --sdd` checking the C23 block and hooks (TASK-4080); `test_command` semantics
  (TASK-4299); FEAT-577's `install_hooks` intake-prune hook (not named by C23); a foreign-repo
  validation phase (rev 0.5 C21: deferred to v1.1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | CREATE | plan / install / uninstall / status over `_assets/manifest.json`; C4 receipt (`sdd/.sdd-installed.json`); C5 dry-run; gitignore block; ledger, config (C6) and conventions (C10) seeds; S9 audit; C23 `.gitattributes` block + four ledger hooks; C21 null-`test_command` warning |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | CREATE | click group `sdd`: `install` / `uninstall` / `status` / `run` (Q1); `--dry-run` on install/uninstall |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `"sdd": "parrot.sdd.cli"` in `cli._lazy_commands` |
| `packages/ai-parrot/tests/sdd/test_installer.py` | CREATE | Installer unit tests (receipt states, dry-run, seeds, C23 block + hooks, C21 warning) + `test_sdd_flow_in_foreign_repo` integration |
| `packages/ai-parrot/tests/sdd/test_sdd_cli.py` | CREATE | CliRunner tests for the group, lazy registration, `--dry-run`, `run` |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | CREATE | C3: wheel-only managed install + foreign repo with bare origin; every documented `parrot sdd run <name> …` invocation (all three hosts) runs with fixture inputs under an allowlisted PATH and scrubbed env; C16: the installed `worktree_environment --hook` still denies a shared-environment write; C21: pinned test-step outcomes; C23: `.gitattributes` block + four ledger hooks after `--host codex` (merge tier, `pytestmark = pytest.mark.integration`) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import click                                   # core dependency: packages/ai-parrot/pyproject.toml:139 ("click>=8.1.7")
from importlib import resources                # stdlib; precedent: tests/flows/dev_loop/test_subagent_parity.py:15
from importlib.resources.abc import Traversable   # stdlib (Python >= 3.11; core requires-python >=3.11)
from parrot.cli import cli                     # packages/ai-parrot/src/parrot/cli/__init__.py:104 (LazyGroup instance)
import hashlib, pkgutil, runpy, sys            # stdlib — receipt SHA-256 (C4), helper discovery + dispatch (Q1)
from importlib import metadata                 # stdlib — metadata.version("ai-parrot") stamps the receipt (C4)
from typing import Literal
from pydantic import BaseModel                 # core dependency; convention: data structures are Pydantic v2 models
# Created by dependency tasks (do NOT exist on dev yet — verify exact names before use):
from parrot.sdd.audit import AssumptionFinding, missing_tools, scan_paths   # TASK-4070
from parrot.sdd.scripts.id_ledger import LEDGER_PATH, bootstrap_ledger, save_ledger  # TASK-4085 (moved from
                                               # scripts/sdd/id_ledger.py:28,145,69 — same names)
from parrot.sdd.config import CONFIG_PATH, default_sdd_config  # TASK-4299 (C6): CONFIG_PATH = Path("sdd/config.json");
                                               # default_sdd_config() -> SddConfig (Pydantic v2; .model_dump_json(indent=2))
from parrot.sdd.config import load_sdd_config  # TASK-4299: load_sdd_config(root: Path | None = None) -> SddConfig
                                               # (absent → defaults; bad → SddConfigError); field test_command: str | None (C21)
# rev 0.5 C23 — imported LAZILY inside the ledger-hook step only (never at module load):
from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks   # :973, verified on dev 0263f0724
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                 # line 19
    def get_command(self, ctx, cmd_name):                     # line 71 — imports _lazy_commands[cmd_name]
        attr_name = cmd_name.replace("-", "_")                # line 99
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)  # line 100
#   => parrot/sdd/cli.py MUST expose a module attribute named `sdd` (the click group)
@click.group(cls=LazyGroup)
def cli(): ...                                                # line 104
cli._lazy_commands = {                                        # line 109 (25 entries on 9f51c7735 — "jiratoolkit" came with 094ec8616; TASK-4080 adds "self")
    "devloop": "parrot.cli.devloop",                          # line 125 — insertion anchor, grep -c == 1

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py — PATTERN ONLY (copy, never import)
def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:   # line 51 (re-verified on 9f51c7735)
def _remove_marker_block(text: str, begin: str, end: str) -> str:               # line 72
def _install_gitignore(root: Path) -> str:                                      # line 1013 (non-marker variant)

# scripts/sdd/id_ledger.py (moves verbatim to parrot.sdd.scripts.id_ledger in TASK-4085)
LEDGER_PATH = Path("sdd/tasks/.id_ledger.json")                                 # line 28
def save_ledger(path: Path, ledger: IdLedger) -> None:                          # line 69 — does NOT mkdir parents
def bootstrap_ledger(index_dir: Path = Path("sdd/tasks/index"),
                     specs_dir: Path = Path("sdd/specs")) -> IdLedger:          # line 145 — missing dirs → ids start at 1
# scripts/sdd/reserve_ids.py
def _read_ledger_at(root: Path, base_sha: str) -> IdLedger:                     # line 259 — reads the ledger via
#   `git show <base_sha>:sdd/tasks/.id_ledger.json` and raises IdReservationError (line 54) when absent
#   => the ledger MUST exist AND be committed+pushed on the base branch before any reservation.

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")  # line 33 (style precedent)

# rev 0.5 C23 — verified on dev 0263f0724
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py — CALLED (the "same installer function")
def _install_ledger_hooks(root: Path) -> list[str]:        # line 973 — one action line per event; a non-git root
                                                            #   yields "git <event> ledger hook — skipped (not a git repository)" (:927-928)
def _uninstall_ledger_hooks(root: Path) -> list[str]:      # line 993 — strips only the parrot-ledger block
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"             # line 51
LEDGER_HOOK_EVENTS = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")  # line 53
# .gitattributes (ai-parrot, lines 1-3) — the entries C23 reproduces in a target repo:
#   # FEAT-694: the shared ledger event log is append-only on every machine; take both sides.
#   sdd/ledger/events.jsonl merge=union
#   sdd/ledger/archive/*.jsonl merge=union

# rev 0.5 C21 — the outcomes C3 pins (verified on dev 0263f0724, scripts/sdd/ before TASK-4508 moves them)
# cache_test_contract.py:17,46   — `none — fallback` → prints "fallback", exit 0; missing/malformed section → exit 2
# test_report.py:87-92           — decide-rerun prints "rerun" for a non-empty index, exit 0; render returns 0 (:107)
# select_tests.py:160-164        — `--tier task` with no invocation selected → exit 2
```

### Does NOT Exist
- ~~`parrot.sdd.installer`, `parrot.sdd.cli`, a `sdd` entry in `_lazy_commands`~~ — new here.
- ~~`parrot sdd` / `parrot env` / `parrot doctor`~~ — and **`parrot status` is TAKEN** (agentd); the
  status verb lives under the group: `parrot sdd status`.
- ~~an `sdd` console script, `packages/ai-parrot-sdd/`, `parrot_sdd`~~ — rejected design (spec §6).
- ~~a public marker helper to import~~ — `_upsert_marker_block` is private to the claude installer;
  copy it (spec §6 Integration Points: "same discipline (own copy)").
- ~~a public ledger-hook installer~~ — C23 names the existing private
  `claude_code/installer.py::_install_ledger_hooks`; call it (lazy import), do not copy it.
- ~~a `.gitattributes` writer anywhere in `parrot`~~ (C23 problem statement: nothing writes it in another
  repo) — new here.
- ~~ledger auto-creation inside `reserve_ids`~~ — it raises; seeding is the installer's job.
- ~~exec-bit preservation from wheel package data~~ — not guaranteed; chmod `.sh` targets on install.
- ~~`sdd/.sdd-installed.json`, `load_receipt`, `classify_entry`, `PlannedAction`, `plan_install`,
  `plan_uninstall`~~ — new here (C4/C5, rev 0.2); no receipt exists anywhere on `dev`.
- ~~`parrot sdd run`, any `run` helper dispatcher~~ — new here (Q1, rev 0.2). `python -m
  parrot.sdd.scripts.<name>` is NOT what shipped markdown says after TASK-4089 rev 0.2.
- ~~`parrot.sdd.config`~~ — TASK-4299 creates it; this task imports it lazily inside the seed
  helper and must not re-implement `SddConfig`.
- ~~a `"seed"` key in `_assets/manifest.json` on `dev`~~ — TASK-4090 rev 0.2 adds it for
  `sdd/CONVENTIONS.md`; treat a missing key as `false`.
- ~~`pytest.mark.integration` auto-applied to `tests/sdd/test_wheel_only_foreign_repo.py`~~ —
  the FEAT-563 auto-mark (`packages/ai-parrot/pyproject.toml:1048`) only covers files under an
  `integration/` directory; mark the module explicitly with `pytestmark = pytest.mark.integration`.

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
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_ledger_hooks",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_upsert_marker_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_remove_marker_block",
    "sym:scripts/sdd/id_ledger.py#save_ledger",
    "sym:scripts/sdd/id_ledger.py#bootstrap_ledger",
    "sym:scripts/sdd/reserve_ids.py#_read_ledger_at"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`knowledge/wiki/claude_code/installer.py` — each step returns a human-readable action string;
the public function returns the list; `uninstall` is the exact inverse; marker blocks key on the
BEGIN marker.

### Key Constraints
- **Spec signature delta (rev 0.2; supersedes spec §3 M6 skeleton and the FEAT-633 brief)**:
  `install_sdd_integration(root, hosts=("claude",), *, force=False, dry_run=False)` and
  `uninstall_sdd_integration(root, hosts=("claude",), *, dry_run=False)`; both are
  `plan_* + apply` — `dry_run=True` returns the plan as `plan: <action> <target>` lines and
  performs no filesystem write of any kind (no receipt, no seeds, no gitignore, no mkdir).
- An asset belongs to the install iff `set(entry["hosts"]) & set(hosts)`; shared assets
  (templates, `sdd/WORKFLOW.md`) therefore install for any host. On uninstall, a shared asset is
  removed only if **no remaining installed host** still needs it — "remaining" = hosts NOT
  passed to uninstall that still have at least one host-specific target recorded in the receipt
  and present on disk (FILL IN bounded by this rule).
- Read assets via `importlib.resources.files("parrot.sdd") / "_assets"` — never a repo path
  (installed runtime must not depend on a monorepo checkout, codex S8).
- **Receipt (C4)** is the single source of "ours": `classify_entry` compares on-disk SHA-256
  against the receipt first, then against the packaged bytes. `force=True` overwrites an
  `edited` file and re-records it; it never touches a `foreign` file (present, not recorded,
  not byte-identical), never a non-manifest path, never a seed. The receipt is rewritten once
  per install/uninstall (never per file) and stamped with `metadata.version("ai-parrot")`.
- **Seeds (C6/C10)** — `sdd/config.json` (from `default_sdd_config()`) and every manifest entry
  with `"seed": true` — are written only when absent, are not recorded in the receipt, are
  reported by `status` as `seed-present | missing`, and are never removed by `uninstall`.
- Uninstall never removes an `edited` or `foreign` file, never removes
  `sdd/tasks/.id_ledger.json`, `sdd/config.json`, seeds, or the receipt itself while any
  recorded file remains (when nothing remains, the receipt is deleted too), and prunes only
  directories it leaves empty.
- **`run` (Q1)**: `click.argument("args", nargs=-1, type=click.UNPROCESSED)` under
  `context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False}` so
  `--help` and every other flag reach the helper untouched; `sys.argv = [f"parrot.sdd.scripts.{name}", *args]`;
  `runpy.run_module(f"parrot.sdd.scripts.{name}", run_name="__main__", alter_sys=True)`;
  a `SystemExit` raised by the helper propagates its code; a normal return exits 0; unknown
  name → `click.ClickException` listing the helpers discovered via `pkgutil.iter_modules` over
  `parrot.sdd.scripts.__path__` — all of them, `sdd_meta` included (TASK-4299 gives it a `main()`;
  `pkgutil.iter_modules` never lists `__init__`) (exit 1). Never import the helper module at
  group-load time (lazy by construction).
- Hosts are validated against `SUPPORTED_HOSTS`; unknown → `ValueError` (CLI: `click.Choice`).
- Library code logs via `logger = logging.getLogger(__name__)`; only `cli.py` writes output (`click.echo`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:51-91` — marker helpers to copy.
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py:33-53,180-200` — CLI shape (`--path`, `✓` action lines).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Confirm `parrot.sdd.audit`, `parrot.sdd.scripts.id_ledger`, `parrot.sdd.config` (TASK-4299) and
   `resources.files("parrot.sdd") / "_assets" / "manifest.json"` exist, and whether the manifest
   already carries `"seed": true` on `sdd/CONVENTIONS.md` — *why*: all come from dependency tasks.
2. Write `installer.py` (manifest + receipt loader → `classify_entry` → `plan_install` /
   `plan_uninstall` → `apply` → gitignore → *(C23)* `.gitattributes` block + ledger hooks → ledger /
   config / conventions seeds → receipt write → *(C21)* null-`test_command` warning → audit) — *why*:
   the CLI is a thin shell over it, and `--dry-run` is just "plan without apply".
3. Write `cli.py` exposing the group as attribute `sdd`, with `install` / `uninstall` (`--dry-run`),
   `status` and `run` — *why*: `LazyGroup.get_command` resolves `getattr(mod, "sdd")` (cli/__init__.py:99-100).
4. Add the `_lazy_commands` entry — *why*: lazy import keeps `parrot --help` cheap.
5. Write the three test files; run the Validation Commands (the wheel-only test only with `-m integration`).

### `packages/ai-parrot/src/parrot/sdd/installer.py` (CREATE)
```python
"""Deploy the packaged SDD flow (``parrot/sdd/_assets/``) into a repository (FEAT-633 M6, rev 0.2).

Conflict rule (C4, receipt-driven — ``sdd/.sdd-installed.json`` records the SHA-256 of every
byte sequence this installer wrote): absent → write + record; matches the receipt → upgrade;
differs from the receipt → edited → skip + warning unless ``force``; not in the receipt →
foreign → skip + warning, never overwritten; unrecorded but byte-identical → adopt as current.
``uninstall`` removes only files whose SHA matches the receipt. Seeds (``sdd/config.json`` and
manifest entries flagged ``"seed": true``) are written once and never touched again.
"""

from __future__ import annotations

import hashlib
import json
import logging
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel

from parrot.sdd.audit import missing_tools, scan_paths  # TASK-4070

logger = logging.getLogger(__name__)

SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")
MANIFEST_SCHEMA_VERSION = 1
RECEIPT_PATH = Path("sdd/.sdd-installed.json")  # C4: committed with sdd/; .parrot/ is gitignored (.gitignore:411)
RECEIPT_SCHEMA_VERSION = 1
GITIGNORE_BEGIN = "# >>> parrot sdd (managed) >>>"
GITIGNORE_END = "# <<< parrot sdd (managed) <<<"
GITIGNORE_BLOCK = f"{GITIGNORE_BEGIN}\n# SDD feature worktrees (parrot sdd run ensure_worktree)\n.claude/worktrees/\n{GITIGNORE_END}"
#: rev 0.5 C23 — the shared ledger's union merge (FEAT-694), same marker pair as the .gitignore block.
GITATTRIBUTES_BLOCK = (
    f"{GITIGNORE_BEGIN}\n"
    "# FEAT-694: the shared ledger event log is append-only on every machine; take both sides.\n"
    "sdd/ledger/events.jsonl merge=union\n"
    "sdd/ledger/archive/*.jsonl merge=union\n"
    f"{GITIGNORE_END}"
)

FileState = Literal["missing", "current", "outdated", "edited", "foreign"]
#: Plan vocabulary (C5). install: write | upgrade | overwrite | skip-current | skip-edited | skip-foreign |
#: seed | skip-seed | gitignore | gitattributes | ledger-hooks | ledger-seed | config-seed. uninstall: remove |
#: keep-edited | keep-foreign | skip-missing | keep-shared | gitignore-remove | gitattributes-remove | receipt-remove.
PlanAction = Literal[
    "write", "upgrade", "overwrite", "skip-current", "skip-edited", "skip-foreign",
    "seed", "skip-seed", "gitignore", "gitattributes", "ledger-hooks", "ledger-seed", "config-seed",
    "remove", "keep-edited", "keep-foreign", "skip-missing", "keep-shared", "gitignore-remove",
    "gitattributes-remove", "receipt-remove",
]


class PlannedAction(BaseModel):
    """One step of an install/uninstall plan; ``str()`` is the ``--dry-run`` line."""

    action: PlanAction
    target: str
    note: str = ""

    def __str__(self) -> str:
        return f"plan: {self.action} {self.target}" + (f" ({self.note})" if self.note else "")
HOOK_WIRING_NOTE = (
    "note: .claude/hooks/sdd-worker-format.sh is installed but not registered — add it to "
    ".claude/settings.json (SubagentStop/Stop) if you want post-run formatting"
)


def _assets_root() -> Traversable:
    """Packaged asset tree (works from a wheel; never a repo checkout path)."""
    return resources.files("parrot.sdd") / "_assets"


def load_manifest() -> list[dict[str, Any]]:
    """Return the manifest's ``assets`` list.

    Raises:
        RuntimeError: manifest missing or ``schema_version`` unsupported.
    """
    path = _assets_root() / "manifest.json"
    if not path.is_file():
        raise RuntimeError("parrot/sdd/_assets/manifest.json is missing — broken ai-parrot install")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported SDD asset manifest schema_version {data.get('schema_version')!r}")
    return list(data["assets"])


def _validate_hosts(hosts: Sequence[str]) -> tuple[str, ...]:
    """Normalise ``hosts`` (dedupe, keep order) and reject unknown names with ``ValueError``."""
    unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
    if unknown or not hosts:
        raise ValueError(f"unknown/empty SDD host(s) {unknown or list(hosts)}; choose from {SUPPORTED_HOSTS}")
    return tuple(dict.fromkeys(hosts))


def _selected(entries: list[dict[str, Any]], hosts: Sequence[str]) -> list[dict[str, Any]]:
    """Assets whose ``hosts`` intersect ``hosts``."""
    wanted = set(hosts)
    return [e for e in entries if wanted & set(e["hosts"])]


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py:51 (keys on BEGIN; repairs a missing END)."""
    # FILL IN: copy the body of knowledge/wiki/claude_code/installer.py::_upsert_marker_block verbatim — bounded by spec §6 "own copy"
    raise NotImplementedError


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py:72."""
    # FILL IN: copy the body of knowledge/wiki/claude_code/installer.py::_remove_marker_block verbatim
    raise NotImplementedError


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_receipt(root: Path) -> dict[str, Any]:
    """Return ``<root>/sdd/.sdd-installed.json`` or an empty receipt when absent.

    Shape: ``{"schema_version": 1, "version": "<ai-parrot that wrote it>" | None, "files": {target: sha256}}``.
    An unreadable or wrong-schema receipt is treated as empty and logged at WARNING (never raises).
    """
    # FILL IN: read + validate schema_version == RECEIPT_SCHEMA_VERSION; else empty receipt — bounded by C4
    raise NotImplementedError


def _save_receipt(root: Path, receipt: dict[str, Any]) -> None:
    """Write the receipt once (sorted keys, indent 2, trailing newline), stamped with the running ai-parrot version."""
    receipt["schema_version"] = RECEIPT_SCHEMA_VERSION
    receipt["version"] = metadata.version("ai-parrot")
    path = root / RECEIPT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def classify_entry(root: Path, entry: dict[str, Any], receipt: dict[str, Any]) -> FileState:
    """C4 state of one manifest target.

    missing → not on disk; foreign → on disk, not in the receipt, not byte-identical to the
    packaged copy; edited → on disk, in the receipt, SHA differs from the record; current → SHA
    equals the record (or unrecorded but byte-identical to the packaged copy — adopted) AND equals
    the packaged copy; outdated → SHA equals the record but the packaged copy changed.
    """
    target = root / entry["target"]
    if not target.is_file():
        return "missing"
    on_disk = _sha256(target.read_bytes())
    packaged = _sha256((_assets_root() / entry["source"]).read_bytes())
    recorded = receipt["files"].get(entry["target"])
    if recorded is None:
        return "current" if on_disk == packaged else "foreign"
    if on_disk != recorded:
        return "edited"
    return "current" if on_disk == packaged else "outdated"


def plan_install(root: Path, hosts: Sequence[str], *, force: bool = False) -> list[PlannedAction]:
    """Pure: the ordered plan for ``install`` (assets, seeds, gitignore, ledger, config). No I/O writes."""
    receipt = load_receipt(root)
    plan: list[PlannedAction] = []
    for entry in _selected(load_manifest(), _validate_hosts(hosts)):
        if entry.get("seed", False):
            plan.append(PlannedAction(action="skip-seed" if (root / entry["target"]).exists() else "seed", target=entry["target"]))
            continue
        state = classify_entry(root, entry, receipt)
        # FILL IN: missing→write; current→skip-current; outdated→upgrade; edited→overwrite if force else
        #          skip-edited (note "use --force"); foreign→skip-foreign (note "not written by parrot sdd;
        #          never overwritten") — bounded by the C4 rule in the module docstring
        raise NotImplementedError
    plan.append(PlannedAction(action="gitignore", target=".gitignore"))
    plan.append(PlannedAction(action="gitattributes", target=".gitattributes"))  # rev 0.5 C23, any host
    plan.append(PlannedAction(action="ledger-hooks", target=".git/hooks"))       # rev 0.5 C23, any host
    if not (root / "sdd/tasks/.id_ledger.json").exists():
        plan.append(PlannedAction(action="ledger-seed", target="sdd/tasks/.id_ledger.json"))
    if not (root / "sdd/config.json").exists():
        plan.append(PlannedAction(action="config-seed", target="sdd/config.json"))
    return plan


def plan_uninstall(root: Path, hosts: Sequence[str]) -> list[PlannedAction]:
    """Pure: ``remove`` only targets whose on-disk SHA matches the receipt; keep edited/foreign; keep shared
    assets another installed host still needs; seeds and state are never planned for removal."""
    # FILL IN: per selected non-seed entry — current/outdated→remove (shared+still needed→keep-shared);
    #          edited→keep-edited; foreign→keep-foreign; missing→skip-missing; then gitignore-remove,
    #          gitattributes-remove (C23: the receipt records the block, so uninstall removes it) and
    #          receipt-remove when no recorded file would remain — bounded by Key Constraints
    raise NotImplementedError


def _apply_asset(root: Path, entry: dict[str, Any], action: PlannedAction, receipt: dict[str, Any]) -> str:
    """Execute one asset action; updates ``receipt["files"]`` in place; returns the action-log line."""
    target = root / entry["target"]
    if action.action in {"skip-current", "skip-seed"}:
        if action.action == "skip-current":
            receipt["files"][entry["target"]] = _sha256(target.read_bytes())  # adoption of unrecorded identical files
        return f"{entry['target']} — up to date"
    if action.action in {"skip-edited", "skip-foreign"}:
        logger.warning("sdd install: %s %s; skipped", entry["target"], action.note)
        return f"warning: {entry['target']} — {action.note}"
    payload = (_assets_root() / entry["source"]).read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    if target.suffix == ".sh":
        target.chmod(0o755)  # wheels do not reliably preserve the exec bit
    if action.action != "seed":
        receipt["files"][entry["target"]] = _sha256(payload)
    verb = {"write": "installed", "upgrade": "upgraded", "overwrite": "overwritten (--force)", "seed": "seeded (team-owned; never overwritten)"}
    return f"{entry['target']} — {verb[action.action]}"


def _seed_config(root: Path) -> str:
    """C6: write ``sdd/config.json`` from ``default_sdd_config()`` iff absent (TASK-4299; lazy import)."""
    from parrot.sdd.config import CONFIG_PATH, default_sdd_config  # TASK-4299

    path = root / CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_sdd_config().model_dump_json(indent=2) + "\n", encoding="utf-8")
    return f"{CONFIG_PATH} — seeded; edit base_branch/hotfix_base/issue_tracker/test_command for this repo and commit it"


def _install_gitignore(root: Path) -> str:
    """Upsert the managed ``.claude/worktrees/`` block into ``<root>/.gitignore``."""
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_marker_block(text, GITIGNORE_BLOCK, GITIGNORE_BEGIN, GITIGNORE_END)
    if updated == text:
        return ".gitignore — .claude/worktrees/ block up to date"
    path.write_text(updated, encoding="utf-8")
    return ".gitignore — managed .claude/worktrees/ block written"


def _install_gitattributes(root: Path, receipt: dict[str, Any]) -> str:
    """rev 0.5 C23: upsert ``GITATTRIBUTES_BLOCK`` into ``<root>/.gitattributes`` and record it in the receipt."""
    # FILL IN: same upsert as _install_gitignore (foreign lines in the file untouched), then record the block
    #          in `receipt` — bounded by C23 ("records it in the receipt") and the uninstall removal
    raise NotImplementedError


def _install_ledger_hooks_step(root: Path) -> list[str]:
    """rev 0.5 C23: the four FEAT-694 ledger hooks through the claude installer's own function (lazy import)."""
    from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks  # C23: "the same installer function"

    return _install_ledger_hooks(root)


def _test_command_warning(root: Path) -> str | None:
    """rev 0.5 C21: one ``warning:`` line when ``sdd/config.json`` ``test_command`` is null, else None."""
    from parrot.sdd.config import load_sdd_config  # TASK-4299

    if load_sdd_config(root).test_command is not None:
        return None
    return (
        "warning: sdd/config.json test_command is null — set it to the command that runs this repo's tests; "
        "the shipped test steps run it once from the repo root (C21)"
    )


def _seed_id_ledger(root: Path) -> str | None:
    """Create ``sdd/tasks/.id_ledger.json`` iff absent (reserve_ids reads it from git and raises when missing)."""
    from parrot.sdd.scripts.id_ledger import LEDGER_PATH, bootstrap_ledger, save_ledger  # TASK-4085

    path = root / LEDGER_PATH
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    save_ledger(path, bootstrap_ledger(root / "sdd/tasks/index", root / "sdd/specs"))
    return (
        f"{LEDGER_PATH} — seeded; warning: commit and push it to your base branch before "
        "`parrot sdd run reserve_ids` (it reads the ledger from git)"
    )


def _audit(root: Path, installed: list[Path]) -> list[str]:
    """codex S9: warn about tooling the installed assets need but this machine lacks."""
    findings = scan_paths(installed)
    # FILL IN: map missing_tools(...) result to one 'warning: <tool> not found (needed by <path>:<line>)'
    #          line per tool — bounded by TASK-4070's missing_tools signature; never fail the install
    raise NotImplementedError


def install_sdd_integration(
    root: Path, hosts: Sequence[str] = ("claude",), *, force: bool = False, dry_run: bool = False
) -> list[str]:
    """Deploy packaged SDD assets for ``hosts`` into ``root``; never overwrites foreign content.

    Args:
        root: Target repository root (need not be a Python project).
        hosts: Any of ``SUPPORTED_HOSTS``; shared assets (templates, WORKFLOW.md) install for every host.
        force: Overwrite manifest targets the receipt says we wrote but the team edited since.
            Never touches foreign (unrecorded) files or seeds.
        dry_run: Return the plan (``plan: <action> <target>`` lines) and write NOTHING — no asset,
            seed, gitignore, ledger, config, receipt, or directory.

    Returns:
        Human-readable action log; skipped conflicts and audit findings start with ``warning:``;
        dry-run lines start with ``plan:``.

    Raises:
        ValueError: unknown host.
        RuntimeError: packaged manifest missing/unsupported.
    """
    plan = plan_install(root, hosts, force=force)
    if dry_run:
        return [str(step) for step in plan]
    receipt = load_receipt(root)
    by_target = {e["target"]: e for e in load_manifest()}
    actions: list[str] = []
    for step in plan:
        if step.target in by_target:
            actions.append(_apply_asset(root, by_target[step.target], step, receipt))
        elif step.action == "gitignore":
            actions.append(_install_gitignore(root))
        elif step.action == "gitattributes":
            actions.append(_install_gitattributes(root, receipt))
        elif step.action == "ledger-hooks":
            actions.extend(_install_ledger_hooks_step(root))
        elif step.action == "ledger-seed":
            actions.append(_seed_id_ledger(root) or "")
        elif step.action == "config-seed":
            actions.append(_seed_config(root))
    _save_receipt(root, receipt)
    actions.append(f"{RECEIPT_PATH} — written; commit it with the installed files (it drives upgrades and uninstall)")
    actions.append(_test_command_warning(root) or "")
    if "claude" in hosts:
        actions.append(HOOK_WIRING_NOTE)
    installed = [root / t for t in receipt["files"] if (root / t).is_file()]
    actions.extend(_audit(root, installed))
    return [a for a in actions if a]


def uninstall_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *, dry_run: bool = False) -> list[str]:
    """Remove SDD assets for ``hosts`` whose on-disk SHA matches the receipt (edited/foreign files are kept and reported).

    The ``.gitignore`` block, the recorded ``.gitattributes`` block (C23) and the receipt are removed only
    when no recorded file remains;
    ``sdd/tasks/.id_ledger.json``, ``sdd/config.json`` and seeds are never removed (state / team-owned).
    ``dry_run`` returns the plan and writes nothing.
    """
    plan = plan_uninstall(root, hosts)
    if dry_run:
        return [str(step) for step in plan]
    # FILL IN: apply — remove → unlink + prune now-empty parents up to root + drop from receipt;
    #          keep-edited/keep-foreign → 'warning: … kept'; gitignore-remove and gitattributes-remove
    #          (only when the receipt records the block, C23) via _remove_marker_block;
    #          receipt-remove → unlink RECEIPT_PATH, else _save_receipt — bounded by the C4 rule
    raise NotImplementedError


def sdd_status(root: Path) -> dict[str, Any]:
    """Per-host install state (C4/C15):

    ``{"hosts": {h: {"current": [...], "outdated": [...], "edited": [...], "foreign": [...], "missing": [...]}},
    "seeds": {"<target>": "seed-present" | "missing"}, "config": bool, "gitignore": bool, "id_ledger": bool,
    "receipt_version": str | None}`` (targets are repo-relative strings). Import-cheap: ``parrot self
    doctor`` (TASK-4080) imports this lazily and treats ``outdated``/``edited`` as "not current".
    """
    # FILL IN: classify every non-seed manifest entry per host via classify_entry(…, load_receipt(root));
    #          seeds via existence — bounded by the dict shape in this docstring (test_installer asserts it)
    raise NotImplementedError
```
**Why this shape**: the manifest (TASK-4090) is the only source of what to install; the receipt
(C4) is the only source of what *we* wrote, which is what lets an upgrade tell an untouched
older file from a team edit without `--force`. `plan_*` are pure so `--dry-run` (C5) is
"plan without apply" and the no-write test is trivial. The ledger seed is required because
`reserve_ids._read_ledger_at` (reserve_ids.py:259) raises `IdReservationError` when the ledger is
absent from the base commit — a fresh repo could otherwise never run `/sdd-spec`. Seeding only
when absent and never removing it keeps installs idempotent and uninstall state-safe; the same
rule covers `sdd/config.json` (C6) and `sdd/CONVENTIONS.md` (C10).
*(rev 0.5 C23)* The `.gitattributes` block and the ledger hooks are written for every host because
`/sdd-done` step 9.1 calls `wikitoolkit ledger export-log` / `rotate-log` in any repo; the hooks go
through `_install_ledger_hooks` itself, so FEAT-694's hook bodies have one owner.
Note for implementer: C23 gives neither the marker text nor the receipt shape for the `.gitattributes` block — the blueprint reuses the `.gitignore` marker pair and leaves the receipt key to `_install_gitattributes`; keep `receipt["files"]` meaning "whole files we wrote" and confirm both in review.
Note for implementer: C23 says nothing about `uninstall` and the ledger hooks (`_uninstall_ledger_hooks`, `installer.py:993`, exists) — leave the hooks in place unless the clause is extended.
Note for implementer: the C21 warning reads `sdd/config.json` through `load_sdd_config` (TASK-4299), which raises `SddConfigError` on a bad file — C21 does not say what install does then; confirm in review.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (CREATE)
```python
"""``parrot sdd`` — install the SDD flow (commands, agents, rules, templates) into a repository,
and run its packaged helpers (``parrot sdd run <name>``, Q1) inside the venv the launcher resolved."""

from __future__ import annotations

import json
import pkgutil
import runpy
import sys
from pathlib import Path

import click

from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration

_HELPER_PACKAGE = "parrot.sdd.scripts"
_dry_run_option = click.option("--dry-run", is_flag=True, help="Print the plan and change nothing.")

_path_option = click.option(
    "--path", "path_", type=click.Path(file_okay=False, path_type=Path), default=None,
    help="Target repository root (default: current directory).",
)
_host_option = click.option(
    "--host", "hosts", type=click.Choice(SUPPORTED_HOSTS), multiple=True,
    help="Assistant host(s) to install for; repeatable (default: claude).",
)


def _root(path_: Path | None) -> Path:
    """Resolve ``--path`` (default cwd) or abort when it is not a directory."""
    root = (path_ or Path.cwd()).resolve()
    if not root.is_dir():
        raise click.ClickException(f"Not a directory: {root}")
    return root


def _echo_actions(actions: list[str]) -> None:
    for action in actions:
        if action.startswith(("warning:", "note:")):
            click.echo(f"  ! {action}", err=True)
        elif action.startswith("plan:"):
            click.echo(f"  · {action}")
        else:
            click.echo(f"  ✓ {action}")


def available_helpers() -> list[str]:
    """Names accepted by ``parrot sdd run``: every module of parrot.sdd.scripts (``sdd_meta`` included —
    TASK-4299 gives it a ``main()``; ``pkgutil`` never lists ``__init__``)."""
    import parrot.sdd.scripts as pkg  # TASK-4085 package; lazy so `parrot --help` stays cheap

    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.ispkg)


@click.group(name="sdd")
def sdd() -> None:
    """Spec-Driven Development flow: install / uninstall / status / run."""


@sdd.command()
@_path_option
@_host_option
@click.option("--force", is_flag=True, help="Overwrite SDD files you edited since parrot wrote them (never foreign files or seeds).")
@_dry_run_option
def install(path_: Path | None, hosts: tuple[str, ...], force: bool, dry_run: bool) -> None:
    """Deploy the packaged SDD assets into the repository (upgrades untouched files, keeps your edits)."""
    try:
        _echo_actions(install_sdd_integration(_root(path_), hosts or ("claude",), force=force, dry_run=dry_run))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@_host_option
@_dry_run_option
def uninstall(path_: Path | None, hosts: tuple[str, ...], dry_run: bool) -> None:
    """Remove SDD files that parrot wrote and you have not edited (seeds and state are kept)."""
    try:
        _echo_actions(uninstall_sdd_integration(_root(path_), hosts or ("claude",), dry_run=dry_run))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(path_: Path | None, as_json: bool) -> None:
    """Show each SDD asset as current, outdated, edited, foreign or missing per host, plus seeds and state."""
    report = sdd_status(_root(path_))
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    # FILL IN: one summary line per host (current/outdated/edited/foreign/missing counts), one line per seed,
    #          and the config/gitignore/ledger/receipt_version flags — bounded by the sdd_status docstring
    raise NotImplementedError


@sdd.command(context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("name")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def run(name: str, args: tuple[str, ...]) -> None:
    """Run a packaged SDD helper (e.g. `parrot sdd run reserve_ids --help`) in the venv the launcher resolved.

    This is the only form shipped markdown uses (Q1): `python -m parrot.sdd.scripts.<name>` would
    run whatever `python` is first on PATH, which in a non-Python repo has no ai-parrot.
    """
    helpers = available_helpers()
    if name not in helpers:
        raise click.ClickException(f"unknown helper {name!r}; available: {', '.join(helpers)}")
    sys.argv = [f"{_HELPER_PACKAGE}.{name}", *args]
    try:
        runpy.run_module(f"{_HELPER_PACKAGE}.{name}", run_name="__main__", alter_sys=True)
    except SystemExit as exc:  # the helper's own exit code (argparse --help exits 0)
        raise click.exceptions.Exit(exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)) from exc
```
**Why this shape**: the attribute is named `sdd` because `LazyGroup.get_command` resolves
`getattr(mod, cmd_name.replace("-", "_"))` (cli/__init__.py:99-100); `--host` is a repeatable
`click.Choice` defaulting to `claude` (brief); `--path` defaults to cwd (brief) — deliberately NOT
the wiki's `find_project_root`, so a fresh non-git dir works and `parrot.knowledge.wiki` is never imported.

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "devloop": "parrot.cli.devloop",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "devloop": "parrot.cli.devloop",` (verified: packages/ai-parrot/src/parrot/cli/__init__.py:125)
    # FEAT-633 — SDD flow installer (parrot sdd install|uninstall|status).
    "sdd": "parrot.sdd.cli",
```
**Why**: inside `cli._lazy_commands = {` (cli/__init__.py:109, grep -c == 1). The `devloop` anchor
is used instead of the dict opener so this edit cannot collide with TASK-4080's `"self"` insertion;
if TASK-4080 moved the `devloop` line, re-run the grep and STOP if the count is not 1.

### `packages/ai-parrot/tests/sdd/test_installer.py` (CREATE)
```python
"""Tests for parrot.sdd.installer (FEAT-633 M6; spec §4 test_sdd_install_into_empty_repo,
integration test_sdd_flow_in_foreign_repo)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import (
    GITIGNORE_BEGIN,
    RECEIPT_PATH,
    install_sdd_integration,
    load_manifest,
    sdd_status,
    uninstall_sdd_integration,
)


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """A fresh, non-Python git repository."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# foreign repo\n")
    return tmp_path


def _claude_targets() -> list[str]:
    return [e["target"] for e in load_manifest() if "claude" in e["hosts"]]


def test_sdd_install_into_empty_repo(empty_repo: Path) -> None:
    """Deploy + uninstall round-trip, marker-block safe (spec §4)."""
    install_sdd_integration(empty_repo)
    assert all((empty_repo / t).is_file() for t in _claude_targets())
    assert GITIGNORE_BEGIN in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()
    uninstall_sdd_integration(empty_repo)
    assert not any((empty_repo / t).exists() for t in _claude_targets())
    assert GITIGNORE_BEGIN not in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "README.md").read_text() == "# foreign repo\n"
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()  # state is never removed


def test_reinstall_is_idempotent(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo)
    actions = install_sdd_integration(empty_repo)
    assert not any("installed" in a or "overwritten" in a for a in actions)


def _tree_digest(root: Path) -> dict[str, str]:
    """{relative path: sha256} for every file under root except .git/ (C5 no-write assertion)."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    }


def test_modified_file_skipped_unless_force_and_kept_on_uninstall(empty_repo: Path) -> None:
    """C4: a file in the receipt whose bytes changed is `edited` — kept unless --force, never uninstalled."""
    install_sdd_integration(empty_repo)
    target = empty_repo / _claude_targets()[0]
    target.write_text("user edit\n")
    assert any(a.startswith("warning:") for a in install_sdd_integration(empty_repo))
    assert target.read_text() == "user edit\n"
    uninstall_sdd_integration(empty_repo)
    assert target.read_text() == "user edit\n"
    install_sdd_integration(empty_repo, force=True)
    assert target.read_text() != "user edit\n"
    assert sdd_status(empty_repo)["hosts"]["claude"]["current"]  # re-recorded after --force


def test_untouched_file_upgrades_from_older_record(empty_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4: a file untouched since an OLDER release (receipt sha == on-disk sha != packaged) upgrades without --force."""
    install_sdd_integration(empty_repo)
    target = _claude_targets()[0]
    old_bytes = b"# older packaged copy\n"
    (empty_repo / target).write_bytes(old_bytes)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    receipt["files"][target] = hashlib.sha256(old_bytes).hexdigest()
    receipt["version"] = "0.0.1"
    (empty_repo / RECEIPT_PATH).write_text(json.dumps(receipt))
    assert sdd_status(empty_repo)["hosts"]["claude"]["outdated"] == [target]
    actions = install_sdd_integration(empty_repo)
    assert any(a.endswith("upgraded") and target in a for a in actions)
    assert (empty_repo / target).read_bytes() != old_bytes
    assert json.loads((empty_repo / RECEIPT_PATH).read_text())["version"] != "0.0.1"


def test_foreign_file_never_touched_even_with_force(empty_repo: Path) -> None:
    """C4: a target that exists but was not written by us (and is not byte-identical) is `foreign`."""
    target = empty_repo / _claude_targets()[0]
    target.parent.mkdir(parents=True)
    target.write_text("theirs\n")
    for force in (False, True):
        actions = install_sdd_integration(empty_repo, force=force)
        assert any(a.startswith("warning:") and "never overwritten" in a for a in actions)
        assert target.read_text() == "theirs\n"
    assert sdd_status(empty_repo)["hosts"]["claude"]["foreign"] == [_claude_targets()[0]]
    uninstall_sdd_integration(empty_repo)
    assert target.read_text() == "theirs\n"


def test_unrecorded_identical_file_is_adopted(empty_repo: Path) -> None:
    """C4 interpretation: byte-identical to the packaged copy but missing from the receipt → current + recorded."""
    install_sdd_integration(empty_repo)
    (empty_repo / RECEIPT_PATH).unlink()
    install_sdd_integration(empty_repo)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    assert set(receipt["files"]) >= set(_claude_targets())


def test_dry_run_changes_nothing(empty_repo: Path) -> None:
    """C5: install/uninstall --dry-run print a plan and leave the tree byte-for-byte unchanged."""
    before = _tree_digest(empty_repo)
    plan = install_sdd_integration(empty_repo, dry_run=True)
    assert plan and all(p.startswith("plan: ") for p in plan)
    assert any(p.startswith("plan: write ") for p in plan)
    assert any(p.startswith(("plan: gitignore", "plan: ledger-seed", "plan: config-seed")) for p in plan)
    assert _tree_digest(empty_repo) == before and not (empty_repo / RECEIPT_PATH).exists()
    install_sdd_integration(empty_repo)
    before = _tree_digest(empty_repo)
    plan = uninstall_sdd_integration(empty_repo, dry_run=True)
    assert any(p.startswith("plan: remove ") for p in plan)
    assert _tree_digest(empty_repo) == before


def _seed_targets() -> list[str]:
    """Every manifest entry flagged `"seed": true` (TASK-4090 rev 0.2) — generic, never a hardcoded path."""
    return [e["target"] for e in load_manifest() if e.get("seed", False)]


def test_seeds_written_once_never_overwritten_or_removed(empty_repo: Path) -> None:
    """C6/C10: sdd/config.json and EVERY `"seed": true` asset are written iff absent; --force and uninstall leave them."""
    seeds = _seed_targets()
    assert seeds, "TASK-4090 must flag at least one seed (sdd/CONVENTIONS.md)"
    install_sdd_integration(empty_repo)
    config = empty_repo / "sdd/config.json"
    assert config.is_file() and json.loads(config.read_text())["base_branch"] == "dev"
    assert all((empty_repo / t).is_file() for t in seeds)
    config.write_text('{"base_branch": "develop", "hotfix_base": "main"}\n')
    for t in seeds:
        (empty_repo / t).write_text("# ours\n")
    install_sdd_integration(empty_repo, force=True)
    assert "develop" in config.read_text()
    assert all((empty_repo / t).read_text() == "# ours\n" for t in seeds)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    assert "sdd/config.json" not in receipt["files"] and not set(seeds) & set(receipt["files"])
    uninstall_sdd_integration(empty_repo)
    assert config.is_file() and all((empty_repo / t).read_text() == "# ours\n" for t in seeds)
    report = sdd_status(empty_repo)
    assert all(report["seeds"][t] == "seed-present" for t in seeds)
    assert not any(t in report["hosts"][h][state] for t in seeds for h in report["hosts"] for state in report["hosts"][h])


def test_existing_gitignore_content_preserved(empty_repo: Path) -> None:
    (empty_repo / ".gitignore").write_text("node_modules/\n")
    install_sdd_integration(empty_repo)
    assert (empty_repo / ".gitignore").read_text().startswith("node_modules/\n")


@pytest.mark.parametrize("host", ["claude", "codex", "google"])
def test_gitattributes_block_written_recorded_and_removed(empty_repo: Path, host: str) -> None:
    """rev 0.5 C23: any host writes the ledger merge=union block, keeps foreign lines, uninstall removes it."""
    (empty_repo / ".gitattributes").write_text("*.png binary\n")
    install_sdd_integration(empty_repo, hosts=(host,))
    text = (empty_repo / ".gitattributes").read_text()
    assert text.startswith("*.png binary\n")
    assert "sdd/ledger/events.jsonl merge=union" in text and "sdd/ledger/archive/*.jsonl merge=union" in text
    # FILL IN: assert the receipt records the block — bounded by _install_gitattributes' receipt shape (Note)
    uninstall_sdd_integration(empty_repo, hosts=(host,))
    assert (empty_repo / ".gitattributes").read_text() == "*.png binary\n"


def test_ledger_hooks_installed_for_any_host(empty_repo: Path) -> None:
    """rev 0.5 C23: the four FEAT-694 ledger hooks are installed through the claude installer's function."""
    install_sdd_integration(empty_repo, hosts=("codex",))
    for event in ("pre-commit", "post-merge", "post-checkout", "post-rewrite"):
        assert "# >>> parrot-ledger >>>" in (empty_repo / ".git/hooks" / event).read_text()


def test_install_warns_when_test_command_is_null(empty_repo: Path) -> None:
    """rev 0.5 C21: a seeded (or existing) sdd/config.json with test_command null yields one warning line."""
    actions = install_sdd_integration(empty_repo)
    assert any(a.startswith("warning:") and "test_command" in a for a in actions)


def test_unknown_host_rejected(empty_repo: Path) -> None:
    with pytest.raises(ValueError):
        install_sdd_integration(empty_repo, hosts=("vim",))


def test_status_shape(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo, hosts=("codex",))
    report = sdd_status(empty_repo)
    assert set(report) >= {"hosts", "seeds", "config", "gitignore", "id_ledger", "receipt_version"}
    assert set(report["hosts"]["codex"]) == {"current", "outdated", "edited", "foreign", "missing"}
    assert report["hosts"]["codex"]["missing"] == []
    # FILL IN: assert claude-only targets are reported missing for "claude" — bounded by sdd_status docstring


@pytest.mark.parametrize("hosts", [("claude",), ("codex",), ("google",)])
def test_sdd_flow_in_foreign_repo(empty_repo: Path, hosts: tuple[str, ...]) -> None:
    """Integration (spec §4, rev 0.2): installed markdown invokes helpers ONLY as `parrot sdd run <name>`,
    every such name is a real parrot.sdd.scripts module, and no `python -m` / repo-script form remains."""
    install_sdd_integration(empty_repo, hosts=hosts)
    installed = [empty_repo / e["target"] for e in load_manifest() if set(hosts) & set(e["hosts"])]
    texts = [p.read_text(encoding="utf-8") for p in installed if p.suffix in {".md", ".toml"}]
    # FILL IN: (1) every `parrot sdd run ([a-z_]+)` name resolves via importlib.util.find_spec("parrot.sdd.scripts.<name>");
    #          (2) no `python -m parrot.sdd.scripts.`, `python -m scripts.sdd.`, `scripts/sdd/<x>.(py|sh)` remains
    #          — bounded by spec §5 rev 0.2 ("every helper referenced by installed markdown runs as parrot sdd run <name>")
    raise NotImplementedError
```
**Why**: maps 1:1 onto spec §4 (`test_sdd_install_into_empty_repo`, `test_sdd_flow_in_foreign_repo`)
and the rev 0.2 receipt rule (C4), dry-run (C5) and seeds (C6/C10). `_tree_digest` is the
whole C5 proof: identical digests before/after means no write happened anywhere.

### `packages/ai-parrot/tests/sdd/test_sdd_cli.py` (CREATE)
```python
"""CLI tests for ``parrot sdd`` (FEAT-633 M6)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from parrot.cli import cli
from parrot.sdd.cli import sdd


def test_lazy_registration() -> None:
    assert cli._lazy_commands["sdd"] == "parrot.sdd.cli"
    assert cli.get_command(None, "sdd") is sdd


def test_install_status_uninstall_roundtrip(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output
    status = runner.invoke(cli, ["sdd", "status", "--path", str(tmp_path), "--json"])
    report = json.loads(status.output)
    assert report["hosts"]["claude"]["missing"] == [] and report["hosts"]["codex"]["missing"] == []
    result = runner.invoke(cli, ["sdd", "uninstall", "--path", str(tmp_path), "--host", "claude", "--host", "codex"])
    assert result.exit_code == 0, result.output


def test_unknown_host_is_a_usage_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--host", "vim"])
    assert result.exit_code == 2


def test_force_flag_overwrites(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["sdd", "install", "--path", str(tmp_path)])
    # FILL IN: edit one installed .claude/commands file, re-run without/with --force and assert skip/overwrite


def test_dry_run_flag_prints_plan_and_writes_nothing(tmp_path: Path) -> None:
    """C5 at the CLI layer."""
    result = CliRunner().invoke(cli, ["sdd", "install", "--path", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "plan: write" in result.output
    assert not any(tmp_path.iterdir())


def test_run_dispatches_helper_help() -> None:
    """Q1: `parrot sdd run reserve_ids --help` reaches the helper's argparse and exits 0."""
    result = CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--help"])
    assert result.exit_code == 0, result.output
    assert "--kind" in result.output and "--base-branch" in result.output  # reserve_ids' own argparse help


def test_run_unknown_helper_lists_available() -> None:
    result = CliRunner().invoke(cli, ["sdd", "run", "nope"])
    assert result.exit_code == 1
    assert "unknown helper" in result.output and "reserve_ids" in result.output and "sdd_meta" in result.output


def test_run_sdd_meta_is_dispatchable() -> None:
    """`sdd_meta` is a real helper after TASK-4299 (shipped markdown uses `parrot sdd run sdd_meta parse <spec>`)."""
    result = CliRunner().invoke(cli, ["sdd", "run", "sdd_meta", "--help"])
    assert result.exit_code == 0, result.output


def test_run_propagates_helper_exit_code() -> None:
    """A helper that argparse-rejects exits 2 — the code must pass through, not be flattened to 1."""
    result = CliRunner().invoke(cli, ["sdd", "run", "reserve_ids", "--kind", "bogus"])
    assert result.exit_code == 2
```

### `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (CREATE)
```python
"""C3 (FEAT-633 rev 0.2/0.3): prove the SDD flow from the BUILT WHEEL in a clean foreign repo.

Merge tier only (builds a wheel). Nothing here imports parrot: every assertion goes through
subprocesses whose PATH holds only $PARROT_HOME/bin and an allowlisted tools dir, with every
Python/venv/parrot override variable unset. Helpers are never mocked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

pytestmark = pytest.mark.integration  # FEAT-563 auto-mark covers only integration/ dirs — mark explicitly

REPO_ROOT = Path(__file__).resolve().parents[3]
INVOCATION_RE = re.compile(r"parrot sdd run ([a-z0-9_]+)((?: [^\n`]*)?)")  # digits: check_e2e_closeout
#: A `\`-continued shell line is one command: join before matching, or the flags on the next lines are lost.
CONTINUATION_RE = re.compile(r"\\\n[ \t]*")
#: The argv ends at the first shell control operator — e.g. the C16 frontmatter hook
#: `parrot sdd run worktree_environment --hook || exit 2'` runs as `worktree_environment --hook`.
SHELL_CUT_RE = re.compile(r"\s+(?:\|\||&&|\|)\s+|;")
#: Every host's install tree is scanned (AC: "all three hosts").
INSTALLED_DIRS = (".claude", ".agents", ".agent", ".codex", "sdd")
SCRUBBED_ENV = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PARROT_VENV", "PARROT_PROJECT", "CONDA_PREFIX")
#: System tools the fixture PATH may expose; anything else must come from the wheel.
TOOL_ALLOWLIST = ("git", "bash", "jq")

if shutil.which("uv") is None:  # pragma: no cover — this module must never import parrot itself
    pytest.skip("uv not on PATH", allow_module_level=True)


@dataclass
class Scenario:
    """How to run one documented helper invocation: placeholder values + required state."""

    placeholders: dict[str, str]
    prepare: Callable[[Path], None] = lambda repo: None  # creates ledger/task/index/evidence in a fresh clone
    expect_exit: int = 0
    tools: tuple[str, ...] = ("git",)
    stdin: Callable[[Path], str] | None = None  # e.g. the worktree_environment hook's PreToolUse payload
    expect_stdout: str = ""  # substring the helper's stdout must contain (e.g. '"permissionDecision": "deny"')


# FILL IN: one Scenario per helper name that appears in installed markdown (ensure_worktree, reserve_ids,
#          close_task, heal_orphans, check_task_state, select_tests, doc_taxonomy, worktree_status,
#          (NOT insight — rev 0.5 C22: /sdd-insight is not shipped, so no installed markdown invokes it),
#          finalize_task, check_task_graph, backfill_taxonomy, migrate_index, id_ledger, check_id_collisions,
#          install_hooks, AND sdd_meta — `parrot sdd run sdd_meta parse <spec>` / `taxonomy` / `resolve-flow …`
#          appear in shipped markdown after TASK-4299; review_checkpoint (C12, `prepare|validate`); spec_tools
#          (the seven subcommands, TASK-4334 amendment); brief_meta (`write-index`, rev 0.4 C17);
#          TASK-4508's cache_test_contract (`--spec <spec-path> --index …`, /sdd-task), test_report
#          (`decide-rerun|render`, /sdd-done), check_e2e_closeout (`--spec --feat-id --worktree`, /sdd-done; no
#          `e2e` key → optional → exit 0 without ai-parrot-server) and close_resolved_issues (`--worktree …`,
#          /sdd-done; shells out to `wikitoolkit ledger close`, so needs a seeded ledger); and worktree_environment
#          (C16 hook: argv `--hook`, `stdin` = a PreToolUse Write payload into `<clone>/.venv/` after `prepare`
#          creates `<clone>/.venv/pyvenv.cfg`, `expect_stdout='"permissionDecision": "deny"'`).
#          Placeholders: <FEAT-ID>→FEAT-001, <slug>→demo-feature,
#          TASK-<NNN>→TASK-001, <path>→<repo>, <base_branch>→main. `prepare` commits sdd/tasks/.id_ledger.json,
#          a per-spec index, one active task file and pushes to the bare origin where the helper needs them.
#          — bounded by proposal C3 step 5 (documented command AND flags, fixture inputs, isolated state)
SCENARIOS: dict[str, Scenario] = {}


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(REPO_ROOT / "packages/ai-parrot")], check=True)
    return next(out.glob("ai_parrot-*.whl"))


@pytest.fixture(scope="module")
def managed_home(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~/.parrot-like tree whose venv has ONLY the wheel + its declared runtime deps (non-editable)."""
    home = tmp_path_factory.mktemp("parrot-home")
    subprocess.run(["uv", "venv", str(home / "venv"), "--python", "3.12"], check=True)
    subprocess.run(["uv", "pip", "install", "--python", str(home / "venv/bin/python"), str(wheel)], check=True)
    (home / "bin").mkdir()
    for name in ("parrot", "wikitoolkit", "bookstore"):
        os.symlink(home / "venv/bin" / name, home / "bin" / name)
    return home


@pytest.fixture(scope="module")
def tools_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tools = tmp_path_factory.mktemp("tools")
    for name in TOOL_ALLOWLIST:
        if (found := shutil.which(name)) is not None:
            os.symlink(found, tools / name)
    assert (tools / "git").exists(), "git is a hard prerequisite of every scenario"
    return tools


def _env(home: Path, tools: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    env["PATH"] = f"{home / 'bin'}{os.pathsep}{tools}"
    env["PARROT_HOME"] = str(home)
    return env


@pytest.fixture
def foreign_repo(tmp_path: Path) -> tuple[Path, Path]:
    """(working clone, bare origin) of an unrelated non-Python repo with one commit on main."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    (repo / "README.md").write_text("# not a python project\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "-u", "origin", "main"], check=True)
    return repo, origin


def test_parrot_resolves_to_managed_install(managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]) -> None:
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    which = subprocess.run(["bash", "-c", "command -v parrot"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert Path(which.stdout.strip()).resolve() == (managed_home / "venv/bin/parrot").resolve()
    env_out = subprocess.run(["parrot", "self", "env"], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout
    assert str(managed_home / "venv") in env_out and "rule: managed" in env_out  # TASK-4080 `self env` format


def test_install_then_every_documented_helper_invocation(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, origin = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(
        ["parrot", "sdd", "install", "--host", "claude", "--host", "codex", "--host", "google"],
        cwd=repo, env=env, check=True,
    )
    texts = "\n".join(
        p.read_text(encoding="utf-8")
        for d in INSTALLED_DIRS if (repo / d).is_dir()
        for p in sorted((repo / d).rglob("*")) if p.is_file() and p.suffix in {".md", ".toml"}
    )
    texts = CONTINUATION_RE.sub(" ", texts)
    assert "python -m parrot.sdd.scripts" not in texts, "Q1: shipped markdown must use `parrot sdd run`"
    invocations = {
        (m.group(1), SHELL_CUT_RE.split(m.group(2), maxsplit=1)[0].rstrip(")").strip())
        for m in INVOCATION_RE.finditer(texts)
    }
    assert invocations, "no `parrot sdd run` invocations found — TASK-4089 rewrite missing?"
    missing = sorted({name for name, _ in invocations} - set(SCENARIOS))
    assert not missing, f"helpers documented but without a C3 scenario: {missing}"
    for i, (name, argv) in enumerate(sorted(invocations)):
        scenario = SCENARIOS[name]
        clone = tmp_path / f"scenario-{i}-{name}"
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
        for d in INSTALLED_DIRS:
            if (repo / d).is_dir():
                shutil.copytree(repo / d, clone / d, dirs_exist_ok=True)
        scenario.prepare(clone)
        for placeholder, value in scenario.placeholders.items():
            argv = argv.replace(placeholder, value.replace("<repo>", str(clone)))
        stdin = scenario.stdin(clone) if scenario.stdin else None
        result = subprocess.run(
            ["parrot", "sdd", "run", name, *argv.split()], cwd=clone, env=env, input=stdin, capture_output=True, text=True
        )
        assert result.returncode == scenario.expect_exit, f"{name} {argv}\n{result.stdout}\n{result.stderr}"
        assert scenario.expect_stdout in result.stdout, f"{name} {argv}\n{result.stdout}"


def test_installed_hook_denies_shared_environment_write(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]
) -> None:
    """C16 (proposal step 6): the hook command as installed in the sdd-coder / sdd-worker frontmatter still
    denies a shared-environment write in a foreign repo, with only $PARROT_HOME/bin + allowlisted tools on PATH."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "claude"], cwd=repo, env=env, check=True)
    for agent in ("sdd-coder", "sdd-worker"):
        front = (repo / ".claude/agents" / f"{agent}.md").read_text(encoding="utf-8").split("---", 2)[1]
        line = next(ln for ln in front.splitlines() if "worktree_environment --hook" in ln)
        command = line.split("command:", 1)[1].strip().strip("'")
        assert command == "parrot sdd run worktree_environment --hook || exit 2", command
        denied = {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": str(managed_home / "venv" / "x.py")}}
        result = subprocess.run(["bash", "-c", command], cwd=repo, env=env, input=json.dumps(denied), capture_output=True, text=True)
        decision = json.loads(result.stdout)["hookSpecificOutput"].get("permissionDecision")
        assert decision == "deny", f"{agent}: {result.stdout}\n{result.stderr}"
        # FILL IN: an allowed write (`README.md` in the repo) yields no permissionDecision — bounded by
        #          worktree_environment.hook_response (deny only for shared environments)


def test_c21_test_step_outcomes(managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]) -> None:
    """rev 0.5 C21 ("C3 pins each step's outcome"): the FEAT-699 helpers behave as pinned in a foreign repo."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "claude"], cwd=repo, env=env, check=True)

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["parrot", "sdd", "run", *argv], cwd=repo, env=env, capture_output=True, text=True)

    # FILL IN: fixtures — a spec from the installed sdd/templates/spec.md whose §4 Validation Contract is
    #          `none — fallback`, a copy without the section, and a per-spec index with one task — bounded by
    #          cache_test_contract.py / test_report.py / select_tests.py as listed in the Codebase Contract.
    fallback = run("cache_test_contract", "--spec", "<fallback-spec>", "--index", "<index>")
    assert (fallback.returncode, fallback.stdout.strip()) == (0, "fallback")
    assert run("cache_test_contract", "--spec", "<spec-without-section>", "--index", "<index>").returncode == 2
    decide = run("test_report", "decide-rerun", "--index", "<index>")
    assert (decide.returncode, decide.stdout.strip()) == (0, "rerun")
    assert run("test_report", "render", "--index", "<index>").returncode == 0
    assert run("select_tests", "--tier", "task", "<flags for a task with nothing to select>").returncode == 2


def test_c23_codex_install_writes_ledger_gitattributes_and_hooks(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]
) -> None:
    """rev 0.5 C23 done-when: after `parrot sdd install --host codex` the foreign repo has the block and the hooks."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "codex"], cwd=repo, env=env, check=True)
    attributes = (repo / ".gitattributes").read_text(encoding="utf-8")
    assert "sdd/ledger/events.jsonl merge=union" in attributes
    assert "sdd/ledger/archive/*.jsonl merge=union" in attributes
    for event in ("pre-commit", "post-merge", "post-checkout", "post-rewrite"):
        assert "# >>> parrot-ledger >>>" in (repo / ".git/hooks" / event).read_text(encoding="utf-8")
```
Note for implementer: the angle-bracket arguments in `test_c21_test_step_outcomes` are fixture placeholders (the `FILL IN` above); C21 fixes the outcomes, not the fixture shapes.
**Why**: proposal C3 (rev 0.3) step by step — wheel + declared deps, bare origin, documented
flags with fixture inputs, allowlisted tools, scrubbed env, managed-resolution assertion, no
mocks. `SCENARIOS` is the only `FILL IN`, and the test fails loudly for any documented helper
that lacks one, so coverage of "every documented helper invocation" is enforced, not hoped for.

### FILL IN checklist
- [ ] `installer.py::_upsert_marker_block` / `_remove_marker_block` — verbatim copies of claude_code/installer.py:51/:72.
- [ ] `installer.py::load_receipt` — read/validate; empty receipt on absence or bad schema (C4).
- [ ] `installer.py::plan_install` state→action mapping; `plan_uninstall` — receipt-matching removal, edited/foreign retention, shared-asset retention, gitignore/receipt removal (C4/C5).
- [ ] `installer.py::uninstall_sdd_integration` apply step.
- [ ] `installer.py::_audit` — S9 warnings from `scan_paths` + `missing_tools`; bounded by TASK-4070 API; never raises.
- [ ] `installer.py::sdd_status` — dict shape in the docstring (five states + seeds + flags).
- [ ] `cli.py::status` — human summary.
- [ ] `test_installer.py::test_status_shape`, `test_sdd_flow_in_foreign_repo`; `test_sdd_cli.py::test_force_flag_overwrites`.
- [ ] `test_wheel_only_foreign_repo.py::SCENARIOS` — one per helper name found in installed markdown (C3),
      incl. `review_checkpoint`, `spec_tools`, `brief_meta`, `worktree_environment` (stdin payload) and
      TASK-4508's four (no `insight` — rev 0.5 C22); the outcomes of the `cache_test_contract` /
      `select_tests` / `test_report` steps are pinned by `test_c21_test_step_outcomes` (rev 0.5 C21).
- [ ] `test_wheel_only_foreign_repo.py::test_installed_hook_denies_shared_environment_write` — the allowed-write
      counter-check (C16).
- [ ] `test_wheel_only_foreign_repo.py::test_c21_test_step_outcomes` — the fixture spec / index (C21).
- [ ] `installer.py::_install_gitattributes` — upsert + receipt record; bounded by
      `test_gitattributes_block_written_recorded_and_removed` (C23).

---

## Acceptance Criteria

- [ ] `parrot sdd install` into an empty non-Python git repo deploys every manifest asset for the
      requested host(s), writes the `.gitignore` marker block, seeds `sdd/tasks/.id_ledger.json`,
      `sdd/config.json` (C6) and `sdd/CONVENTIONS.md` (C10), and writes `sdd/.sdd-installed.json`
      (spec §5 rev 0.2: "`parrot sdd install` deploys the flow into an empty non-Python repo").
- [ ] Every helper referenced by installed markdown is invoked as `parrot sdd run <name>` and
      resolves to a `parrot.sdd.scripts` module; no `python -m` form remains
      (`test_sdd_flow_in_foreign_repo`, all three hosts).
- [ ] C4 receipt rule: absent → write + record; matches record → upgrade without `--force`
      (`test_untouched_file_upgrades_from_older_record`); differs from record → kept + `warning:`
      unless `--force`; not in record → foreign, kept even with `--force`
      (`test_foreign_file_never_touched_even_with_force`); unrecorded-but-identical → adopted;
      uninstall removes only receipt-matching files and never the ledger, config, seeds.
- [ ] `parrot sdd status` classifies every target as `missing | current | outdated | edited | foreign`
      and reports seeds as `seed-present | missing`; the receipt carries the writing ai-parrot version.
- [ ] C5: `install --dry-run` / `uninstall --dry-run` print one `plan:` line per action and leave the
      tree byte-for-byte unchanged (`test_dry_run_changes_nothing`).
- [ ] Seeds are written only when absent and survive `--force` and `uninstall`
      (`test_seeds_written_once_never_overwritten_or_removed`).
- [ ] Q1: `parrot sdd run reserve_ids --help` prints the helper's argparse help and exits 0; an
      unknown name exits 1 listing every `parrot.sdd.scripts` module, `sdd_meta` included; the
      helper's own exit code propagates (`test_run_*`).
- [ ] Seeds are generic over the manifest's optional `"seed": true` key (schema_version stays 1;
      missing key = `false`): every flagged entry gets the write-once rule and a `seeds` row in
      `status`; no seed path is hardcoded in `installer.py`.
- [ ] C3: `test_wheel_only_foreign_repo.py` passes on Linux CI in the merge tier with `-m integration`
      once TASK-4089's rewrite is in: ai-parrot loaded only from the built wheel, every documented
      helper invocation run with fixture inputs under the allowlisted PATH and scrubbed env, `parrot`
      and the helper interpreter resolved to the temporary managed install, no helper mocked; the
      invocations are collected from all three hosts' install trees, with `\`-continuations joined.
- [ ] *(rev 0.3 C16)* `test_installed_hook_denies_shared_environment_write` passes: the installed
      `sdd-coder` / `sdd-worker` hook command (`parrot sdd run worktree_environment --hook || exit 2`)
      denies a write into the managed venv in the foreign repo, with only `$PARROT_HOME/bin` + allowlisted
      tools on PATH (spec §5 C16 bullet).
- [ ] *(rev 0.5 C21)* `parrot sdd install` warns when `sdd/config.json` `test_command` is null
      (`test_install_warns_when_test_command_is_null`); `test_c21_test_step_outcomes` pins
      `cache_test_contract` (`none — fallback` → exit 0 `fallback`; missing section → exit 2),
      `test_report decide-rerun` → `rerun`, `test_report render` → exit 0, and `select_tests --tier task`
      with nothing selected → exit 2.
- [ ] *(rev 0.5 C23)* Any host writes the marker-delimited `.gitattributes` block (`merge=union` for
      `sdd/ledger/events.jsonl` and `sdd/ledger/archive/*.jsonl`), records it in the receipt, and
      `uninstall` removes it while keeping foreign lines; the four ledger hooks are installed through
      `claude_code/installer.py::_install_ledger_hooks`; after `parrot sdd install --host codex` the C3
      foreign repo has both (`test_c23_codex_install_writes_ledger_gitattributes_and_hooks`).
- [ ] *(rev 0.5 C22)* No C3 scenario or assertion involves `/sdd-insight`; counts follow TASK-4090
      (14 commands per host, 79 manifest entries).
- [ ] Unavailable tooling referenced by installed assets is reported as warnings, never as a failure (codex S9).
- [ ] `parrot sdd --help` lists `install`, `uninstall`, `status`, `run`; `--host` accepts only
      `claude|codex|google`; `parrot status` (agentd) is unchanged.
- [ ] `parrot.sdd.installer` does not import `parrot.knowledge.wiki.*` at module load (the C23
      ledger-hook step imports `_install_ledger_hooks` lazily, inside the step); `parrot.sdd.cli` imports
      no helper module at load time.
- [ ] `ruff check` passes on all six files; all tests below pass.

---

- [ ] *(rev 0.4 C17)* C3 scenarios exist for `ensure_worktree --brief-key`, `brief_meta write-index`
      and `check_task_graph` over a brief index; `parrot sdd install --host google` writes
      `.agent/workflows/sdd-brief.md`; every host writes `sdd/templates/brief.md`.

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py -q -m integration`
  (C3; merge tier only — builds a wheel, needs `uv` and `git`; skipped automatically without `uv`.
  Expected to FAIL until TASK-4089's `parrot sdd run` rewrite has landed: that failure is the
  design, not a bug in this task — record it in the Completion Note if TASK-4089 is not yet done.)
Also, outside the pytest contract: lint with `ruff check packages/ai-parrot/src/parrot/sdd/installer.py packages/ai-parrot/src/parrot/sdd/cli.py packages/ai-parrot/tests/sdd/`.

---

## Test Specification

> Minimal test scaffold. The agent must make these pass.

```python
# packages/ai-parrot/tests/sdd/test_installer.py — see the CREATE block:
#   test_sdd_install_into_empty_repo (spec §4), test_reinstall_is_idempotent,
#   test_modified_file_skipped_unless_force_and_kept_on_uninstall (C4 edited),
#   test_untouched_file_upgrades_from_older_record (C4 outdated), test_foreign_file_never_touched_even_with_force (C4 foreign),
#   test_unrecorded_identical_file_is_adopted (C4 adoption), test_dry_run_changes_nothing (C5),
#   test_seeds_written_once_never_overwritten_or_removed (C6/C10), test_existing_gitignore_content_preserved,
#   test_unknown_host_rejected, test_status_shape, test_sdd_flow_in_foreign_repo[claude|codex|google] (spec §4 integration),
#   test_gitattributes_block_written_recorded_and_removed[claude|codex|google], test_ledger_hooks_installed_for_any_host (C23),
#   test_install_warns_when_test_command_is_null (C21)
# packages/ai-parrot/tests/sdd/test_sdd_cli.py — see the CREATE block:
#   test_lazy_registration, test_install_status_uninstall_roundtrip, test_unknown_host_is_a_usage_error,
#   test_force_flag_overwrites, test_dry_run_flag_prints_plan_and_writes_nothing (C5),
#   test_run_dispatches_helper_help, test_run_unknown_helper_lists_available, test_run_sdd_meta_is_dispatchable,
#   test_run_propagates_helper_exit_code (Q1)
# packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py — see the CREATE block (C3, merge tier):
#   test_parrot_resolves_to_managed_install, test_install_then_every_documented_helper_invocation,
#   test_installed_hook_denies_shared_environment_write (C16), test_c21_test_step_outcomes (C21),
#   test_c23_codex_install_writes_ledger_gitattributes_and_hooks (C23)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4091 parrot-installer verified`
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
