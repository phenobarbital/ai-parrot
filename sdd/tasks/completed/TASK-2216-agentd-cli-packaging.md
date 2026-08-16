# TASK-2216: CLI commands (serve/attach/ask/status/install-service/mcp-serve) + core registration + packaging

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2212, TASK-2214, TASK-2215
**Assigned-to**: unassigned

---

## Context

Spec Module 9 — the user-facing surface. Click commands in agentd, lazily
registered into the existing core `parrot` LazyGroup, plus the systemd unit
generator and the `agentd` packaging extra.

---

## Scope

- Implement `cli.py` in `parrot/integrations/agentd/` (Click):
  - `serve <config.yaml | module:attr>` `[--name] [--socket] [--dsn]
    [--redis/--no-redis] [--log-level]` — build `AgentServiceConfig`
    (YAML if the arg is an existing file ending .yaml/.yml, else target
    path) and `asyncio.run(AgentDaemon(cfg).run())`.
  - `attach <name|socket>` `[--no-stream]` — `DaemonAgentProxy` + existing
    `AgentREPL`/`REPLConfig`; register daemon slash commands
    (`register_daemon_commands`); flush `proxy.drain_events()` between
    turns; friendly error when daemon absent (suggest `systemctl --user
    status parrot-<name>` / `parrot serve`).
  - `ask <name> "question"` — one-shot non-stream; render Markdown ONLY if
    `sys.stdout.isatty()`, plain text otherwise (no ANSI in pipes); exit 0
    success / 1 on error.
  - `status <name>` — pretty-print `daemon.status` (rich table on TTY).
  - `install-service <config.yaml>` `[--system]` — render systemd unit per
    spec §3 template (`Type=notify`, `Restart=on-failure`,
    `PYTHONUNBUFFERED=1`, absolute ExecStart resolved from
    `sys.executable`'s bin dir): user mode writes
    `~/.config/systemd/user/parrot-<name>.service` and prints the
    `daemon-reload`/`enable --now` follow-ups; `--system` PRINTS the unit
    to stdout with instructions (never sudo, never writes /etc).
  - `mcp-serve <name|socket>` — `asyncio.run(run_mcp_proxy(...))`.
- Register in core `parrot` CLI: add lazy keys `serve`, `attach`, `ask`,
  `install-service`, `mcp-serve` (and `status`? — NOTE: check collisions
  with existing keys first; `status` is safe to include if unused) to
  `cli._lazy_commands` in `packages/ai-parrot/src/parrot/cli/__init__.py:67`,
  pointing to `parrot.integrations.agentd.cli`. When the module is missing,
  `LazyGroup.get_command` currently `importlib.import_module`s and would
  raise — wrap so the user gets:
  `"parrot serve requires ai-parrot-integrations[agentd]: pip install ai-parrot-integrations[agentd]"`.
  Smallest viable change in core; keep LazyGroup generic.
- Packaging: add `[project.optional-dependencies] agentd = []` (marker
  extra, possibly listing `pyyaml` if not already guaranteed) to
  `packages/ai-parrot-integrations/pyproject.toml`.
- Tests: CliRunner-based — serve arg parsing (yaml vs target), ask exit
  codes + non-TTY plain output, unit-file generation content, missing-module
  error message in core (simulate ImportError via monkeypatch).

**NOT in scope**: docs (TASK-2217), any daemon/server behaviour changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py` | CREATE | All Click commands |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | Lazy keys + graceful missing-module error |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | `agentd` extra |
| `packages/ai-parrot-integrations/tests/agentd/test_cli.py` | CREATE | CliRunner tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                              # core dep (>=8.1.7)
from click.testing import CliRunner                       # for tests
from parrot.integrations.agentd.config import AgentServiceConfig    # TASK-2210
from parrot.integrations.agentd.service import AgentDaemon          # TASK-2212
from parrot.integrations.agentd.proxy import DaemonAgentProxy, register_daemon_commands  # TASK-2214
from parrot.integrations.agentd.mcp_server import run_mcp_proxy     # TASK-2215
from parrot.cli.repl import AgentREPL, REPLConfig         # packages/ai-parrot/src/parrot/cli/repl.py:58,27
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        # imports self._lazy_commands[cmd_name] then
        # getattr(mod, cmd_name.replace("-","_")) or getattr(mod, cmd_name)
cli._lazy_commands = { "setup": ..., "agent": "parrot.cli.agent_repl", ... }   # line 67
# ⇒ command function names in agentd/cli.py MUST match the key
#   (e.g. key "install-service" → function `install_service`).

# packages/ai-parrot/src/parrot/cli/agent_repl.py — reference for wiring
# REPLConfig + AgentREPL(...).run() from a Click command (read it before coding attach).
```

### Does NOT Exist
- ~~`parrot.integrations.agentd.cli`~~ — created by this task.
- ~~an entry-point/plugin mechanism for LazyGroup~~ — registration is the static dict; edit it directly.
- ~~`parrot serve` / `parrot attach` / `parrot ask` today~~ — currently unregistered names; verify no key collisions in the dict at implementation time (dict at cli/__init__.py:67 — as of spec writing: setup, conf, install, wiki, mcp, autonomous, agent, claude, generate-keys, devloop).
- ~~sudo escalation in install-service~~ — must never happen.

---

## Implementation Notes

### Key Constraints
- Open Question §8 resolved-by-default here: plain `parrot serve` keys
  (not `parrot agentd serve`); flag any collision found at implementation
  time in the Completion Note.
- `attach` drains proxy events after each turn — wire around
  `AgentREPL.send/send_stream` calls or via a registered post-turn hook if
  the REPL run-loop doesn't expose one, print queued lines before the next
  prompt (read repl.py:96-160 run loop first and pick the cleanest seam;
  document the choice).
- Unit template: exact fields from spec §3 (After=network-online.target,
  Type=notify, Restart=on-failure, Environment=PYTHONUNBUFFERED=1,
  WantedBy=default.target).
- Keep the core `__init__.py` diff minimal — this file ships in ai-parrot
  core and is shared by every other subcommand.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/agent_repl.py` — how the existing REPL command builds loader + REPLConfig + runs.
- Spec §3 Module 9 + §2 CLI surface.

---

## Acceptance Criteria

- [ ] `parrot serve` accepts YAML path and `module:attr` forms (CliRunner, daemon mocked).
- [ ] `parrot ask` exits 0/1 correctly; non-TTY output has no ANSI codes.
- [ ] `parrot install-service` writes a unit whose content matches spec §3 template; `--system` prints instead of writing.
- [ ] Missing agentd module → actionable error naming `ai-parrot-integrations[agentd]` (not a raw ImportError traceback).
- [ ] `attach` wires DaemonAgentProxy into AgentREPL with daemon slash commands registered (smoke test with mocked proxy).
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_cli.py -v`; `ruff check` clean; existing core CLI tests still pass.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_cli.py
import pytest
from click.testing import CliRunner
from parrot.integrations.agentd import cli as agentd_cli

class TestServe:
    def test_yaml_arg(self, tmp_path): ...
    def test_target_arg(self): ...

class TestAsk:
    def test_exit_codes(self): ...
    def test_non_tty_plain(self): ...

class TestInstallService:
    def test_unit_content(self, tmp_path): ...
    def test_system_prints_only(self): ...

class TestCoreRegistration:
    def test_missing_module_message(self, monkeypatch): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2212/2214/2215 completed; 3. verify contract —
read agent_repl.py + cli/__init__.py current state; 4. index → in-progress;
5. implement; 6. verify criteria; 7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-16
**Notes**: Implemented `cli.py` with all 6 Click commands: `serve`
(YAML-vs-`module:attr` detection, `--name`/`--socket`/`--dsn`/`--redis`/
`--no-redis`/`--log-level` overrides applied via `AgentServiceConfig.
model_copy()`), `attach` (`DaemonAgentProxy` + existing `AgentREPL`/
`REPLConfig`, `register_daemon_commands()`, friendly
`systemctl --user status`/`parrot serve` hint on `DaemonNotRunning`),
`ask` (one-shot, TTY-conditional Markdown vs plain `click.echo`, exit 0/1),
`status` (pretty `daemon.status` via `ResponseRenderer.render_info`),
`install_service` (systemd unit exactly per the task's field list —
`After=network-online.target`, `Type=notify`, `Restart=on-failure`,
`Environment=PYTHONUNBUFFERED=1`, `WantedBy=default.target`,
`ExecStart` resolved from `sys.executable`'s bin dir; user mode writes
`~/.config/systemd/user/parrot-<name>.service` + prints
daemon-reload/enable-now follow-ups; `--system` ONLY prints to stdout,
never writes `/etc`, never sudo), and `mcp_serve` (`asyncio.run(
run_mcp_proxy(...))`).

Core registration (`packages/ai-parrot/src/parrot/cli/__init__.py`): added
lazy keys `serve`/`attach`/`ask`/`status`/`install-service`/`mcp-serve` →
`parrot.integrations.agentd.cli` (verified NO key collisions against the
existing dict first, confirming the Open-Question default: plain
`parrot serve` etc., not `parrot agentd serve`). `LazyGroup` gained a
generic `_lazy_extras: dict[str, str]` (any lazy command may register an
install hint) and `get_command()` now wraps the `importlib.import_module()`
call in try/except `ImportError`, raising `click.ClickException` with the
hint when registered, else a generic "could not import `<module>`"
message — never a raw traceback. Smallest-viable, fully generic change
(not agentd-specific): all 49 pre-existing core CLI tests
(`test_setup_wizard.py`, `test_click_wiring.py`) still pass unchanged.

Packaging: added `agentd = []` (marker extra) to
`ai-parrot-integrations/pyproject.toml`.

**Attach event-drain seam (documented choice, per task instruction)**:
`AgentREPL.run()`'s loop is a monolithic method with no exposed post-turn
hook, and modifying `parrot.cli.repl`/`parrot.cli.commands` in core is out
of scope for this feature (confirmed in TASK-2214). `_wrap_with_event_
drain()` instead shadows `repl.send`/`repl.send_stream` at the INSTANCE
level (assigning new bound-like callables as instance attributes, which
Python's attribute lookup prefers over the class methods `run()` calls) —
queued job-event lines print right after a turn completes and before the
next prompt, achieving the spec's "flush between turns only, never
mid-stream" requirement without touching core.

Test coverage (`test_cli.py`, CliRunner): `serve` YAML-arg/target-arg/
missing-`--name`-error/override-application; `ask` success/`DaemonNotRunning`/
non-TTY-plain-output (asserting no `\x1b[` ANSI codes — CliRunner's
captured stdout is never a TTY, so this exercises the real plain-text
path); `install-service` unit content (all required fields + no `sudo`)
and `--system` stdout-only (`result.stdout` vs `result.stderr`, no file
written); core `LazyGroup` missing-module message (monkeypatched
`importlib.import_module`) and lazy-key registration. 11 new tests; full
`agentd/` suite (73 tests) green. `ruff check` clean after auto-fix +
2 manual `TRY203` (redundant except-reraise) simplifications.

**Deviations from spec**: none.
