# TASK-1897: Click Command Surface + LazyGroup Wiring + Docs

**Feature**: FEAT-374 — `parrot devloop`: Interactive CLI Console for Dev-Loop Flows
**Spec**: `sdd/specs/devloop-cli-console.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1896
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / Goal G1. Expose the console as `parrot devloop` through
the existing `LazyGroup` (one dict entry — no new console_script), keep
`--help` import-light, and document usage.

---

## Scope

- Replace the placeholder `packages/ai-parrot/src/parrot/cli/devloop/__init__.py`
  with the click surface:
  - `devloop` — a `click.group(invoke_without_command=True)`; bare
    invocation runs the interactive console
    (`DevLoopConsole().start()` via `asyncio.run`).
  - `devloop run [--brief FILE] [--yes]` — `--brief` + `--yes` =
    non-interactive dispatch (wizard skipped; abort on invalid brief);
    `--brief` without `--yes` = wizard pre-seeded from file.
  - `devloop revise [--brief FILE]` — revision-mode entry
    (`start(revision=True, brief_file=...)`).
  - The module-level attribute MUST be named `devloop` so
    `LazyGroup.get_command` resolves it (`cli/__init__.py:52-57`:
    `getattr(mod, cmd_name.replace("-","_")) or getattr(mod, cmd_name)`).
  - Heavy imports (console, bootstrap, conf) INSIDE command bodies —
    `parrot devloop --help` must not boot navconfig (spec §7).
- Modify `packages/ai-parrot/src/parrot/cli/__init__.py`: add
  `"devloop": "parrot.cli.devloop"` to `cli._lazy_commands` (lines 67-78).
  Touch NOTHING else in that file.
- Write `documentation/parrot-devloop-cli.md` (style/structure mirror of
  `documentation/parrot-wiki-cli.md`): what it is, prerequisites
  (preflight table), wizard walkthrough, slash commands, brief-file format
  (YAML example of a full `WorkBrief`), revision mode.
- Tests `packages/ai-parrot/tests/cli/devloop/test_click_wiring.py`:
  CliRunner `--help` on group and subcommands; LazyGroup resolution
  (`cli.get_command(ctx, "devloop")` not None); `run --brief x.yaml --yes`
  invokes console with expected kwargs (console mocked).

**NOT in scope**: console behavior (TASK-1896); integration tests
(TASK-1898); pyproject changes (none needed — `parrot` script exists).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | MODIFY | placeholder → click group `devloop` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | one `_lazy_commands` entry |
| `documentation/parrot-devloop-cli.md` | CREATE | usage guide |
| `packages/ai-parrot/tests/cli/devloop/test_click_wiring.py` | CREATE | CliRunner tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                            # click>=8.1.7, pyproject.toml:81
from click.testing import CliRunner                      # tests
# Inside command bodies only:
from parrot.cli.devloop.console import DevLoopConsole    # TASK-1896
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                            # line 18
    def get_command(self, ctx, cmd_name):                # line 42
        module_path = self._lazy_commands[cmd_name]      # line 54
        mod = importlib.import_module(module_path)       # line 55
        attr_name = cmd_name.replace("-", "_")           # line 56
        return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)  # line 57
cli._lazy_commands = {                                   # lines 67-78
    "setup": "parrot.setup.cli",
    ...
    "agent": "parrot.cli.agent_repl",
    "generate-keys": "parrot.cli.generate_keys",
}   # ← add "devloop": "parrot.cli.devloop"

# Click entry precedent:
# packages/ai-parrot/src/parrot/cli/agent_repl.py:27-48
#   @click.command("agent") / @click.argument / @click.option → def agent(...)
#   runs async engine via asyncio.run(_run(...))

# packages/ai-parrot/pyproject.toml:110-111
# [project.scripts]
# parrot = "parrot.cli:cli"          ← already exists; do NOT add a script

# TASK-1896 surface:
# DevLoopConsole.start(*, brief_file: str | None = None, revision: bool = False) -> int
```

### Does NOT Exist
- ~~A `devloop` console_script / `[project.scripts]` entry~~ — devloop is a
  `parrot` subcommand only (spec Does-NOT-Exist).
- ~~`cli.add_command(...)` registration~~ — this CLI uses the
  `_lazy_commands` dict, not eager `add_command`.
- ~~`documentation/parrot-devloop-cli.md`~~ — created by this task.
- Note: `cli/__init__.py:67-78` currently has a duplicated `"wiki"` key
  (lines 71 and 75) — pre-existing; do NOT "fix" it in this task.

---

## Implementation Notes

### Pattern to Follow
- `agent_repl.py` for click decorator + `asyncio.run` bridging.
- `documentation/parrot-wiki-cli.md` for doc structure.

### Key Constraints
- `parrot devloop --help` must work without navconfig env (lazy imports in
  command bodies; the LazyGroup already defers the module import itself).
- Exit code: propagate `DevLoopConsole.start()` return via `sys.exit`.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/__init__.py:1-13` — module docstring
  documents the lazy-import rationale; extend its listing with devloop.

---

## Acceptance Criteria

- [ ] `parrot devloop --help`, `parrot devloop run --help`,
  `parrot devloop revise --help` all render via CliRunner without importing
  `parrot.conf` (assert module not in `sys.modules` after `--help`).
- [ ] LazyGroup resolves `devloop` (`cli.get_command`), and it appears in
  `parrot --help` listing.
- [ ] `run --brief x.yaml --yes` calls `DevLoopConsole.start(brief_file=...)`
  (mocked) — no wizard.
- [ ] Doc page exists with brief-file YAML example that validates against
  `WorkBrief`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/cli/devloop/test_click_wiring.py -v`
- [ ] `ruff check` clean; `cli/__init__.py` diff is exactly one added dict
  entry (+ optional docstring line).

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_click_wiring.py
from click.testing import CliRunner
from parrot.cli import cli

def test_devloop_help_no_conf_import(): ...
def test_lazygroup_resolves_devloop(): ...
def test_run_brief_yes_invokes_console(monkeypatch, tmp_path): ...
def test_revise_flag_passthrough(monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 M5, §6, §7).
2. **Check dependencies** — TASK-1896 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** (esp. current `_lazy_commands` dict).
4. **Update index** → `"in-progress"`.  5. **Implement** (TDD).
6. **Verify** criteria.  7. **Move to completed/**; index → `"done"`.
8. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
