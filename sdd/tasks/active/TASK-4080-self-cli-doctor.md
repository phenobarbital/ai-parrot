# TASK-4080: parrot self: CLI group (add/update/doctor/env/uninstall) + doctor checks + lazy registration

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h) — was M; raised by the rev 0.2/0.3 amendments (SDD readiness checks, `--sdd` / `--runtime-only` scopes)
**Depends-on**: TASK-4079
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (CLI + doctor half). TASK-4079 built the engine
(`parrot.self_.components`). This task exposes it as the lazy `parrot self` Click group —
`add | update | doctor | env | uninstall` — and implements `parrot self doctor`'s fixed
check list (spec §3 M3 skeleton, §7 "Gemini config is user-global … `self doctor` flags
baked-path collisions there"). `parrot status` is TAKEN by agentd (cli/__init__.py:136),
so every diagnostic lives under `self`.

---

## Amendments — spec rev 0.2 (2026-10-14)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` (§3 C14/C15, §5;
decisions by Jesus Lara, 2026-10-14; C14/C15 scope wording from the proposal's rev 0.3 Codex
review). Every section below is already rewritten to match; this list is the delta.

- **C15 — SDD readiness checks.** `run_doctor` gains a second check family, run when
  `<root>/sdd/` exists or `parrot self doctor --sdd` is passed: `origin` remote present; the
  configured base branch exists on `origin` (branch from `sdd/config.json` via
  `parrot.sdd.config.load_sdd_config(root)` — TASK-4299 — default `dev`; probed with
  `git ls-remote --heads origin <branch>`, a network error is reported as a *warning*, not a
  failure); `sdd/tasks/.id_ledger.json` is git-tracked; `.claude/worktrees/` is ignored; `gh`
  present **and** `gh auth status` exits 0; `jq` present — reported only while an installed
  shipped file still references it (TASK-4070's `external-tool` scan over the installed files);
  installed SDD files current (TASK-4091's `sdd_status`: any `outdated`/`edited` target is "not
  current"); host CLI (`claude` / `codex` / `agy`) present per installed host — **informational**.
  Doctor still only reports and suggests a concrete `fix`; it never changes anything.
- **C14 — `--runtime-only` scope (bootstrap).** `install-parrot.sh --global` /
  `install-parrot.ps1 -Global` (TASK-4074/4075) end by running `parrot self doctor
  --runtime-only` against the freshly installed managed runtime and roll back on failure. That
  scope checks **only** managed uv, managed Python, the runtime entry points
  (`parrot`/`wikitoolkit`/`bookstore` shims resolvable from `$PARROT_HOME/bin`) and PATH; it
  excludes repository readiness, host configuration and optional-component checks, so a sound
  runtime is never rolled back because the invoking repo has an unauthenticated `gh`, an
  uncommitted ledger or outdated SDD assets. `--runtime-only` and `--sdd` are mutually
  exclusive (usage error, exit 2). Plain `parrot self doctor` keeps runtime + host + component
  diagnostics and adds the applicable SDD checks.
- **Exit code rule.** Exit 1 only when a **non-informational** check in the selected scope
  fails; informational host-CLI checks never fail doctor. `DoctorCheck` gains
  `informational: bool = False`.
- **Circularity / lazy imports.** TASK-4091 depends on this task, so `parrot.sdd.config`,
  `parrot.sdd.installer` and `parrot.sdd.audit` must be imported **lazily inside the SDD
  checks** and tolerated when absent (ImportError → the check reports "module unavailable" /
  "SDD flow not installed" as informational, never raises). No new `Depends-on`.
- **Effort** raised M → L; new test module `packages/ai-parrot/tests/self_/test_doctor_sdd.py`.

---

## Amendments — spec rev 0.6 C25 (2026-10-21)

- **C25 — `sdd: guard hook`** (proposal C25, approved by Jesus Lara 2026-10-21). `doctor --sdd`
  (or `full` with an `sdd/` tree) adds one check, read from TASK-4091's
  `sdd_status()["guard_hook"]` = `{"form": "bare"|"baked"|"other"|None, "command", "targets",
  "resolvable"}`, through the same lazy import as "sdd files current":
  - key or module absent, or `form is None` → `ok=True, informational=True` ("no sdd-coder/sdd-worker agents");
  - `form == "other"` → `ok=False`, detail names the targets and the command (hand-patched or copied by
    hand, e.g. a `site-packages/.../worktree_environment.py` path), fix "delete the hand-copied agent
    files and re-run `parrot sdd install`";
  - `resolvable is False` → `ok=False`, fix "re-run `parrot sdd install` (re-bakes the path), or install
    the global launcher (`install-parrot.sh --global`) and re-install with `--portable`";
  - `form == "bare"` and resolvable → `ok=True`, detail notes that this checks the shell's PATH, not the
    Claude Code process's.
  Doctor still only reads. New tests in `test_doctor_sdd.py`: `test_guard_hook_unresolvable_fails_with_fix`,
  `test_guard_hook_hand_patched_is_other`, `test_guard_hook_absent_is_informational`.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: agentd `status` anchor `cli/__init__.py:134`→`:136` (094ec8616 added `jiratoolkit`); Codex `MCP_TABLE` 19→20 and toolkit table 84→85; `_check_python` contract + test now accept `version_info = 3.12` as well as `3.12.x` (repo `.venv` records `3.12`); added the remote-HTTP-entry contract note and `test_remote_http_entry_is_not_flagged`.
- Resolved by spec rev 0.5 (2026-10-20):
  - C24 — `_check_host_configs` checks both Gemini MCP config files (user-global + `<root>/.agents/plugins/parrot/mcp_config.json`, via `toolkit_config_paths`); the cross-repo collision check runs on the user-global one only. New test `test_gemini_repo_local_config_checked`.
  - C20 — new `_check_tools_wiki()` (all three scopes, including `--runtime-only`): `parrot_tools.wiki` must import in the managed venv; fix `parrot self update`. New test `test_tools_wiki_check`.
  - C23 — `doctor --sdd` adds `sdd: ledger merge=union` (`.gitattributes` ledger block) and `sdd: ledger hooks` (pre-commit, post-merge, post-checkout, post-rewrite carry the `parrot-ledger` block); `ready_repo` fixture and the failure matrix extended.
  - C23 / D5 details (dev 2026-10-20): `LEDGER_HOOK_EVENTS` = `pre-commit`, `post-merge`, `post-checkout`, `post-rewrite` (`claude_code/assets.py:53`), each hook must contain `LEDGER_HOOK_BEGIN` (`claude_code/assets.py:51`); the hook file is resolved through `git rev-parse --git-path hooks/<event>` (follows `core.hooksPath` and linked worktrees). Doctor only reads; writing them is TASK-4091's job (and `parrot claude install`, `claude_code/installer.py:973`). The `.gitattributes` check matches the two `merge=union` lines (PR #1746 review), never TASK-4091's marker text.
  - D13 (Gemini repo-local file) is resolved by C24 above — implement it.
- Anchors re-verified on dev 2026-10-20: all unchanged.

## Scope

- Create `parrot/self_/cli.py`: `@click.group(name="self")` `self_group` with
  `add(component, --here)`, `update(--version)`, `doctor()`, `env()`, `uninstall(--yes)`;
  expose it under the module attribute `self` (LazyGroup's lookup convention, below).
- Create `parrot/self_/doctor.py`: `DoctorCheck` model (name, ok, detail, fix, informational),
  `run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]`,
  `installed_version(venv) -> str | None`, `failed(checks) -> list[DoctorCheck]` (non-informational
  failures only).
- Implement the three scopes (C14/C15): `"runtime-only"` = uv, Python, runtime entry points, PATH,
  `parrot_tools.wiki` (rev 0.5 C20; PR #1746 review);
  `"full"` = runtime + host configs + toolkits + SDD checks iff `<root>/sdd/` exists;
  `"sdd"` = `"full"` with the SDD checks forced on.
- Implement the SDD readiness checks (C15): `origin` remote; configured base branch on `origin`;
  ledger git-tracked; `.claude/worktrees/` ignored; `gh` present + authenticated; `jq` present
  while referenced; installed SDD files current (`sdd_status`); host CLIs present (informational);
  *[spec rev 0.5 C23 / D5]* the `.gitattributes` ledger block (`merge=union` for `sdd/ledger/events.jsonl`
  and `sdd/ledger/archive/*.jsonl`) and the four ledger hooks (pre-commit, post-merge, post-checkout,
  post-rewrite) — both plain failures with fix `parrot sdd install`. All `parrot.sdd.*` imports lazy
  and absence-tolerant.
- `parrot self doctor [--sdd | --runtime-only]`: mutually exclusive flags (usage error, exit 2);
  exit 1 iff a non-informational check in the selected scope failed.
- Register `"self": "parrot.self_.cli"` in `cli._lazy_commands`.
- `env` prints: resolved venv + the rule that picked it (`resolve_venv`), the ai-parrot
  version inside that venv, and the managed venv's ai-parrot version.
- Doctor checks (spec §3 M3): pinned uv present + version; managed venv Python is 3.12;
  PATH contains `~/.parrot/bin`; host configs whose command paths don't exist (Claude
  `<root>/.mcp.json`, Codex `<root>/.codex/config.toml`, Google user-global
  `~/.gemini/config/mcp_config.json` and *[spec rev 0.5 C24]* Google repo-local
  `<root>/.agents/plugins/parrot/mcp_config.json`) incl. the Gemini cross-repo baked-path
  collision — checked on the user-global file only (C24);
  installed toolkits with unmet `requires_dist` / `requires_env`; *[spec rev 0.5 C20]*
  `parrot_tools.wiki` imports in the managed venv (ai-parrot-tools is part of the base runtime).
- Tests for the CLI and doctor.

**NOT in scope**: the engine (TASK-4079); fixing anything doctor reports (it only
reports + suggests a `fix`); `parrot sdd` registration (TASK-4091 adds `"sdd"` to the same
dict later — leave room, touch only the `self` line); touching `parrot status`;
`parrot.sdd.config` (TASK-4299), `parrot.sdd.installer.sdd_status` (TASK-4091) and
`parrot.sdd.audit` (TASK-4070) — consumed lazily, never created or re-implemented here; the
bootstrap scripts' call to `parrot self doctor --runtime-only` and their rollback
(TASK-4074/4075); the pre-install gate (C14b, TASK-4074/4075).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/self_/cli.py` | CREATE | `parrot self` Click group |
| `packages/ai-parrot/src/parrot/self_/doctor.py` | CREATE | `DoctorCheck`, `run_doctor`, `installed_version` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Lazy `"self"` entry |
| `packages/ai-parrot/tests/self_/test_self_cli.py` | CREATE | CLI tests (registration, env, add/uninstall wiring) |
| `packages/ai-parrot/tests/self_/test_doctor.py` | CREATE | Doctor check tests (runtime / host incl. both Gemini files / toolkits / `parrot_tools.wiki`) |
| `packages/ai-parrot/tests/self_/test_doctor_sdd.py` | CREATE | C15 SDD readiness checks (+ rev 0.5 C23 ledger block and hooks), `--sdd` / `--runtime-only` scopes, exit-code rule (fixture repo per missing prerequisite) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli import cli  # verified: packages/ai-parrot/src/parrot/cli/__init__.py:103-104
from parrot.mcp.toolkit_seed import available_templates  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:49
from parrot.mcp.toolkit_install import ToolkitState, inventory  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_install.py:32,94
from parrot.knowledge.wiki.google.assets import default_mcp_config_path  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:61
from parrot.knowledge.wiki.google.installer import toolkit_config_paths  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py:142 (rev 0.5 C24)
from parrot.knowledge.wiki.claude_code import assets as claude_assets  # verified: claude_code/assets.py:51-53 LEDGER_HOOK_* (rev 0.5 C23)
from parrot.knowledge.wiki.claude_code.installer import _git_hook_path  # verified: claude_code/installer.py:832 (private; read-only use, rev 0.5 C23)
import tomllib  # stdlib (requires-python >=3.11, packages/ai-parrot/pyproject.toml:18)
# Created by dependency tasks:
from parrot.launcher import MANAGED_PYTHON, find_project_root, parrot_home, resolve_venv, script_path  # TASK-4071
from parrot.self_.components import install_component, managed_venv, uninstall_runtime, update_runtime  # TASK-4079
# Consumed LAZILY inside the SDD checks and tolerated when absent (these tasks land AFTER this one —
# TASK-4091 depends on TASK-4080; never import them at module level, never add them to Depends-on):
from parrot.sdd.config import load_sdd_config        # TASK-4299 — load_sdd_config(root: Path) -> SddConfig (.base_branch, default "dev")
from parrot.sdd.installer import sdd_status          # TASK-4091 — sdd_status(root) -> {"hosts": {h: {"current"|"outdated"|"edited"|"foreign"|"missing": [...]}}, ...}
from parrot.sdd.audit import scan_paths, missing_tools  # TASK-4070 — external-tool findings over installed files (jq)
import shutil, subprocess  # stdlib — shutil.which for gh/jq/claude/codex/agy; git/gh probes via subprocess.run
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                                  # line 19
    def get_command(self, ctx, cmd_name):                      # line 71
        mod = importlib.import_module(module_path)             # line 85
        attr_name = cmd_name.replace("-", "_")                 # line 99
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)  # line 100
#   ⇒ for "self" the module MUST expose a global named `self` (the group object).
cli._lazy_commands = {                                         # line 109
    "toolkits": "parrot.cli.toolkits",                         # line 117
    "status": "parrot.integrations.agentd.cli",                # line 136 — TAKEN, never reuse
}

# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:  # line 94
#   NOTE: hosts=[] is falsy → _resolve_hosts falls back to detect_hosts(root) (line 76-78)
class ToolkitRow(BaseModel):  # line 38: name, state, requires_dist, dist_available (line 46-47)
#   TASK-4078 adds requires_pip / post_install / requires_env
class ToolkitState(str, Enum): NOT_INSTALLED / ENABLED / DISABLED  # line 32-35

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def default_mcp_config_path() -> Path:  # line 61 → ~/.gemini/config/mcp_config.json (USER-GLOBAL)
def wikitoolkit_mcp_entry(root) -> {"command": ..., "args": ["mcp"], "cwd": str(root.resolve())}  # line 74-80
#   ⇒ a user-global "wikitoolkit" entry whose `cwd` != current root is baked for another repo

# packages/ai-parrot/src/parrot/mcp/hosts.py
class ClaudeAdapter.config_paths(root) -> (root / ".mcp.json",)                 # line 63-64
class CodexAdapter.config_paths(root) -> (root / ".codex" / "config.toml",)     # line 125-126
class GoogleAdapter.config_paths(root) -> toolkit_config_paths(root, ...)       # line 185-188

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py  (rev 0.5 C24)
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]:  # line 142
#   → (mcp_path or default_mcp_config_path(), root / assets.PLUGIN_DIR / "mcp_config.json")  # line 151-152
#   PLUGIN_DIR = Path(".agents/plugins/parrot")  — google/assets.py:19
#   reconcile_toolkit_entries writes `parrot-<name>` entries (with "command") into BOTH files (line 155-200)

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_TABLE = "mcp_servers.wikitoolkit"   # line 20; toolkit tables `[mcp_servers.parrot-<name>]` line 85

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py  (rev 0.5 C23 — FEAT-694 ledger hooks)
LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"                                            # line 51
LEDGER_HOOK_END = "# <<< parrot-ledger <<<"                                              # line 52
LEDGER_HOOK_EVENTS = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")      # line 53

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py  (rev 0.5 C23)
def _git_hook_path(root: Path, hook_name: str = "post-commit") -> Optional[Path]:        # line 832 — None if not a git repo;
#   linked worktrees resolve hooks/ against the common git dir
def _install_ledger_hooks(root: Path) -> list[str]:                                      # line 973 — writes LEDGER_HOOK_BEGIN
#   block into each LEDGER_HOOK_EVENTS hook (the installer C23 reuses for `parrot sdd install`)
```
- Claude `.mcp.json` shape: `{"mcpServers": {name: {"command": str, "args": [...]}}}`.
- uv-created `pyvenv.cfg` carries `version_info = 3.12` (venv built on uv's minor-version Python link)
  or `3.12.x` (verified 2026-10-19: repo `.venv/pyvenv.cfg` has `version_info = 3.12`, `uv = 0.11.29`).
- Remote MCP entries carry no `command`: Claude `{"type": "http", "url": …, "headers": …}`
  (`knowledge/wiki/claude_code/assets.py:128-134`), Codex `url = …` (`knowledge/wiki/codex/assets.py:115`).
- Pinned uv version for the bootstrap: `0.11.28` (shared brief; same value the M2 install scripts pin).
- *[rev 0.5 C20]* `parrot_tools.wiki` is a package in ai-parrot-tools
  (`packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py`); `wikitoolkit mcp`'s wiki tools live there
  since FEAT-540, so a managed venv without it cannot answer MCP `initialize`.
- *[rev 0.5 C23]* The two `merge=union` lines the ledger block carries — ai-parrot's own `.gitattributes:2-3`
  (unmarked, FEAT-694): `sdd/ledger/events.jsonl merge=union`, `sdd/ledger/archive/*.jsonl merge=union`.

### Does NOT Exist
- ~~`parrot self`, `parrot env`, `parrot doctor` commands~~ — `"self"` is added here; never add top-level `env`/`doctor`.
- ~~reusing `parrot status`~~ — agentd owns it (cli/__init__.py:136).
- ~~`parrot.self_.cli` / `parrot.self_.doctor`~~ — created here.
- ~~a shared host-config parser in core~~ — doctor reads the four files directly (json / tomllib; two Gemini files since rev 0.5 C24).
- ~~marker strings for the `.gitattributes` ledger block on `dev`~~ — C23's block is written by `parrot sdd install` (TASK-4091), which defines its markers.
- ~~`parrot sdd` in `_lazy_commands`~~ — TASK-4091's line, not this task's.
- ~~`parrot.sdd.config`, `parrot.sdd.installer`, `parrot.sdd.audit` on `dev` today~~ — created by
  TASK-4299 / TASK-4091 / TASK-4070; the SDD checks must work (report "unavailable") when any is missing.
- ~~`DoctorScope`, `--sdd`, `--runtime-only`, `DoctorCheck.informational`, `failed()`~~ — new here (rev 0.2/0.3).
- ~~a `sdd/config.json` schema in this task~~ — `base_branch` is the only field read, via `load_sdd_config`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/self_/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/self_/doctor.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/self_/test_self_cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/self_/test_doctor_sdd.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#cli",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#inventory",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ToolkitState",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py#default_mcp_config_path",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#ClaudeAdapter.config_paths",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#CodexAdapter.config_paths",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#toolkit_config_paths",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_git_hook_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_ledger_hooks"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/cli/toolkits.py:26-28 — a lazily-registered top-level group
@click.group(name="toolkits")
def toolkits() -> None:
    """Install and manage local MCP toolkit servers."""
```

### Key Constraints
- Keep `parrot/self_/cli.py` import-cheap: import `click` at top; import `components`,
  `doctor`, `inventory`, host modules **inside** each command (precedent: cli/toolkits.py
  lazy imports at lines 57, 111, 166).
- `DoctorCheck` is a Pydantic v2 model (codebase convention "Data structures are Pydantic
  v2 models"; the brief's "dataclass" shape — fields name/ok/detail/fix — is kept).
- Doctor never mutates anything and never raises for a broken config file — an
  unreadable/unparsable config is itself a failed check.
- `requires_env`: navconfig can also supply values from `env/.env`, which `os.environ`
  does not show — the failed check's `detail` must say so.
- CLI output via `click.echo` / `click.secho` only.
- Python version check reads `pyvenv.cfg` (no subprocess); version reporting of ai-parrot
  inside a venv uses `subprocess.run([python, "-c", ...], capture_output=True, text=True)`
  — synchronous is correct in a one-shot CLI (no event loop).
- **Scopes (C14/C15)**: `"runtime-only"` runs exactly `_check_uv`, `_check_python`,
  `_check_entrypoints`, `_check_path`, `_check_tools_wiki` — nothing that touches `root`, a host config, a toolkit
  or the network. `"full"` adds host configs + toolkits, and `_check_sdd(root)` iff
  `(root / "sdd").is_dir()`. `"sdd"` forces `_check_sdd`. The `--runtime-only` scope must stay
  cheap and offline: the bootstrap runs it on a machine that may have no repo at all.
  Resolved (PR #1746 review, 2026-10-20): `_check_tools_wiki` is part of `--runtime-only`. C20 makes
  ai-parrot-tools part of the base runtime, and a managed venv where `parrot_tools.wiki` does not import
  cannot serve `wikitoolkit mcp`. The bootstrap must roll back on it. The check is offline, repo-free,
  and runs one interpreter probe.
- **SDD checks are lazy and absence-tolerant**: every `parrot.sdd.*` import sits inside the
  `_check_sdd_*` function that needs it; `ImportError` → `DoctorCheck(ok=True, informational=True,
  detail="… unavailable in this ai-parrot build")`. Git probes use `subprocess.run(["git", "-C", root, …],
  capture_output=True, text=True, check=False)`; a non-zero `git ls-remote` with a network-ish
  stderr is reported as `ok=True, informational=True, detail="could not reach origin: …"`
  (warning), while "branch absent" (exit 0, empty stdout) is a real failure.
- **Exit code**: `failed(checks)` = `[c for c in checks if not c.ok and not c.informational]`;
  `doctor` exits 1 iff that list is non-empty. Informational checks print with `·`, failures
  with `✗`, passes with `✓`.
- **Fix strings are concrete commands**, e.g. `git remote add origin <url>`,
  `git push -u origin dev`, `git add sdd/tasks/.id_ledger.json && git commit -m "sdd: seed id ledger"`,
  `parrot sdd install` (adds the `.gitignore` block), `gh auth login`, `parrot sdd install`
  (outdated files), `parrot sdd status` (edited files), `parrot sdd install` (writes the
  `.gitattributes` ledger block / installs the four ledger hooks — rev 0.5 C23), `parrot self update`
  (`parrot_tools.wiki` missing — rev 0.5 C20).

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/toolkits.py` — CLI style, lazy imports
- `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py:61-121` — Google entry shapes

---

## Implementation Blueprint

### Steps (in order)
1. Create `doctor.py` (`DoctorCheck`, `DoctorScope`, `installed_version`, one private `_check_*` per spec check, the `_check_sdd_*` family, `run_doctor(root, *, scope)`, `failed`) — *why*: the CLI and tests both consume it.
2. Create `cli.py` with the group, five subcommands (`doctor` taking `--sdd` / `--runtime-only`) and `self = self_group` — *why*: LazyGroup resolves `getattr(mod, "self")` (cli/__init__.py:99-100).
3. Register `"self"` in `_lazy_commands` — *why*: spec §3 M3 / §6 Edit Sites.
4. Write tests — *why*: spec §4 `test_self_env_rule_report`, `test_doctor_flags_broken_host_config`, plus the C15 fixture-repo matrix and the scope/exit-code rules (rev 0.2/0.3).

### `packages/ai-parrot/src/parrot/self_/doctor.py` (CREATE)
```python
"""`parrot self doctor` checks (FEAT-633, spec §3 M3; rev 0.2 C14/C15; rev 0.5 C20/C23/C24). Read-only diagnostics.

Scopes: "runtime-only" (bootstrap: uv, Python, entry points, PATH, parrot_tools.wiki — offline, repo-free),
"full" (runtime + host configs + toolkits + SDD readiness iff <root>/sdd exists),
"sdd" (full with SDD readiness forced). Every parrot.sdd.* import is lazy and absence-tolerant.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from parrot.launcher import MANAGED_PYTHON, parrot_home, script_path  # TASK-4071
from parrot.self_.components import managed_venv  # TASK-4079

logger = logging.getLogger(__name__)

#: Kept in sync with the pin in scripts/install/install-parrot.{sh,ps1} (--global mode).
PINNED_UV_VERSION: str = "0.11.28"
DoctorScope = Literal["full", "runtime-only", "sdd"]
RUNTIME_ENTRYPOINTS: tuple[str, ...] = ("parrot", "wikitoolkit", "bookstore")
HOST_CLIS: dict[str, str] = {"claude": "claude", "codex": "codex", "google": "agy"}
SDD_LEDGER = Path("sdd/tasks/.id_ledger.json")


class DoctorCheck(BaseModel):
    """One diagnostic result. ``informational`` checks never fail doctor (C15 host-CLI checks, warnings)."""

    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    informational: bool = False


def failed(checks: list[DoctorCheck]) -> list[DoctorCheck]:
    """Non-informational failures — the only thing that makes ``parrot self doctor`` exit 1."""
    return [c for c in checks if not c.ok and not c.informational]


def installed_version(venv: Path) -> str | None:
    """ai-parrot version installed in ``venv`` (None when absent or not queryable)."""
    python = script_path(venv, "python")
    if not python.exists():
        return None
    code = "import importlib.metadata as m; print(m.version('ai-parrot'))"
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True, check=False)
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _check_uv() -> DoctorCheck:
    """Pinned uv present under ~/.parrot/bin and at PINNED_UV_VERSION."""
    bundled = parrot_home() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    # FILL IN: missing → ok=False, fix "re-run install-parrot --global"; present → `[bundled, "--version"]`
    # (capture_output) and compare the second token with PINNED_UV_VERSION — bounded by spec §3 M3 check 1
    raise NotImplementedError


def _check_python() -> DoctorCheck:
    """Managed venv's pyvenv.cfg ``version_info`` equals MANAGED_PYTHON (uv may record ``3.12``) or starts with MANAGED_PYTHON + '.'."""
    # FILL IN: parse managed_venv()/'pyvenv.cfg' (key = value lines); missing file → ok=False — bounded by spec §3 M3 check 2
    raise NotImplementedError


def _check_path() -> DoctorCheck:
    """PATH contains ~/.parrot/bin (resolved comparison, os.pathsep split)."""
    # FILL IN: fix text differs per OS (POSIX profile line vs Windows user PATH) — bounded by spec §5 PATH bullets
    raise NotImplementedError


def _check_entrypoints() -> DoctorCheck:
    """C14 runtime scope: the three console-script shims exist under ~/.parrot/bin AND resolve in the managed venv."""
    home_bin = parrot_home() / "bin"
    missing = [n for n in RUNTIME_ENTRYPOINTS if not (home_bin / (f"{n}.exe" if os.name == "nt" else n)).exists()
               or not script_path(managed_venv(), n).exists()]
    return DoctorCheck(
        name="runtime entry points", ok=not missing,
        detail="all present" if not missing else f"missing: {', '.join(missing)}",
        fix="" if not missing else "re-run install-parrot --global (or: parrot self update)",
    )


def _check_tools_wiki() -> DoctorCheck:
    """Rev 0.5 C20: ``parrot_tools.wiki`` imports in the managed venv (ai-parrot-tools is base runtime)."""
    python = script_path(managed_venv(), "python")
    # FILL IN: DoctorCheck(name="parrot_tools.wiki", …); no interpreter → ok=False; else subprocess.run([python, "-c", "import parrot_tools.wiki"],
    # capture_output=True, text=True, check=False) (same pattern as installed_version); non-zero → ok=False,
    # detail = last stderr line, fix "parrot self update" — bounded by spec rev 0.5 C20
    raise NotImplementedError


# --- C15: SDD readiness (lazy, absence-tolerant; run only in "full" with <root>/sdd present, or "sdd") ---

def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _sdd_base_branch(root: Path) -> tuple[str, DoctorCheck | None]:
    """(branch, informational check when the config module is unavailable). Default 'dev'."""
    try:
        from parrot.sdd.config import load_sdd_config  # TASK-4299 — lazy on purpose
    except ImportError:
        return "dev", DoctorCheck(name="sdd config", ok=True, informational=True,
                                  detail="parrot.sdd.config unavailable in this build; assuming base branch 'dev'")
    try:
        return load_sdd_config(root).base_branch, None
    except (OSError, ValueError) as exc:  # unreadable / invalid sdd/config.json is itself a failed check
        return "dev", DoctorCheck(name="sdd config", ok=False, detail=f"sdd/config.json invalid: {exc}",
                                  fix="fix sdd/config.json (parrot sdd install --dry-run shows the seed shape)")


def _check_sdd(root: Path) -> list[DoctorCheck]:
    """C15 check list, in proposal order. Never raises; never writes."""
    checks: list[DoctorCheck] = []
    origin = _git(root, "remote", "get-url", "origin")
    checks.append(DoctorCheck(name="sdd: origin remote", ok=origin.returncode == 0,
                              detail=origin.stdout.strip() or origin.stderr.strip(),
                              fix="git remote add origin <url>"))
    branch, cfg_check = _sdd_base_branch(root)
    if cfg_check:
        checks.append(cfg_check)
    # FILL IN (bounded by Key Constraints "SDD checks are lazy and absence-tolerant"):
    #   base branch on origin: `git ls-remote --heads origin <branch>`; exit!=0 → ok=True informational
    #     "could not reach origin: <stderr>"; exit 0 + empty stdout → ok=False fix f"git push -u origin {branch}"
    #   ledger tracked: `git ls-files --error-unmatch sdd/tasks/.id_ledger.json` → fix "git add … && git commit"
    #   worktrees ignored: `git check-ignore -q .claude/worktrees/x` → fix "parrot sdd install (adds the .gitignore block)"
    #   gh: shutil.which("gh") and `gh auth status` exit 0 → fix "install gh / gh auth login"
    #   jq: only if TASK-4070's scan over the installed files (lazy import parrot.sdd.audit; ImportError → skip)
    #     yields an external-tool finding for jq → shutil.which("jq") → fix "install jq"
    #   sdd files current: lazy `from parrot.sdd.installer import sdd_status`; ImportError or no receipt →
    #     ok=True informational "SDD flow not installed"; any host with outdated/edited targets → ok=False,
    #     detail lists them, fix "parrot sdd install" (outdated) / "parrot sdd status" (edited)
    #   host CLIs: for each host with installed assets (sdd_status hosts with any current target),
    #     shutil.which(HOST_CLIS[host]) → ALWAYS informational=True
    #   [rev 0.5 C23] "sdd: ledger merge=union": <root>/.gitattributes carries the ledger block — `merge=union` for
    #     `sdd/ledger/events.jsonl` and `sdd/ledger/archive/*.jsonl`; absent file/line → ok=False, detail names
    #     the missing pattern(s), fix "parrot sdd install (writes the .gitattributes ledger block)"
    #     Resolved (PR #1746 review, 2026-10-20): the check matches the two `merge=union` lines, not TASK-4091's
    #     marker pair, so ai-parrot's own unmarked `.gitattributes:2-3` passes and a repo that adds the
    #     lines by hand is not flagged.
    #   [rev 0.5 C23] "sdd: ledger hooks": lazy-import claude_code.assets + installer._git_hook_path; for each
    #     event in claude_assets.LEDGER_HOOK_EVENTS the hook file exists and contains claude_assets.LEDGER_HOOK_BEGIN;
    #     _git_hook_path → None (not a git repo) or any event missing → ok=False, detail lists the events,
    #     fix "parrot sdd install (installs the four ledger hooks)". [rev 0.5 D5] _git_hook_path resolves
    #     `git rev-parse --git-path hooks/<event>` (follows core.hooksPath and linked worktrees); doctor only
    #     reads — writing the block and the hooks is TASK-4091's job (and `parrot claude install`, installer.py:973).
    raise NotImplementedError


def _command_problem(entry: Any, root: Path) -> str | None:
    """Return why one MCP entry's command is broken, else None.

    Absolute command → must exist; bare command → must resolve via ``shutil.which``.
    """
    # FILL IN: non-dict / missing "command" → None (not ours to judge) — bounded by "doctor never fails on foreign shapes"
    raise NotImplementedError


def _check_host_configs(root: Path) -> list[DoctorCheck]:
    """Claude .mcp.json, Codex .codex/config.toml, both Google mcp_config.json files (rev 0.5 C24).

    The user-global Google file also flags the cross-repo collision: a ``wikitoolkit`` / ``parrot-*``
    entry whose ``cwd`` (or absolute ``--config`` arg) belongs to another root — fix: re-install with
    ``--portable`` (spec §7). The repo-local Google file gets the command check only (C24).
    """
    from parrot.knowledge.wiki.google.installer import toolkit_config_paths  # verified: google/installer.py:142

    claude = root / ".mcp.json"
    codex = root / ".codex" / "config.toml"
    google, google_local = toolkit_config_paths(root)  # (default_mcp_config_path(), root/.agents/plugins/parrot/mcp_config.json)
    # FILL IN: absent file → skip (no check); unparsable → ok=False; json servers under "mcpServers",
    # toml under data["mcp_servers"]; one DoctorCheck per file listing broken entries; collision check on
    # `google` only — bounded by spec §3 M3 check 4 and rev 0.5 C24
    raise NotImplementedError


def _check_toolkits(root: Path) -> list[DoctorCheck]:
    """Installed toolkits (state != NOT_INSTALLED) with unmet requires_dist / requires_env."""
    from parrot.mcp.toolkit_install import ToolkitState, inventory  # verified: toolkit_install.py:32,94

    checks: list[DoctorCheck] = []
    for row in inventory(root):
        if row.state is ToolkitState.NOT_INSTALLED:
            continue
        # FILL IN: unmet dist → ok=False, fix f"parrot self add {row.name}"; missing env (row.requires_env,
        # TASK-4078 field) → ok=False, detail notes navconfig env/.env may still supply it — bounded by spec §3 M3 check 5
        raise NotImplementedError
    return checks


def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:
    """Run the checks of ``scope`` in spec order; never raises for a broken environment.

    "runtime-only" (C14 bootstrap) touches neither ``root`` nor the network and includes parrot_tools.wiki
    (rev 0.5 C20); "full" adds host configs, toolkits and — iff ``root/sdd`` exists — the C15 SDD readiness checks;
    "sdd" forces the latter.
    """
    checks = [_check_uv(), _check_python(), _check_entrypoints(), _check_path(), _check_tools_wiki()]
    if scope == "runtime-only":
        return checks
    checks.extend(_check_host_configs(root))
    checks.extend(_check_toolkits(root))
    if scope == "sdd" or (root / "sdd").is_dir():
        checks.extend(_check_sdd(root))
    return checks
```
**Why this shape**: one function per spec check keeps each independently testable;
`run_doctor`'s positional signature is the spec skeleton's, and `scope` is keyword-only so
existing callers are untouched. `_check_uv` inspects the bundled path directly — never
`bundled_uv()`, whose PATH fallback would mask a missing pinned uv. `"runtime-only"` returns
before anything repo- or network-bound so the bootstrap (C14) can never roll back a sound
runtime because of the invoking repo's state.

### `packages/ai-parrot/src/parrot/self_/cli.py` (CREATE)
```python
"""`parrot self` — manage the parrot-managed runtime (~/.parrot) (FEAT-633, spec §3 M3).

Registered lazily as ``"self"`` in ``parrot.cli._lazy_commands``; LazyGroup resolves the
module attribute named ``self`` (cli/__init__.py:99-100), aliased at the bottom.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click


@click.group(name="self")
def self_group() -> None:
    """Manage the parrot-managed runtime (~/.parrot)."""


def _echo_log(log: list[str]) -> None:
    for line in log:
        click.echo(f"  {line}")


@self_group.command()
@click.argument("component")
@click.option("--here", is_flag=True, default=False, help="Install into the project venv instead of ~/.parrot/venv.")
def add(component: str, here: bool) -> None:
    """Install COMPONENT's packages (+ post-install step) into the managed venv."""
    from parrot.mcp.toolkit_seed import available_templates
    from parrot.self_.components import install_component, managed_venv

    try:
        _echo_log(install_component(component, venv=managed_venv(), here=here))
    except KeyError as exc:
        raise click.ClickException(f"unknown component {component!r}; available: {', '.join(available_templates())}") from exc
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc


@self_group.command()
@click.option("--version", "version", default=None, help="Exact ai-parrot version (default: latest).")
def update(version: str | None) -> None:
    """Upgrade ai-parrot in the managed venv."""
    # FILL IN: call update_runtime(version); map FileNotFoundError/CalledProcessError → ClickException — bounded by add's mapping
    raise NotImplementedError


@self_group.command()
@click.option("--sdd", "sdd_scope", is_flag=True, help="Force the SDD readiness checks even without an sdd/ tree.")
@click.option("--runtime-only", is_flag=True, help="Bootstrap scope: managed uv, Python, entry points and PATH only.")
def doctor(sdd_scope: bool, runtime_only: bool) -> None:
    """Diagnose the managed runtime, host configs, toolkit requirements and SDD readiness.

    Exit 1 only when a non-informational check in the selected scope fails.
    """
    from parrot.launcher import find_project_root  # TASK-4071
    from parrot.self_.doctor import failed, run_doctor

    if sdd_scope and runtime_only:
        raise click.UsageError("--sdd and --runtime-only are mutually exclusive")
    scope = "runtime-only" if runtime_only else ("sdd" if sdd_scope else "full")
    root = find_project_root(sys.argv[1:], os.environ, Path.cwd()) or Path.cwd()
    checks = run_doctor(root, scope=scope)
    for check in checks:
        if check.informational:
            mark, colour = "·", "yellow" if not check.ok else None
        else:
            mark, colour = ("✓", "green") if check.ok else ("✗", "red")
        click.secho(f"  {mark} {check.name}: {check.detail}", fg=colour)
        if not check.ok and check.fix:
            click.echo(f"      fix: {check.fix}")
    if failed(checks):
        raise click.exceptions.Exit(1)


@self_group.command()
def env() -> None:
    """Print the venv the launcher resolves, the rule that picked it, and versions."""
    from parrot.launcher import resolve_venv  # TASK-4071
    from parrot.self_.components import managed_venv
    from parrot.self_.doctor import installed_version

    venv, rule = resolve_venv("parrot", argv=sys.argv[1:], env=os.environ, cwd=Path.cwd())
    click.echo(f"venv: {venv}")
    click.echo(f"rule: {rule}")
    click.echo(f"ai-parrot (resolved): {installed_version(venv) or 'not installed'}")
    click.echo(f"ai-parrot (managed):  {installed_version(managed_venv()) or 'not installed'}")


@self_group.command()
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
def uninstall(yes: bool) -> None:
    """Remove ~/.parrot/{bin,venv,python}; wikis, library, skills, brains and parrot.db are kept."""
    from parrot.self_.components import uninstall_runtime

    if not yes and not click.confirm("Remove the managed runtime (user data is kept)?"):
        return
    _echo_log(uninstall_runtime(yes=True))


#: LazyGroup lookup name (cli/__init__.py:99-100: getattr(mod, "self")).
self = self_group
```

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "toolkits": "parrot.cli.toolkits",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "toolkits": "parrot.cli.toolkits",` (verified: cli/__init__.py:117), inside
# `cli._lazy_commands = {` (verified: cli/__init__.py:109; grep -c = 1). TASK-4091 adds "sdd" separately.
    # FEAT-633 — managed-runtime lifecycle (`parrot status` is agentd's; diagnostics live here).
    "self": "parrot.self_.cli",
```

### `packages/ai-parrot/tests/self_/test_self_cli.py` (CREATE)
```python
"""`parrot self` CLI (FEAT-633, TASK-4080)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from parrot.cli import cli


def test_self_is_registered() -> None:
    result = CliRunner().invoke(cli, ["self", "--help"])
    assert result.exit_code == 0, result.output
    for sub in ("add", "update", "doctor", "env", "uninstall"):
        assert sub in result.output


def test_self_env_rule_report(tmp_path: Path, monkeypatch) -> None:
    """Spec §4 — `self env` prints the resolved venv and the rule."""
    monkeypatch.setattr("parrot.launcher.resolve_venv", lambda *a, **k: (tmp_path / "venv", "VIRTUAL_ENV"))
    with mock.patch("parrot.self_.doctor.installed_version", return_value="1.2.3"):
        result = CliRunner().invoke(cli, ["self", "env"])
    assert result.exit_code == 0, result.output
    assert str(tmp_path / "venv") in result.output and "VIRTUAL_ENV" in result.output and "1.2.3" in result.output


def test_add_unknown_component_lists_available() -> None:
    # FILL IN: invoke ["self", "add", "nope"]; exit_code 1, "available" in output — bounded by add's KeyError mapping
    raise NotImplementedError


def test_add_passes_here_flag() -> None:
    # FILL IN: patch parrot.self_.components.install_component; invoke ["self","add","scraping","--here"];
    # assert called with here=True — bounded by spec §5 `--here`
    raise NotImplementedError


def test_uninstall_without_yes_prompts_and_aborts() -> None:
    # FILL IN: input="n\n"; uninstall_runtime not called — bounded by spec §7 data safety
    raise NotImplementedError
```

### `packages/ai-parrot/tests/self_/test_doctor.py` (CREATE)
```python
"""`parrot self doctor` checks (FEAT-633, TASK-4080)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.self_ import doctor


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PARROT_HOME + fake HOME so the Google user-global config is a tmp file."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_doctor_flags_broken_host_config(isolated_home: Path, tmp_path: Path) -> None:
    """Spec §4 — a config pointing at a missing binary is reported."""
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = tmp_path / "gone" / "wikitoolkit"
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikitoolkit": {"command": str(missing), "args": ["mcp"]}}}), encoding="utf-8"
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and str(missing) in c.detail for c in checks)


def test_remote_http_entry_is_not_flagged(isolated_home: Path, tmp_path: Path) -> None:
    """A remote MCP entry has no `command` (claude_code/assets.py:128-134) — never a broken-command finding."""
    repo = tmp_path / "repo"
    repo.mkdir()
    remote = {"type": "http", "url": "https://wiki.example/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikitoolkit": remote}}), encoding="utf-8")
    assert all(c.ok for c in doctor._check_host_configs(repo))


def test_gemini_cross_repo_collision(isolated_home: Path, tmp_path: Path) -> None:
    # FILL IN: ~/.gemini/config/mcp_config.json with wikitoolkit cwd=<other repo>; assert a failed check whose
    # fix mentions --portable — bounded by spec §7 Gemini bullet
    raise NotImplementedError


def test_gemini_repo_local_config_checked(isolated_home: Path, tmp_path: Path) -> None:
    """Rev 0.5 C24 — the repo-local Gemini file is command-checked too."""
    repo = tmp_path / "repo"
    local = repo / ".agents" / "plugins" / "parrot" / "mcp_config.json"
    local.parent.mkdir(parents=True)
    missing = tmp_path / "gone" / "parrot"
    local.write_text(
        json.dumps({"mcpServers": {"parrot-memory": {"command": str(missing), "args": ["mcp-local", "memory"]}}}),
        encoding="utf-8",
    )
    checks = doctor._check_host_configs(repo)
    assert any(not c.ok and str(missing) in c.detail for c in checks)
    # FILL IN: an entry in the repo-local file whose cwd is another repo yields NO collision (--portable)
    # failure — the collision check runs on the user-global file only — bounded by rev 0.5 C24


def test_tools_wiki_check(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: managed venv with a python stub; patch doctor.subprocess.run → returncode 1 → check "parrot_tools.wiki"
    # ok=False, fix "parrot self update"; returncode 0 → ok=True; no interpreter → ok=False — bounded by rev 0.5 C20
    raise NotImplementedError


def test_python_check_reads_pyvenv_cfg(isolated_home: Path) -> None:
    # FILL IN: write parrot-home/venv/pyvenv.cfg with version_info = 3.11.9 → ok False; 3.12.3 → ok True;
    # 3.12 (uv minor-version link, as in the repo .venv) → ok True; 3.120 → ok False — bounded by MANAGED_PYTHON
    raise NotImplementedError


def test_path_check(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: PATH with/without parrot-home/bin — bounded by spec §3 M3 check 3
    raise NotImplementedError


def test_toolkit_missing_env_and_dist(isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: seed querysource via parrot.mcp.toolkit_seed.seed_toolkit_sections(repo, ["querysource"]),
    # delenv PG_USER/PG_PWD, patch parrot.mcp.toolkit_install.dist_available → False; expect two failed
    # checks, fix "parrot self add querysource" — bounded by spec §3 M3 check 5
    raise NotImplementedError


def test_run_doctor_never_raises_on_empty_home(isolated_home: Path, tmp_path: Path) -> None:
    checks = doctor.run_doctor(tmp_path)
    assert all(isinstance(c, doctor.DoctorCheck) for c in checks)
```

### `packages/ai-parrot/tests/self_/test_doctor_sdd.py` (CREATE)
```python
"""C15 SDD readiness checks + C14 scopes (FEAT-633 rev 0.2/0.3, TASK-4080).

The parrot.sdd.* modules may not exist when this task lands (TASK-4091/4299 come later): every
test here must pass BOTH with them absent (checks report 'unavailable' as informational) and present.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.self_ import doctor


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x", *args], check=True, capture_output=True)


@pytest.fixture
def ready_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo satisfying EVERY C15 + rev 0.5 C23 prerequisite: bare origin with 'dev', tracked ledger, ignored
    worktrees, config, the `.gitattributes` ledger lines and the four ledger hooks."""
    from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks  # verified: installer.py:973

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(origin)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    (repo / "sdd/tasks").mkdir(parents=True)
    (repo / "sdd/tasks/.id_ledger.json").write_text('{"task": 0, "feature": 0}\n')
    (repo / "sdd/config.json").write_text(json.dumps({"base_branch": "dev", "hotfix_base": "main"}) + "\n")
    (repo / ".gitignore").write_text(".claude/worktrees/\n")
    # FILL IN: wrap in TASK-4091's marker lines if review requires the marker (see the C23 note in _check_sdd)
    (repo / ".gitattributes").write_text("sdd/ledger/events.jsonl merge=union\nsdd/ledger/archive/*.jsonl merge=union\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "push", "-q", "-u", "origin", "dev")
    _install_ledger_hooks(repo)  # after the seed commit, so the pre-commit ledger hook never fires here
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")  # gh, jq, claude present
    monkeypatch.setattr(doctor.subprocess, "run", _gh_ok(doctor.subprocess.run))
    return repo


def _gh_ok(real_run):
    """Pass-through for git; fake `gh auth status` → exit 0."""
    def run(cmd, *a, **k):
        if cmd[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    return run


def test_ready_repo_has_no_sdd_failures(ready_repo: Path) -> None:
    checks = doctor._check_sdd(ready_repo)
    assert checks and not doctor.failed(checks), [c.model_dump() for c in doctor.failed(checks)]


@pytest.mark.parametrize(
    "break_it, check_name, fix_fragment",
    [
        (lambda r: _git(r, "remote", "remove", "origin"), "sdd: origin remote", "git remote add origin"),
        (lambda r: subprocess.run(["git", "-C", str(r), "push", "-q", "origin", "--delete", "dev"], check=True), "sdd: base branch on origin", "git push -u origin dev"),
        (lambda r: (_git(r, "rm", "-q", "--cached", "sdd/tasks/.id_ledger.json"), _git(r, "commit", "-q", "--no-verify", "-m", "untrack")), "sdd: id ledger tracked", "git add sdd/tasks/.id_ledger.json"),
        (lambda r: (r / ".gitignore").write_text(""), "sdd: worktrees ignored", "parrot sdd install"),
        (lambda r: (r / ".gitattributes").write_text(""), "sdd: ledger merge=union", "parrot sdd install"),  # rev 0.5 C23
        (lambda r: (r / ".git" / "hooks" / "post-merge").unlink(), "sdd: ledger hooks", "parrot sdd install"),  # rev 0.5 C23
    ],
)
def test_each_missing_prerequisite_fails_its_check_with_a_fix(ready_repo: Path, break_it, check_name: str, fix_fragment: str) -> None:
    """C15 'done when': a fixture repo missing each prerequisite gets the matching check failing, with its fix."""
    break_it(ready_repo)
    bad = {c.name: c for c in doctor.failed(doctor._check_sdd(ready_repo))}
    assert check_name in bad and fix_fragment in bad[check_name].fix


def test_gh_unauthenticated_fails_non_informational(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: patch subprocess.run so `gh auth status` exits 1 → "sdd: gh" in failed(), fix mentions "gh auth login"
    raise NotImplementedError


def test_host_cli_missing_is_informational_only(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: which("claude") → None with an installed claude host → a check with ok=False, informational=True,
    #          NOT in failed() — bounded by C15 "informational host-CLI checks never fail doctor"
    raise NotImplementedError


def test_sdd_modules_absent_degrade_to_informational(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ImportError for parrot.sdd.config / installer / audit must yield informational checks, never raise."""
    import builtins
    real_import = builtins.__import__

    def no_sdd(name, *a, **k):
        if name.startswith("parrot.sdd"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_sdd)
    checks = doctor._check_sdd(ready_repo)
    assert not doctor.failed([c for c in checks if "config" in c.name or "files current" in c.name])


def test_scope_runtime_only_excludes_repo_host_and_component_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C14: a broken repo / host config / toolkit must NOT surface under --runtime-only."""
    repo = tmp_path / "repo"
    (repo / "sdd").mkdir(parents=True)  # no git at all → every SDD check would fail in "full"
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "/nope/wikitoolkit"}}}))
    names = {c.name for c in doctor.run_doctor(repo, scope="runtime-only")}
    assert names == {"uv", "python", "runtime entry points", "PATH", "parrot_tools.wiki"} or all(
        not n.startswith("sdd:") and "mcp" not in n.lower() and "toolkit" not in n.lower() for n in names
    )
    assert any(c.name.startswith("sdd:") for c in doctor.run_doctor(repo, scope="full"))
    assert any(c.name.startswith("sdd:") for c in doctor.run_doctor(tmp_path / "no-sdd-dir", scope="sdd"))
    assert not any(c.name.startswith("sdd:") for c in doctor.run_doctor(tmp_path / "no-sdd-dir", scope="full"))


def test_cli_flags_mutually_exclusive_and_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli, ["self", "doctor", "--sdd", "--runtime-only"])
    assert result.exit_code == 2 and "mutually exclusive" in result.output
    informational_fail = [doctor.DoctorCheck(name="sdd: host cli claude", ok=False, informational=True)]
    with mock.patch("parrot.self_.doctor.run_doctor", return_value=informational_fail):
        assert CliRunner().invoke(cli, ["self", "doctor"]).exit_code == 0
    real_fail = [doctor.DoctorCheck(name="sdd: gh", ok=False, fix="gh auth login")]
    with mock.patch("parrot.self_.doctor.run_doctor", return_value=real_fail):
        result = CliRunner().invoke(cli, ["self", "doctor", "--sdd"])
        assert result.exit_code == 1 and "gh auth login" in result.output
```
**Why**: the C15 "done when" is literally the parametrized matrix (each prerequisite removed →
its check fails with its fix); C14/rev 0.3 is the scope test (runtime-only never sees repo,
host or component failures; full/`--sdd` still do) plus the exit-code and mutual-exclusion
rules at the CLI layer. The ImportError test pins the circularity rule (TASK-4091/4299 land later).

### FILL IN checklist
- [ ] `doctor.py::_check_uv` — presence + version compare; bounded by spec §3 M3 check 1
- [ ] `doctor.py::_check_python` — pyvenv.cfg parse; bounded by MANAGED_PYTHON (3.12)
- [ ] `doctor.py::_check_path` — OS-specific fix text; bounded by spec §5 PATH bullets
- [ ] `doctor.py::_command_problem` / `_check_host_configs` — per-file checks (both Gemini files) + Gemini collision on the user-global file only; bounded by spec §3 M3 check 4, §7, rev 0.5 C24
- [ ] `doctor.py::_check_tools_wiki` — managed-venv import probe; bounded by rev 0.5 C20
- [ ] `doctor.py::_check_toolkits` — dist/env checks; bounded by spec §3 M3 check 5
- [ ] `doctor.py::_check_sdd` — the seven remaining C15 checks after `origin` + the two rev 0.5 C23 ledger checks + the rev 0.6 C25 guard-hook check; bounded by Key Constraints (lazy, absence-tolerant, informational rules)
- [ ] `cli.py::update` — bounded by add's error mapping (`doctor`'s exit code is now fully specified in the blueprint)
- [ ] tests marked FILL IN in all three test files

---

## Acceptance Criteria

- [ ] `parrot self --help` lists `add`, `update`, `doctor`, `env`, `uninstall`; `parrot status` is untouched.
- [ ] `parrot self env` prints the resolved venv, the rule (`PARROT_VENV|project|VIRTUAL_ENV|managed`), and both ai-parrot versions (spec §4 `test_self_env_rule_report`).
- [ ] `parrot self doctor` reports every spec §3 M3 check; a host config pointing at a missing binary is flagged (spec §4 `test_doctor_flags_broken_host_config`); the Gemini cross-repo collision is flagged with a `--portable` fix (spec §7).
- [ ] *[rev 0.5 C24]* Both Gemini MCP config files are command-checked (user-global + `<root>/.agents/plugins/parrot/mcp_config.json`); the cross-repo collision is checked on the user-global one only (`test_gemini_repo_local_config_checked`).
- [ ] *[rev 0.5 C20]* Outside `--runtime-only`, doctor checks that `parrot_tools.wiki` imports in the managed venv; failure fix `parrot self update` (`test_tools_wiki_check`).
- [ ] *[rev 0.5 C23]* `doctor --sdd` (or `full` with an `sdd/` tree) checks the `.gitattributes` ledger block (`merge=union` for `sdd/ledger/events.jsonl` and `sdd/ledger/archive/*.jsonl`) and the four ledger hooks (pre-commit, post-merge, post-checkout, post-rewrite), each with fix `parrot sdd install` (matrix rows in `test_each_missing_prerequisite_fails_its_check_with_a_fix`).
- [ ] *[rev 0.6 C25]* `doctor --sdd` reports `sdd: guard hook` from `sdd_status()["guard_hook"]`: unresolvable
      or `"other"` fails with its fix, absent is informational (`test_guard_hook_*` in `test_doctor_sdd.py`).
- [ ] C15: with an `sdd/` tree (or `--sdd`), doctor reports `origin` remote, configured base branch on `origin` (from `sdd/config.json`, default `dev`), ledger git-tracked, `.claude/worktrees/` ignored, `gh` present + authenticated, `jq` present while referenced, installed SDD files current, and host CLIs (informational); a fixture repo missing each prerequisite gets exactly that check failing with a concrete `fix` (`test_each_missing_prerequisite_fails_its_check_with_a_fix`).
- [ ] C14: `parrot self doctor --runtime-only` runs only uv, Python, runtime entry points and PATH — no repository, host-config or toolkit check, no network — and a repo with a broken host config, uncommitted ledger or unauthenticated `gh` does not fail it (`test_scope_runtime_only_excludes_repo_host_and_component_checks`).
- [ ] `--sdd` and `--runtime-only` together are a usage error (exit 2); doctor exits 1 iff a non-informational check in the selected scope failed; informational host-CLI checks never fail it (`test_cli_flags_mutually_exclusive_and_exit_codes`).
- [ ] Every `parrot.sdd.*` import is lazy and its absence degrades to an informational check (`test_sdd_modules_absent_degrade_to_informational`); doctor never writes and never raises.
- [ ] `parrot self add <c> [--here]` delegates to `install_component`; unknown names list available templates; errors exit 1 via `ClickException`.
- [ ] `parrot self uninstall` confirms unless `--yes` and never touches user data (delegates to TASK-4079).
- [ ] `ruff check packages/ai-parrot/src/parrot/self_/ packages/ai-parrot/src/parrot/cli/__init__.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`
- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`
Also, outside the pytest contract: lint with `ruff check packages/ai-parrot/src/parrot/self_/ packages/ai-parrot/src/parrot/cli/__init__.py packages/ai-parrot/tests/self_/`.

---

## Test Specification

See the CREATE blocks for `test_self_cli.py` (registration, `test_self_env_rule_report`,
add/uninstall wiring), `test_doctor.py` (`test_doctor_flags_broken_host_config`,
remote HTTP entry not flagged, Gemini collision, Gemini repo-local file (C24), `parrot_tools.wiki` (C20),
Python/PATH/toolkit checks, never-raises) and `test_doctor_sdd.py`
(C15 ready-repo baseline + per-prerequisite failure matrix incl. the C23 ledger block / hooks, `gh` unauthenticated, informational
host CLI, `parrot.sdd.*` absent, C14 `--runtime-only` scope exclusion, mutual exclusion + exit codes).

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4080 parrot-installer verified`
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
