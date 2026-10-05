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
4. **The SDD flow is not installable.** 14 `/sdd-*` commands, 9 `sdd-*` agents, hooks,
   rules, 13 templates and ~29 `scripts/sdd/` helpers live only in this repo.
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
  helpers migrate to `parrot.sdd.scripts` (`python -m parrot.sdd.scripts.<name>`);
  `.claude/` stays authoritative with a CI byte-equality sync check.
- Store safety under version skew: auto-migration (already existing in
  `SQLiteWikiStore`) hardened with pre-migration backup, single-writer locking and a
  **min-runtime gate** so an older runtime fails fast instead of corrupting a newer store.
- Core wheel matrix: macOS arm64 and linux aarch64 added; redundant linux legs removed.
- Validation-first: spikes S1–S6 are the first tasks of this feature; S1 (compiler-free
  install matrix) gates the bootstrap deliverable ordering.

### Non-Goals (explicitly out of scope)

- No `ai-parrot-sdd` satellite package, no `sdd` console binary, no manifest/symlink
  machinery — FEAT-583's design is rejected (owner, 2026-10-05).
- No per-component venv isolation (`uvx`-per-server) — one managed venv only.
- No code signing, notarization, PyApp or Rust launcher in v1 (brainstorm Options C/D;
  D remains the fallback if spike S2 fails on Windows).
- No replacement of FEAT-586's project-venv install mode — it is extended, not removed.
- No portable-by-default host config — baked absolute paths remain the default;
  `--portable` is opt-in (owner decision; rejects the brainstorm proposal's auto-detect).
- No implicit modification of a project's dependencies — installing into a project venv
  is always the explicit `--here` verb.
- No new root-level `install.sh`/`install.ps1` — the scripts stay in `scripts/install/`.

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
   `python -m parrot.sdd.scripts.<name>` everywhere (monorepo `scripts/sdd/*.py` become
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
| `flows/dev_loop/worktree_environment.py` | source template | `repository_paths`/`shared_environments` logic ported (not imported) into the launcher |
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
- `parrot sdd install|uninstall|status [--host claude|codex|google]` (click group, lazy).
- `python -m parrot.sdd.scripts.<name>` for the 18 flow helpers (see M6).
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
- **Depends on**: M1 (home paths, `resolve_venv` for `env`); M4 (component metadata).
- **Interface Skeleton**:
  ```python
  # parrot/self_/cli.py  (new; registered in cli/__init__.py:109 _lazy_commands as "self")
  @click.group(name="self")
  def self_group() -> None:
      """Manage the parrot-managed runtime (~/.parrot)."""
  # subcommands: add(component, here: bool), update(version: str | None),
  #              doctor(), env(), uninstall(yes: bool)

  # parrot/self_/components.py  (new)
  def install_component(name: str, *, venv: Path, here: bool = False) -> list[str]:
      """Resolve the toolkit template's requires_pip, run bundled
      `uv pip install --python <venv>`, then post_install argv. Returns action log.
      ToolkitTemplate verified: mcp/toolkit_seed.py:27-34."""

  # parrot/self_/doctor.py  (new)
  def run_doctor(root: Path) -> list[DoctorCheck]:
      """Checks: pinned uv present/version; managed venv Python == 3.12; PATH contains
      ~/.parrot/bin; host configs whose command paths don't exist (3 hosts incl. the
      Gemini user-global file); installed toolkits with unmet requires_dist/requires_env."""
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
- **Responsibility**: package the 14 commands, 9 agents, SDD hooks, 2 rules and 13
  templates as package data; `parrot sdd install [--host …]` deploys them with the
  marker-block discipline (template: `claude_code/installer.py` `_upsert_marker_block`,
  installer.py:50). The 18 doc-referenced helpers (`sdd_meta`, `reserve_ids`,
  `ensure_worktree`, `close_task`, `heal_orphans`, `check_task_state`, `select_tests`,
  `insight`, `doc_taxonomy`, `worktree_status`, `finalize_task`, `check_task_graph`,
  `backfill_taxonomy`, `migrate_index`, `id_ledger`, `check_id_collisions`,
  `install_hooks`, + `__init__`) move to `parrot/sdd/scripts/`; ALL markdown (installed
  AND monorepo) references the single form `python -m parrot.sdd.scripts.<name>` so the
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
- **Interface Skeleton**:
  ```python
  # parrot/sdd/installer.py  (new)
  def install_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",)) -> list[str]:
      """Deploy packaged SDD assets into <root> (marker-block/merge; never overwrites
      foreign content). Returns action log."""
  def uninstall_sdd_integration(root: Path) -> list[str]: ...
  def sdd_status(root: Path) -> dict: ...
  # parrot/sdd/cli.py  (new; lazy "sdd" in cli/__init__.py:109)
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
  - M0, M4, M8 have no incoming edges — expected to run concurrently with everything.
- **Shared files** (tasks touching them get serialized):
  - `packages/ai-parrot/pyproject.toml` — M1 (`[project.scripts]`, :199) + M6
    (package-data, :969) + M8 (`[tool.cibuildwheel]`, :1043)
  - `cli/__init__.py` — M3 (`self`) + M6 (`sdd`), both in `_lazy_commands` (:109)
- **Exclusive resources**: `.github/workflows/release.yml` (M8 only — but release
  verification requires a tag, so M8's validation is PR-CI only); no extension rebuild
  or lockfile steps.
- **Cross-feature dependencies**: none. FEAT-583 is superseded (stamp its spec
  `Status: superseded` in this feature's first SDD-state commit); FEAT-586 and FEAT-495
  are completed history.

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
| `test_sdd_scripts_module_entrypoints` | M6 | `python -m parrot.sdd.scripts.<each>` resolves |
| `test_asset_sync_check` | M6 | divergence between `.claude/` and `_assets/` fails |
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
| `test_sdd_flow_in_foreign_repo` | `parrot sdd install` into a tmp non-Python repo; installed command markdown references only `parrot.sdd.scripts` modules that resolve |
| `test_store_migrate_then_old_open` | migrate a fixture store, reopen with a mocked older version ⇒ fail-fast gate (spike S6 codified) |

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
      referenced by installed markdown resolves as `python -m parrot.sdd.scripts.<name>`;
      `scripts/sdd/` wrappers keep the monorepo's existing invocations working;
      `check_asset_sync.py` gates CI on `.claude/` ↔ `_assets/` divergence.
- [ ] Wiki store migration takes a sidecar backup first, restores it on failure, runs
      locked, stamps `min_runtime_version`; an older runtime opening a newer store fails
      fast with both versions and the fix in the message (read-only paths included).
- [ ] `release.yml` builds core wheels for linux x86_64 + aarch64, windows AMD64 and
      macOS arm64 (cp311–cp313 minimum); the redundant quadruple ubuntu legs are gone.
- [ ] `sdd/specs/portable-sdd-flow.spec.md` is stamped `Status: superseded` referencing
      FEAT-633.
- [ ] No new runtime dependency in ai-parrot core; `ruff check` passes; all tests in §4
      pass; docs updated (`INSTALL.md`, `docs/INSTALL.md`, `.mcp.json.example` note).

---

## 6. Codebase Contract

> Verified on branch `dev` @ `56ff8cd58` (2026-10-05) by direct source reads.
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
  `python -m parrot.sdd.scripts.<name>` or the sync check can never pass — the
  migration commit flips docs and wrappers together.
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
