# TASK-3089: Managed guard installation — `parrot claude|codex install --tool-guards`, status and owned uninstall

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3088, TASK-3087
**Assigned-to**: unassigned

---

## Context

Spec §2 "Host Guards and SDD Workflow" (paragraphs 4–5: idempotent
managed installation, owned-entry-only uninstall, preserve foreign and
malformed config, report installed/supported), §3 Module M7
(`installation.py` + installer integration), AC13 (installer half).

The Claude Code and Codex wiki installers already reconcile managed
entries with "touch only what we own" semantics
(`claude_code/installer.py:161-210` for the settings hook,
`:276-360` for `.mcp.json`; `codex/installer.py:112-170` for the TOML
block). This task adds a sibling, **opt-in** guard installation that
follows the same rules and plugs into the existing `install` / `status`
/ `uninstall` commands through a lazily imported module in
`parrot_tools`.

**Decisions fixed here:**

1. Ownership marker: a hook command string containing
   `parrot_tools.tool_optimizations.hooks` identifies our entry (same
   idea as `_is_our_hook` matching `HOOK_COMMAND`, `installer.py:126-131`).
2. Claude: one `PreToolUse` entry in `<root>/.claude/settings.json`,
   `matcher: "Read|Bash"`, command
   `"<abs venv python>" -m parrot_tools.tool_optimizations.hooks --host claude`,
   `timeout: 10`. Codex: `<root>/.codex/hooks.json` with
   `{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "...--host codex", "timeout": 10}]}]}}`
   (shape per the Codex hooks doc; **verify against `codex --version`
   0.154.0 by running `codex` with a temp hooks.json in the host smoke
   test of TASK-3091** — if the installed version needs `config.toml`
   `[hooks]` tables instead, switch the writer to that format and record
   it in the Completion Note).
3. Threshold file `<root>/.parrot/tool-guards.json` is written from the
   `bounded-source` toolkit section kwargs (`max_lines`,
   `large_file_bytes`, defaults 350/64000) and the section name
   (`reader_server = f"parrot-{name}"`, `tool = "source_read"`), using
   `load_toolkits_config(root)` (`toolkit_config.py:80`). If no section
   uses `BoundedSourceToolkit`, install still works with defaults and
   reports `"reader MCP not configured — guard denials will reference parrot-bounded-source"`.
4. Malformed JSON in a target file → `RuntimeError` naming the file
   (mirrors `_load_settings`, `installer.py:134-152`); nothing is written.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/installation.py`:
  - `HOOK_MODULE = "parrot_tools.tool_optimizations.hooks"`,
    `CLAUDE_MATCHER = "Read|Bash"`, `CODEX_MATCHER = "Bash"`.
  - `def resolve_python(root: Path) -> str`: `<root>/.venv/bin/python`
    if it exists, else `sys.executable` (absolute; hooks run without the
    venv on PATH — same reasoning as `assets.hook_command`, `assets.py:99-111`).
  - `def hook_command(root: Path, host: str) -> str`.
  - `def guard_thresholds(root: Path) -> dict`: Decision 3.
  - `def install_guards(root: Path, host: Literal["claude", "codex"]) -> list[str]`:
    writes `.parrot/tool-guards.json` (idempotent: only if content
    differs), then the host entry (add / update in place when matcher or
    command changed / "already installed"), preserving every foreign
    entry byte-for-byte except for JSON re-serialisation of the file we
    own the edit of (pretty JSON, 2 spaces, trailing newline — same as
    `_write_settings`, `installer.py:155-158`). Returns action strings
    like the existing installers.
  - `def uninstall_guards(root: Path, host) -> list[str]`: remove only
    entries matching Decision 1; drop empty `PreToolUse`/`hooks`
    containers only if we emptied them (mirror `installer.py:630-645`);
    remove `.parrot/tool-guards.json` only if no other host still has a
    guard installed. Never delete a malformed file.
  - `def guard_status(root: Path, host) -> dict`: `{"installed": bool, "supported": bool | None, "hook_path": str, "thresholds": dict | None, "host_version": str | None}`
    where `host_version` comes from `shutil.which("claude"|"codex")` +
    `--version` with a 5 s timeout (subprocess, never raises; `None` on
    failure) and `supported` is `True` for Claude ≥ 2.1 and Codex ≥
    0.150 (parsed leniently), `None` when unknown. This is the
    "report whether guards are installed and supported" requirement.
- Core CLI integration (lazy import so core never hard-depends on
  `parrot_tools`):
  - `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py`:
    add `--tool-guards/--no-tool-guards` (default off) to `install`
    (`:54-118`); when on, `from parrot_tools.tool_optimizations.installation import install_guards`
    inside the function; `ImportError` → `click.ClickException("tool guards require ai-parrot-tools: uv pip install ai-parrot-tools")`.
    `uninstall` (`:120-127`) always attempts `uninstall_guards` when the
    module imports (no flag; it removes only owned entries). `status`
    (`:129-154`) adds a `tool_guards` key from `guard_status` when
    importable.
  - Same three edits in `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py`
    (`install :42-88`, `uninstall :89-100`, `status :102-...`).
  - Do NOT modify `install_claude_integration` / `install_codex_integration`
    themselves; call the guard functions from the CLI layer after them so
    the wiki installers' tests stay untouched.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py`
  (fixtures build `<root>/.claude/settings.json` and `.codex/hooks.json`
  with foreign entries, malformed variants, and the repo's own two
  PreToolUse entries copied from `.claude/settings.json`). CLI tests use
  `click.testing.CliRunner` against `parrot.knowledge.wiki.claude_code.cli.claude`
  and `...codex.cli.codex` with `--path <tmp root>`.

**NOT in scope**: the hook logic (TASK-3088); documenting the coverage
matrix (TASK-3092); host smoke tests (TASK-3091).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/installation.py` | CREATE | Install / uninstall / status for both hosts |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | `--tool-guards` flag, uninstall + status wiring |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` | MODIFY | Same |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py` | CREATE | Idempotence, foreign/malformed preservation, CLI |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config, ToolkitSection     # toolkit_config.py:80, :19
from parrot.knowledge.wiki.claude_code.cli import claude                       # cli.py:49 (click group)
from parrot.knowledge.wiki.codex.cli import codex                              # cli.py:37 (click group)
import click, json, shutil, subprocess, sys
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _hook_entry(root: Path) -> dict[str, Any]          # :108  {"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": ..., "timeout": 10}]}
def _is_our_hook(entry: dict[str, Any]) -> bool        # :126  HOOK_COMMAND in str(hook["command"])
def _load_settings(path: Path) -> Optional[dict]       # :134  RuntimeError on invalid JSON / non-object
def _write_settings(path: Path, settings: dict) -> None# :155  json.dumps(indent=2) + "\n"
def _install_settings_hook(root: Path) -> str          # :161  add / update-in-place / already-installed
def integration_status(root: Path) -> dict[str, Any]   # :709  hook_installed via _is_our_hook (:733-741)
# :630-645  uninstall: kept = [e for e in pre if not _is_our_hook(e)]; pops empty containers
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
HOOK_MATCHER = "Grep|Glob|Read|Bash"                    # :39
def hook_command(root: Path) -> str                     # :99  absolute path so hooks fire in worktrees
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
@click.group(name="claude") def claude()                # :49
@claude.command() ... def install(...)                  # :54-118 (options :56-80, path_option)
@claude.command() def uninstall(path_)                  # :120-127
@claude.command() def status(path_, as_json)            # :129-154
def _resolve_root(path: Optional[str]) -> Path          # :36
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py
@click.group(name="codex") def codex()                  # :37 ; install :42-88 ; uninstall :89-100 ; status :102
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _validate_toml(path: Path, text: str) -> None       # :44  (only needed if Codex needs config.toml hooks)
def integration_status(root: Path) -> dict[str, Any]    # :281
# This repo's live .claude/settings.json has two PreToolUse entries (wiki nudge "Grep|Glob|Read|Bash", dangerous-actions-blocker "Bash|Edit|Write|MultiEdit") — fixtures must keep both untouched.
```

### Does NOT Exist
- ~~`parrot claude install --guards` / `parrot tool-guard install`~~ — the flag is `--tool-guards`; there is no separate command.
- ~~`assets.GUARD_*` constants in core~~ — all guard constants live in `parrot_tools.tool_optimizations.installation`.
- ~~Codex `~/.codex/hooks.json` writes~~ — project scope only (`<root>/.codex/hooks.json`); never touch the user's home.
- ~~Automatic permission allow-rules for the MCP tools~~ — spec Git Contract 12: no broad automatic-approval installation; do not edit `permissions.allow`.
- ~~Importing `parrot_tools` at module level in core cli.py~~ — lazy import inside the command body only.

---

## Implementation Notes

### Pattern to Follow
```python
def _is_guard_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and any(HOOK_MODULE in str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict))

def _install_json_hook(path: Path, matcher: str, command: str) -> str:
    data = _load_json_object(path) or {}                       # RuntimeError on malformed → caller reports, writes nothing
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise RuntimeError(f"{path}: 'hooks' is not a JSON object")
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list): raise RuntimeError(f"{path}: 'hooks.PreToolUse' is not a list")
    ours = next((e for e in pre if _is_guard_entry(e)), None)
    entry = {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 10}]}
    if ours == entry: return f"{path.name} — tool guard already installed"
    if ours is None: pre.append(entry); verb = "installed"
    else: ours.clear(); ours.update(entry); verb = "updated"
    _write_json(path, data); return f"{path.name} — tool guard {verb}"
```

### Key Constraints
- Idempotent: running install twice yields identical bytes and the
  "already installed" message.
- Foreign entries (other matchers, other commands, unknown keys at any
  level) are preserved exactly; assert with a deep-equal of everything
  except our entry.
- Malformed file → actionable `RuntimeError`/`ClickException`, file
  untouched (compare bytes).
- Uninstall on a file where our entry was hand-deleted → "nothing to
  remove", no write.
- The CLI must still work when `parrot_tools` is not installed
  (`--tool-guards` gives the install hint; `status` omits the key).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:161-210, 598-645, 709-760`.
- `packages/ai-parrot/tests/knowledge/wiki/` (if present) — existing installer tests to mirror in style; otherwise follow `tests/mcp/test_local_cli.py` for `CliRunner` usage.

---

## Acceptance Criteria

- [ ] `install_guards(root, "claude")` twice → second returns "already installed", bytes identical; foreign entries and the two repo-standard entries preserved.
- [ ] `install_guards(root, "codex")` writes `.codex/hooks.json` with the documented shape; existing foreign hooks preserved.
- [ ] Malformed `settings.json` / `hooks.json` → `RuntimeError` naming the file; bytes unchanged.
- [ ] `.parrot/tool-guards.json` reflects `bounded-source` kwargs when configured (`max_lines: 100` in YAML → file says 100) and defaults otherwise.
- [ ] `uninstall_guards` removes only our entry; empty containers dropped only when we emptied them; thresholds file removed only when neither host has a guard.
- [ ] `guard_status` reports `installed`, `hook_path`, `thresholds`, `host_version` (None when the binary is absent) without raising.
- [ ] `parrot claude install --path <tmp> --tool-guards` (CliRunner) prints the guard action; `--no-tool-guards` (default) leaves `settings.json` without our entry; `parrot claude status --json` includes `tool_guards`; `parrot claude uninstall` removes it. Same for `codex`.
- [ ] With `parrot_tools` import forced to fail (monkeypatch `builtins.__import__`), `--tool-guards` yields the install hint and exit code ≠ 0; plain `install` still succeeds.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py -v` plus the existing `tests/` suites for the two CLIs; lint clean; log in `artifacts/logs/TASK-3089-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_installation.py
import json
from pathlib import Path
import pytest
from click.testing import CliRunner
from parrot_tools.tool_optimizations.installation import install_guards, uninstall_guards, guard_status, HOOK_MODULE

FOREIGN = {"matcher": "Bash|Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": "bash x.sh", "timeout": 5}]}

@pytest.fixture
def root(tmp_path):
    (tmp_path / ".claude").mkdir(); (tmp_path / ".parrot").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [FOREIGN]}, "other": {"k": 1}}, indent=2) + "\n")
    return tmp_path

def test_install_is_idempotent_and_preserves_foreign(root):
    a = install_guards(root, "claude"); first = (root / ".claude" / "settings.json").read_bytes()
    b = install_guards(root, "claude"); second = (root / ".claude" / "settings.json").read_bytes()
    assert first == second and any("already" in s for s in b)
    data = json.loads(first); pre = data["hooks"]["PreToolUse"]
    assert pre[0] == FOREIGN and data["other"] == {"k": 1} and HOOK_MODULE in pre[1]["hooks"][0]["command"] and pre[1]["matcher"] == "Read|Bash"

def test_malformed_settings_refused(root):
    p = root / ".claude" / "settings.json"; p.write_text("{not json"); before = p.read_bytes()
    with pytest.raises(RuntimeError, match="settings.json"):
        install_guards(root, "claude")
    assert p.read_bytes() == before

def test_uninstall_only_owned(root):
    install_guards(root, "claude"); uninstall_guards(root, "claude")
    assert json.loads((root / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"] == [FOREIGN]
    assert not (root / ".parrot" / "tool-guards.json").exists()

def test_codex_hooks_json_shape(root):
    install_guards(root, "codex")
    data = json.loads((root / ".codex" / "hooks.json").read_text())
    entry = data["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Bash" and entry["hooks"][0]["command"].endswith("--host codex")

def test_thresholds_from_config(root):
    (root / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  bounded-source:\n    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n    kwargs: {repo_root: ., max_lines: 100}\n")
    install_guards(root, "claude")
    assert json.loads((root / ".parrot" / "tool-guards.json").read_text())["max_lines"] == 100

def test_cli_flag(root):
    from parrot.knowledge.wiki.claude_code.cli import claude
    r = CliRunner().invoke(claude, ["install", "--path", str(root), "--tool-guards", "--no-gitignore"])
    assert r.exit_code == 0 and "tool guard" in r.output
    s = CliRunner().invoke(claude, ["status", "--path", str(root), "--json"])
    assert json.loads(s.output)["tool_guards"]["installed"] is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3088 and TASK-3087 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3089-guard-installation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5, session_01G9NM1TzdkFLd5foNDmh72K)
**Date**: 2026-09-10
**Notes**:

Created `installation.py` (`install_guards`, `uninstall_guards`,
`guard_status`, `guard_thresholds`, `hook_command`, `resolve_python`) and
wired `--tool-guards` into both wiki CLIs. 20 tests in
`test_installation.py`, 293 across the feature suite.

The "touch only what we own" discipline is what the tests actually pin:

- `test_install_is_idempotent_and_preserves_foreign_entries` asserts the
  foreign entries come back **deep-equal to the originals**, including an
  unknown `customKey` and an unrelated top-level key. The fixture models
  this repository's real `.claude/settings.json` (the wiki nudge hook and
  `dangerous-actions-blocker.sh`), so a regression that rewrites a
  neighbour's entry fails immediately.
- `test_malformed_config_is_never_clobbered` compares the file's **bytes**
  before and after a failed install *and* a failed uninstall.
- `test_wrong_container_types_are_refused` covers `hooks: []` and
  `PreToolUse: {}` — a naive `setdefault` would silently reset either.
- `test_uninstall_collapses_only_containers_we_emptied` and
  `test_thresholds_survive_while_another_host_still_uses_them` cover the
  two subtle lifecycle rules: containers are dropped only when we emptied
  them, and the shared `.parrot/tool-guards.json` survives while the other
  host still has a guard installed.
- `test_cli_reports_a_useful_error_when_parrot_tools_is_absent` blocks the
  import via `builtins.__import__` and asserts `--tool-guards` fails with
  the install hint **while a plain install still succeeds** — core never
  hard-depends on `ai-parrot-tools`.

`guard_status` deliberately never raises: a malformed config reads as "not
installed" rather than propagating, because status is a diagnostic. It
reports `supported: None` for an unparseable/absent host version rather
than guessing — an unknown version is never reported as supported. Against
the locally installed hosts it correctly read `2.1.267 (Claude Code)` and
resolved `supported: True`.

The guard is **opt-in and off by default** (`--tool-guards/--no-tool-guards`,
default False), and `permissions.allow` is never touched, per spec Git
Contract 12 (no broad automatic-approval installation).

**Regression check**: `tests/knowledge/wiki` (4 failed / 1595 passed / 12
errors) and `packages/ai-parrot/tests/knowledge/wiki` (7 failed / 276
passed) produce **byte-identical** counts on this branch and on `dev`, so
the CLI edits regress nothing. (The two directories must be run separately
— running both in one pytest invocation hits a pre-existing
`ImportPathMismatchError` between their two `tests.conftest` modules.)

**Testing**: 293 tests in the feature suite; ruff and black clean. Log at
`artifacts/logs/TASK-3089-pytest.log`.

**Deviations from spec**: none in behaviour. One open verification is
explicitly deferred, as the task itself allows: the Codex hook format is
written as `<root>/.codex/hooks.json` per the documented shape, but it was
**not** validated against a running `codex` binary here. If the installed
Codex version requires `config.toml` `[hooks]` tables instead, the writer
must switch format — that check belongs to TASK-3091's host smoke test,
which is where installed host versions get pinned and recorded.
