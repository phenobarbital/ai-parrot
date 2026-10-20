---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, ci, docs]
tags: [installer, bootstrap, uv, launcher, mcp, windows, sdd-packaging]
---

# Feature Specification: Parrot Bootstrap Installer

**Feature ID**: FEAT-633
**Date**: 2026-10-05
**Author**: Jesus Lara (brainstorm + decisions); spec drafted with Claude
**Status**: approved
**Target version**: Next release (assigned by release tooling)
**Revision**: 0.5 (2026-10-20) — folds in C18–C24 of
`sdd/proposals/parrot-installer-amendments.proposal.md` (rev 0.6), from the 2026-10-19
readiness review (`sdd/state/FEAT-633/readiness-checkpoint-2026-10-19.md`) and Jesus Lara's
answers: helper inventory completed (TASK-4508), C16 move mechanics (TASK-4509),
`wikitoolkit mcp` on a core-only install, test steps in foreign repos, monorepo-specific
shipped text, the shared ledger in foreign repos, host/store follow-through.
**Revision 0.4** (2026-10-18) — folds in C17 of
`sdd/proposals/parrot-installer-amendments.proposal.md` (rev 0.5): `/sdd-brief` (FEAT-698)
ships through the installer (amends TASK-4070, 4085, 4089, 4090, 4091, 4299).
**Revision 0.3** (2026-10-17) — folds in C16 of the same proposal (rev 0.4):
`worktree_environment` enters scope (amends TASK-4085, 4072, 4089, 4090, 4091).
**Revision 0.2** (2026-10-14) — folds in the approved amendments of the same proposal
(rev 0.3): C2–C6, C8–C15, Q1, C7.
Amendment tags below (`[rev 0.2 C<n>]`, `[rev 0.3 C16]`, `[rev 0.4 C17]`, `[rev 0.5 C<n>]`) mark every changed clause.

> Source brainstorm: `sdd/proposals/parrot-installer.brainstorm.md` (accepted, Option B′,
> all 16 open questions resolved). Supersedes `sdd/specs/portable-sdd-flow.spec.md`
> (FEAT-583, draft — rejected design: no satellite package, no `sdd` binary).

---

## 1. Motivation & Business Requirements

### Problem Statement

Using the SDD flow, the wikitoolkit and the ai-parrot MCP toolkits inside Claude Code,
Codex or Gemini/Antigravity assumes a developer who already has Python and a project
`.venv` with ai-parrot installed. Everything downstream exists and works
(`parrot claude|codex|google install`, `parrot toolkits install`, `.parrot/mcp-toolkits.yaml`,
`parrot mcp-local`). What is missing is upstream and cross-cutting:

1. **No managed runtime.** `scripts/install/install-parrot.{sh,ps1}` (FEAT-586) assume a
   system Python and create a *project* venv with `python -m venv` + pip. There is no
   global `~/.parrot/venv`, no pinned `uv`, no path for "give my coding assistant the
   wikitoolkit in a repo that is not a Python project".
2. **No run-time venv resolution.** Host installers bake absolute paths at install time
   (`resolve_*_bin`: `<root>/.venv/bin/<name>` → `shutil.which` → bare name). A `.venv`
   created later is ignored; worktrees need the FEAT-495 `sh -c` fallback chain.
3. **POSIX-only wiring, three hosts over.** `.venv/bin/` is hardcoded in
   `claude_code/assets.py`, `codex/assets.py` and `google/assets.py`; no
   `Scripts\`/`.exe` branch exists anywhere. The bookstore entries pin
   `sys.executable -m parrot.knowledge.bookstore.cli mcp` with absolute `cwd` in all
   three hosts. Gemini's config is **user-global** (`~/.gemini/config/mcp_config.json`),
   so absolute per-project paths collide across repos.
4. **The SDD flow is not installable.** 15 `/sdd-*` commands *[rev 0.4 C17: `/sdd-brief`,
   FEAT-698]*, 9 `sdd-*` agents, hooks, rules, 13 templates and ~31 `scripts/sdd/` helpers
   *[rev 0.5: recounted on `dev` `0263f0724`]* live only in this repo. *[rev 0.5 C22]* 14 of
   the 15 commands ship in v1; `/sdd-insight` stays repo-local.
5. **Toolkit exposure installs nothing.** Templates carry only
   `summary|requires_llm|requires_dist`; no pip requirement, post-install step, or
   env-var declaration.
6. **No macOS wheels for core.** `release.yml` builds linux x86_64 + windows AMD64 only;
   only `parrot-codec` has a macOS job. The compiled chain (navigator-api[uvloop],
   navigator-auth (Rust), asyncdb, python-datamodel, ormsgpack, brotli, numexpr,
   faiss-cpu, pyarrow, two Cython extensions) makes compiler-free install on
   macOS/Windows unproven — the gating spike.

### Goals

- One-command global install on a clean machine (Linux/macOS/Windows): pinned `uv`,
  uv-managed **Python 3.12**, `~/.parrot/{bin,venv}`, `parrot`/`wikitoolkit`/`bookstore`
  on PATH — as a `--global` / `-Global` mode of the existing FEAT-586 scripts, fetched
  via raw GitHub URL + published checksum.
- Launch-time venv resolution: the three console scripts enter through a stdlib-only
  launcher that re-execs **only when running from the managed venv**; order
  `PARROT_VENV` → project venv (worktree `.venv` first, then main checkout) →
  `VIRTUAL_ENV` → stay managed; warn once per session on stderr when a project `.venv`
  lacks the script.
- Lifecycle group `parrot self` (`add | update | doctor | env | uninstall`), with
  `self add <component>` driven by new toolkit-template metadata
  (`requires_pip`, `post_install`, `requires_env`); `--here` targets the project venv.
- Three-host parity: Windows venv paths, opt-in `--portable` emission (bare launcher
  commands, committable, fixes the Gemini cross-repo collision), bookstore
  `sys.executable` pins replaced — default emission stays baked absolute paths.
- SDD flow installable: markdown assets packaged in core
  (`parrot/sdd/_assets/`), deployed by `parrot sdd install [--host …]`; invocable
  helpers migrate to `parrot.sdd.scripts`, invoked as `parrot sdd run <name>` so they run
  in the venv the launcher resolved, never in whatever `python` is first on PATH [rev 0.2 Q1];
  `.claude/` stays authoritative with a CI byte-equality sync check.
- Store safety under version skew: auto-migration (already existing in
  `SQLiteWikiStore`) hardened with pre-migration backup, single-writer locking and a
  **min-runtime gate** so an older runtime fails fast instead of corrupting a newer store.
- Core wheel matrix: macOS arm64 and linux aarch64 added; redundant linux legs removed.
- Validation-first: spikes S1–S6 are the first tasks of this feature; S1 (compiler-free
  install matrix) gates the bootstrap deliverable ordering.

### Non-Goals (explicitly out of scope)

- No `ai-parrot-sdd` satellite package, no `sdd` console binary, no manifest/symlink
  machinery — FEAT-583's design is rejected (owner, 2026-10-05). *[rev 0.2 C4]*
  "manifest machinery" means FEAT-583's packaging manifest and symlinks; the committed
  install receipt `sdd/.sdd-installed.json` (M6) is a different mechanism and is in scope.
- No generated `sdd/CONFIG.md`: the per-repo configuration is the single committed
  `sdd/config.json`, read directly by the shipped commands *[rev 0.2 C6]*.
- No repo-supplied test-selection policy in v1 *[rev 0.2 C7, option C]*: outside
  ai-parrot the shipped commands run the repo's `test_command` from `sdd/config.json`;
  FEAT-620's `CORE_PATHS` policy stays ai-parrot code. Revisit (option A) in v1.1.
- No shipped code rulebook *[rev 0.2 C10]*: `codebase-conventions.md` is ai-parrot's and
  stays a repo file; adopters get a `sdd/CONVENTIONS.md` seed they own.
- No per-component venv isolation (`uvx`-per-server) — one managed venv only.
- No code signing, notarization, PyApp or Rust launcher in v1 (brainstorm Options C/D;
  D remains the fallback if spike S2 fails on Windows).
- No replacement of FEAT-586's project-venv install mode — it is extended, not removed.
- No portable-by-default host config — baked absolute paths remain the default;
  `--portable` is opt-in (owner decision; rejects the brainstorm proposal's auto-detect).
- No implicit modification of a project's dependencies — installing into a project venv
  is always the explicit `--here` verb.
- No new root-level `install.sh`/`install.ps1` — the scripts stay in `scripts/install/`.
- No foreign-repo validation phase in v1 *[rev 0.5 C21]*: outside ai-parrot the shipped test
  steps run `test_command` or report "⚠️ not run"; layout-aware selection, a provisioned
  worktree venv and a zero-test gate in `report.py` are deferred to v1.1 with C7 option A.
- No `/sdd-insight` in the shipped set in v1 *[rev 0.5 C22]*: it depends on unshipped
  `reference/sdd-insight/` and `.claude/workflows/sdd-insight.js`.
- No core-only `wikitoolkit mcp` in v1 *[rev 0.5 C20]*: the managed runtime installs
  `ai-parrot-tools` alongside core; a core-only fallback is a follow-up outside FEAT-633.

---

## 2. Architectural Design

### Overview

Four cooperating pieces, each small, none changing current behavior by default:

1. **Bootstrap (`--global` mode)** extends `install-parrot.sh`/`.ps1`: download a pinned
   `uv` into `~/.parrot/bin/`, `uv venv ~/.parrot/venv --python 3.12`,
   `uv pip install --python ~/.parrot/venv "ai-parrot[...]"`, expose the three console
   scripts from `~/.parrot/bin`, add it to PATH (on Windows: auto-edit the *user* PATH,
   uv/rustup style). `~/.parrot` is a live data directory (wikis, library, skills,
   brains, parrot.db) — the bootstrap only adds `bin/` and `venv/`, and rollback on
   failure removes only what it created.
2. **Launcher (`parrot/launcher.py`, stdlib-only)** fronts the three
   `[project.scripts]` entries. When `sys.prefix` is NOT under `$PARROT_HOME/venv` it is
   a cheap comparison plus a direct call — every existing setup is byte-for-byte
   untouched. From the managed venv it resolves: `PARROT_VENV` → project venv (root from
   `--project`/`PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walk-up; worktree `.venv`
   first, then main checkout's) → `VIRTUAL_ENV` → stay managed. A candidate is valid
   only if it contains the requested console script; a project venv lacking it warns
   once per session on stderr and falls through. POSIX re-exec is `os.execv`; Windows is
   a child process with forwarded stdio/exit/termination (spike S2). Also consolidates
   the three existing `parrot_home()` copies.
3. **Lifecycle (`parrot self`)**: `add` installs a component's `requires_pip` into the
   managed venv with the bundled uv and runs `post_install`; `env` prints the resolved
   venv + the rule that picked it; `doctor` checks uv/Python/PATH/host configs/
   `requires_env`; `update`/`uninstall` manage the managed home. `parrot status` is
   taken (agentd) — diagnostics live under `self`.
4. **SDD asset installer (`parrot sdd`)**: packaged markdown assets deployed with the
   marker-block/merge discipline the wiki installers already use; helpers invocable as
   `parrot sdd run <name>` everywhere (monorepo `scripts/sdd/*.py` become
   thin wrappers so existing automation keeps working).

Host wiring stays with the three existing per-host installers (`mcp/hosts.py` adapters
reconcile *toolkit* entries only). All three `assets.py` gain the Windows branch;
`--portable` threads through the install CLIs down to the entry emitters, and
`_install_mcp_json`'s reconcile learns to respect a portable entry instead of reverting
it (today it force-replaces any differing `wikitoolkit` entry, installer.py:726–731).

Store safety: `SQLiteWikiStore` already auto-migrates on `schema_version` mismatch
(store.py `_maybe_migrate`/`_migrate`). This feature adds the safety rails the owner
required for the skew policy: pre-migration backup, migration under an exclusive lock,
and a `min_runtime_version` meta row stamped by migration — an older runtime opening the
store fails fast naming both versions and the fix (`parrot self update` /
`parrot self add --here`).

### Component Diagram

```
install-parrot.sh/.ps1 --global
        │  (downloads pinned uv; creates ~/.parrot/{bin,venv}; PATH)
        ▼
~/.parrot/venv (managed, py3.12) ──installs──► ai-parrot (+ components via `parrot self add`)
        │
[project.scripts] parrot / wikitoolkit / bookstore
        ▼
parrot/launcher.py ── is_managed()? ──no──► direct call (today's behavior, zero change)
        │ yes
        ├─ PARROT_VENV ─► reexec
        ├─ project venv (worktree .venv → main checkout .venv) ─► reexec
        ├─ VIRTUAL_ENV ─► reexec
        └─ stay managed ─► run here
                                 │
   parrot claude|codex|google install [--portable]      parrot sdd install [--host …]
        │ default: baked abs paths (+Windows fix)             │ marker-block deploy of
        │ --portable: bare launcher commands                  │ parrot/sdd/_assets/*
        ▼                                                     ▼
   .mcp.json / .codex/config.toml / ~/.gemini/…          .claude/commands|agents|rules, sdd/templates
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/install/install-parrot.{sh,ps1}` (FEAT-586) | extends | `--global`/`-Global` mode; existing modes untouched; CI dry-run grows |
| `pyproject.toml [project.scripts]` | modifies | three entries repointed to `parrot.launcher` wrappers |
| `cli/__init__.py::LazyGroup` | extends | `self`, `sdd` lazy commands |
| `knowledge/wiki/{claude_code,codex,google}/assets.py` | modifies | Windows `Scripts\` branch; `portable=` emission |
| `knowledge/wiki/{claude_code,codex,google}` bookstore emitters | modifies | `sys.executable` pin → `bookstore` command (portable) |
| `knowledge/wiki/claude_code/installer.py::_install_mcp_json` | modifies | reconcile respects portable entries (L726–731) |
| `mcp/toolkit_seed.py::ToolkitTemplate` + templates | extends | `requires_pip`, `post_install`, `requires_env` (parser is forward-compatible: unknown keys are skipped today) |
| `mcp/toolkit_install.py`, `cli/toolkits.py` | extends | offer `parrot self add` when `dist_available` is false |
| `knowledge/wiki/store.py::SQLiteWikiStore` | modifies | backup + lock + min-runtime gate around existing `_maybe_migrate` |
| `knowledge/wiki/project.py`, `knowledge/bookstore/config.py`, `cli/modes.py` | refactor | three `parrot_home()` copies delegate to `parrot.launcher` |
| `flows/dev_loop/worktree_environment.py` | source template **+ relocated** *[rev 0.3 C16]* | `repository_paths`/`shared_environments` logic ported (not imported) into the launcher; the module itself moves to `parrot/sdd/scripts/` (light parent) and leaves a re-export shim behind |
| `.github/workflows/release.yml` | modifies | core matrix: +macOS arm64, +linux aarch64, dedupe linux legs |
| `.claude/` SDD assets + `scripts/sdd/*` | packaged | synced copies under `parrot/sdd/_assets/`; helpers migrate to `parrot.sdd.scripts` |

### Data Models

```python
# mcp/toolkit_seed.py — extended template model (new fields, defaults keep old templates valid)
class ToolkitTemplate(BaseModel):
    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""
    requires_dist: tuple[str, ...] = ()        # import names (existing)
    requires_pip: tuple[str, ...] = ()         # NEW: pip requirement strings for `self add`
    post_install: tuple[str, ...] = ()         # NEW: argv executed after install (e.g. playwright install)
    requires_env: tuple[str, ...] = ()         # NEW: env keys `self doctor` checks

# knowledge/wiki/store.py — meta rows (key/value in the existing `meta` table; no new table)
#   'schema_version'      — existing (SCHEMA_VERSION = "3", store.py:51)
#   'min_runtime_version' — NEW: lowest wikitoolkit version allowed to open this store
```

### New Public Interfaces

- `parrot.launcher` — `parrot_home()`, `is_managed()`, `resolve_venv()`, `script_path()`,
  `reexec()`, `main_parrot()`, `main_wikitoolkit()`, `main_bookstore()` (skeletons in §3).
- `parrot self add|update|doctor|env|uninstall` (click group, lazy).
- `parrot sdd install|uninstall [--host claude|codex|google] [--dry-run] [--force]`,
  `parrot sdd status` (per-file `missing|current|outdated|edited|foreign`, seeds
  `seed-present|missing`) and `parrot sdd run <name> [args…]` (click group, lazy)
  *[rev 0.2 C4/C5/Q1]*.
- `parrot.sdd.config.SddConfig` + `load_sdd_config(root) -> SddConfig` over the committed
  `sdd/config.json` (`base_branch`, `staging_branch`, `hotfix_base`, `issue_tracker`,
  `jira_host`, `reviewer`, `test_command`) *[rev 0.2 C6]*; `knowledge/wiki/ledger/sdd_meta`
  (`resolve_flow`, `parse`, `FlowMeta`) takes its defaults from it *[rev 0.2 C8]*.
- `sdd/.sdd-installed.json` (install receipt: writing version + SHA-256 per target) and
  the `sdd/CONVENTIONS.md` seed *[rev 0.2 C4/C10]*.
- `parrot self doctor [--sdd | --runtime-only]` *[rev 0.2 C14/C15]*.
- `parrot sdd run <name>` for the flow helpers (see M6; 26 modules plus `__init__` after *[rev 0.5 C18]*).
- `--portable` flag on `parrot claude|codex|google install`.
- `--global` / `-Global` mode on `scripts/install/install-parrot.{sh,ps1}`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M0: spikes | no | — | evidence gathering, judgment calls |
| M1: launcher | no | — | core contract; Windows re-exec semantics tied to spike S2 |
| M2: bootstrap --global | yes | flag set, home layout, rollback rule and PATH strategy fixed below; mirror FEAT-586 script structure (sh case loop L56–99; ps1 param block L37–46) | — |
| M3: parrot self | partial | CLI surface + home consolidation fixed; `doctor` check list fixed in skeleton | `components.py` ↔ M4 metadata coupling needs M4 landed |
| M4: template metadata | yes | field names/types fixed in §2 Data Models; parser keys mirror existing `requires_dist:` branch (toolkit_seed.py:96) | — |
| M5: host portability | yes | `portable: bool = False` keyword threaded; Windows branch via `parrot.launcher.script_path`; reconcile rule fixed below | — |
| M6: SDD packaging | partial | asset tree, sync check, module migration list fixed | markdown rewrite needs spike S5's assumption inventory |
| M7: store gate | no | — | migration/locking semantics interact with live stores; spike S6 |
| M8: wheel matrix | yes | target matrix fixed below; follows build-parrot-codec's macOS/aarch64 precedent (release.yml:408–468) | — |

### Module 0: Spike validation (S1–S6)
- **Path**: `sdd/state/FEAT-633/spikes/` (reports only; no production code)
- **Responsibility**: de-risk before building. S1 clean-machine install matrix
  (macOS arm64 / Win11 x64 / Ubuntu x64, no compiler: `uv venv --python 3.12` +
  `uv pip install ai-parrot` + `wikitoolkit mcp` answers `initialize`; records every
  sdist fallback). S2 Windows stdio re-exec prototype. S3 host cwd/env probe (3 hosts,
  incl. Gemini user-global config). S4 launcher overhead timing. S5 SDD portability
  dry-run (assumption inventory for the markdown rewrite). S6 migration-safety prototype
  (backup + lock + gate vs a concurrent older runtime).
- **Depends on**: nothing. **Gates**: S1 → ordering of M2 vs M8 (if S1 fails, M8 ships
  first); S2 → M1 Windows path (fail ⇒ escalate to Option D for the launcher only);
  S5 → M6 rewrite list; S6 → M7 mechanism.

### Module 1: Run-time launcher
- **Path**: `packages/ai-parrot/src/parrot/launcher.py` (new) +
  `packages/ai-parrot/pyproject.toml` (scripts repoint)
- **Responsibility**: stdlib-only venv resolution + re-exec in front of the three
  console scripts; single home-path authority.
- **Depends on**: nothing in parrot (hard rule: stdlib imports only — hook latency,
  FEAT-595; enforced by a unit test asserting `parrot.launcher` imports no third-party
  or parrot modules). The re-exec decision happens **before importing any target**:
  `parrot` pulls Click and `bookstore` imports configuration at module load, so the
  wrappers must resolve first and import the real entry only on the final interpreter;
  the `wikitoolkit claude-hook` fast path must survive **after** a re-exec too (codex S1).
  *[rev 0.3 C16]* The same fast-path shape covers
  `parrot sdd run worktree_environment --hook`: it fires on every `PreToolUse` of an
  `sdd-coder`/`sdd-worker` seat, so its argv check happens before Click is imported,
  behind one `is_managed()` call. *[rev 0.5 C19]* That fast path is TASK-4509 (split out of
  TASK-4072); its budget reuses S4's targets (median delta ≤ 5 ms non-managed, ≤ 50 ms
  managed→project). *[rev 0.5 C24]* The launcher's `.git` walk-up stops at the system temp
  directory, mirroring `wiki.project._is_temp_root`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/launcher.py  (new; stdlib-only)
  PARROT_HOME_ENV = "PARROT_HOME"           # existing convention verified: knowledge/wiki/project.py:1234
  PARROT_VENV_ENV = "PARROT_VENV"           # new explicit override
  PARROT_PROJECT_ENV = "PARROT_PROJECT"     # new project-root pin (adapters set it when cwd is unreliable)
  LOOP_GUARD_ENV = "PARROT_LAUNCHER_RESOLVED"
  MANAGED_PYTHON = "3.12"                   # owner decision

  def parrot_home() -> Path:
      """$PARROT_HOME or ~/.parrot. Single authority; the three existing copies delegate here
      (knowledge/wiki/project.py:1223, knowledge/bookstore/config.py:66, cli/modes.py:68)."""

  def is_managed(prefix: str | None = None) -> bool:
      """True iff (prefix or sys.prefix) is under parrot_home()/'venv'."""

  def repository_paths(cwd: Path) -> tuple[Path, Path | None]:
      """(repo_root, main_checkout_or_None). Stdlib port of
      flows/dev_loop/worktree_environment.py:53-71 (gitdir:/commondir parsing)."""

  def find_project_root(argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> Path | None:
      """--project <p> / PARROT_PROJECT -> CLAUDE_PROJECT_DIR -> cwd walk-up to a git marker."""

  def script_path(venv: Path, name: str) -> Path:
      """venv/'bin'/name on POSIX; venv/'Scripts'/f'{name}.exe' on Windows."""

  def resolve_venv(script: str, *, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> tuple[Path, str]:
      """Returns (venv_path, rule); rule in {'PARROT_VENV','project','VIRTUAL_ENV','managed'}.
      A candidate is valid only if script_path(venv, script) exists. A project venv missing
      the script emits ONE stderr warning per process and falls through (owner decision)."""

  def reexec(target: Path, argv: list[str]) -> int:
      """POSIX: os.execv (no return). Windows: child with inherited stdio, exit-code
      propagation and teardown when the parent pipe closes (spike S2). Sets LOOP_GUARD_ENV."""

  def main_parrot() -> int: ...       # [project.scripts] parrot
  def main_wikitoolkit() -> int: ...  # wikitoolkit; preserves the claude-hook fast path cost
  def main_bookstore() -> int: ...    # bookstore
      # Each: if not is_managed() or LOOP_GUARD_ENV set -> import and call the real entry
      # (parrot.cli:cli / parrot.knowledge.wiki.entry:main / parrot.knowledge.bookstore.cli:main)
      # verified: packages/ai-parrot/pyproject.toml:199-207
  ```

### Module 2: Bootstrap `--global` mode
- **Path**: `scripts/install/install-parrot.sh`, `scripts/install/install-parrot.ps1`,
  `.github/workflows/ci.yml` (dry-run leg), `packages/ai-parrot/tests/docs/`
- **Responsibility**: pinned-uv download (checksum-verified), `~/.parrot/{bin,venv}`
  creation, Python 3.12, console-script shims, PATH (POSIX: profile line; Windows:
  auto-edit user PATH + "reopen terminal" notice). Rollback on failure removes only
  `bin/`+`venv/` additions it made — never pre-existing `~/.parrot` data. Never touches
  a user's own uv. Distribution: raw GitHub URL + checksum documented in INSTALL.md.
  **The `--global` branch runs BEFORE the existing system-Python guard** (codex S10):
  both scripts currently require Python up front, which a clean machine does not have —
  global mode parses/validates options, fetches pinned uv, and builds `~/.parrot`
  without ever hitting that guard; project mode behavior is unchanged. Interrupted
  downloads/upgrades must not leave broken shims (write-then-rename).
  **[rev 0.2 C14]** (a) *Transparency* (FEAT-586 AC8): at the start of `--global` mode the
  script prints what it downloads (pinned uv version, URL, checksum), where it writes
  (`PARROT_HOME/{bin,venv,python}`) and that the user's own uv is never touched; the docs
  give a non-piped alternative (download, inspect, verify checksum, run). (b) *Pre-install
  gate*, evaluated before anything is written or downloaded: platform in the supported
  wheel matrix (M8), a download tool and a checksum tool present, `PARROT_HOME` writable
  with free space above a named minimum, GitHub and PyPI reachable (skipped in
  `--dry-run`), `git` present — each failure exits with the condition and a fix.
  (c) *Post-install*: the script runs `"$PARROT_HOME/bin/parrot" self doctor --runtime-only`
  against the new managed runtime; a runtime failure triggers the existing rollback and
  prints doctor's fixes. Repository readiness (C15) never rolls back the runtime.
- *[rev 0.5 C20]* The managed venv installs `ai-parrot-tools` at the same version pin as
  `ai-parrot`: `wikitoolkit mcp`'s wiki tools live in `parrot_tools.wiki` since FEAT-540, so a
  core-only venv cannot answer MCP `initialize`.
- **Depends on**: M1 (the installed package must expose the launcher-fronted scripts).
- **Interface Skeleton** *(shell contract — flags only)*:
  ```
  install-parrot.sh  --global [--version X] [--python 3.12] [--with sdd,scraping] [--dry-run]
  install-parrot.ps1 -Global  [-Version X]  [-Python 3.12]  [-With sdd,scraping]  [-DryRun]
  # existing flags keep working unchanged (sh case loop verified scripts/install/install-parrot.sh:56-99;
  # ps1 param block verified scripts/install/install-parrot.ps1:37-46)
  ```

### Module 3: `parrot self` lifecycle group
- **Path**: `packages/ai-parrot/src/parrot/self_/` (new: `cli.py`, `components.py`,
  `doctor.py`) + `cli/__init__.py` (lazy entry) + the three `parrot_home()` call sites
- **Responsibility**: component install into the managed venv, environment inspection,
  diagnostics, update/uninstall of the managed home. Home-path consolidation: the three
  existing copies delegate to `parrot.launcher.parrot_home` (import is stdlib-safe).
- *[rev 0.5 C20/C23/C24]* `parrot self` treats `ai-parrot-tools` as part of the base runtime.
  `doctor` checks that `parrot_tools.wiki` imports. `doctor --sdd` checks the `.gitattributes`
  ledger block and the four ledger hooks. Both Gemini MCP config files are checked, with
  cross-repo collisions checked only on the user-global one.
- **Depends on**: M1 (home paths, `resolve_venv` for `env`); M4 (component metadata).
- **Interface Skeleton**:
  ```python
  # parrot/self_/cli.py  (new; registered in cli/__init__.py:109 _lazy_commands as "self")
  @click.group(name="self")
  def self_group() -> None:
      """Manage the parrot-managed runtime (~/.parrot)."""
  # subcommands: add(component, here: bool), update(version: str | None),
  #              doctor(sdd: bool = False, runtime_only: bool = False), env(), uninstall(yes: bool)
  #   [rev 0.2 C14/C15] --sdd and --runtime-only are mutually exclusive; exit 1 only when a
  #   non-informational check in the selected scope fails.

  # parrot/self_/components.py  (new)
  def install_component(name: str, *, venv: Path, here: bool = False) -> list[str]:
      """Resolve the toolkit template's requires_pip, run bundled
      `uv pip install --python <venv>`, then post_install argv. Returns action log.
      ToolkitTemplate verified: mcp/toolkit_seed.py:27-34."""

  # parrot/self_/doctor.py  (new)
  def run_doctor(root: Path) -> list[DoctorCheck]:
      """Checks: pinned uv present/version; managed venv Python == 3.12; PATH contains
      ~/.parrot/bin; host configs whose command paths don't exist (3 hosts incl. the
      Gemini user-global file); installed toolkits with unmet requires_dist/requires_env.
      [rev 0.2 C15] SDD readiness, run when <root>/sdd exists or --sdd: `origin` remote;
      configured base branch (sdd/config.json, default dev) exists on origin;
      sdd/tasks/.id_ledger.json git-tracked; .claude/worktrees/ ignored; `gh` present and
      authenticated; `jq` present while an installed file still uses it; installed SDD
      files current (parrot.sdd.installer.sdd_status, lazy import); host CLI present per
      installed host (informational). --runtime-only (bootstrap scope, C14): managed uv,
      Python, runtime entry points and PATH only. Doctor reports and suggests a fix; it
      never changes anything."""
  ```

### Module 4: Toolkit template install metadata
- **Path**: `mcp/toolkit_seed.py`, `mcp/_toolkit_templates/*.yaml`,
  `mcp/toolkit_install.py`, `cli/toolkits.py`
- **Responsibility**: `requires_pip` / `post_install` / `requires_env` header keys
  (`# parrot:` prefix, mirroring the `requires_dist:` branch at toolkit_seed.py:96 —
  the parser skips unknown keys silently, so old runtimes tolerate new templates);
  `inventory()` rows carry the new fields; `parrot toolkits install` prints the
  `parrot self add <name>` hint when `dist_available` is false (cli/toolkits.py:134).
  Contract boundaries (codex S6, adopted scoped): `requires_pip` holds **PEP 508
  requirement strings** (distribution names + optional constraints) and is never used
  for import probing — `requires_dist` keeps that job; `post_install` argv is executed
  by `self add` ONLY for templates shipped as package data (`available_templates()`
  reads `importlib.resources` exclusively, toolkit_seed.py:49 — there is no repo-local
  template loading), never from any user-writable source.
- *[rev 0.5 C24]* `bounded-source.yaml` and `targeted-writer.yaml` declare
  `requires_dist: parrot_tools` / `requires_pip: ai-parrot-tools`.
- **Depends on**: nothing (M3 consumes it).
- **Interface Skeleton**:
  ```python
  # mcp/toolkit_seed.py  (modifies class ToolkitTemplate, toolkit_seed.py:27-34)
  # new fields per §2 Data Models; parser gains three elif branches next to
  # `elif meta_content.startswith("requires_dist:"):`  # verified: mcp/toolkit_seed.py:96
  ```

### Module 5: Host portability (3 hosts + bookstore)
- **Path**: `knowledge/wiki/claude_code/{assets,installer,bookstore,cli}.py`,
  `knowledge/wiki/codex/{assets,installer,bookstore}.py`,
  `knowledge/wiki/google/{assets,installer}.py`, host CLI entry points
- **Responsibility**: (a) Windows branch — every `root/.venv/bin/<name>` resolution goes
  through `parrot.launcher.script_path`; (b) `--portable` flag on the three install
  CLIs, threaded to emitters: wikitoolkit entry `{"command": "wikitoolkit", "args": ["mcp"]}`,
  toolkit entries `parrot mcp-local …`, bookstore entry `{"command": "bookstore", "args": ["mcp"]}`
  (replacing the `sys.executable -m …` pin) — plus `PARROT_PROJECT` in `env` where cwd
  is unreliable (per spike S3); (c) reconcile rule: `_install_mcp_json` keeps an existing
  entry that matches EITHER the baked or the portable managed form — it only replaces
  entries matching neither (fixes installer.py:726-731 reverting portable entries);
  (d) **portable is a per-host field contract, not just a bare command** (codex S5):
  for each host define exactly which fields are omitted or made runtime-relative —
  Google's absolute `cwd`, toolkit entries' absolute `--config`, bookstore's absolute
  `cwd` — and test the default↔portable transitions in both directions; (e) Google's
  managed-entry detection uses `PurePosixPath` and must be made path-flavor-safe before
  the Windows branch lands (codex S4).
- *[rev 0.5 C24]* (a) also covers the git-hook bodies: `git_hook_block`/`ledger_hook_block`
  quote the binary path and write it with forward slashes, and `_is_wikitoolkit_entry` matches
  the script basename (`.exe` included). `--remote` (FEAT-569) composes with `--portable`:
  `--remote` decides only the `wikitoolkit` key. When that entry is http, url-only, absent or
  foreign, the portable mode is inferred from the managed `parrot-*` entries.
- **Depends on**: M1 (`script_path`; portable form assumes launcher on PATH).
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/claude_code/assets.py
  def resolve_wikitoolkit_bin(root: Path) -> str: ...   # modifies claude_code/assets.py:88 — Windows branch
  def mcp_json_entry(root: Path, *, portable: bool = False) -> dict: ...  # modifies :114
  # knowledge/wiki/codex/assets.py
  def resolve_binary(root: Path, name: str) -> str: ...  # modifies codex/assets.py:54
  def mcp_block(root: Path, toolkit_block: str = "", *, portable: bool = False) -> str: ...
  # knowledge/wiki/google/assets.py
  def bookstore_mcp_entry(root: Path, *, portable: bool = False) -> dict[str, Any]: ...  # modifies google/assets.py:107
  # knowledge/wiki/claude_code/installer.py
  def _install_mcp_json(root: Path, *, portable: bool = False) -> str: ...  # modifies installer.py:693
  ```

### Module 6: SDD asset packaging + installer
- **Path**: `packages/ai-parrot/src/parrot/sdd/` (new: `__init__.py`, `cli.py`,
  `installer.py`, `scripts/`, `_assets/{commands,agents,hooks,rules,templates}/`),
  `cli/__init__.py` (lazy `sdd`), `pyproject.toml` (package-data),
  `scripts/sdd/check_asset_sync.py` (new CI check), `scripts/sdd/*.py` (thin wrappers)
- **Responsibility**: package 14 of the 15 commands *[rev 0.4 C17; rev 0.5 C22: not `/sdd-insight`]*, 9 agents, SDD hooks, **one** rule
  (`worktree-management`, after C11's rewrite), the `second-opinion` skill, a
  `CONVENTIONS.md` seed and 13 templates *[rev 0.4 C17; rev 0.5: 13]* as package data *[rev 0.2 C9/C10]*; `parrot sdd install [--host …]` deploys them with the
  marker-block discipline (template: `claude_code/installer.py` `_upsert_marker_block`,
  installer.py:50). The 18 doc-referenced helpers (`sdd_meta`, `reserve_ids`,
  `ensure_worktree`, `close_task`, `heal_orphans`, `check_task_state`, `select_tests`,
  `insight`, `doc_taxonomy`, `worktree_status`, `finalize_task`, `check_task_graph`,
  `backfill_taxonomy`, `migrate_index`, `id_ledger`, `check_id_collisions`,
  `install_hooks`, + `__init__`) move to `parrot/sdd/scripts/`; *[rev 0.3 C16]* so does
  `flows/dev_loop/worktree_environment.py` — not because it is unpackaged (it already
  ships) but because the shipped `sdd-coder`/`sdd-worker` frontmatter addresses it by
  monorepo path, and its current parent package `parrot.flows.dev_loop` imports the
  whole dev-loop stack at module load, so `python -m` is not an option; it leaves a
  re-export shim for its three in-core importers; ALL markdown (installed
  AND monorepo) references the single form `parrot sdd run <name>` so the
  byte-equality sync holds; `scripts/sdd/*.py` become thin wrappers (import + main) for
  direct-invocation compatibility; `close_task.sh`/`heal_orphans.sh` logic ports to
  Python modules with the `.sh` files wrapping them. Source of truth: `.claude/` +
  `sdd/templates/` (owner decision); `check_asset_sync.py` fails CI on divergence
  (FEAT-553 `_rules_data` precedent). Packaging is a **verified build artifact**
  (codex S8): `MANIFEST.in` (today Cython-sources-only) grows the asset tree, and CI
  gains a wheel-content check proving the built wheel actually contains the full asset
  set — installed runtime behavior never depends on a monorepo checkout. The installer
  also **reports clearly** when an installed asset references tooling unavailable on
  the target machine (shell-only helpers, `jq`, POSIX-isms — codex S9; spike S5
  inventories them).
- **Depends on**: spike S5 (assumption inventory drives the markdown rewrite list).
- **Rev 0.4 amendment C17 — `/sdd-brief` ships** (details and "done when" in the
  amendments proposal §3 C17). FEAT-698 (merged 2026-10-17, PR #1715) added a 15th command
  (`.claude/commands/sdd-brief.md` + the Codex twin `.agents/skills/sdd-brief/SKILL.md`), a
  14th template (`sdd/templates/brief.md`), a repo-local helper (`scripts/sdd/brief_meta.py`)
  and `ensure_worktree --brief-key`. The packaging globs pick the command, the skill and the
  template up by themselves; what does not follow by itself: `brief_meta` joins TASK-4085's
  move (`ensure_worktree` imports it, so it cannot stay behind) and gains an argparse
  `main()` (`plan`, `write-index`) in TASK-4299 so installed markdown can say
  `parrot sdd run brief_meta …`; the missing Google twin `.agent/workflows/sdd-brief.md` is
  created by TASK-4089 before its rewrite; TASK-4070's helper map, TASK-4090's asset counts
  (15 commands per host, 13 tracked templates, 81 manifest entries; *[rev 0.5 C22]* 14 commands
  and **78** entries once `/sdd-insight` is excluded) and TASK-4091's C3
  scenarios (`ensure_worktree --brief-key`, `brief_meta write-index`) cover the new files.
- **Rev 0.5 amendments C18–C24 (M6 part)** (details and "done when" in the amendments
  proposal §3, rev 0.6):
  - **C18 — helper inventory.** Every module that moves into `parrot.sdd.scripts`: the 17
    this module named, plus `review_checkpoint`, `spec_tools`, `prune_intake`, `brief_meta`,
    `worktree_environment`, `test_report`, `close_resolved_issues`, `cache_test_contract`
    and `check_e2e_closeout`. That is 26 plus `__init__`; TASK-4508 moves the last four.
    Every `_KERNEL_PARENT`-style path loader becomes package-relative. `nightly_red_set`
    stays repo-local (CI only). C12's "`review_checkpoint` is the only one" is superseded.
  - **C19 — C16 move mechanics.** In both module and script mode, `_load_guard_bash` puts
    the package-relative kernel parent on `sys.path` and never imports
    `parrot.flows.dev_loop`; otherwise FEAT-563's guard fails open. The old path is a
    re-export shim that, run as a script, executes the moved file through `runpy`, so a
    bare `python3` keeps working. The programmatic hook command is
    `sys.executable -m parrot.sdd.scripts.worktree_environment --hook`. (TASK-4085, TASK-4509)
  - **C21 — test steps in a foreign repo.** `sdd/config.json` `test_command` is the switch:
    - When it is set, shipped `/sdd-done`, sdd-worker, qa-runner and sdd-autopilot run it
      once from the repo root instead of `select_tests`/`test_report`, and a non-zero exit
      blocks the merge.
    - When it is null (ai-parrot), the FEAT-699 path is unchanged.
    - Zero tests is reported "⚠️ not run", never ✅.
    - The spec template hints `none — fallback` for such repos, and `parrot sdd install`
      warns when `test_command` is null. (TASK-4089, TASK-4299, TASK-4091)
  - **C22 — monorepo-specific text.** Five categories, applied to all twins:
    - A: examples become placeholders.
    - B: layout and environment point to `sdd/CONVENTIONS.md`, which gains `## Repository
      layout` and `## Project areas`; ai-parrot's own rules move to the unshipped
      `codebase-conventions.md` twins; `SddConfig.projects` replaces `KNOWN_PROJECTS` when set.
    - C: citations of this repo's tests or CI are dropped.
    - D: `sdd-worker-format.sh:76` is the only allowlisted line.
    - E: navconfig one-liners become an env-var precondition.

    Both C16 gates add `tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/`.
    `/sdd-insight` does not ship, so there are **78** manifest entries. (TASK-4089, 4090,
    4091, 4299)
  - **C23 — shared ledger in foreign repos.** `parrot sdd install` (any host) writes a
    marker-delimited `.gitattributes` block (`merge=union` for `sdd/ledger/events.jsonl` and
    `archive/*.jsonl`), records it in the receipt, and installs the four ledger hooks.
    (TASK-4091, TASK-4080)
  - **C24 (SDD part).** TASK-4089 ports the E2E gate to the Google `/sdd-done` twin.
    `brief_meta`/`ensure_worktree` read `SddConfig` (TASK-4299). S5 also scans `.agents/` and
    `.agent/` (TASK-4070).
- **Rev 0.2 amendments** (details and "done when" in the amendments proposal §3):
  - **C2 — one copy of each agent prompt.** `load_subagent_definition()`
    (`flows/dev_loop/_subagent_defs.py`) reads the packaged `_assets/` copy, stripping
    frontmatter; the `_subagent_data/` copies of shipped prompts are deleted; the asset
    sync check replaces the (currently failing) prompt-parity test. (TASK-4090)
  - **C3 — wheel-only proof in a foreign repo.** An integration test builds the wheel,
    installs it (with runtime deps, non-editable) into a temporary `PARROT_HOME`, runs
    `parrot sdd install` in an unrelated non-Python git repo, and executes every helper
    invocation in the installed markdown with fixture inputs, only `$PARROT_HOME/bin` plus
    an allowlist of system tools on PATH, and no `PYTHONPATH`/`VIRTUAL_ENV`/`PARROT_VENV`.
    (TASK-4091; mirrored in the release smoke legs, TASK-4094)
  - **C4 — install receipt.** `sdd/.sdd-installed.json` records the writing version and
    the SHA-256 of every file written. Conflict rule: absent → write; matches record →
    upgrade; differs from record → edited, skip + warn unless `--force`; not in record →
    foreign, never touched. `uninstall` removes only recorded, unmodified files.
    `status` reports `missing|current|outdated|edited|foreign`. (TASK-4091)
  - **C5 — `--dry-run`** on `install`/`uninstall`: prints the full plan (per-path action,
    `.gitignore` block, ledger/config/conventions seeds) and writes nothing. (TASK-4091)
  - **C6 — repo config.** Committed `sdd/config.json`, validated by
    `parrot.sdd.config.SddConfig` (`base_branch`, `staging_branch`, `hotfix_base`,
    `issue_tracker`, `jira_host`, `reviewer`, `test_command`; features never base on the
    hotfix base). Shipped commands say "the base branch in `sdd/config.json`" instead of
    literals, so command files stay byte-identical across repos. The installer seeds it;
    ai-parrot's own `sdd/config.json` (`dev`/`staging`/`main`, Jira, codex) lands in the
    same task. (TASK-4299, after TASK-4298, before TASK-4089)
  - **C8 — one branch policy in core.** `_LONG_LIVED_BRANCHES` (`nodes/base.py`),
    `_WORK_KIND_BASE_BRANCH` and `_parse_flow_frontmatter` (`nodes/research.py`), the
    second `_parse_flow_frontmatter` (`nodes/feature_handoff.py`) and `KNOWN_BRANCHES` /
    `WORK_KIND_FLOW` / `resolve_flow` / `parse` / `FlowMeta` (`knowledge/wiki/ledger/
    sdd_meta.py`) collapse into the `sdd_meta` module, which gains
    `read_declared_base_branch(path) -> str | None` and takes its defaults from the C6
    config (today's values when no config exists). (TASK-4298)
  - **C9 — `second-opinion` ships** (claude host) and its references are conditional on
    `reviewer: codex`. (TASK-4090, TASK-4089)
  - **C10 — conventions seed.** `codebase-conventions.md` is not packaged; `sdd/
    CONVENTIONS.md` is seeded once, never overwritten or removed. (TASK-4090, TASK-4091)
  - **C11 — publication safety.** Scanner kinds `org-data`, `claude-md-ref`,
    `branch-literal` (TASK-4070); shipped text uses placeholders
    (`https://your-org.atlassian.net`, `PROJ-123`) and the `agy` reviewer ban stays only in
    ai-parrot's `CLAUDE.md` (TASK-4089); CI fails on any finding over `_assets/`; the wheel
    check also enforces a deny-list (`sdd/references/`, `sdd/state/`, `.parrot/`, `*.jsonl`,
    `*.db`, ledger files) (TASK-4090).
  - **C12 — no shipped reference to monorepo-only helpers.** `review_checkpoint` moves
    into `parrot.sdd.scripts` (TASK-4086); `test_no_repo_script_refs` fails on ANY
    `scripts.sdd.*` / `scripts/sdd/*` reference in a shipped file (TASK-4089).
  - **Q1 — `parrot sdd run <name> [args…]`** replaces `python -m` as the single form in
    ALL markdown (installed and monorepo). It runs the helper via `runpy.run_module` in
    the venv the launcher resolved. `python -m parrot.sdd.scripts.<name>` keeps working
    for direct use. (TASK-4091 implements; TASK-4089 rewrites)
- **Interface Skeleton**:
  ```python
  # parrot/sdd/installer.py  (new)
  def install_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *,
                              force: bool = False, dry_run: bool = False) -> list[str]:
      """Deploy packaged SDD assets into <root> (marker-block/merge; never overwrites
      foreign content; receipt-driven conflict rule; seeds config/conventions/ledger).
      Returns action log (the plan only, when dry_run)."""  # [rev 0.2 C4/C5/C6/C10]
  def uninstall_sdd_integration(root: Path, *, dry_run: bool = False) -> list[str]: ...
  def sdd_status(root: Path) -> dict[str, str]: ...  # target -> missing|current|outdated|edited|foreign
  RECEIPT_PATH = Path("sdd/.sdd-installed.json")   # {"version": str, "files": {target: sha256}}

  # parrot/sdd/config.py  (new) [rev 0.2 C6]
  CONFIG_PATH = Path("sdd/config.json")
  class SddConfig(BaseModel):
      base_branch: str = "dev"; staging_branch: str | None = None; hotfix_base: str = "main"
      issue_tracker: Literal["jira", "none"] = "none"; jira_host: str | None = None
      reviewer: Literal["codex", "none"] = "none"; test_command: str | None = None
      # validator: base_branch != hotfix_base
  def load_sdd_config(root: Path) -> SddConfig: ...   # defaults when the file is absent

  # parrot/sdd/cli.py  (new; lazy "sdd" in cli/__init__.py:109)
  #   install [--host …] [--dry-run] [--force] · uninstall [--dry-run] · status · run <name> [args…]
  ```

### Module 7: Store migration safety (backup + lock + min-runtime gate)
- **Path**: `knowledge/wiki/store.py`
- **Responsibility**: harden the EXISTING auto-migration (`_maybe_migrate`,
  store.py:1167; `_migration_needed`, :1413; `_migrate`, :1444): (a) before migrating,
  copy the db file to a timestamped sidecar backup and restore it if migration fails;
  (b) run the migration under an exclusive transaction/lock (pragmas applied in
  `_apply_pragmas`, :1074); (c) stamp `min_runtime_version` in `meta` alongside
  `schema_version` (:1493-1495); (d) `_open` (:1108) and `_connect_readonly` (:1321)
  check the gate first — an older runtime raises `WikiStoreVersionError` naming the
  store's minimum, the running version, and the fix. No `PRAGMA user_version` exists or
  is introduced; the `meta` key/value mechanism is extended. The migration lock must be
  **cross-process and Windows-safe** (codex S7): the store's asyncio lock is
  per-instance and the repo's existing file-lock precedent is `fcntl`-based
  (POSIX-only, see project.py:38-41) — use an `os.O_EXCL` sidecar lockfile or
  equivalent, never a no-op on Windows. Foreign/read-only stores keep never migrating.
- *[rev 0.5 C24]* The plane is stamped at creation (`_ensure_schema`) as well as in
  `_migrate`. A stored `schema_version` greater than `SCHEMA_VERSION`, compared as integers,
  raises `WikiStoreVersionError` instead of being migrated and re-stamped downward (ledger
  `issue:f249c19e8a4d`). Lock or backup creation failing with any `OSError` other than
  `FileExistsError` raises a clear error naming the directory; migration is never silently
  skipped. `SourceRegistry` opening `wiki.db` directly is a known bypass, out of scope
  (ledger `issue:1555e747bcb9`).
- **Depends on**: spike S6 (validates the concurrent-older-runtime failure mode).
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/store.py  (modifies class SQLiteWikiStore, store.py:948)
  MIN_RUNTIME_KEY = "min_runtime_version"   # new meta row next to 'schema_version' (store.py:1158)

  class WikiStoreVersionError(RuntimeError):
      """Raised when the store's min_runtime_version exceeds the running wikitoolkit
      version; message names both versions and the fix."""

  async def _check_runtime_gate(self, conn) -> None: ...   # called from _open (store.py:1108)
                                                           # and _connect_readonly (store.py:1321)
  def _backup_store(self) -> Path: ...                     # sidecar copy before _migrate (store.py:1444)
  ```

### Module 8: Core wheel matrix
- **Path**: `.github/workflows/release.yml`, `packages/ai-parrot/pyproject.toml`
  (`[tool.cibuildwheel]`)
- **Responsibility**: build-core gains macOS arm64 (macos-latest, following
  build-parrot-codec's precedent at release.yml:430-432) and linux aarch64
  (drop `*-manylinux_aarch64` from the skip string, pyproject.toml:1043-1051; add
  QEMU/archs config); collapse the four redundant ubuntu legs (each currently rebuilds
  the same cp311–314 set) into one.
- **Depends on**: nothing; can land first (and MUST land first if spike S1 fails).
- **Interface Skeleton**: n/a (CI yaml + toml config; target matrix:
  linux x86_64 + aarch64, windows AMD64, macos arm64, each cp311–cp313; cp314 stays
  built only if `requires-python <3.14` is relaxed — otherwise drop it from `build`).
  Build success is not the gate (codex S11): each platform leg adds a clean-environment
  smoke test — install the built wheel into a fresh venv, import parrot, run the three
  console scripts `--help`, and answer an MCP `initialize` — before `deploy` accepts it.
  **[rev 0.2 C3]** The Linux leg also runs the wheel-only foreign-repo SDD check
  (`parrot sdd install` in a temp non-Python repo, then every `parrot sdd run <name>`
  invocation from the installed markdown with fixture inputs), skipped with a notice while
  `parrot sdd` is absent from the wheel under test.
  *[rev 0.5 C20/C24]* Smoke legs install the `ai-parrot-tools` wheel (from `build-tools`)
  alongside core before the MCP `initialize`. `install-matrix` gains a linux-aarch64 leg so
  that wheel is smoke-tested too.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-633; the `sdd-coder` engine gives each
  task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (bootstrap exposes the launcher-fronted scripts; shim names fixed by M1)
  - M3 → M1 (`parrot_home`/`resolve_venv` imports) and M3 → M4 (`components.py` reads
    the new template fields)
  - M5 → M1 (`script_path` import; portable form assumes the launcher)
  - M6 → M0/S5 (rewrite list); M7 → M0/S6 (mechanism validation)
  - M6 internal order *[rev 0.2]*: TASK-4085 → TASK-4298 (C8) → TASK-4299 (C6) →
    TASK-4089 (rewrite) → TASK-4091 (installer); TASK-4090 (packaging) before TASK-4091.
  - M0, M4, M8 have no incoming edges — expected to run concurrently with everything.
- **Shared files** (tasks touching them get serialized):
  - `packages/ai-parrot/pyproject.toml` — M1 (`[project.scripts]`, :199) + M6
    (package-data, :969) + M8 (`[tool.cibuildwheel]`, :1043)
  - `cli/__init__.py` — M3 (`self`) + M6 (`sdd`), both in `_lazy_commands` (:109)
- **Exclusive resources**: `.github/workflows/release.yml` (M8 only — but release
  verification requires a tag, so M8's validation is PR-CI only); no extension rebuild
  or lockfile steps.
- **Cross-feature dependencies**: none. FEAT-583 is superseded (its spec was stamped
  `Status: superseded` in `2ed09515e` *[rev 0.2]*, so no task stamps it); FEAT-586 and
  FEAT-495 are completed history.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_launcher_not_managed_direct_call` | M1 | non-managed `sys.prefix` ⇒ no resolution, direct dispatch |
| `test_launcher_stdlib_only` | M1 | importing `parrot.launcher` loads no parrot/third-party modules |
| `test_resolve_order_and_validity` | M1 | PARROT_VENV > project > VIRTUAL_ENV > managed; candidates without the script skipped |
| `test_worktree_prefers_local_then_main` | M1 | linked-worktree fixture: worktree `.venv` wins; absent ⇒ main checkout |
| `test_script_path_windows` | M1 | `Scripts\name.exe` branch (monkeypatched `os.name`) |
| `test_warn_once_per_session` | M1 | project venv lacking script warns exactly once, on stderr |
| `test_install_sh_global_dry_run` | M2 | extends `tests/docs/test_install_posix.py` pattern for `--global` |
| `test_install_ps1_global_parse` | M2 | extends `tests/docs/test_install_powershell.py` for `-Global` |
| `test_self_env_rule_report` | M3 | `self env` prints venv + rule |
| `test_doctor_flags_broken_host_config` | M3 | config pointing at a missing binary is reported |
| `test_template_new_headers_parse` | M4 | requires_pip/post_install/requires_env round-trip |
| `test_template_unknown_keys_ignored` | M4 | forward-compat: old parser behavior preserved |
| `test_toolkits_install_offers_self_add` | M4 | missing dist ⇒ hint printed (cli/toolkits.py:134) |
| `test_portable_entries_no_abs_paths` | M5 | 3 hosts + bookstore: portable emission contains no absolute path |
| `test_default_emission_unchanged` | M5 | without `--portable`, output identical to today's (plus Windows fix) |
| `test_reconcile_respects_portable` | M5 | re-install does not revert a portable wikitoolkit entry |
| `test_sdd_install_into_empty_repo` | M6 | deploy + uninstall round-trip, marker-block safe |
| `test_sdd_scripts_module_entrypoints` | M6 | `parrot sdd run <each> --help` exits 0 for every packaged helper; unknown name fails listing the helpers [rev 0.2 Q1] |
| `test_asset_sync_check` | M6 | divergence between `.claude/` and `_assets/` fails; `--wheel` also fails on a planted deny-listed file or any scanner finding [rev 0.2 C11] |
| `test_installed_receipt_upgrade_paths` | M6 | untouched older file upgrades, edited file kept (unless `--force`), foreign file never touched, uninstall removes only recorded files [rev 0.2 C4] |
| `test_dry_run_changes_nothing` | M6 | tree hashes identical before/after `--dry-run` install and uninstall [rev 0.2 C5] |
| `test_sdd_config_validation` | M6 | `SddConfig` defaults, `base_branch == hotfix_base` rejected, absent file → defaults [rev 0.2 C6] |
| `test_branch_policy_single_source` | M6 | one definition; `read_declared_base_branch` returns `None` for missing/invalid frontmatter; `resolve_flow` fallback follows the config [rev 0.2 C8] |
| `test_audit_new_kinds` | M0 | `org-data`, `claude-md-ref`, `branch-literal` detected; placeholders excluded [rev 0.2 C11] |
| `test_no_repo_script_refs` | M6 | zero `scripts.sdd.*` / `scripts/sdd/*` references in any shipped file [rev 0.2 C12] |
| `test_subagent_single_source` | M6 | `load_subagent_definition` returns the packaged body; no `_subagent_data` twin remains for shipped prompts [rev 0.2 C2] |
| `test_doctor_sdd_readiness` | M3 | fixture repo missing each prerequisite fails the matching check with its fix; `--runtime-only` excludes repo/host checks; `--sdd` + `--runtime-only` rejected [rev 0.2 C14/C15] |
| `test_install_global_pre_install_gate` | M2 | each failed gate exits before any write; failed post-install `doctor --runtime-only` rolls back; repo-readiness failures do not [rev 0.2 C14] |
| `test_docs_claims_cli_verb_flag` | docs | claim harness verifies `cli-verb`/`flag` claims against the real click commands [rev 0.2 C13] |
| `test_gate_blocks_older_runtime` | M7 | store stamped with higher min_runtime ⇒ `WikiStoreVersionError` with both versions in message |
| `test_migration_backup_and_restore` | M7 | failed migration restores the sidecar backup |
| `test_migration_lock_windows_safe` | M7 | cross-process lock is not a no-op when `fcntl` is unavailable |
| `test_portable_transitions_both_ways` | M5 | default→portable and portable→default re-installs land exactly the requested form |

### Integration Tests
| Test | Description |
|---|---|
| `test_launcher_state_machine_subprocess` | subprocess-level matrix (codex S3): each console script from managed/project envs × missing script × linked worktree × symlinked interpreter × `--project` × no-candidate fallback (Windows names via monkeypatch) |
| `test_managed_to_project_reexec_stdio` | spawn via launcher from a fake managed venv; JSON-RPC initialize round-trip intact, stderr-only diagnostics |
| `test_portable_config_two_roots` | same `--portable` output generated from two different fake roots is byte-identical (committable) |
| `test_wheel_only_foreign_repo` | *(replaces `test_sdd_flow_in_foreign_repo` [rev 0.2 C3])* build the wheel, install it into a temp `PARROT_HOME`, `parrot sdd install` into a tmp non-Python git repo, run every helper invocation from the installed markdown with fixture inputs and only `$PARROT_HOME/bin` + an allowlist of system tools on PATH |
| `test_store_migrate_then_old_open` | migrate a fixture store, reopen with a mocked older version ⇒ fail-fast gate (spike S6 codified) |

### Validation Contract
> *[rev 0.5 C21]* Merge- and feature-tier selection for FEAT-633 (FEAT-699 format).
> The contract covers every pytest file that a FEAT-633 task's Validation Commands name, following
> the FEAT-699 convention that `check_task_graph` enforces (`test-contract-task-tests-uncovered`).
> It also includes the module-level suites listed per module above. Operands that tasks create
> are skipped until they exist. `test_wheel_only_foreign_repo` (TASK-4091) runs `uv build` and
> exists only from TASK-4091 onward. Each comment lists the declaring tasks, or `spec` for a
> module-level suite.

tests:
- packages/ai-parrot/tests/cli/test_modes.py  # 4073
- packages/ai-parrot/tests/cli/test_toolkits_cli.py  # 4078,4080,spec
- packages/ai-parrot/tests/docs/test_ci_install_wiring.py  # 4076
- packages/ai-parrot/tests/docs/test_getting_started_claims.py  # 4095,spec
- packages/ai-parrot/tests/docs/test_install_posix.py  # 4068,4074,4076,spec
- packages/ai-parrot/tests/docs/test_install_powershell.py  # 4075,spec
- packages/ai-parrot/tests/docs/test_probe_mcp_env.py  # 4069
- packages/ai-parrot/tests/docs/test_release_matrix.py  # 4094
- packages/ai-parrot/tests/docs/test_smoke_install.py  # 4068
- packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_finalize_task.py  # 4086,4087
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_optimization_workflow_contracts.py  # 4086
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py  # 4086
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_handoff_contract.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py  # 4089
- packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py  # 4298
- packages/ai-parrot/tests/flows/dev_loop/test_branch_policy_single_source.py  # 4298
- packages/ai-parrot/tests/flows/dev_loop/test_flow_type_override.py  # 4298
- packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_rules_parity.py  # 4089,4090
- packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_codereview.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs_conventions.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py  # 4090
- packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py  # 4089
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py  # 4085,4509
- packages/ai-parrot/tests/knowledge/bookstore/test_config.py  # 4073
- packages/ai-parrot/tests/knowledge/wiki/schema/test_cli_schema.py  # 4081
- packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py  # 4082
- packages/ai-parrot/tests/knowledge/wiki/test_claude_portable_emitters.py  # 4081
- packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py  # 4083
- packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py  # 4083
- packages/ai-parrot/tests/knowledge/wiki/test_google_installer_conventions.py  # 4084
- packages/ai-parrot/tests/knowledge/wiki/test_google_portable.py  # 4084
- packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py  # 4081,4082
- packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py  # 4081,4082
- packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py  # 4083
- packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py  # 4081
- packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py  # 4092,4093
- packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py  # 4092,4093
- packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py  # 4092,4093,spec
- packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py  # 4093
- packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py  # 4092
- packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py  # 4092,spec
- packages/ai-parrot/tests/launcher/test_launcher_core.py  # 4071
- packages/ai-parrot/tests/launcher/test_launcher_reexec.py  # 4072,spec
- packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py  # 4509
- packages/ai-parrot/tests/launcher/test_launcher_stdlib_only.py  # 4072,spec
- packages/ai-parrot/tests/launcher/test_parrot_home_consolidation.py  # 4073
- packages/ai-parrot/tests/mcp/test_lsp_template.py  # 4077
- packages/ai-parrot/tests/mcp/test_toolkit_install.py  # 4078
- packages/ai-parrot/tests/mcp/test_toolkit_seed_install_metadata.py  # 4077
- packages/ai-parrot/tests/sdd/test_audit.py  # 4070,spec
- packages/ai-parrot/tests/sdd/test_config.py  # 4299,spec
- packages/ai-parrot/tests/sdd/test_installer.py  # 4091,spec
- packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py  # 4089
- packages/ai-parrot/tests/sdd/test_scripts_closeout_helpers.py  # 4508
- packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py  # 4085
- packages/ai-parrot/tests/sdd/test_scripts_shell_port.py  # 4087
- packages/ai-parrot/tests/sdd/test_scripts_task_state.py  # 4086
- packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py  # 4088
- packages/ai-parrot/tests/sdd/test_sdd_cli.py  # 4091
- packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py  # 4091
- packages/ai-parrot/tests/self_/test_components.py  # 4079
- packages/ai-parrot/tests/self_/test_doctor.py  # 4080
- packages/ai-parrot/tests/self_/test_doctor_sdd.py  # 4080,spec
- packages/ai-parrot/tests/self_/test_self_cli.py  # 4080
- tests/knowledge/wiki/test_claude_code.py  # 4081,4082,spec
- tests/knowledge/wiki/test_claude_code_bookstore.py  # 4081,4082
- tests/knowledge/wiki/test_codex_bookstore.py  # 4083
- tests/knowledge/wiki/test_codex_installer_toolkit_entries.py  # 4083
- tests/knowledge/wiki/test_codex_integration.py  # 4083,spec
- tests/knowledge/wiki/test_codex_toolkit_reconcile.py  # 4083
- tests/knowledge/wiki/test_google_bookstore.py  # 4084
- tests/knowledge/wiki/test_google_installer_toolkit_entries.py  # 4084
- tests/knowledge/wiki/test_google_integration.py  # 4084,spec
- tests/knowledge/wiki/test_installer_ledger_hooks.py  # 4081,4082
- tests/knowledge/wiki/test_installer_mcp_approval.py  # 4082
- tests/knowledge/wiki/test_installer_toolkit_entries.py  # 4081,4082
- tests/knowledge/wiki/test_project_namespaces.py  # 4073
- tests/mcp/test_toolkit_seed.py  # 4077,spec
- tests/mcp/test_toolkit_templates.py  # 4077
- tests/sdd/test_close_task_ledger.py  # 4087
- tests/sdd/test_codex_sdd_sync.py  # 4089
- tests/sdd/test_ledger_lifecycle_acceptance.py  # 4087
- tests/sdd/test_ledger_workflow_twins.py  # 4089,4508
- tests/sdd_scripts/test_backfill_taxonomy.py  # 4088
- tests/sdd_scripts/test_brief_meta.py  # 4085,4299
- tests/sdd_scripts/test_brief_scaffold_integration.py  # 4085,4086,4299
- tests/sdd_scripts/test_brief_template_contract.py  # 4085,4299
- tests/sdd_scripts/test_cache_test_contract.py  # 4508
- tests/sdd_scripts/test_check_asset_sync.py  # 4090,spec
- tests/sdd_scripts/test_check_e2e_closeout.py  # 4508
- tests/sdd_scripts/test_check_id_collisions.py  # 4085
- tests/sdd_scripts/test_check_task_graph.py  # 4086
- tests/sdd_scripts/test_check_task_state.py  # 4086,4087
- tests/sdd_scripts/test_close_resolved_issues.py  # 4508
- tests/sdd_scripts/test_command_contracts.py  # 4089,4090,4298,4299,4334,spec
- tests/sdd_scripts/test_command_twin_parity.py  # 4089,4334,spec
- tests/sdd_scripts/test_design_research_templates.py  # 4334
- tests/sdd_scripts/test_doc_taxonomy.py  # 4088
- tests/sdd_scripts/test_e2e_closeout_contract.py  # 4089,4508
- tests/sdd_scripts/test_ensure_worktree.py  # 4085,4298,4299,spec
- tests/sdd_scripts/test_feat699_doc_contract.py  # 4090
- tests/sdd_scripts/test_id_ledger.py  # 4085
- tests/sdd_scripts/test_insight_sdd.py  # 4088
- tests/sdd_scripts/test_install_hooks.py  # 4088
- tests/sdd_scripts/test_migrate_index.py  # 4088
- tests/sdd_scripts/test_prune_intake.py  # 4088
- tests/sdd_scripts/test_reserve_ids.py  # 4085
- tests/sdd_scripts/test_sdd_brief_command_contract.py  # 4089
- tests/sdd_scripts/test_sdd_brief_twin_contract.py  # 4089
- tests/sdd_scripts/test_sdd_meta.py  # 4085
- tests/sdd_scripts/test_sdd_meta_branch_policy.py  # 4298,4299
- tests/sdd_scripts/test_sdd_meta_config_defaults.py  # 4299
- tests/sdd_scripts/test_sdd_meta_resolve_flow.py  # 4298,4299
- tests/sdd_scripts/test_select_tests.py  # 4088
- tests/sdd_scripts/test_spec_tools.py  # 4088,4334
- tests/sdd_scripts/test_test_report.py  # 4508
- tests/sdd_scripts/test_worktree_plan.py  # 4085,4298,4299
- tests/sdd_scripts/test_worktree_status.py  # 4086
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
def fake_managed_home(tmp_path, monkeypatch):
    """~/.parrot-like tree with bin/ + venv/ (pyvenv.cfg + script stubs); sets PARROT_HOME."""

@pytest.fixture
def linked_worktree_repo(tmp_path):
    """main checkout + git worktree with/without own .venv (gitdir:/commondir files)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Console scripts invoked from any non-managed venv behave byte-for-byte as today
      (no re-exec, no output change) — guarded by `test_launcher_not_managed_direct_call`.
- [ ] From the managed venv, resolution order is `PARROT_VENV` → project venv (worktree
      `.venv` first, then main checkout) → `VIRTUAL_ENV` → managed; a candidate without
      the requested script is skipped; a project venv lacking ai-parrot warns once per
      session on stderr.
- [ ] `parrot.launcher` imports stdlib only (test-enforced); `wikitoolkit claude-hook`
      latency in a non-managed venv is unchanged within noise (spike S4 evidence in
      `sdd/state/FEAT-633/spikes/`).
- [ ] stdout is never written before the MCP handshake; all launcher diagnostics go to
      stderr.
- [ ] `install-parrot.sh --global` / `install-parrot.ps1 -Global` produce
      `~/.parrot/{bin,venv}` with pinned uv and Python 3.12; never touch the user's own
      uv; failure rolls back only what the run created (pre-existing `~/.parrot` data
      intact); CI dry-run legs cover the new mode; the documented install command is a
      raw GitHub URL with a published checksum.
- [ ] Windows: user PATH is auto-edited (registry) with a reopen-terminal notice;
      `script_path` resolves `Scripts\<name>.exe`.
- [ ] Default host emission (no `--portable`) is unchanged except the Windows fix;
      `--portable` emission for Claude, Codex AND Google contains no machine-specific
      absolute path **in any field** — command, args (`--config`), `cwd` and env
      included; bookstore carries no `sys.executable` — and re-running
      `parrot claude install` (either mode) lands exactly the requested form without
      reverting the other (codex S5).
- [ ] Toolkit templates accept `requires_pip`/`post_install`/`requires_env`; old
      runtimes still parse new templates (unknown-key skip verified);
      `parrot toolkits install` offers `parrot self add` when the distribution is
      missing; `parrot self add <component>` installs into the managed venv and runs
      post-install; `--here` targets the project venv and is the only way dependencies
      enter a project.
- [ ] `parrot sdd install` deploys the flow into an empty non-Python repo; every helper
      referenced by installed markdown is invoked as `parrot sdd run <name>` and runs from
      a wheel-only managed install (C3 test); `scripts/sdd/` wrappers keep the monorepo's
      existing invocations working; `check_asset_sync.py` gates CI on `.claude/` ↔
      `_assets/` divergence AND on deny-listed or scanner-flagged content [rev 0.2 Q1/C3/C11].
- [ ] *[rev 0.3 C16]* No shipped file names a monorepo source path (`packages/`,
      `scripts/`, `$CLAUDE_PROJECT_DIR/…`) — `test_no_repo_script_refs` is widened past
      C12's `scripts/sdd` sweep — and C3's foreign-repo test shows the shared-environment
      guard denying a write with only `$PARROT_HOME/bin` on PATH.
- [ ] *[rev 0.4 C17]* `parrot sdd install` deploys `/sdd-brief` on all three hosts
      (`.claude/commands/sdd-brief.md`, `.agents/skills/sdd-brief/SKILL.md`,
      `.agent/workflows/sdd-brief.md`) and `sdd/templates/brief.md`; the installed
      `sdd-brief.md` invokes only `parrot sdd run ensure_worktree --brief-key …`,
      `parrot sdd run brief_meta write-index …` and `parrot sdd run check_task_graph …`,
      each covered by a C3 scenario; `scripts.sdd.brief_meta` stays importable as a shim.
- [ ] *[rev 0.2 C4/C5]* Re-running `parrot sdd install` upgrades untouched files, keeps
      edited ones (warning; `--force` overrides), never touches files it did not write;
      `parrot sdd status` reports `missing|current|outdated|edited|foreign`; `--dry-run`
      prints the full plan and changes nothing.
- [ ] *[rev 0.2 C6/C8]* A foreign repo using `main` + `develop` runs the flow by editing
      only `sdd/config.json`; the branch policy has exactly one definition in core and
      ai-parrot's own behaviour is unchanged (`dev`/`staging`/`main`).
- [ ] *[rev 0.2 C10/C11/C12]* No shipped file mandates a language, framework or package
      manager; no shipped file carries org data, `CLAUDE.md` references, branch literals or
      references to helpers outside `parrot.sdd.scripts`; `sdd/CONVENTIONS.md` is seeded
      once and never overwritten.
- [ ] *[rev 0.2 C2]* Each shipped agent prompt has exactly one source; the dev-loop loads
      the packaged copy; the prompt-parity test is gone.
- [ ] *[rev 0.2 C14/C15]* `--global` bootstrap explains what it downloads and writes, gates
      on platform/tools/space/network/git before any write, and runs
      `parrot self doctor --runtime-only` afterwards (runtime failure rolls back; repo
      readiness never does); `parrot self doctor` reports SDD readiness with a fix per check.
- [ ] Wiki store migration takes a sidecar backup first, restores it on failure, runs
      locked, stamps `min_runtime_version`; an older runtime opening a newer store fails
      fast with both versions and the fix in the message (read-only paths included).
- [ ] `release.yml` builds core wheels for linux x86_64 + aarch64, windows AMD64 and
      macOS arm64 (cp311–cp313 minimum); the redundant quadruple ubuntu legs are gone.
- [x] `sdd/specs/portable-sdd-flow.spec.md` is stamped `Status: superseded` referencing
      FEAT-633 (done in `2ed09515e`, 2026-10-14 *[rev 0.2]*).
- [ ] *[rev 0.5 C18]* No shipped file invokes a helper outside `parrot.sdd.scripts`.
- [ ] *[rev 0.5 C19]* `test_worktree_environment.py` passes against the moved module, and the old
      path still answers `--hook` when run with a bare interpreter.
- [ ] *[rev 0.5 C20]* S1: `wikitoolkit mcp` answers `initialize` from the managed runtime on every leg.
- [ ] *[rev 0.5 C21]* In a foreign repo with `test_command` set, every shipped test step runs it or
      reports ⚠️, and none reports ✅ on zero tests. `cache_test_contract --check` passes on
      this spec and its index.
- [ ] *[rev 0.5 C22]* Both C16 gates pass with the single allowlisted line;
      `check_asset_sync.py` reports 78 entries.
- [ ] *[rev 0.5 C23]* After `parrot sdd install --host codex`, the C3 foreign repo has the
      `.gitattributes` ledger block and the four ledger hooks.
- [ ] *[rev 0.5 C24]* A newer `schema_version` is refused, not re-stamped (`issue:f249c19e8a4d`
      closed by TASK-4092), and git-hook bodies survive a Windows path.
- [ ] No new runtime dependency in ai-parrot core; `ruff check` passes; all tests in §4
      pass; docs updated *[rev 0.2 C13]*: `docs/getting-started.md` is the canonical,
      CI-verified install guide (`--global`, `parrot self`, `parrot sdd`, "Use the SDD
      flow in your repo"); `docs/install/global-runtime.md` holds the reference detail;
      `INSTALL.md` / `docs/INSTALL.md` are pointers; `.mcp.json.example` note.

---

## 6. Codebase Contract

> Verified on branch `dev` @ `56ff8cd58` (2026-10-05) by direct source reads.
> *[rev 0.5]* Several anchors below have since moved on `dev`, e.g. `store.py` +144 after
> `6791d81ce`, `project.py` `parrot_home` 1223→1371, `cli/__init__.py` `status` 134→136, and
> `claude_code/installer.py` `_install_mcp_json` → 694 with a `remote=` parameter. The task
> files carry anchors re-verified on 2026-10-19 (`dev` `9f51c7735`) and are authoritative.
> Paths relative to `packages/ai-parrot/src/parrot/` unless noted.

### Verified Imports
```python
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template  # mcp/toolkit_seed.py:27,49,63
from parrot.mcp.toolkit_install import dist_available, inventory, install_toolkits      # mcp/toolkit_install.py:60,94,152
from parrot.mcp.hosts import HostKind, detect_hosts                                     # mcp/hosts.py:18,~235
from parrot.knowledge.wiki.claude_code import assets                                    # claude_code/assets.py
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration      # claude_code/installer.py:964
from parrot.knowledge.wiki.codex.installer import install_codex_integration             # codex/installer.py:316
from parrot.knowledge.wiki.google.installer import install_google_integration           # google/installer.py:285
```

### Existing Class Signatures
```python
# mcp/toolkit_seed.py
class ToolkitTemplate(BaseModel):                      # line 27
    name: str; body: str
    requires_llm: bool = False                         # line 32
    summary: str = ""                                  # line 33
    requires_dist: tuple[str, ...] = ()                # line 34
# header parser: elif meta_content.startswith("requires_dist:")  # line 96; ctor call line 105
# unknown "# parrot:" keys are skipped silently (lines 84-98) ⇒ new keys are forward-compatible

# mcp/toolkit_install.py
def dist_available(requires_dist: Sequence[str]) -> bool:                      # line 60
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:  # line 94
#   calls dist_available at line 131; ToolkitRow.dist_available: bool = True   # line 47

# cli/toolkits.py
#   if row.requires_dist and not row.dist_available:   # line 134 — the "missing dist" hint site

# cli/__init__.py
cli._lazy_commands = {                                 # line 109; 24 entries; "toolkits" at line 117
#   NO self / sdd / env / doctor; `parrot status` is TAKEN (agentd)

# knowledge/wiki/claude_code/assets.py
def resolve_wikitoolkit_bin(root: Path) -> str:        # line 88  (.venv/bin → which → bare; NO Windows branch)
def mcp_json_entry(root: Path) -> dict:                # line 114 ({"command": abs, "args": ["mcp"], "env": {}})
def resolve_parrot_bin(root: Path) -> str:             # line 123

# knowledge/wiki/claude_code/installer.py
def _install_mcp_json(root: Path) -> str:              # line 693; entry = assets.mcp_json_entry(root) line 719
#   lines 726-731: `if servers.get("wikitoolkit") == entry:` else REPLACE — reverts portable entries
#   marker discipline: _upsert_marker_block line 50, _remove_marker_block line 71

# knowledge/wiki/claude_code/bookstore.py
#   "command": sys.executable,                          # line 36 (inside mcp_json_entry, line 33)
#   _MANAGED_ARGS = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]  # line 30

# knowledge/wiki/codex/assets.py
def resolve_binary(root: Path, name: str) -> str:      # line 54 (same order, no Windows branch)
# knowledge/wiki/codex/bookstore.py: f"command = {json.dumps(sys.executable)}"  # line 43

# knowledge/wiki/google/assets.py
def resolve_binary(root: Path, name: str) -> str:      # line 66
def bookstore_mcp_entry(root: Path) -> dict[str, Any]: # line 107; "command": sys.executable line 121
#   default_mcp_config_path() = ~/.gemini/config/mcp_config.json (USER-GLOBAL)  # line 61

# knowledge/wiki/store.py — the wiki SQLite plane
class SQLiteWikiStore(BaseWikiStore):                  # line 948
SCHEMA_VERSION = "3"                                   # line 51
async def _apply_pragmas(self, conn, *, writable):     # line 1074 (busy_timeout line 1092)
async def _open(self, *, writable: bool):              # line 1108 (sole RW connect, line 1122)
async def _ensure_schema(...):                         # line 1133 (schema_version INSERT OR IGNORE line 1158)
async def _maybe_migrate(...):                         # line 1167 (shared by _read line 1190 / _write line 1240)
def _connect_immutable / _connect_readonly:            # lines 1301 / 1321 (RO opens)
def _migration_needed:                                 # line 1413 (reads meta.schema_version line 1437)
def _migrate:                                          # line 1444 (restamps version lines 1493-1495)
# NO `PRAGMA user_version` anywhere in knowledge/wiki/; versioning = meta key/value rows only.
# Today a version mismatch is ALWAYS migrated silently; nothing is ever refused.

# parrot_home() copies to consolidate
def parrot_home() -> Path:                             # knowledge/wiki/project.py:1223 (env read line 1234)
def _parrot_home() -> Path:                            # knowledge/bookstore/config.py:66 (kept local on purpose — note its docstring)
def cli_state_dir() -> Path:                           # cli/modes.py:68 (inline PARROT_HOME read line 70)

# flows/dev_loop/worktree_environment.py — launcher extraction SOURCE (port, don't import)
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:   # lines 53-71
def shared_environments(cwd: Path) -> tuple[Path, ...]:        # lines 74-92
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parrot.launcher.main_*` | `parrot.cli:cli`, `wiki.entry:main`, `bookstore.cli:main` | lazy import + call | `pyproject.toml:199-207` |
| `parrot.self_.components` | `ToolkitTemplate.requires_pip` (new) | template lookup | `mcp/toolkit_seed.py:27` |
| `cli/toolkits.py` hint | `dist_available` row flag | existing condition | `cli/toolkits.py:134` |
| `--portable` emitters | `_install_mcp_json` reconcile | keyword thread | `claude_code/installer.py:693,726-731` |
| `parrot.sdd.installer` | `_upsert_marker_block` pattern | same discipline (own copy) | `claude_code/installer.py:50` |
| `_check_runtime_gate` | `_open` / `_connect_readonly` | call before use | `store.py:1108,1321` |
| `_backup_store` | `_maybe_migrate` → `_migrate` | wrap | `store.py:1167,1444` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/launcher.py`, any launcher module, `PARROT_VENV`/`PARROT_PROJECT`/`PARROT_LAUNCHER_RESOLVED` env vars~~ — all new in M1.
- ~~`parrot self`, `parrot sdd`, `parrot env`, `parrot doctor` commands~~ — not in `_lazy_commands`; and **`parrot status` is TAKEN** (agentd daemon status) — never reuse it.
- ~~Windows venv handling (`Scripts\`, `.exe`) in any assets/installer/resolver~~ — none exists anywhere.
- ~~`requires_pip` / `post_install` / `requires_env` template headers~~ — parser knows exactly 3 keys today.
- ~~`PRAGMA user_version` or any store open-time version refusal~~ — versioning is `meta.schema_version` only, and mismatches are silently migrated today.
- ~~macOS or linux-aarch64 core wheels~~ — only `parrot-codec` builds them (release.yml:408-468).
- ~~`packages/ai-parrot-sdd/`, `parrot_sdd`, an `sdd` console script~~ — FEAT-583 was never implemented AND is rejected; never create these.
- ~~a root-level `install.sh`/`install.ps1` or uv-download code in the installers~~ — FEAT-586 scripts live in `scripts/install/` and use python -m venv + pip; uv appears only in `Makefile install-uv` and docs.
- ~~a shared host-adapter path for the wikitoolkit MCP entry~~ — `mcp/hosts.py` adapters reconcile toolkit entries only; each wiki installer owns its wikitoolkit block.
- ~~`parrot.sdd` package or `scripts/sdd/check_asset_sync.py`~~ — new in M6.
- ~~`parrot/sdd/config.py`, `sdd/config.json`, `sdd/.sdd-installed.json`, `sdd/CONVENTIONS.md`,
  `parrot sdd run`, `parrot self doctor --sdd|--runtime-only`, `read_declared_base_branch`~~
  — all new in rev 0.2 (C4/C5/C6/C8/C10/Q1/C14/C15). `sdd_meta.resolve_flow` DOES exist
  (`knowledge/wiki/ledger/sdd_meta.py:263`) and is parameterized, not created.

### Edit Sites (Blueprint Anchors)

Verified against: `56ff8cd58`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | `[project.scripts]` | `pyproject.toml:199` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `"parrot.flows" = ["_rules_data/*.md"]` | `pyproject.toml:969` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `cli._lazy_commands = {` | `cli/__init__.py:109` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | (ambiguous one-liner; context) `requires_llm: bool = False` ␤ `summary: str = ""` ␤ `requires_dist: tuple[str, ...] = ()` | `toolkit_seed.py:32-34` | field line count 2 (local var at :81) — use 3-line context |
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | `        elif meta_content.startswith("requires_dist:"):` | `toolkit_seed.py:96` | 1 |
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `def dist_available(requires_dist: Sequence[str]) -> bool:` | `toolkit_install.py:60` | 1 |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `        if row.requires_dist and not row.dist_available:` | `cli/toolkits.py:134` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `def resolve_wikitoolkit_bin(root: Path) -> str:` | `claude_code/assets.py:88` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `def mcp_json_entry(root: Path) -> dict:` | `claude_code/assets.py:114` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `    if servers.get("wikitoolkit") == entry:` | `claude_code/installer.py:726` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/bookstore.py` | MODIFY | `        "command": sys.executable,` | `claude_code/bookstore.py:36` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | `def resolve_binary(root: Path, name: str) -> str:` | `codex/assets.py:54` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py` | MODIFY | `            f"command = {json.dumps(sys.executable)}",` | `codex/bookstore.py:43` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | `def resolve_binary(root: Path, name: str) -> str:` | `google/assets.py:66` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | `def bookstore_mcp_entry(root: Path) -> dict[str, Any]:` | `google/assets.py:107` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `async def _open(self, *, writable: bool):` *(signature line; see store refs above)* | `store.py:1108` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `def _migrate` *(see store refs; restamp at :1493-1495)* | `store.py:1444` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `def parrot_home() -> Path:` | `project.py:1223` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/config.py` | MODIFY | `def _parrot_home() -> Path:` | `bookstore/config.py:66` | 1 |
| `packages/ai-parrot/src/parrot/cli/modes.py` | MODIFY | `def cli_state_dir() -> Path:` | `cli/modes.py:68` | 1 |
| `packages/ai-parrot/MANIFEST.in` | MODIFY | *(Cython-sources-only today; grows the SDD asset tree — codex S8)* | `MANIFEST.in` | — |
| `scripts/install/install-parrot.sh` | MODIFY | `    --with-wiki)` | `install-parrot.sh:74` | 1 |
| `scripts/install/install-parrot.ps1` | MODIFY | `  [switch]$WithWiki,` | `install-parrot.ps1:42` | 1 |
| `.github/workflows/release.yml` | MODIFY | `        os: [ubuntu-latest]` | `release.yml:18` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `skip = "pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32"` | `pyproject.toml:~1045` | 1 |
| `packages/ai-parrot/src/parrot/launcher.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/self_/{__init__,cli,components,doctor}.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/{__init__,cli,installer}.py` + `scripts/` + `_assets/` | CREATE | — | — | — |
| `scripts/sdd/check_asset_sync.py` | CREATE | — | — | — |
| `scripts/sdd/brief_meta.py` | MODIFY | `from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan` *(becomes alias shim — rev 0.4 C17)* | `brief_meta.py:19` | 1 |
| `scripts/sdd/ensure_worktree.py` | MODIFY | `from scripts.sdd.brief_meta import brief_worktree_plan` *(second import rewrite — rev 0.4 C17)* | `ensure_worktree.py:20` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | CREATE | — *(`git mv` + argparse `main` — rev 0.4 C17)* | — | — |
| `.agent/workflows/sdd-brief.md` | CREATE | — *(Google twin of `.claude/commands/sdd-brief.md` — rev 0.4 C17)* | — | — |

Anchors go stale between spec time and task time — `/sdd-task` MUST re-run the
`grep -c` for every row it uses.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Launcher is stdlib-only, forever** — enforce with a unit test; port (never import)
  `worktree_environment.py` logic. The `wikitoolkit claude-hook` fast path
  (`wiki/entry.py` imports only `sys`) must stay behind a single `is_managed()` check.
- **stderr-only diagnostics** in anything on the MCP launch path
  (`mcp/local_cli.py::_configure_stderr_logging` precedent, local_cli.py:99).
- **Marker-block/merge discipline** for every file the installers touch
  (`_upsert_marker_block`, claude_code/installer.py:50): never clobber foreign content,
  warn-and-skip on collisions.
- **Lenient template parser stays lenient** — new header keys follow the existing
  `elif meta_content.startswith(...)` shape (toolkit_seed.py:96); never make unknown
  keys fatal.
- **`~/.parrot` is a live data directory** (wikis.json, library/, skills/, brains/,
  parrot.db, services/, cli/) — the bootstrap and `self uninstall` may only touch
  `bin/` and `venv/` (plus an explicit `--purge` out of scope for v1).
- **Explicit over implicit**: dependencies enter a project venv only via
  `self add --here`; the managed venv is never implied into a project.
- Follow `.claude/rules/codebase-conventions.md` throughout (aiohttp-only, no
  langchain, logging via `self.logger`, 120-col, Google docstrings, strict hints).

### Known Risks / Gotchas
- **Wheel availability is the gating risk (S1)**: navigator-api[uvloop] (uvloop has no
  Windows wheels — the extra must be marker-guarded or the install documented
  POSIX-first), navigator-auth (Rust rs_pep), asyncdb, python-datamodel, ormsgpack,
  brotli==1.2.0, numexpr==2.10.2, semantic-text-splitter, faiss-cpu, pyarrow, plus the
  two in-repo Cython extensions (setup.py: parrot.utils.types C++, parrot.utils.parsers.toml C).
  If S1 fails, M8 ships first and M2 waits.
- **Windows stdio re-exec (S2)**: stray stdout bytes or orphaned children break stdio
  MCP. Fallback: Option D (Rust launcher) for the launcher only — do not redesign B′.
- **`_install_mcp_json` force-replace** (installer.py:726-731) will silently revert
  portable entries unless the reconcile learns both managed forms — covered by
  `test_reconcile_respects_portable`.
- **Version-skew auto-migration**: migration is already silent today; the new backup +
  gate makes it safe, but a *newer* store opened by an older runtime pre-FEAT-633 has no
  gate — document that the gate protects only runtimes ≥ this release.
- **Byte-equality sync vs path rewrite** (M6): monorepo markdown must ALSO use
  `parrot sdd run <name>` or the sync check can never pass — the
  migration commit flips docs and wrappers together.
- **Q1 residual — inline `python -c` blocks** *[rev 0.2]*: six shipped one-liners that
  import `sdd_meta` are covered by the `sdd_meta` CLI (TASK-4299) and rewritten to
  `parrot sdd run sdd_meta …` (TASK-4089). Other inline blocks in `sdd-spec.md` (stdlib
  JSON/index edits, one `jsonschema` import, one `reserve_ids.existing_feature_id`) still
  needed a `python` on PATH in a foreign repo. **Resolved 2026-10-15 by TASK-4334**
  (`scripts/sdd/spec_tools.py`, promoted from ledger `issue:cac5c029bd88`, now closed): the
  seven blocks call `python -m scripts.sdd.spec_tools <sub> …` on one line, TASK-4088 moves the
  helper and TASK-4089 rule 5a rewrites the invocations like any other helper, so C3's
  wheel-only test covers them through their `spec_tools` scenarios (TASK-4091).
- **C6/C11 change ai-parrot's own command files** *[rev 0.2]*: byte-equality means the
  placeholders and the "base branch in `sdd/config.json`" wording land in `.claude/` too;
  ai-parrot's `sdd/config.json` must be committed in the same change or the monorepo's
  own flow loses its branch policy.
- **Gemini config is user-global** (`~/.gemini/config/mcp_config.json`): `--portable` is
  what makes it multi-repo-safe; `self doctor` flags baked-path collisions there.
- **cp314 in `build` vs `requires-python <3.14`** (pyproject): M8 must reconcile
  (either relax the ceiling or drop cp314 from the build string) — do not ship wheels
  the package refuses to install on.
- **Hook latency budget (S4)**: managed→project re-exec budget is tens of ms;
  non-managed path must be noise.
- **Google `PurePosixPath` managed-entry detection** breaks on Windows paths — fix it
  with the Windows branch, not after (codex S4).
- **File locking**: the repo's `fcntl` import has a non-POSIX fallback that degrades to
  a no-op (project.py:38-41) — M7's migration lock must NOT reuse that pattern.
- **`post_install` execution surface**: argv comes exclusively from templates inside
  the installed wheel; if template loading ever grows a repo-local source, this
  constraint must be revisited first (codex S6).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `uv` (binary, not a Python dep) | pinned, checksum-verified | bootstrap: Python download, venv, installs |
| `cibuildwheel` | existing in CI | wheel matrix growth (macOS arm64, linux aarch64) |
| — | — | **no new Python runtime dependency in core** (launcher is stdlib-only) |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec (rounds of 2026-10-05).
> Echoed here for the audit trail; none remain open.

- [x] Flow type / base — *Resolved in brainstorm*: feature → `dev`.
- [x] v1 scope — *Resolved in brainstorm*: full stack (bootstrap+launcher+self, SDD asset install, toolkit metadata, wheel matrix).
- [x] Launcher scope — *Resolved in brainstorm*: all three console scripts; re-exec only from the managed venv.
- [x] Committable host config — *Resolved in brainstorm*: default stays baked absolute paths; `--portable` opt-in.
- [x] Bootstrap vehicle — *Resolved in brainstorm*: extend FEAT-586's `scripts/install/install-parrot.{sh,ps1}`; no new root scripts.
- [x] SDD component — *Resolved in brainstorm*: markdown asset install via `parrot sdd install`; FEAT-583 satellite/`sdd`-binary design REJECTED; its spec stamped superseded.
- [x] Host parity — *Resolved in brainstorm*: Claude + Codex + Google/Gemini, full (Windows, `--portable`, bookstore pins).
- [x] Version-skew policy — *Resolved in brainstorm*: auto-migrate with backup + lock (supersedes "never migrate silently").
- [x] Skew concurrency guard — *Resolved in brainstorm*: store-side min-runtime gate; older runtime fails fast naming both versions and the fix.
- [x] Fallback visibility — *Resolved in brainstorm*: warn once per session on stderr.
- [x] Worktree fallback — *Resolved in brainstorm*: worktree `.venv` first, then main checkout.
- [x] Managed Python — *Resolved in brainstorm*: pin 3.12.
- [x] Flag naming / Windows PATH — *Resolved in brainstorm*: `--global`/`-Global`; auto-edit user PATH (registry), reopen-terminal notice.
- [x] `scripts/sdd` helpers — *Resolved in brainstorm*: move invocable helpers to `parrot.sdd.scripts`; thin wrappers remain.
- [x] SDD asset source of truth — *Resolved in brainstorm*: `.claude/` authoritative + CI byte-equality sync into `parrot/sdd/_assets/`.
- [x] Distribution — *Resolved in brainstorm*: raw GitHub URL + published checksum.

Rev 0.2 amendment decisions (Jesus Lara, 2026-10-14; full text in
`sdd/proposals/parrot-installer-amendments.proposal.md` §5):
- [x] C4 install receipt — approved; the non-goal rejected FEAT-583's packaging manifest, not a receipt.
- [x] C6 repo config — approved, reduced: one `sdd/config.json`, no `CONFIG.md`, `test_command` added, `sync_down` dropped.
- [x] C10 conventions seed — approved; `codebase-conventions.md` stays an ai-parrot repo file.
- [x] C12 monorepo-only helpers — approved; `review_checkpoint` is the only one a shipped file references. *[rev 0.5 C18: superseded — four more found, moved by TASK-4508]*
- [x] Q1 helper invocation — `parrot sdd run <name>`; `parrot-python` shim rejected.
- [x] C7 test-selection policy — option C for v1 (`test_command`); option A revisited in v1.1 with evidence.
- [x] *[rev 0.5]* Readiness decisions D1–D18 (2026-10-19):
  - D1 → C20
  - D2 → C21
  - D3 and D18 → C22
  - D4 and D17 → C19
  - D5 → C23
  - D6–D16 → C24

  Jesus Lara answered D1, D2, D3, D4 and D8. The others adopt the review's recommendations
  and are confirmed in the PR review.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-633/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Launcher import boundary genuinely stdlib-only; decide re-exec before importing targets; fast path survives re-exec (architecture) | CONFIRM | `parrot`/`bookstore` import heavy modules at load; resolution must precede import | §3 M1 |
| S2 | Extract PARROT_HOME into dependency-free module; callers delegate (architecture) | CONFIRM | matches M1/M3 consolidation design exactly | §3 M1/M3 |
| S3 | Specify venv resolution as subprocess-tested state machine incl. symlinks, Windows names, `--project`, no-candidate (testing) | CONFIRM | unit tests alone can't prove the exec boundary | §4 Integration |
| S4 | Centralize only low-level binary resolution; Google `PurePosixPath` breaks on Windows (architecture) | CONFIRM | matches M5 via `launcher.script_path`; PurePosixPath gotcha was unknown | §3 M5, §7 |
| S5 | Portable = complete per-host ownership/cwd contract (`cwd`, `--config`, bookstore), test both transitions (api) | CONFIRM | bare command alone leaves absolute state behind | §3 M5, §4, §5 |
| S6 | PEP 508 field separate from import probes; post_install as versioned handler registry (api) | CONFIRM (scoped) | separation already designed; handler registry NOT adopted — templates load from `importlib.resources` only (toolkit_seed.py:49), so argv never comes from user-writable input; constraint recorded instead | §3 M4, §7 |
| S7 | Migration safety = storage-layer protocol: cross-process Windows-safe lock; per-instance asyncio lock and POSIX-only fcntl insufficient (risk) | CONFIRM | real gap found in the brainstorm's "single-writer lock" | §3 M7, §4, §7 |
| S8 | SDD packaging as verified build artifact: MANIFEST.in, wheel-content CI check (architecture) | CONFIRM | MANIFEST.in is Cython-only today; byte-equality alone doesn't prove wheel contents | §3 M6, §6 Edit Sites |
| S9 | Audit installed commands for shell/jq/non-Windows assumptions; installer reports unavailable tooling (risk) | CONFIRM | folded into spike S5 scope + M6 install-time report | §3 M0/M6 |
| S10 | Global bootstrap branches BEFORE the system-Python guard; interrupted-run safety (risk) | CONFIRM | both scripts hard-require Python today — a clean machine never reaches `--global` otherwise | §3 M2, §5 |
| S11 | Gate wheel matrix on clean-install + console-script smoke tests; resolve cp314 vs `<3.14` (testing) | CONFIRM | build success ≠ installable; contradiction already flagged in §7 | §3 M8, §5 |

Summary: **11** confirmed (1 scoped) · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-05 | Jesus Lara + Claude | Initial draft from accepted brainstorm (FEAT-633) |
| 0.2 | 2026-10-14 | Jesus Lara + Claude | Amendments C2–C6, C8–C15, Q1, C7 folded in (proposal `parrot-installer-amendments` rev 0.3): `parrot sdd run`, install receipt, `--dry-run`, `sdd/config.json` + single branch policy (TASK-4298/4299), conventions seed, publication safety, canonical docs, bootstrap gate + `doctor --runtime-only`, SDD readiness checks; FEAT-583 stamp marked done |
| 0.3 | 2026-10-17 | Jesus Lara + Claude | Amendment C16 folded in (proposal rev 0.4): `worktree_environment` enters scope — relocated to `parrot/sdd/scripts/` with a re-export shim, hook invoked as `parrot sdd run worktree_environment --hook` behind a launcher fast path, `test_no_repo_script_refs` widened to any monorepo source path (amends TASK-4085, 4072, 4089, 4090, 4091) |
| 0.4 | 2026-10-18 | Jesus Lara + Claude | Amendment C17 folded in (proposal rev 0.5): `/sdd-brief` (FEAT-698, merged after rev 0.3) ships through the installer — `brief_meta` moves with TASK-4085 and gets a CLI (`plan`, `write-index`) in TASK-4299, TASK-4089 creates the missing Google twin `.agent/workflows/sdd-brief.md` and rewrites the three `sdd-brief` files, counts updated to 15 commands per host / 14 templates / 81 manifest entries (TASK-4070, 4090), C3 scenarios for `ensure_worktree --brief-key` and `brief_meta write-index` (TASK-4091) |
| 0.5 | 2026-10-20 | Arturo Martinez + Claude, decisions by Jesus Lara | Amendments C18–C24 folded in (proposal rev 0.6) from the 2026-10-19 readiness review: four more helpers to move (TASK-4508) and package-relative loaders; C16 move mechanics and the TASK-4509 fast path; `ai-parrot-tools` in the managed runtime for `wikitoolkit mcp` (core-only fallback is a follow-up); test steps in foreign repos via `test_command`, own §4 Validation Contract, validation phase deferred to v1.1; monorepo-text rules A–E, `/sdd-insight` not shipped (78 assets); `.gitattributes` + ledger hooks in foreign repos; Windows hook quoting, `--remote` × `--portable`, store downgrade refusal (`issue:f249c19e8a4d`), `SourceRegistry` bypass recorded (`issue:1555e747bcb9`); counts and §6 anchor note |
