<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
Using the SDD flow, the wikitoolkit and the ai-parrot MCP toolkits inside Claude Code, Codex **or Gemini/Antigravity** today assumes a developer who already has Python, a project `.venv` and ai-parrot installed in it. Everything downstream of that assumption exists and works: `parrot claude|codex|google install`, `parrot toolkits install <name> --host …`, `.parrot/mcp-toolkits.yaml`, `parrot mcp-local`. What is missing is upstream and cross-cutting:

1. **No uv-based bootstrap / managed runtime.** `scripts/install/install-parrot.{sh,ps1}` (FEAT-586) exist but assume (or apt/brew/winget-install) a system Python and create a **project** venv with `python -m venv` + `pip`. There is no managed global runtime (`~/.parrot/venv`), no pinned `uv`, no path for "give my coding assistant the wikitoolkit in a repo that is not a Python project".
2. **No run-time venv resolution for the console scripts.** Host installers bake absolute paths at install time (`resolve_*_bin`: `<root>/.venv/bin/<name>` → `shutil.which` → bare name). Fragments of run-time resolution exist (`flows/dev_loop/worktree_environment.py::shared_environments`, `sdd_coder/lint.py::resolve_bin`, `parrot_tools/tool_optimizations/installation.py::resolve_python`) but none fronts the entry points.
3. **POSIX-only wiring, three times over.** `.venv/bin/` is hardcoded in `claude_code/assets.py`, `codex/assets.py` **and `google/assets.py`**; no `Scripts\`/`.exe` branch exists anywhere venv-related. The bookstore entries add a second machine-specific pin: `sys.executable -m parrot.knowledge.bookstore.cli mcp` with absolute `cwd` (claude_code/bookstore.py, codex/bookstore.py, google/assets.py). `.mcp.json.example` is a POSIX `sh -c` one-liner (FEAT-495). Google's config is **user-global** (`~/.gemini/config/mcp_config.json`), so its absolute per-project paths collide across repos on one machine.
4. **The SDD flow is not installable.** 14 `/sdd-*` commands, 9 `sdd-*` agents, hooks, rules, 13 templates, `sdd/WORKFLOW.md` and ~29 `scripts/sdd/` scripts live only in this repo. 11 prompt/rules files are packaged (9 in `flows/dev_loop/_subagent_data/`, 1 in `dev_flow/_subagent_data/`, `flows/_rules_data/codebase-conventions.md`) but they serve the in-process dev-loop, not an installer. The flow itself is markdown files — the fix is to package them as data and deploy them with an installer verb (`parrot sdd install`), with the marker-block/merge discipline the wiki installers already use. (FEAT-583's heavier answer — a satellite package with its own `sdd` binary — was rejected by the owner.)
5. **Toolkit exposure does not install anything.** Templates carry only `# parrot:summary|requires_llm|requires_dist`; `requires_dist` holds import names checked via `find_spec`. No pip requirement, no post-install (browser binaries), no env-var declaration for a doctor to check.
6. **No macOS wheels for core.** `release.yml` builds core wheels on linux x86_64 + windows AMD64 only (cibuildwheel `cp3{11,12,13,14}`, skip `pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32`). Only `parrot-codec` has a macOS arm64 job. The heavy compiled chain (navigator-api[uvloop], navigator-auth (Rust rs_pep), asyncdb, python-datamodel, ormsgpack, brotli 1.2.0, numexpr ==2.10.2, faiss-cpu, pyarrow, our two Cython extensions) makes compiler-free install on macOS/Windows unproven — the gating spike.

Who is affected: anyone adopting the SDD flow or the wikitoolkit outside the monorepo; Windows and macOS users; multi-repo users of the Gemini global config. Why now: FEAT-485/556/570/586/595 shipped the downstream layers; FEAT-583 is drafted; the remaining gap is bounded.

### Constraints and goals
Owner-confirmed (Rounds 0–2, 2026-10-05):

- **v1 scope is the full stack**: bootstrap + launcher + `parrot self`, SDD asset install (`parrot sdd install`), toolkit install metadata, and the CI wheel matrix.
- **Extend `scripts/install/install-parrot.{sh,ps1}`** with the uv/managed-global mode — do not create new root-level `install.sh`/`install.ps1`. FEAT-586's CI wiring (`ci.yml` bash -n / pwsh parse / `--dry-run`) and tests (`tests/docs/test_install_*.py`) must keep passing and grow with the new mode.
- **All three console scripts** (`parrot`, `wikitoolkit`, `bookstore`) enter through the launcher; re-exec happens **only** when running from the managed venv.
- **Host config default stays baked absolute paths; `--portable` is opt-in** (emits the bare launcher command). Deviation from the proposal's auto-detection.
- **Three-host parity in v1**: Claude Code, Codex and Google/Gemini all get Windows paths, launcher-aware `--portable` emission, and the bookstore `sys.executable` pin replaced.
- **Version skew: auto-migrate.** On store schema mismatch the runtime migrates the project store automatically (supersedes the proposal's "never migrate silently"). Safety rails (decided): pre-migration backup copy, single-writer locking, and a **min-runtime gate** stamped in the migrated store so an older runtime fails fast instead of corrupting it.
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

### Recommended option / probable scope
**Option B′.** The core argument of the proposal survives verification: "use the venv that is already there" is a resolution rule, and a resolution rule must run at launch time — A freezes it, C/D would embed it anyway. What changed after verification and the owner's decisions: the bootstrap is an *extension of FEAT-586's scripts* (their CI and tests already exist); the launcher must be built on a stdlib extraction of `worktree_environment.py` logic, **not** `project.py` (heavier than documented); parity is three hosts plus the bookstore `sys.executable` pins; `PARROT_HOME` is an existing convention to consolidate, not invent; and the SDD component is deliberately minimal — packaged markdown assets plus `parrot sdd install`, rejecting FEAT-583's satellite-package/`sdd`-binary design. D stays as the Windows fallback for the launcher only; C as a later packaging layer; A is absorbed (its Windows fix is lane 0 of B′).

---

### Option B′: Extended bootstrap + managed venv + run-time launcher + SDD asset installer — *recommended*

Four pieces.

**1. Bootstrap — extend FEAT-586's scripts.** `install-parrot.sh/ps1 --global` (naming TBD at spec time): download pinned `uv` into `~/.parrot/bin/`, `uv venv ~/.parrot/venv --python 3.12` (uv-managed CPython), `uv pip install --python ~/.parrot/venv ai-parrot[...]`, expose `parrot`/`wikitoolkit`/`bookstore` shims from `~/.parrot/bin`, add to PATH. The existing project-venv mode stays as-is. `~/.parrot` is already the established home — **`parrot_home()` and `$PARROT_HOME` already exist** (`knowledge/wiki/project.py:1223`, `knowledge/bookstore/config.py:67`, `cli/modes.py:69`) and `~/.parrot` already holds `services/`, `wikis.json`, `library/`, `parrot.db`, `artifacts/`, `skills/`, `brains/`, `cli/` — the installer adds `bin/` and `venv/` to an existing convention, and must consolidate the three duplicate `parrot_home()` implementations rather than add a fourth.

**2. Launcher** (`parrot/launcher.py`, stdlib-only). Console scripts enter through it; it re-executes into another venv **only when `sys.prefix` is under `PARROT_HOME/venv`**. Any other invocation is a `sys.prefix` comparison and a direct call — existing setups stay byte-for-byte identical. From the managed venv the order is: `PARROT_VENV` → project venv (root from `--project`/`PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walk; `<root>/.venv`; linked worktree without one → main checkout's `.venv`) → `VIRTUAL_ENV` → stay managed. A candidate is valid only if it contains the requested console script. `os.execv` on POSIX; forwarded-stdio child process on Windows (spike 2). The worktree logic needs a **stdlib-only extraction** — `project.py` is disqualified at module level (it imports pydantic and, via `schema/models.py:9` → `parrot.bots.database.models`, the whole `parrot.bots` package; its "stdlib + pydantic" docstring is stale). Precedent to extract from: `flows/dev_loop/worktree_environment.py:54–90` (`repository_paths`, `shared_environments` — already parses `gitdir:`/`commondir` with stdlib and checks `pyvenv.cfg`).

**3. Lifecycle group `parrot self`** (`self add | update | doctor | env | uninstall`): name is free — `_lazy_commands` has 24 entries and no `self`/`sdd`/`env`/`doctor`; note `parrot status` **is taken** (agentd), so diagnostics live under `self`. `self add <component>` installs the component's pip requirement into the managed venv with the bundled uv and runs its post-install; `--here` targets the project venv explicitly. Toolkit templates gain `# parrot:requires_pip`, `# parrot:post_install`, `# parrot:requires_env` (parser at `toolkit_seed.py:84–98` skips unknown keys silently today, so old runtimes tolerate new headers). `parrot toolkits install` offers `self add` when `dist_available` is false.

**4. SDD component = markdown asset installer.** Package the repo's `.claude/commands/sdd-*.md`, `.claude/agents/sdd-*.md`, the SDD hooks/rules and `sdd/templates/` as package data (e.g. `parrot/sdd/_assets/`, following the `_subagent_data`/`_toolkit_templates` precedent), and add `parrot sdd install [--host claude|codex|google]` (lazy command) that deploys them with the marker-block/merge discipline the wiki installers already use, plus `uninstall`/`status` twins. Since the assets ship inside ai-parrot core, the managed venv has them with no extra install step. Decided (2026-10-05): the invocable `scripts/sdd/*.py` helpers **move into `parrot.sdd.scripts`** (`python -m parrot.sdd.scripts.ensure_worktree`, `reserve_ids`, …; `close_task.sh` logic ported or wrapped) and the installed markdown references those module paths — the monorepo's `scripts/sdd/` becomes thin wrappers for compatibility. Source of truth: **`.claude/` stays authoritative**, with a build/commit sync into `parrot/sdd/_assets/` and a CI byte-equality check (FEAT-553 `_rules_data` precedent). Spike 5's assumption inventory drives the markdown rewrite list.

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

### Verified code anchors (paths only — open them yourself)
.claude/agents/sdd-*.md
.claude/commands/sdd-*.md
.claude/hooks/*
.claude/rules/*
.github/workflows/ci.yml
.github/workflows/release.yml
.mcp.json.example
Makefile
packages/ai-parrot-sdd/
packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/installation.py
packages/ai-parrot/pyproject.toml
packages/ai-parrot/setup.py
packages/ai-parrot/src/parrot/
packages/ai-parrot/src/parrot/codec-rs
packages/ai-parrot/tests/docs/test_install_{posix,powershell}.py
packages/hosts
scripts/install/
scripts/install/install-parrot.sh
scripts/sdd/*
sdd/WORKFLOW.md
sdd/_assets/
sdd/env/doctor
sdd/specs/parrot-install-guide.spec.md
sdd/specs/portable-sdd-flow.spec.md
sdd/specs/portable-wikitoolkit-config-paths.spec.md
sdd/templates/*

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
