---
# SDD flow type and base branch.
type: feature
base_branch: dev
---

# Brainstorm: Parrot Bootstrap Installer — self-contained, cross-platform install of the SDD flow, wikitoolkit and MCP toolkits

**Date**: 2026-10-05
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Related**: `claude/schema-plane.brainstorm.md` (FEAT-600, wikitoolkit planes), `claude/sdd-work-ledger.brainstorm.md` (FEAT-566, shared-root / worktree policy), `knowledge/wiki/claude_code/` + `knowledge/wiki/codex/` (host installers), `mcp/toolkit_install.py` (FEAT-570, `parrot toolkits`), `.mcp.json.example`

---

## Problem Statement

Using the SDD flow, the wikitoolkit and the ai-parrot MCP toolkits (browsing, scraping, …) inside Claude Code or Codex today assumes a developer who already has Python, `uv`, a project `.venv` and ai-parrot installed in it. Everything downstream of that assumption already exists and works: `parrot claude install`, `parrot codex install`, `parrot toolkits install <name> --host …`, `.parrot/mcp-toolkits.yaml`, `parrot mcp-local`. What is missing is everything upstream of it:

1. **No bootstrap.** Python and `uv` are not present by default on any target OS. `INSTALL.md` is a Debian/Ubuntu guide (apt packages, PostgreSQL, Redis, FFmpeg) aimed at running the framework, not at "give my coding assistant the wikitoolkit". There is no one-command install.
2. **No runtime when there is no project venv.** The installers resolve binaries at install time as `<root>/.venv/bin/<name>` → `shutil.which` → bare name. A repo that is not a Python project (or a Python project that does not depend on ai-parrot) has nowhere to get `wikitoolkit` from.
3. **POSIX-only wiring.** `.venv/bin/` is hardcoded in `claude_code/assets.py` and `codex/assets.py` (Windows is `.venv\Scripts\<name>.exe`); the committable `.mcp.json.example` is a `sh -c` one-liner; permission rules are `Bash(source .venv/bin/activate && …)`.
4. **The SDD flow is not installable.** `/sdd-*` commands, `sdd-*` sub-agents, hooks, rules and `sdd/templates/` live in the ai-parrot repo's `.claude/` and `sdd/` directories. Only four sub-agent prompts are packaged (`flows/dev_loop/_subagent_data/`, `flows/dev_flow/_subagent_data/`). Another repo cannot get the flow without copying files by hand.
5. **Toolkit exposure does not install anything.** `parrot toolkits install scraping` seeds the YAML section and writes host config; the template's `requires_dist: parrot_tools` is only checked with `find_spec`. If the distribution is absent the user has to know which package and extra to install, and which post-install step (browser binaries) follows.

Who is affected: anyone adopting the SDD flow or the wikitoolkit outside the ai-parrot monorepo; Windows and macOS users in particular. Why now: the host-adapter and toolkit-catalog layers shipped (FEAT-485/556/570), so the remaining gap is small and well-bounded.

## Constraints & Requirements

- **Use the venv that is already there.** Owner's requirement: when a project has its own `.venv` with ai-parrot (ai-parrot itself and the other packages under development), the wikitoolkit must run from it exactly as it does today. The installer must not change that behaviour or touch that venv.
- **One managed venv as fallback, not isolated per component.** Owner's decision. `uvx`-per-server isolation is out of scope.
- **Shared stdio MCP across hosts.** Claude Code and Codex launch the same local stdio servers against the same project wiki. Both must resolve the same venv, so resolution cannot depend on how each host was started.
- **Venv is chosen before the MCP handshake.** The process must already be the right interpreter when JSON-RPC starts; MCP `roots` arrive too late to pick it.
- **stdout is the JSON-RPC channel.** Anything in the launch path writes diagnostics to stderr only (`mcp/local_cli.py::_configure_stderr_logging` precedent).
- **Hook latency.** `wikitoolkit claude-hook` runs before every matching tool call; `wiki/entry.py` (FEAT-595) keeps it off the click import path. Nothing added to the launch path may import more than stdlib.
- **Never modify a project's dependencies implicitly.** Installing ai-parrot into a project venv is an explicit, separate verb.
- **No new prerequisites.** No npm, no system Python, no compiler. `uv` (single static binary) is the only thing the bootstrap downloads besides wheels.
- **No signing work in v1.** The only executable the bootstrap fetches is Astral's already-signed `uv`.
- **Language split:** identifiers, CLI verbs, docs in English.
- **Validation-first:** spikes (§Spike Gate) before `/sdd-spec`.

---

## Options Explored

### Option A: Bootstrap scripts only; keep install-time path resolution

`install.sh` / `install.ps1` download `uv`, create `~/.parrot/venv` and install ai-parrot there. `resolve_wikitoolkit_bin` / `resolve_parrot_bin` / `codex.assets.resolve_binary` gain a fourth candidate (the managed venv) and a Windows branch (`Scripts\<name>.exe`). Host config keeps absolute paths baked at `parrot claude install` time.

✅ **Pros:**
- Smallest change: two scripts plus three resolver functions.
- Zero runtime indirection; nothing new in the launch path.

❌ **Cons:**
- Baked absolute paths stay machine-specific, so `.mcp.json` remains uncommittable and the `sh -c` example remains the only shareable form — which does not run on Windows.
- Resolution is frozen at install time: create a project `.venv` later and the host keeps launching the managed one until someone re-runs the installer.
- Worktrees keep needing the special-cased shell fallback chain.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/claude_code/assets.py::resolve_wikitoolkit_bin`, `resolve_parrot_bin`; `knowledge/wiki/codex/assets.py::resolve_binary`.

---

### Option B: Bootstrap scripts + managed venv + run-time launcher — *recommended*

Three pieces, each small.

**1. Bootstrap** (`install.sh`, `install.ps1`). Download a pinned `uv` into `~/.parrot/bin/` (not the user's own uv, no profile edits beyond adding `~/.parrot/bin` to PATH), `uv venv ~/.parrot/venv --python 3.12` (uv fetches a managed CPython), `uv pip install --python ~/.parrot/venv ai-parrot`, and expose `parrot`, `wikitoolkit`, `bookstore` from `~/.parrot/bin`. `~/.parrot/` is already ai-parrot's home (`install/cli.py::PARROT_SERVICES_DIR = ~/.parrot/services`).

**2. Launcher** (`parrot/launcher.py`, stdlib-only). The console scripts enter through it. It re-executes into another venv **only when the running interpreter is the managed venv**; a binary invoked from any other venv runs as-is. That single rule is what guarantees "no deviation": every existing setup (activated shell, baked absolute path, the monorepo) never enters the resolution path. From the managed venv, the order is:

1. `PARROT_VENV` (explicit override).
2. Project venv: root from `--project` / `PARROT_PROJECT` → `CLAUDE_PROJECT_DIR` → cwd walking up; then `<root>/.venv`, and if the root is a linked worktree without one, the main checkout's `.venv`. This is the order `.mcp.json.example` already encodes in shell.
3. `VIRTUAL_ENV`, only when no project venv was found.
4. Stay in the managed venv.

A candidate is valid only if it contains the requested console script. Project venv ranks above `VIRTUAL_ENV` so Claude Code and Codex converge on the same interpreter regardless of the shell each was launched from (same choice `uv run` makes). `parrot self env` prints the resolved venv and the rule that picked it.

**3. Lifecycle group `parrot self`** (`uv self` / `rustup self` naming; `parrot install` is taken by the Docker-tools group and `parrot setup` by the wizard): `self add <component>`, `self update`, `self doctor`, `self env`, `self uninstall`. `self add scraping` installs the template's pip requirement into the managed venv with the bundled uv and runs its post-install step. `--here` targets the project venv instead, explicitly.

Host wiring stays with the existing adapters. When the launcher is on PATH they write the stable command (`wikitoolkit mcp`, `parrot mcp-local <name> …`) instead of a baked venv path, which makes the generated config portable across machines and OSes and retires the `sh -c` example.

**SDD component.** Package the repo's `.claude/commands/sdd-*.md`, `.claude/agents/sdd-*.md`, the SDD hooks/rules and `sdd/templates/` as package data, and add `parrot sdd install [--host …]` that deploys them with the marker-block/merge discipline the wiki installers already use. It depends on the wiki integration and on the `sdd-coder` toolkit template, so it installs those first.

✅ **Pros:**
- Meets the owner's constraint by construction: project venv first, managed venv only as fallback, existing invocations untouched.
- Deterministic across hosts; late-binding (a `.venv` created tomorrow is picked up without re-running an installer).
- Reuses what shipped: `HostAdapter`s, `ToolkitTemplate`, `parrot toolkits`, marker-block installers, `find_shared_root`.
- Portable host config; first real Windows path.
- No compiled artefact of ours to sign or release.

❌ **Cons:**
- A re-exec in the launch path of every globally-invoked command. Trivial on POSIX (`os.execv`); on Windows it is a child process whose stdio, exit code and termination must be forwarded correctly for stdio MCP (spike 2).
- Version skew becomes possible: the managed wikitoolkit may be newer or older than the one that built a project's `.parrot/` stores (see Edge Cases).
- Depends on ai-parrot and its Cython dependency chain installing from wheels on macOS and Windows, which is not true today (spike 1).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `uv` (binary) | Python download, venv, installs | pinned version, fetched by the bootstrap |
| stdlib only | launcher | no new Python dependency |
| `cibuildwheel` | wheel matrix | already in `release.yml`; matrix must grow |

🔗 **Existing Code to Reuse:**
- `knowledge/wiki/entry.py` — light stdlib dispatcher in front of the click CLI (FEAT-595); the launcher is the same shape one level earlier.
- `knowledge/wiki/project.py::resolve_git_common_dir / is_linked_worktree / find_shared_root` — worktree → main checkout logic (needs a stdlib-only extraction; `project.py` itself is heavy).
- `.mcp.json.example` — the resolution order to port from shell to Python.
- `mcp/hosts.py::ClaudeAdapter / CodexAdapter / GoogleAdapter / detect_hosts`, `mcp/toolkit_install.py::install_toolkits / inventory / dist_available` — host wiring and toolkit state.
- `mcp/toolkit_seed.py::ToolkitTemplate` (`requires_dist`, `requires_llm`, `summary`) and `mcp/_toolkit_templates/*.yaml` — the component catalog to extend.
- `knowledge/wiki/claude_code/installer.py::install_claude_integration`, `knowledge/wiki/codex/installer.py::install_codex_integration`, `knowledge/wiki/coding_agents.py::install` — marker-delimited, merge-safe installers; template for `parrot sdd install`.
- `cli/__init__.py::LazyGroup` (`_lazy_commands`, `_lazy_extras`) — register `self` and `sdd`.

---

### Option C: PyApp single binary per platform

Build one executable per OS/arch with PyApp (Rust wrapper that bootstraps a Python distribution and the package on first run, optional uv backend, built-in `self update`). Distribute through GitHub Releases, Homebrew, winget.

✅ **Pros:**
- "Download one file" experience; no curl-pipe-shell.
- No Rust code to write; bootstrap and self-update come for free.

❌ **Cons:**
- One binary is one entry point; `parrot`, `wikitoolkit` and `bookstore` would need three binaries or a subcommand-only surface.
- Owns its private environment by design; the "use the project venv" rule still needs the Option B launcher inside it.
- Brings macOS notarization and Windows SmartScreen/code-signing into scope.
- Does not remove the wheel-availability problem.

📊 **Effort:** Medium (plus recurring signing cost)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| PyApp | bootstrap wrapper | built per target in CI |

---

### Option D: Custom Rust launcher (`parrot-up`) distributed with cargo-dist

A purpose-built Rust binary that fetches uv, manages `~/.parrot/venv`, performs venv resolution natively and execs the target, with installers generated by cargo-dist (shell, PowerShell, MSI, Homebrew).

✅ **Pros:**
- Fastest and most robust launch path, especially on Windows (real process control, no Python start before the re-exec).
- Full control of UX and distribution channels.

❌ **Cons:**
- Re-implements a thin layer over uv plus the resolver; a second language and release pipeline in the project.
- Same signing burden as Option C.
- Premature unless spike 2 shows the Python launcher cannot be made reliable on Windows.

📊 **Effort:** High

---

## Recommendation

**Option B.** The owner's constraint — keep using the venv that is already there — is a resolution rule, and a resolution rule has to run at launch time; Option A freezes it at install time and Options C/D would still need the same rule inside them. B implements it in about one stdlib module, guarded so that only the globally installed entry points ever re-exec, and leaves every current setup byte-for-byte as it is.

What we trade: one extra process hop on the fallback path, a Windows stdio-forwarding risk that must be proven by a spike, and a new failure class (version skew between the managed wikitoolkit and a project's stores). D stays available as a drop-in replacement for the launcher if spike 2 fails; C is a packaging layer that can be added later for distribution channels without changing the design. A is not rejected so much as absorbed: its Windows fix to the `resolve_*_bin` helpers is needed in B as well, for projects that keep baked paths.

---

## Feature Description

### User-Facing Behavior

- **Install (clean machine):** `curl -LsSf <url>/install.sh | sh` or `irm <url>/install.ps1 | iex`. Result: `~/.parrot/{bin,venv}`, `parrot` and `wikitoolkit` on PATH. Flags: `--version`, `--python`, `--with sdd,scraping`.
- **Wire a repo:** `cd repo && parrot claude install` / `parrot codex install` / `parrot sdd install` / `parrot toolkits install scraping --host claude --host codex` — the existing verbs, now working with no project venv.
- **Add a component to the runtime:** `parrot self add scraping` installs the required distribution and runs post-install (e.g. browser binaries). `parrot toolkits install` offers to run it when `dist_available` is false.
- **Inspect:** `parrot self env` → resolved venv, rule that selected it, ai-parrot version in it, managed-venv version. `parrot self doctor` → uv, Python, PATH, host configs pointing at missing binaries, components with unmet requirements or missing env vars.
- **Update / remove:** `parrot self update [--version X]`, `parrot self uninstall`.
- **Inside a project that has its own `.venv` with ai-parrot:** nothing changes. The host launches that venv's binaries, either directly (baked path, as today) or through the launcher's rule 2.
- **Inside a project whose `.venv` lacks ai-parrot:** the managed venv serves it. `parrot self add --here wiki` is the explicit way to put it in the project venv instead.

### Internal Behavior

1. `parrot/launcher.py` (new, stdlib-only): `is_managed()` (`sys.prefix` under `PARROT_HOME/venv`), `find_project_root()`, `resolve_venv(script) -> (path, rule)`, `script_path(venv, name)` (`bin/<name>` or `Scripts/<name>.exe`), `reexec(target, argv)` (`os.execv` on POSIX; `subprocess` with inherited handles, exit-code propagation and child teardown on Windows), loop guard via `PARROT_LAUNCHER_RESOLVED`.
2. `[project.scripts]`: `parrot`, `wikitoolkit`, `bookstore` enter through `launcher.main(<target>)`; `wiki/entry.py` keeps its hook fast-path behind it. When not managed, the launcher is a `sys.prefix` comparison and a direct call.
3. `parrot/self/` (new): `cli.py` (`self` group), `home.py` (`PARROT_HOME`, paths, pinned uv), `components.py` (catalog lookups, `uv pip install --python <venv>`), `doctor.py`.
4. `ToolkitTemplate`: add `requires_pip` (pip requirement strings) and `post_install` (argv list) header keys next to `requires_dist`; `requires_env` for keys the doctor checks.
5. `claude_code/assets.py` / `codex/assets.py`: `resolve_*_bin` gain the Windows `Scripts` branch; when the launcher is on PATH the adapters emit the bare command plus `PARROT_PROJECT`-free, cwd-independent args where possible.
6. `parrot/sdd/` (new) or under `flows/`: packaged assets + `install_sdd_integration(root, hosts)`; `sdd` lazy command.
7. Repo root: `install.sh`, `install.ps1`; `release.yml` wheel matrix extended.

### Edge Cases & Error Handling

- **Version skew** (managed wikitoolkit vs. the version that built `.parrot/*.db`): stores carry a schema version; on mismatch the server fails with a message naming both versions and the fix (`parrot self update` or `parrot self add --here`). Never migrate a project store silently from the fallback runtime.
- **Linked worktree with its own `.venv`:** used as found. Without one, the main checkout's venv runs — with an editable install that executes main-checkout code, which is correct for the wikitoolkit as a tool and wrong only when the feature under development is the wikitoolkit itself. `parrot self env` makes it visible.
- **Host starts the server from an unexpected cwd** (FEAT-556 found this for Codex and pinned `--config`): the launcher honours `PARROT_PROJECT`; adapters set it when cwd is not reliable for that host.
- **Project `.venv` exists but is broken** (missing interpreter): skip with a stderr warning, fall through to the next rule.
- **Two hosts, one wiki:** two server processes on the same SQLite stores; relies on the existing `sqlite_busy_timeout` / pragmas in `WikiProjectConfig`.
- **No network on first run:** bootstrap fails before touching PATH; partial `~/.parrot` is removed.
- **User already has uv:** the bootstrap never replaces it; it uses its own pinned copy under `~/.parrot/bin`.

---

## Capabilities

### New Capabilities
- `parrot-bootstrap`: `install.sh` / `install.ps1`, managed home `~/.parrot/{bin,venv}`, pinned uv.
- `parrot-launcher`: stdlib venv resolver and re-exec in front of the console scripts.
- `parrot-self`: `self add | update | doctor | env | uninstall`.
- `sdd-install`: packaged SDD commands, agents, hooks, rules, templates and their installer.

### Modified Capabilities
- `mcp-toolkit-templates`: `requires_pip`, `post_install`, `requires_env`.
- `wiki-claude-code-installer`, `wiki-codex-installer`: Windows script paths; launcher-aware command emission.
- `release-pipeline`: wheel matrix (macOS, Windows cp311–313, Linux aarch64).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/launcher.py` (new) | new | stdlib-only resolver + re-exec |
| `parrot/self/` (new) | new | lifecycle CLI, component install, doctor |
| `parrot/sdd/` (new) + package data | new | SDD assets and installer |
| `install.sh`, `install.ps1` (repo root) | new | bootstrap |
| `packages/ai-parrot/pyproject.toml` | modifies | `[project.scripts]` targets; package-data for SDD assets |
| `cli/__init__.py` | extends | `self`, `sdd` lazy commands |
| `mcp/toolkit_seed.py`, `mcp/_toolkit_templates/*.yaml` | extends | new header keys |
| `mcp/toolkit_install.py`, `cli/toolkits.py` | extends | offer `self add` when a distribution is missing |
| `knowledge/wiki/claude_code/assets.py`, `codex/assets.py` | modifies | Windows paths, launcher-aware entries |
| `knowledge/wiki/project.py` | refactor | extract worktree helpers into a stdlib-only module |
| `.github/workflows/release.yml` | modifies | wheel matrix |
| `INSTALL.md`, `.mcp.json.example` | modifies | new quick path; example simplified |

No breaking change intended: a console script run from a non-managed venv behaves exactly as before.

---

## Code Context

### User-Provided Code
_None — requirement given in prose: a system-wide installed ai-parrot CLI usable on Windows, Linux and macOS that bootstraps uv and a venv and registers `parrot` / `wikitoolkit`; a single managed venv (not isolated); reuse an existing project venv when there is one; wikitoolkit is launched as a local stdio MCP by Claude Code and shared by Codex._

### Verified Codebase References
_Paths relative to `packages/ai-parrot/src/parrot/` unless noted; verified against `main` @ `fb9dd935` (2026-10-05). Grep anchors, not line numbers._

```python
# packages/ai-parrot/pyproject.toml
[project.scripts]  parrot = "parrot.cli:cli"; wikitoolkit = "parrot.knowledge.wiki.entry:main"; bookstore = "parrot.knowledge.bookstore.cli:main"; parrot-graphindex = ...
requires-python = ">=3.11,<3.14"
dependencies include "navigator-api[uvloop,locale,google]>=3.2.2", "faiss-cpu>=1.9.0", "pandas", "pyarrow", "Cython>=3.1.4"   # no torch/transformers in core
[tool.setuptools.package-data] "parrot.mcp" = ["_toolkit_templates/*.yaml"]; "parrot.flows.dev_loop" / "parrot.flows.dev_flow" = ["_subagent_data/*.md"]
cibuildwheel skip = "pp* *-musllinux* *-manylinux_i686 *-manylinux_aarch64 *-win32"

# packages/ai-parrot/setup.py — two Cython extensions: parrot.utils.types (C++), parrot.utils.parsers.toml (C)

# .github/workflows/release.yml — build-core matrix: ubuntu-latest × py3.11–3.14 (x86_64), windows-latest × py3.12 only (AMD64). No macOS job.

# cli/__init__.py
class LazyGroup(click.Group)      # _lazy_commands, _lazy_extras
cli._lazy_commands = {"setup","conf","install","wiki","bookstore","mcp","mcp-local","toolkits","autonomous","agent","claude","codex","google","gemini","generate-keys","devloop","manuals","e2e","serve","attach","ask","status","install-service","mcp-serve"}

# install/cli.py
PARROT_SERVICES_DIR = Path.home() / ".parrot" / "services"     # `parrot install` = external Docker tools (cloudsploit, prowler, scoutsuite)

# knowledge/wiki/entry.py — "imports only sys at module level"; dispatches `claude-hook` to claude_code.hook, everything else to wiki.cli (FEAT-595)

# knowledge/wiki/claude_code/assets.py
def resolve_wikitoolkit_bin(root) -> str    # <root>/.venv/bin/wikitoolkit → shutil.which → bare name
def resolve_parrot_bin(root) -> str         # same order for `parrot`
def mcp_json_entry(root) -> dict            # {"command": <abs bin>, "args": ["mcp"], "env": {}}
def toolkit_mcp_json_entry(root, name, section) -> dict   # parrot mcp-local <name> --config <abs>/.parrot/mcp-toolkits.yaml, "cwd": <abs root>
def git_hook_block(root) -> str             # POSIX sh, absolute bin, no-op inside linked worktrees
PERMISSION_RULES includes "Bash(source .venv/bin/activate && wikitoolkit:*)"

# knowledge/wiki/codex/assets.py
def resolve_binary(root, name) -> str       # <root>/.venv/bin/<name> → shutil.which → name
def mcp_block(root, toolkit_block="") / toolkit_mcp_block(root, sections)   # project-scoped [mcp_servers.*] tables; --config pinned "regardless of the cwd Codex starts the server from" (FEAT-556)

# knowledge/wiki/claude_code/installer.py: install_claude_integration, uninstall_claude_integration, integration_status, _install_mcp_json, _install_settings_hook, _install_permissions, _install_git_hook, _install_post_merge_hook
# knowledge/wiki/codex/installer.py: install_codex_integration, uninstall_codex_integration, integration_status
# knowledge/wiki/coding_agents.py: install(agent, root) — "intentionally stdlib-only"
# knowledge/wiki/project.py: resolve_git_common_dir, is_linked_worktree, find_shared_root

# mcp/toolkit_config.py: class ToolkitSection(class_path alias "class", enabled, kwargs, include, exclude, llm, llm_kwargs, env); load_toolkits_config(root, config_path=None)
# mcp/toolkit_seed.py:   class ToolkitTemplate(name, body, requires_llm, summary, requires_dist); available_templates(); load_template(name); seed_toolkit_sections(root, names)
# mcp/toolkit_install.py: dist_available(requires_dist)  # importlib.util.find_spec, import names not pip names; inventory(); install_toolkits(); uninstall_toolkits(); set_toolkits_enabled()
# mcp/hosts.py:          HostKind, HostAdapter (Protocol), ClaudeAdapter, CodexAdapter, GoogleAdapter, get_adapter, detect_hosts(root)
# mcp/_toolkit_templates/: bounded-source, browsing, database-query, lsp, memory, querysource, scraping, sdd-coder, targeted-writer  (header keys: `# parrot:summary`, `# parrot:requires_llm`, `# parrot:requires_dist`)
# cli/toolkits.py: `parrot toolkits list|status|install|uninstall|enable|disable --host claude|codex|google`; "wikitoolkit is deliberately invisible here — it stays owned by `parrot claude install`"
# mcp/local_cli.py: `parrot mcp-local [name] --config … --include … --exclude … --list`; _configure_stderr_logging()
```

`.mcp.json.example` (repo root) launches `wikitoolkit` and `bookstore` through `sh -c`, trying `$CLAUDE_PROJECT_DIR/.venv/bin`, then `git rev-parse --show-toplevel`, then the parent of `git rev-parse --git-common-dir`.

Repo-only SDD assets: `.claude/commands/sdd-{brainstorm,codereview,done,explain,fix,fromjira,insight,next,proposal,spec,start,status,task,tojira}.md`; `.claude/agents/sdd-{autopilot,coder,feedback,ideation,planner,qa,research,secondopinion,worker}.md`; `.claude/hooks/sdd-worker-format.sh`; `.claude/rules/`; `sdd/templates/*`; `sdd/WORKFLOW.md`; `.codex/agents/sdd-worker.toml`.

### Does NOT Exist (Anti-Hallucination)
- ~~any bootstrap script (`install.sh` / `install.ps1`) or code that downloads uv or Python~~ — `uv` appears only in hints and dev-loop argv checks.
- ~~a managed venv (`~/.parrot/venv`) or a `PARROT_HOME` / `PARROT_VENV` / `PARROT_PROJECT` variable~~ — `~/.parrot` is used only for `services/`.
- ~~run-time venv resolution in Python~~ — resolution is install-time (`resolve_*_bin`) or shell (`.mcp.json.example`).
- ~~`parrot self`, `parrot sdd`, `parrot env`, `parrot doctor`~~ — none registered in `_lazy_commands`.
- ~~Windows venv layout handling (`Scripts\`, `.exe`)~~ — `.venv/bin` is hardcoded in both `assets.py` files; no `sys.platform` branch in the installers.
- ~~packaged `/sdd-*` slash commands or an SDD installer~~ — only four sub-agent prompts ship as package data.
- ~~pip requirement or post-install metadata on toolkit templates~~ — `requires_dist` holds import names for `find_spec` only.
- ~~macOS or Linux-aarch64 wheels for `ai-parrot`~~ — not built by `release.yml`; Windows wheels are cp312 only.
- ~~a plugin marketplace manifest (`.claude-plugin/`)~~ — host wiring is done by the installers writing project files.

**Not verified (need the spikes):** whether `navigator-api[uvloop]` and the owner's other compiled dependencies (`navconfig`, `asyncdb`, `python-datamodel`, …) install from wheels on macOS and native Windows; whether Codex and Claude Code both export a usable project directory or cwd to stdio MCP children in all launch modes.

---

## Spike Gate (before `/sdd-spec`)

1. **Clean-machine install matrix.** On macOS arm64, Windows 11 x64 and Ubuntu x64 with no Python and no compiler: `uv venv --python 3.12` + `uv pip install ai-parrot`, then `wikitoolkit mcp` answering `initialize`. Record every package that falls back to an sdist build. Pass = no compiler needed on all three. This is the gating risk: if it fails, the first deliverable is the wheel matrix (or a pure-Python fallback for the two Cython extensions and a platform marker for uvloop), not the installer.
2. **Windows stdio re-exec.** Prototype `launcher.reexec` and run `wikitoolkit mcp` through it from Claude Code and Codex on Windows: handshake completes, no stray bytes on stdout, child exits when the host closes the pipe or kills the launcher, exit code propagates. Fail → Option D for the launcher only.
3. **Host cwd / env probe.** A dummy stdio server that logs `cwd`, `CLAUDE_PROJECT_DIR` and `VIRTUAL_ENV` to stderr, launched by Claude Code and Codex from project-scoped and user-scoped config, from the repo root and from a linked worktree. Decides whether rule 2 can rely on cwd or adapters must set `PARROT_PROJECT`.
4. **Launcher overhead.** Time `wikitoolkit claude-hook` with and without the launcher in a non-managed venv (must be noise) and through a managed→project re-exec (budget: tens of ms).
5. **SDD portability.** `parrot sdd install` prototype into an empty non-Python repo with only the managed venv: `/sdd-brainstorm` → `/sdd-spec` run; list every hard-coded assumption (`.venv`, `uv run`, monorepo paths) found in the command and agent files.

---

## Parallelism Assessment

- **Internal parallelism**: yes after spikes 1–3. Lane 1 (`launcher.py` + script targets + worktree-helper extraction) is the contract. Lane 2 (bootstrap scripts + `self` group) and Lane 3 (template metadata + `toolkits` integration) only need the home layout. Lane 4 (SDD packaging + installer) is independent. Lane 5 (wheel matrix) is CI-only and can start immediately.
- **Cross-feature independence**: touches `claude_code/assets.py`, `codex/assets.py` and `pyproject.toml` `[project.scripts]` — shared with any in-flight wiki-installer work; land the script-target change once.
- **Recommended isolation**: `mixed` — one worktree for Lane 1, per-lane worktrees afterwards.
- **Rationale**: the launcher is one small module whose interface (`resolve_venv`, home paths) everything else consumes.

---

## Open Questions

- [ ] **Launcher scope**: all three console scripts through the launcher (recommended), or a separate `parrot-launch` command used only in host configs, leaving `parrot` itself untouched? — *Owner: Jesus*
- [ ] **Project venv without ai-parrot**: fall back to managed silently (recommended) or warn once per session on stderr? — *Owner: Jesus*
- [ ] **Worktree fallback**: keep "worktree `.venv` → main checkout `.venv`" as in `.mcp.json.example`, or always prefer the main checkout so the wiki server version is stable across worktrees? — *Owner: Jesus*
- [ ] **Version-skew policy**: hard fail on store schema mismatch, or allow read-only serving from a newer runtime? — *Owner: Jesus*
- [ ] **Committable host config**: should `parrot claude install` default to the bare launcher command (portable, needs the global install) or keep baked absolute paths and offer `--portable`? — *Owner: Jesus*
- [ ] **Component catalog**: extend toolkit templates with `requires_pip` / `post_install` (recommended), or a separate `components.yaml` that also covers non-toolkit components (`sdd`, `wiki`, `bookstore`)? — *Owner: Jesus*
- [ ] **Managed Python version**: pin 3.12 (the only version with Windows wheels today) or follow the newest version with a full wheel set? — *Owner: Jesus*
- [ ] **SDD assets source of truth**: move them under `src/` and have the monorepo's own `.claude/` generated by `parrot sdd install`, or keep `.claude/` authoritative and copy into the package at build time? — *Owner: Jesus*
- [ ] **Codex / Gemini SDD parity**: v1 installs SDD for Claude Code only, or also renders Codex agents (`.codex/agents/sdd-worker.toml` exists) in the same pass? — *Owner: Jesus*
- [ ] **Script hosting**: raw GitHub, the `landing/` site, or a release asset with a checksum? — *Owner: Jesus*
