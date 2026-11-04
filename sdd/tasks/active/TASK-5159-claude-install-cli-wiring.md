# TASK-5159: Wire welcome + wizard into `parrot claude install` (CLI flags)

**Feature**: FEAT-799 — `parrot claude install` Welcome Wizard
**Spec**: `sdd/specs/claude-install-welcome-wizard.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5158
**Assigned-to**: unassigned

---

## Context

Implements spec §3 M4: three new options on `install` and the call into
`welcome.py` after the final success `click.secho`.

---

## Scope

- Add `--sandbox-mode [native|legacy]`, `--non-interactive`, `--no-welcome`.
- Wiring rules:
  - `--sandbox-mode` is always honoured (persisted) even with `--no-welcome` — the user asked for it.
  - The wizard prompt only runs when stdin is a TTY and `--non-interactive` is not set
    (`non_interactive = non_interactive or not sys.stdin.isatty()`) — *because* CI pipes
    stdin and a blocking prompt would hang it.
  - `--no-welcome` skips `render_welcome` only; existing `click.echo` lines remain (AC7).
  - `ValueError`/`RuntimeError` from the wizard → `click.ClickException`.
- Append CLI integration tests to `test_welcome.py`.

**NOT in scope**: changes to `install_claude_integration`, `parrot sdd install`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | options + wiring |
| `packages/ai-parrot/tests/knowledge/wiki/test_welcome.py` | MODIFY | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import sys                                   # already imported, cli.py:15
from click.testing import CliRunner          # pattern: tests/knowledge/wiki/test_claude_installer_portable.py:10
from parrot.knowledge.wiki.claude_code.cli import claude   # group, cli.py:50
from parrot.knowledge.wiki.claude_code.welcome import (render_welcome, run_bwrap_diagnostic, sandbox_mode_wizard)  # TASK-5157/5158
```

### Existing Signatures to Use
```python
# cli.py:126-147 — last option then signature
@click.option(
    "--portable/--no-portable",   # line 127
    ...
)
def install(path_, git_hook, gitignore, build_now, bookstore, tool_guards, approve_mcp, compaction,
            typesafe_api_key, plugin_cli, use_remote, remote_url, token_env, portable) -> None:  # line 132
    root = _resolve_root(path_)
    ...
    actions = install_claude_integration(...)   # list[str]
    ...
    click.secho(                                # line 214 — final success line, ends line 217
        "Claude Code integration installed. Try: " ...,
        fg="green",
    )
```
See `test_claude_installer_portable.py:159` for how existing tests invoke `install` with
`CliRunner` and stub the heavy installer.

### Does NOT Exist
- ~~`--sandbox-mode`, `--non-interactive`, `--no-welcome`~~ on `install` — added here
- ~~`--build/--no-build` is NOT the flag name~~ — verify the real build flag name in cli.py's options before using it in tests (param is `build_now`)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_welcome.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#claude"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the three decorators after the `--portable/--no-portable` option (directly above `def install(`).
2. Add the three params to the signature (after `portable`).
3. Append the wiring after the final `click.secho(...)`.
4. Add CLI tests; run validation plus the existing installer CLI tests.

### `cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def install($' cli.py) — insert decorators directly ABOVE `def install(` (cli.py:132)
@click.option(
    "--sandbox-mode",
    type=click.Choice(["native", "legacy"]),
    default=None,
    help="Set the SDD sandbox mode (native or legacy) without prompting.",
)
@click.option("--non-interactive", is_flag=True, default=False, help="Skip interactive prompts.")
@click.option("--no-welcome", is_flag=True, default=False, help="Suppress the rich welcome message.")

# signature: add after `portable: Optional[bool],`
    sandbox_mode: Optional[str],
    non_interactive: bool,
    no_welcome: bool,

# occurrences: 1 (verified: grep -c 'click.secho($' cli.py) — AFTER the closing `)` of that call (cli.py:217)
    from parrot.knowledge.wiki.claude_code.welcome import (
        render_welcome,
        run_bwrap_diagnostic,
        sandbox_mode_wizard,
    )

    interactive_ok = not non_interactive and sys.stdin.isatty()
    try:
        # FILL IN: when no_welcome: only persist a --sandbox-mode preset (wizard with non_interactive=True)
        #          and return; else run diagnostic → wizard → render_welcome — Scope rules, AC6/AC7
        ...
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
```
Also update the `install` docstring with one sentence about the welcome/wizard.

### Tests to append (`test_welcome.py`)
```python
def test_install_cli_non_interactive_flag(tmp_path, monkeypatch): ...  # FILL IN: stub install_claude_integration
    # (monkeypatch cli.install_claude_integration → lambda *a, **k: ["x"]) and welcome.run_bwrap_diagnostic → [];
    # invoke ["install", "--path", str(tmp_path), "--non-interactive", <no-build flag>]; exit_code == 0; no prompt text
def test_install_cli_sandbox_mode_flag(tmp_path, monkeypatch): ...     # FILL IN: "--sandbox-mode native" → pyproject has required
def test_install_cli_no_welcome(tmp_path, monkeypatch): ...            # FILL IN: no "Claude Code Integration Installed" header; "✓ x" still printed
```
Check `_resolve_root` requirements (it may need a `.git` dir / wiki config in `tmp_path`) — copy the fixture setup used by `test_claude_installer_portable.py`.

### FILL IN checklist
- [ ] wiring branch
- [ ] three CLI tests

---

## Acceptance Criteria

- [ ] Spec AC4–AC7, AC9
- [ ] Existing installer CLI tests unchanged and passing
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_welcome.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_claude_installer_portable.py -q`

---

## Agent Instructions

Standard SDD flow; close with `parrot sdd task close TASK-5159 claude-install-welcome-wizard verified`.

---

## Completion Note

*(Agent fills this in when done)*
