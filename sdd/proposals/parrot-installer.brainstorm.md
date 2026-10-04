---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, ci, docs]
tags: [installer, bootstrap, uv, launcher, mcp, windows, sdd-packaging]
---

# Brainstorm: Parrot Bootstrap Installer — cross-platform install of the SDD flow, wikitoolkit and MCP toolkits

**Date**: 2026-10-05
**Author**: Jesus Lara (proposal) + Claude (codebase re-verification on `dev`)
**Status**: exploration
**Recommended Option**: B′ (Option B of the proposal, revised against the verified codebase and the owner's Round 1/2 decisions)
**Related**:
- `sdd/proposals/parrot-installer.proposal.md` — the source proposal this brainstorm re-grounds (verified against `main @ fb9dd935`; this document re-verifies on `dev`, 2026-10-05).
- `sdd/specs/portable-sdd-flow.spec.md` (**FEAT-583**, draft, no tasks) — **rejected/superseded** (owner decision, revised 2026-10-05): no `ai-parrot-sdd` satellite, no `sdd` binary. The SDD flow is markdown files; this feature installs them as packaged assets via `parrot sdd install`. The draft spec (not the owner's) is stamped superseded.
- `sdd/specs/parrot-install-guide.spec.md` (**FEAT-586**, completed) — shipped `scripts/install/install-parrot.{sh,ps1}`; **extended, not replaced** (owner decision, Round 2).
- `sdd/specs/portable-wikitoolkit-config-paths.spec.md` (**FEAT-495**, completed) — produced today's `sh -c` resolver in `.mcp.json.example`; the launcher retires that mechanism.
- `sdd/proposals/parrot-install-guide.brainstorm.md` — public docs/onboarding guide (different scope: documentation, not tooling).
- FEAT-570 (`parrot toolkits`), FEAT-556 (host adapters / `--config` pinning), FEAT-595 (`wiki/entry.py` fast path).

---

## Problem Statement

Using the SDD flow, the wikitoolkit and the ai-parrot MCP toolkits inside Claude Code, Codex **or Gemini/Antigravity** today assumes a developer who already has Python, a project `.venv` and ai-parrot installed in it. Everything downstream of that assumption exists and works: `parrot claude|codex|google install`, `parrot toolkits install <name> --host …`, `.parrot/mcp-toolkits.yaml`, `parrot mcp-local`. What is missing is upstream and cross-cutting:

1. **No uv-based bootstrap / managed runtime.** `scripts/install/install-parrot.{sh,ps1}` (FEAT-586) exist but assume (or apt/brew/winget-install) a system Python and create a **project** venv with `python -m venv` + `pip`. There is no managed global runtime (`~/.parrot/venv`), no pinned `uv`, no path for "give my coding assistant the wikitoolkit in a repo that is not a Python project".
2. **No run-time venv resolution for the console scripts.** Host installers bake absolute paths at install time (`resolve_*_bin`: `<root>/.venv/bin/<name>` → `shutil.which` → bare name). Fragments of run-time resolution exist (`flows/dev_loop/worktree_environment.py::shared_environments`, `sdd_coder/lint.py::resolve_bin`, `parrot_tools/tool_optimizations/installation.py::resolve_python`) but none fronts the entry points.
3. **POSIX-only wiring, three times over.** `.venv/bin/` is hardcoded in `claude_code/assets.py`, `codex/assets.py` **and `google/assets.py`**; no `Scripts\`/`.exe` branch exists anywhere venv-related. The bookstore entries add a second machine-specific pin: `sys.executable -m parrot.knowledge.bookstore.cli mcp` with absolute `cwd` (claude_code/bookstore.py, codex/bookstore.py, google/assets.py). `.mcp.json.example` is a POSIX `sh -c` one-liner (FEAT-495). Google's config is **user-global** (`~/.gemini/config/mcp_config.json`), so its absolute per-project paths collide across repos on one machine.
4. **The SDD flow is not installable.** 14 `/sdd-*` commands, 9 `sdd-*` agents, hooks, rules, 13 templates, `sdd/WORKFLOW.md` and ~29 `scripts/sdd/` scripts live only in this repo. 11 prompt/rules files are packaged (9 in `flows/dev_loop/_subagent_data/`, 1 in `dev_flow/_subagent_data/`, `flows/_rules_data/codebase-conventions.md`) but they serve the in-process dev-loop, not an installer. The flow itself is markdown files — the fix is to package them as data and deploy them with an installer verb (`parrot sdd install`), with the marker-block/merge discipline the wiki installers already use. (FEAT-583's heavier answer — a satellite package with its own `sdd` binary — was rejected by the owner.)
5. **Toolkit exposure does not install anything.** Templates carry only `# parrot:summary|requires_llm|requires_dist`; `requires_dist` holds import names checked via `find_spec`. No pip requirement, no post-install (browser binaries), no env-var declaration for a doctor to check.
6. **No macOS wheels for core.** `release.yml` builds core wheels on linux x86_64 + windows AMD64 only (cibuildwheel `cp3{11,12,13,14}`, skip `pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32`). Only `parrot-codec` has a macOS arm64 job. The heavy compiled chain (navigator-api[uvloop], navigator-auth (Rust rs_pep), asyncdb, python-datamodel, ormsgpack, brotli 1.2.0, numexpr ==2.10.2, faiss-cpu, pyarrow, our two Cython extensions) makes compiler-free install on macOS/Windows unproven — the gating spike.

Who is affected: anyone adopting the SDD flow or the wikitoolkit outside the monorepo; Windows and macOS users; multi-repo users of the Gemini global config. Why now: FEAT-485/556/570/586/595 shipped the downstream layers; FEAT-583 is drafted; the remaining gap is bounded.

## Constraints & Requirements

Owner-confirmed (Rounds 0–2, 2026-10-05):

- **v1 scope is the full stack**: bootstrap + launcher + `parrot self`, SDD asset install (`parrot sdd install`), toolkit install metadata, and the CI wheel matrix.
- **Extend `scripts/install/install-parrot.{sh,ps1}`** with the uv/managed-global mode — do not create new root-level `install.sh`/`install.ps1`. FEAT-586's CI wiring (`ci.yml` bash -n / pwsh parse / `--dry-run`) and tests (`tests/docs/test_install_*.py`) must keep passing and grow with the new mode.
- **All three console scripts** (`parrot`, `wikitoolkit`, `bookstore`) enter through the launcher; re-exec happens **only** when running from the managed venv.
- **Host config default stays baked absolute paths; `--portable` is opt-in** (emits the bare launcher command). Deviation from the proposal's auto-detection.
- **Three-host parity in v1**: Claude Code, Codex and Google/Gemini all get Windows paths, launcher-aware `--portable` emission, and the bookstore `sys.executable` pin replaced.
- **Version skew: auto-migrate.** On store schema mismatch the runtime migrates the project store automatically (supersedes the proposal's "never migrate silently"). Safety rails required: pre-migration backup copy and single-writer locking; concurrent sessions on older runtimes are the known risk (see Edge Cases + Open Questions).
- **SDD component is an asset installer, nothing more** (owner decision, revised 2026-10-05, overriding the earlier "absorb FEAT-583" answer): the flow is markdown files — package the `/sdd-*` commands, `sdd-*` agents, hooks, rules and `sdd/templates/` as package data and deploy them with `parrot sdd install [--host …]`. **No `ai-parrot-sdd` satellite, no `sdd` binary, no manifest/symlink machinery.** FEAT-583 (`portable-sdd-flow`, draft, not the owner's spec) is rejected and stamped superseded.
- **Use the venv that is already there.** A project `.venv` with ai-parrot keeps working untouched; the managed venv is fallback only.
- **One managed venv**, not per-component isolation (`uvx`-per-server out of scope).
- **Venv chosen before the MCP handshake**; stdout is the JSON-RPC channel — diagnostics to stderr only (`mcp/local_cli.py::_configure_stderr_logging` precedent).
- **Hook latency**: `wikitoolkit claude-hook` fast path (entry.py imports only `sys`) must stay stdlib-only through the launcher.
- **Never modify a project's dependencies implicitly**; installing into a project venv is an explicit verb (`parrot self add --here`).
- **No new prerequisites**: `uv` (pinned static binary) is the only non-wheel download.
- **No signing work in v1.**
- **Validation-first**: spikes (§Spike Gate) before `/sdd-spec`.

---

## Options Explored

(Structure carried from the proposal; facts corrected against `dev`.)

### Option A: Bootstrap-mode flag only; keep install-time path resolution

Extend `install-parrot.sh/ps1` with `--global` (uv + `~/.parrot/venv`), and give the four `resolve_*` helpers (claude, codex, google, + bookstore pins) a managed-venv candidate and a Windows branch. Host config keeps baked absolute paths.

✅ **Pros:**
- Smallest change; nothing new in the launch path.
- The Windows branch and managed-venv candidate are needed under every option anyway.

❌ **Cons:**
- Resolution frozen at install time: a `.venv` created later is ignored until re-install; the Gemini user-global config keeps colliding across repos.
- Worktrees keep needing the FEAT-495 `sh -c` fallback chain; `.mcp.json` stays uncommittable.
- `--portable` cannot exist without something stable on PATH to point at.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:** `claude_code/assets.py::resolve_wikitoolkit_bin/resolve_parrot_bin`, `codex/assets.py::resolve_binary`, `google/assets.py::resolve_binary`, `scripts/install/install-parrot.{sh,ps1}`.

---

### Option B′: Extended bootstrap + managed venv + run-time launcher + SDD asset installer — *recommended*

Four pieces.

**1. Bootstrap — extend FEAT-586's scripts.** `install-parrot.sh/ps1 --global` (naming TBD at spec time): download pinned `uv` into `~/.parrot/bin/`, `uv venv ~/.parrot/venv --python 3.12` (uv-managed CPython), `uv pip install --python ~/.parrot/venv ai-parrot[...]`, expose `parrot`/`wikitoolkit`/`bookstore` shims from `~/.parrot/bin`, add to PATH. The existing project-venv mode stays as-is. `~/.parrot` is already the established home — **`parrot_home()` and `$PARROT_HOME` already exist** (`knowledge/wiki/project.py:1223`, `knowledge/bookstore/config.py:67`, `cli/modes.py:69`) and `~/.parrot` already holds `services/`, `wikis.json`, `library/`, `parrot.db`, `artifacts/`, `skills/`, `brains/`, `cli/` — the installer adds `bin/` and `venv/` to an existing convention, and must consolidate the three duplicate `parrot_home()` implementations rather than add a fourth.

**2. Launcher** (`parrot/launcher.py`, stdlib-only). Console scripts enter through it; it re-executes into another venv **only when `sys.prefix` is under `PARROT_HOME/venv`**. Any other invocation is a `sys.prefix` comparison and a direct call — existing setups stay byte-for-byte identical. From the managed venv the order is: `PARROT_VENV` → project venv (root from `--project`/`PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walk; `<root>/.venv`; linked worktree without one → main checkout's `.venv`) → `VIRTUAL_ENV` → stay managed. A candidate is valid only if it contains the requested console script. `os.execv` on POSIX; forwarded-stdio child process on Windows (spike 2). The worktree logic needs a **stdlib-only extraction** — `project.py` is disqualified at module level (it imports pydantic and, via `schema/models.py:9` → `parrot.bots.database.models`, the whole `parrot.bots` package; its "stdlib + pydantic" docstring is stale). Precedent to extract from: `flows/dev_loop/worktree_environment.py:54–90` (`repository_paths`, `shared_environments` — already parses `gitdir:`/`commondir` with stdlib and checks `pyvenv.cfg`).

**3. Lifecycle group `parrot self`** (`self add | update | doctor | env | uninstall`): name is free — `_lazy_commands` has 24 entries and no `self`/`sdd`/`env`/`doctor`; note `parrot status` **is taken** (agentd), so diagnostics live under `self`. `self add <component>` installs the component's pip requirement into the managed venv with the bundled uv and runs its post-install; `--here` targets the project venv explicitly. Toolkit templates gain `# parrot:requires_pip`, `# parrot:post_install`, `# parrot:requires_env` (parser at `toolkit_seed.py:84–98` skips unknown keys silently today, so old runtimes tolerate new headers). `parrot toolkits install` offers `self add` when `dist_available` is false.

**4. SDD component = markdown asset installer.** Package the repo's `.claude/commands/sdd-*.md`, `.claude/agents/sdd-*.md`, the SDD hooks/rules and `sdd/templates/` as package data (e.g. `parrot/sdd/_assets/`, following the `_subagent_data`/`_toolkit_templates` precedent), and add `parrot sdd install [--host claude|codex|google]` (lazy command) that deploys them with the marker-block/merge discipline the wiki installers already use, plus `uninstall`/`status` twins. Since the assets ship inside ai-parrot core, the managed venv has them with no extra install step. Open points: whether the `scripts/sdd/*.py` helpers the commands invoke (`ensure_worktree`, `reserve_ids`, `close_task.sh`, …) ship too and how commands locate them outside the monorepo (spike 5 enumerates every such assumption), and which copy is the source of truth in the monorepo (package data vs `.claude/` + build-time sync, the same pattern FEAT-553 uses for `codebase-conventions.md`).

**Host wiring** stays with the existing per-host installers (there is no shared adapter for the wikitoolkit entry — `mcp/hosts.py` adapters only reconcile *toolkit* entries). All three `assets.py` get the Windows `Scripts\`/`.exe` branch; `--portable` makes `mcp_json_entry`/`mcp_block`/`wikitoolkit_mcp_entry` emit the bare command, and replaces the bookstore `sys.executable -m …` pin with `bookstore mcp` through the launcher. Known catch to fix: `claude_code/installer.py::_install_mcp_json` (L724–729) force-replaces any differing `wikitoolkit` entry — it must respect a portable entry instead of reverting it to an absolute path.

✅ **Pros:**
- Owner's constraint holds by construction: project venv first, managed venv only as fallback, re-exec only from the managed venv.
- Late-binding: a `.venv` created tomorrow is picked up with no re-install; fixes the Gemini global-config cross-repo collision (bare command is repo-independent).
- Reuses what shipped: FEAT-586 scripts + their CI/tests, marker-block installers, `ToolkitTemplate` forward-compatible headers, `worktree_environment.py` parsing, the `_subagent_data`/`_toolkit_templates` package-data precedent.
- First real Windows path; portable config becomes *possible* without changing anyone's default.

❌ **Cons:**
- Re-exec hop in the launch path of globally-invoked commands; Windows stdio forwarding must be proven (spike 2).
- Auto-migration on version skew makes the managed runtime a *writer* of project stores — backup + locking become mandatory, and a concurrent older-runtime session can meet a migrated store (open question).
- Depends on compiler-free install of the navigator/Cython chain on macOS and Windows (spike 1; wheel-matrix lane is the hedge).
- SDD commands may assume monorepo paths (`scripts/sdd/`, `.venv`, `uv run`); markdown-only install does not fix those references by itself (spike 5 is the gate).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `uv` (binary) | Python download, venv, installs | pinned, fetched by the bootstrap into `~/.parrot/bin` |
| stdlib only | launcher | hard requirement (hook latency) |
| `cibuildwheel` | wheel matrix | already in `release.yml`; matrix must grow (macOS; aarch64) |

🔗 **Existing Code to Reuse:** see §Code Context (all entries re-verified on `dev`).

---

### Option C: PyApp single binary per platform

Unchanged from the proposal. Still rejected for v1: three entry points, private-env design still needs the Option B launcher inside, brings notarization/SmartScreen signing into scope, and does not remove the wheel problem. Remains a later distribution layer.

📊 **Effort:** Medium + recurring signing cost

### Option D: Custom Rust launcher (`parrot-up`) via cargo-dist

Unchanged from the proposal. Premature unless spike 2 fails on Windows; then it replaces **only** the launcher. Same signing burden as C.

📊 **Effort:** High

---

## Recommendation

**Option B′.** The core argument of the proposal survives verification: "use the venv that is already there" is a resolution rule, and a resolution rule must run at launch time — A freezes it, C/D would embed it anyway. What changed after verification and the owner's decisions: the bootstrap is an *extension of FEAT-586's scripts* (their CI and tests already exist); the launcher must be built on a stdlib extraction of `worktree_environment.py` logic, **not** `project.py` (heavier than documented); parity is three hosts plus the bookstore `sys.executable` pins; `PARROT_HOME` is an existing convention to consolidate, not invent; and the SDD component is deliberately minimal — packaged markdown assets plus `parrot sdd install`, rejecting FEAT-583's satellite-package/`sdd`-binary design. D stays as the Windows fallback for the launcher only; C as a later packaging layer; A is absorbed (its Windows fix is lane 0 of B′).

---

## Feature Description

### User-Facing Behavior

- **Install (clean machine):** run `scripts/install/install-parrot.sh --global` (POSIX) / `install-parrot.ps1 -Global` (Windows) — flag naming decided at spec time. Result: `~/.parrot/{bin,venv}`, pinned uv, `parrot`/`wikitoolkit`/`bookstore` on PATH. Existing flags (`--provider`, `--extras`, `--with-wiki`, …) keep working; the project-venv mode is untouched.
- **Wire a repo:** `parrot claude|codex|google install`, `parrot toolkits install scraping --host …` — the existing verbs, now working with no project venv. Default emission: baked absolute paths (today's behavior). `--portable` emits the bare launcher commands (committable, multi-OS, requires the global install on each machine).
- **Add a component:** `parrot self add scraping` installs the template's `requires_pip` into the managed venv and runs `post_install` (e.g. browser binaries). `--here` targets the project venv. The SDD flow needs no `self add`: its assets ship inside ai-parrot — `parrot sdd install [--host …]` deploys them into the current repo.
- **Inspect:** `parrot self env` (resolved venv + rule that picked it + versions); `parrot self doctor` (uv, Python, PATH, host configs pointing at missing binaries, `requires_env` gaps).
- **Update / remove:** `parrot self update [--version X]`, `parrot self uninstall`.
- **Project with its own ai-parrot `.venv`:** nothing changes, with or without the global install.
- **Store version skew:** the runtime migrates the project store automatically after taking a backup; `self env` shows runtime vs store schema versions.

### Internal Behavior

1. `parrot/launcher.py` (new, stdlib-only): `is_managed()`, `find_project_root()`, `resolve_venv(script) -> (path, rule)`, `script_path(venv, name)` (`bin/<name>` | `Scripts\<name>.exe`), `reexec(...)` (POSIX `os.execv`; Windows child with forwarded stdio/exit/termination), loop guard env var. Worktree→main-checkout logic extracted stdlib-only (from `worktree_environment.py` parsing, replacing what `.mcp.json.example` does in shell).
2. `[project.scripts]` route `parrot`, `wikitoolkit`, `bookstore` through `launcher.main(<target>)`; `wiki/entry.py`'s `claude-hook` fast path sits behind the `is_managed()` cheap check.
3. `parrot/self_/` (module name avoiding the keyword; CLI group `self`): `home.py` (consolidated `parrot_home()`, paths, pinned-uv record), `components.py` (`uv pip install --python <venv>`), `doctor.py`. Registered in `LazyGroup._lazy_commands`.
4. `ToolkitTemplate` + templates: `requires_pip`, `post_install`, `requires_env` headers; `toolkit_install.py` surfaces "run `parrot self add`" when `dist_available` is false.
5. Three `assets.py` (claude_code, codex, google) + three bookstore emitters: Windows branch; `--portable` flag threaded through the install CLIs; `_install_mcp_json` reconcile respects portable entries.
6. `parrot/sdd/` (new in core): packaged markdown assets + `install_sdd_integration(root, hosts)` / `uninstall` / `status` using the marker-block installers as template; `sdd` registered as a lazy `parrot` subcommand. Package-data entry added to `pyproject.toml`.
7. Store schema: version stamp + auto-migration path with pre-backup and single-writer lock (wiki plane; schema plane already has staleness metadata).
8. `release.yml`: core wheel matrix grows macOS (arm64 at minimum — the only runner family left) and linux aarch64; redundancy of the current 4-leg linux build cleaned up opportunistically.

### Edge Cases & Error Handling

- **Version skew (auto-migrate)**: backup `.parrot/<store>.db` → migrate → single-writer lock during migration; on failure restore backup and fail with both versions named. **Risk**: a concurrent session on an older runtime opening a migrated store — mitigation options in Open Questions.
- **Linked worktree with own `.venv`**: used as found; without one, main checkout's venv (matches `.mcp.json.example` semantics). `self env` makes it visible.
- **Gemini user-global config**: `--portable` is what makes one `~/.gemini/config/mcp_config.json` valid across repos; with baked paths (default) the current per-repo collision remains and `self doctor` flags it.
- **Broken project `.venv`** (no interpreter / no script): stderr warning, fall through to next rule.
- **Host starts server from unexpected cwd**: launcher honours `PARROT_PROJECT`; adapters set it where cwd is unreliable (FEAT-556 precedent).
- **No network on first run**: bootstrap fails before touching PATH; partial `~/.parrot/{bin,venv}` additions rolled back (never deleting pre-existing `~/.parrot` data — it is a live data directory, see Code Context).
- **User already has uv**: untouched; the pinned copy lives in `~/.parrot/bin`.
- **`_install_mcp_json` reconcile**: must not revert a `--portable` entry to an absolute path on re-install.

---

## Capabilities

### New Capabilities
- `parrot-bootstrap-global`: `--global` mode in `scripts/install/install-parrot.{sh,ps1}` — pinned uv, managed CPython, `~/.parrot/{bin,venv}`.
- `parrot-launcher`: stdlib venv resolver + re-exec fronting the three console scripts.
- `parrot-self`: `self add | update | doctor | env | uninstall` lifecycle group.
- `sdd-install`: packaged SDD markdown assets (commands, agents, hooks, rules, templates) + `parrot sdd install|uninstall|status [--host …]`.

### Modified Capabilities
- `mcp-toolkit-templates`: `requires_pip`, `post_install`, `requires_env` headers (forward-compatible with the lenient parser).
- `wiki-claude-code-installer`, `wiki-codex-installer`, `wiki-google-installer`: Windows script paths; `--portable` emission; bookstore pin replacement; reconcile respects portable entries.
- `wiki-store-versioning`: schema stamp + auto-migration with backup/lock.
- `release-pipeline`: core wheel matrix (macOS arm64, linux aarch64; dedupe linux legs).
- `parrot-install-scripts` (FEAT-586): extended with the global mode; CI checks and `tests/docs/test_install_*.py` grow accordingly.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/launcher.py` (new) | new | stdlib-only resolver + re-exec |
| `parrot/self_/` (new) | new | lifecycle CLI, component install, doctor |
| `parrot/sdd/` (new) + package data | new | packaged SDD markdown assets + marker-block installer |
| `scripts/install/install-parrot.sh` / `.ps1` | extends | `--global` mode (uv download, managed venv); FEAT-586 tests/CI updated |
| `packages/ai-parrot/pyproject.toml` | modifies | `[project.scripts]` → launcher targets; package-data for SDD assets |
| `cli/__init__.py` | extends | `self` and `sdd` lazy commands |
| `mcp/toolkit_seed.py`, `_toolkit_templates/*.yaml` | extends | new header keys |
| `mcp/toolkit_install.py`, `cli/toolkits.py` | extends | offer `self add` on missing dist |
| `knowledge/wiki/{claude_code,codex,google}/assets.py` + bookstore emitters | modifies | Windows paths, `--portable`, bookstore pin |
| `knowledge/wiki/claude_code/installer.py` | modifies | reconcile must respect portable entries (L724–729) |
| `knowledge/wiki/project.py`, `bookstore/config.py`, `cli/modes.py` | refactor | consolidate the three `parrot_home()` into one home module |
| wiki store open path | modifies | schema stamp + auto-migrate (backup + lock) |
| `.github/workflows/release.yml` | modifies | wheel matrix |
| `INSTALL.md`, `docs/INSTALL.md`, `.mcp.json.example` | modifies | global quick path; example superseded by `--portable` |
| `sdd/specs/portable-sdd-flow.spec.md` (FEAT-583) | superseded | rejected design (satellite + `sdd` binary); stamp Status: superseded |

No breaking change intended: console scripts from a non-managed venv behave exactly as before; host installs without `--portable` emit what they emit today (plus the Windows fix).

---

## Code Context

### User-Provided Code
_None — requirements in prose (proposal + Rounds 0–2 decisions recorded under Constraints)._

### Verified Codebase References
_Verified on branch `dev` at the primary checkout, 2026-10-05, by direct source reads. Paths relative to `packages/ai-parrot/src/parrot/` unless noted._

#### Entry points & CLI
```python
# packages/ai-parrot/pyproject.toml:199-207  [project.scripts]
parrot = "parrot.cli:cli"; parrot-graphindex = "parrot.knowledge.graphindex.cli:main"
wikitoolkit = "parrot.knowledge.wiki.entry:main"; bookstore = "parrot.knowledge.bookstore.cli:main"
# requires-python = ">=3.11,<3.14" (L18); classifiers: Linux + Windows only, no macOS

# knowledge/wiki/entry.py (33 lines) — module-level imports: only sys (L12)
# main() L21-29: fast-paths exactly argv == ["claude-hook"] → claude_code.hook; else wiki.cli.main

# cli/__init__.py:19 class LazyGroup(click.Group); _lazy_commands L109-137: 24 names
# (setup, conf, install, wiki, bookstore, mcp, mcp-local, toolkits, autonomous, agent, claude,
#  codex, google, gemini, generate-keys, devloop, manuals, e2e, serve, attach, ask, status,
#  install-service, mcp-serve) — NO self/sdd/env/doctor; `parrot status` = agentd daemon status

# install/cli.py:11 PARROT_SERVICES_DIR = Path.home()/".parrot"/"services"
# `parrot install` subcommands: cloudsploit (docker build), prowler (docker pull),
#   scoutsuite (uv pip install — NOT docker), pulumi (curl | sh)  ← proposal said 3, there are 4
# setup/cli.py:7-50 `parrot setup` = provider/env wizard (WizardRunner); does not install packages/hosts
```

#### Existing home convention (proposal claimed none existed — REFUTED)
```python
# knowledge/wiki/project.py:1223-1235  parrot_home(): os.environ["PARROT_HOME"] or ~/.parrot  (wikis.json registry)
# knowledge/bookstore/config.py:67-74  second parrot_home() (library → ~/.parrot/library)
# cli/modes.py:69-70                   third copy (~/.parrot/cli, 0o700)
# Also hardcoding Path.home()/".parrot": conf.py:569 (parrot.db), storage/backends/__init__.py:124,197
#   (parrot.db, artifacts), skills/store.py:942, agents/conf.py:158,202, memory/unified/mixin.py:220 (brains)
# ⇒ ~/.parrot is a LIVE DATA DIR; bootstrap may only add bin/ + venv/ and must never purge it wholesale
```

#### Host installers (three, not two)
```python
# knowledge/wiki/claude_code/assets.py
def resolve_wikitoolkit_bin(root: Path) -> str   # L88-106: root/.venv/bin/<n> → shutil.which → bare
def resolve_parrot_bin(root: Path) -> str        # L123-142: same
def mcp_json_entry(root: Path) -> dict           # L114-120: {"command": abs, "args": ["mcp"], "env": {}}
def toolkit_mcp_json_entry(root, name, section)  # L145-168: mcp-local + pinned --config + cwd
def git_hook_block(root: Path) -> str            # L171-196: POSIX sh only
PERMISSION_RULES  # L53-68, incl. "Bash(source .venv/bin/activate && wikitoolkit:*)"
# NO sys.platform / os.name / Scripts / .exe anywhere in the file

# knowledge/wiki/claude_code/installer.py (1277 lines)
install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True,
    approve_mcp=True, compaction=False, typesafe_api_key=None, plugin_cli=True) -> list[str]  # L964
# _install_mcp_json L693: L724-729 force-replaces a differing "wikitoolkit" entry with mcp_json_entry
#   ⇒ reverts hand-written sh -c / portable entries to absolute paths (must change for --portable)
# marker discipline: _upsert_marker_block/_remove_marker_block L50/L71 (BEGIN-keyed)

# knowledge/wiki/codex/assets.py
def resolve_binary(root: Path, name: str) -> str  # L54-59, same order, no Windows branch
def toolkit_mcp_block(root, sections) -> str      # L62-92, pinned --config (FEAT-556)
def mcp_block(root, toolkit_block="") -> str      # L95-118, marker-delimited [mcp_servers.wikitoolkit]
# knowledge/wiki/codex/installer.py: install_codex_integration L316, uninstall L369, status L416

# knowledge/wiki/google/  ← THIRD HOST, absent from the proposal
# assets.py: resolve_binary L66-71 (same POSIX order); wikitoolkit_mcp_entry L74;
#   toolkit_mcp_entries L83 (pinned --config + cwd); bookstore_mcp_entry L107
#   (sys.executable -m parrot.knowledge.bookstore.cli mcp; passes PARROT_HOME/PARROT_LIBRARY_DIR);
#   default_mcp_config_path() L61 = ~/.gemini/config/mcp_config.json — USER-GLOBAL, collides across repos;
#   PLUGIN_DIR = Path(".agents/plugins/parrot") (assets.py:19) → plugin.json + mcp_config.json tracked in-repo
# installer.py: install_google_integration L285, uninstall L330, status L405;
#   toolkit_config_paths L142 writes global file + <root>/.agents/plugins/parrot/mcp_config.json

# Bookstore entry pins the interpreter, not the script (all three hosts):
# claude_code/bookstore.py:33-40, codex/bookstore.py:37-52, google/assets.py:107 —
#   "command": sys.executable, "args": ["-m", "parrot.knowledge.bookstore.cli", "mcp"], abs cwd

# knowledge/wiki/coding_agents.py: install(agent, root=Path.cwd()) L123, stdlib-only,
#   _AGENTS covers codex/claude/gemini/google; hook command is bare "parrot wiki <agent> hook" (L119)
```

#### Worktree / venv resolution — what exists at run time today
```python
# knowledge/wiki/project.py: resolve_git_common_dir L1337, is_linked_worktree L1386, find_shared_root L1398
#   BUT module-level imports pydantic (L27) + wiki.schema.models (L30) → parrot.bots.database.models
#   (schema/models.py:9) → whole parrot.bots package. "stdlib + pydantic" docstring (L9-10) is STALE.
#   ⇒ unusable in a fast launcher; extract stdlib-only.
# flows/dev_loop/worktree_environment.py:54-71 repository_paths() — stdlib gitdir:/commondir parser
#   L74-90 shared_environments(cwd): sys.prefix, root/.venv, main-checkout .venv, $VIRTUAL_ENV,
#   $UV_PROJECT_ENVIRONMENT, each validated via pyvenv.cfg  ← the extraction template
# flows/dev_loop/sdd_coder/lint.py:38-56 resolve_bin(name): which → dir of sys.executable
# packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/installation.py:65-83
#   resolve_python(root): root/.venv/bin/python else sys.executable (POSIX-only)
# NO Windows venv handling anywhere: sys.platform=="win32" only in tools/repl_worker/{worker,handle}.py
#   and packages/ai-parrot/setup.py:10 (compile args)
```

#### Toolkit layer
```python
# mcp/toolkit_config.py:20 ToolkitSection(class_path alias "class", enabled, kwargs, include,
#   exclude, llm, llm_kwargs, env); load_toolkits_config(root, config_path=None) L90
# mcp/toolkit_seed.py:27 ToolkitTemplate(name, body, requires_llm=False, summary="", requires_dist=())
#   header parser L84-98: ONLY "# parrot:summary|requires_llm|requires_dist"; unknown keys skipped
#   silently (⇒ new keys are forward-compatible); available_templates L49; load_template L63;
#   seed_toolkit_sections L304; template_drift L135; preflight_seed L186
# mcp/toolkit_install.py: dist_available L60 (find_spec, import names); inventory L94;
#   install_toolkits L152; uninstall_toolkits L181; set_toolkits_enabled L216
# mcp/hosts.py:18 HostKind{CLAUDE,CODEX,GOOGLE}; HostAdapter Protocol L37; ClaudeAdapter L58
#   (<root>/.mcp.json); CodexAdapter L120 (.codex/config.toml); GoogleAdapter L176 (user-global
#   ~/.gemini/config/mcp_config.json + repo plugin file, NOT repo-scoped); detect_hosts ~L235
#   — adapters reconcile TOOLKIT entries only; the wikitoolkit entry is owned by each installer
# mcp/_toolkit_templates/: 9 templates (bounded-source, browsing, database-query, lsp, memory,
#   querysource, scraping, sdd-coder, targeted-writer); requires_dist values: parrot_tools (browsing,
#   lsp, scraping), parrot_tools+querysource (querysource), empty/absent (rest)
# mcp/local_cli.py:136 mcp-local(name?, --config, --include, --exclude, --list);
#   _configure_stderr_logging L99 (stderr-only precedent)
# cli/toolkits.py: list|status|install|uninstall|enable|disable, --host claude|codex|google (L16-21)
```

#### Existing installers, packaging, CI (proposal partially REFUTED)
```python
# scripts/install/install-parrot.sh + install-parrot.ps1 — EXIST (FEAT-586, completed):
#   --provider anthropic|openai|google|claude-code|codex-code, --extras, --venv, --python,
#   --with-wiki, --install-cli, --system-deps (apt/brew/winget), --dry-run.
#   python -m venv + pip; do NOT download uv or standalone Python.
#   CI: .github/workflows/ci.yml:139-155 (bash -n, pwsh parse, --dry-run run)
#   Tests: packages/ai-parrot/tests/docs/test_install_{posix,powershell}.py, test_ci_install_wiring.py
# Makefile:62-63 target install-uv: curl -LsSf https://astral.sh/uv/install.sh | sh

# packages/ai-parrot/setup.py — two Cython exts: parrot.utils.types (C++), parrot.utils.parsers.toml (C)
# pyproject [tool.cibuildwheel] L1043-1051: build "cp3{11,12,13,14}-*",
#   skip "pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32"; linux x86_64; windows AMD64;
#   NO [tool.cibuildwheel.macos]
# .github/workflows/release.yml build-core L13-82: ubuntu × {3.11..3.14} + one windows 3.12 include;
#   each linux leg rebuilds the same cp311-314 set (redundant); sdist on linux/3.12 only; NO macOS leg.
#   Only packages/ai-parrot/src/parrot/codec-rs (build-parrot-codec L408-468) builds macOS arm64 +
#   linux aarch64 wheels today. build-navrules (maturin): linux + windows only.
# Heavy compiled deps (wheel-availability risk, pyproject L36-197): navigator-api[uvloop,locale,google]
#   >=3.2.2 (uvloop ⇒ no Windows), navconfig[default]>=2.5.2, navigator-auth>=0.28.3 (Rust rs_pep),
#   asyncdb>=2.16.2, python-datamodel>=0.10.17, ormsgpack>=1.5, brotli==1.2.0, numexpr==2.10.2,
#   semantic-text-splitter (Rust), tiktoken, rustworkx>=0.15, faiss-cpu>=1.9.0, pyarrow>=25.0,
#   Cython>=3.1.4; no torch/transformers in core

# Packaged prompt/rules data (proposal said 4 — there are 11):
#   flows/dev_loop/_subagent_data/: 9 (sdd-autopilot, -coder, -codereview, -feedback, -planner,
#     -qa, -research, -secondopinion, -worker); loader _subagent_defs.py _VALID_NAMES = 8 names
#     (sdd-autopilot shipped but not loadable)
#   flows/dev_flow/_subagent_data/: sdd-ideation.md
#   flows/_rules_data/codebase-conventions.md (read by flows/conventions.py:50-51)
# SDD assets in-repo (to be packaged as parrot/sdd/_assets/ package data): 14 .claude/commands/sdd-*.md,
#   9 .claude/agents/sdd-*.md, 3 .claude/hooks/*, 2 .claude/rules/*, 13 sdd/templates/*,
#   sdd/WORKFLOW.md, ~29 scripts/sdd/*, .codex/agents/sdd-worker.toml, .agents/skills/ (17)
```

#### Related SDD state
```python
# sdd/specs/portable-sdd-flow.spec.md — FEAT-583, Status: draft, NO task index ⇒ never implemented.
#   REJECTED by the owner (2026-10-05): no ai-parrot-sdd satellite, no `sdd` binary, no
#   manifest/symlink machinery. Kept here only so implementers don't mistake it for live design.
# sdd/specs/parrot-install-guide.spec.md — FEAT-586, completed 2026-09-22 (index: 5 tasks done)
# sdd/specs/portable-wikitoolkit-config-paths.spec.md — FEAT-495, completed 2026-09-02
#   (produced the sh -c resolver now in .mcp.json.example; history of 3 regressions documented there)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`PARROT_VENV`, `PARROT_PROJECT`, `PARROT_LAUNCHER` env vars~~ — only in the proposal text (`AI_PARROT_VENV` only in the FEAT-495 brainstorm).
- ~~any `parrot/launcher.py` or launcher module~~ — none under any package.
- ~~`parrot self`, `parrot sdd`, `parrot env`, `parrot doctor` commands~~ — not in `_lazy_commands`; and `parrot status` is TAKEN (agentd), don't reuse it.
- ~~Windows venv handling (`Scripts\`, `.exe`) in any assets/installer/resolver~~ — none anywhere.
- ~~`requires_pip` / `post_install` / `requires_env` template headers~~ — parser knows exactly 3 keys.
- ~~macOS or linux-aarch64 wheels for ai-parrot core~~ — only `parrot-codec` builds them.
- ~~a root-level `install.sh` / `install.ps1`~~ — the FEAT-586 scripts live in `scripts/install/` and do not fetch uv/Python.
- ~~uv-download code in the installers~~ — uv appears only in `Makefile install-uv` and docs.
- ~~a `.claude-plugin/` marketplace manifest~~ — `.agents/plugins/parrot/plugin.json` is the Gemini workspace plugin (different thing); `compaction.py` *consumes* an external marketplace, the repo publishes none.
- ~~a shared host-adapter path for the wikitoolkit MCP entry~~ — `mcp/hosts.py` adapters reconcile toolkit entries only; each wiki installer owns its wikitoolkit block.
- ~~`packages/ai-parrot-sdd/`, a `parrot_sdd` package or an `sdd` console script~~ — FEAT-583 was never implemented AND is rejected; never create these.
- ~~a store schema-version stamp / migration path in the wiki plane~~ — to be designed (schema plane has staleness metadata; the wiki SQLite plane has no version gate today).

**Not verified (spikes):** compiler-free install of the navigator/Cython chain on macOS arm64 and native Windows; Windows stdio re-exec fidelity; what cwd/env each host exports to stdio children in every launch mode.

---

## Spike Gate (before `/sdd-spec`)

1. **Clean-machine install matrix** (gating): macOS arm64, Windows 11 x64, Ubuntu x64, no compiler: `uv venv --python 3.12` + `uv pip install ai-parrot`, then `wikitoolkit mcp` answers `initialize`. Record every sdist fallback (watch: navigator-auth, asyncdb, python-datamodel, ormsgpack, numexpr==2.10.2, brotli==1.2.0, uvloop-on-Windows via the navigator extra). Fail ⇒ the wheel-matrix lane (and/or platform markers + pure-Python fallbacks for the two Cython exts) becomes deliverable #1.
2. **Windows stdio re-exec**: prototype `launcher.reexec`; `wikitoolkit mcp` through it from Claude Code and Codex on Windows — handshake, no stray stdout bytes, child dies with the pipe, exit code propagates. Fail ⇒ Option D for the launcher only.
3. **Host cwd/env probe**: dummy stdio server logging cwd / `CLAUDE_PROJECT_DIR` / `VIRTUAL_ENV` to stderr from Claude Code, Codex **and Gemini** (project- and user-scoped config; repo root and linked worktree). Decides whether rule 2 can trust cwd or adapters must set `PARROT_PROJECT`. Include the Gemini **user-global** config case explicitly.
4. **Launcher overhead**: `wikitoolkit claude-hook` with/without launcher in a non-managed venv (must be noise) and through managed→project re-exec (budget: tens of ms).
5. **SDD portability**: `parrot sdd install` prototype into an empty non-Python repo using only the managed venv; run `/sdd-brainstorm` → `/sdd-spec`; list every hard-coded assumption in the command/agent markdown (`.venv`, `uv run`, monorepo paths, and especially every `scripts/sdd/*.py` / `close_task.sh` invocation) — this decides whether v1 also ships the helper scripts and how commands locate them.
6. **Auto-migration safety** (new, owner chose auto-migrate): prototype backup + single-writer-locked migration on a copy of a real `.parrot/wiki` store; then open it concurrently from an older runtime and record the failure mode. Decides the Open Question on concurrent-session protection.

---

## Parallelism Assessment

- **Internal parallelism**: yes, after spikes 1–3. Lane 0 (Windows `Scripts` branch in the three `assets.py` + bookstore pins — needed under every option) can start immediately. Lane 1 (`launcher.py` + script targets + stdlib worktree extraction) is the contract. Lane 2 (bootstrap `--global` + `self` group + `parrot_home()` consolidation) and Lane 3 (template metadata + toolkits integration) need only the home layout. Lane 4 (SDD asset packaging + `parrot sdd install`) is independent of the others. Lane 5 (wheel matrix) is CI-only, starts immediately.
- **Cross-feature independence**: touches the three `assets.py`, `claude_code/installer.py`, `pyproject.toml [project.scripts]`, `release.yml` — shared with any in-flight wiki-installer or release work; land the script-target change once. FEAT-583 being superseded removes the one real cross-feature collision.
- **Recommended isolation**: `mixed` — Lane 1 worktree first (contract), then per-lane worktrees.
- **Rationale**: the launcher is one small module whose interface (`resolve_venv`, home paths) Lanes 2/3 consume; Lane 4 only consumes the package-data precedent and the marker-block installers.

---

## Open Questions

- [x] Flow type / base — *Owner: Jesus*: feature → `dev` (Round 0, 2026-10-05).
- [x] v1 scope — *Owner: Jesus*: full stack (bootstrap+launcher+self, SDD, toolkit metadata, wheel matrix) (Round 1).
- [x] Launcher scope — *Owner: Jesus*: all three console scripts; re-exec only from the managed venv (Round 1).
- [x] Committable host config — *Owner: Jesus*: default stays baked absolute paths; `--portable` opt-in (Round 1 — deviates from the proposal's auto-detection).
- [x] Bootstrap vehicle — *Owner: Jesus*: extend `scripts/install/install-parrot.{sh,ps1}` (FEAT-586) with the uv/global mode; no new root scripts (Round 2).
- [x] SDD component — *Owner: Jesus*: markdown asset install only — `parrot sdd install` deploying packaged commands/agents/hooks/rules/templates. FEAT-583's satellite-package/`sdd`-binary design is REJECTED (revised 2026-10-05, overriding the earlier Round 2 "absorb" answer); its spec gets stamped superseded.
- [x] Host parity — *Owner: Jesus*: Claude + Codex + Google/Gemini, full (Windows, `--portable`, bookstore pins) (Round 2).
- [x] Version-skew policy — *Owner: Jesus*: auto-migrate (Round 2 — supersedes the proposal's "never migrate silently"; backup + lock mandatory).
- [ ] Auto-migration vs concurrent older-runtime sessions: lock-and-wait, fail the older side with a message, or store-side min-runtime gate? (spike 6 informs) — *Owner: Jesus*
- [ ] Project venv without ai-parrot: silent fallback to managed, or warn once per session on stderr? (recommendation: warn once) — *Owner: Jesus*
- [ ] Worktree fallback: keep "worktree `.venv` → main checkout `.venv`", or always prefer the main checkout for wiki-server version stability? (recommendation: keep, `self env` makes it visible) — *Owner: Jesus*
- [ ] Managed Python: pin 3.12 or newest-with-full-wheel-set? (recommendation: 3.12 — only version with Windows wheels today) — *Owner: Jesus*
- [ ] `--global` flag naming and PATH strategy on Windows (user PATH registry edit vs shim dir instructions)? — *Owner: Jesus*
- [ ] `scripts/sdd/*.py` helpers: do they ship as package data too (the commands invoke `python -m scripts.sdd.ensure_worktree`, `reserve_ids`, `close_task.sh`, …), and how do installed commands locate them outside the monorepo? (spike 5 enumerates; recommendation: decide at spec time from the spike inventory) — *Owner: Jesus*
- [ ] SDD asset source of truth in the monorepo: package data authoritative with `.claude/` synced at build time, or `.claude/` authoritative copied into the package (FEAT-553 `_rules_data` precedent)? — *Owner: Jesus*
- [ ] Clean-machine distribution of the extended script: raw GitHub URL, `landing/` site, or release asset + checksum? (recommendation: raw GitHub + checksum) — *Owner: Jesus*
