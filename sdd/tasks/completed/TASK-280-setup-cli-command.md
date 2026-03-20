# TASK-280: Setup CLI Command and Registration

**Feature**: CLI Wizard Setup (FEAT-041)
**Spec**: `sdd/specs/cli-wizard-setup.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-276, TASK-277, TASK-278
**Assigned-to**: claude-session

---

## Context

> Wires the wizard into the `parrot` CLI. Creates the `parrot/setup/cli.py` Click
> command entry point and registers it in the root `parrot/cli.py`.
> Implements spec Section 3 — Modules 4 and 5.

---

## Scope

1. Create `parrot/setup/cli.py` with a `setup` Click command that:
   - Accepts an optional `--force` flag (overwrites existing `app.py`/`run.py`)
   - Instantiates `WizardRunner` and calls `run(force=force)`
   - Handles `KeyboardInterrupt` cleanly
   - Prints a styled completion summary using `click.secho`
2. Modify `parrot/cli.py` to import and register `setup` as a subcommand

**NOT in scope**: `WizardRunner` logic (TASK-276), provider wizards (TASK-277),
scaffolding (TASK-278), tests (TASK-281).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/setup/cli.py` | CREATE | Click command `setup` |
| `parrot/cli.py` | MODIFY | Register `setup` command |

---

## Implementation Notes

### `parrot/setup/cli.py`
```python
"""CLI entry point for the parrot setup wizard."""
import click
from parrot.setup.wizard import WizardRunner


@click.command()
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing app.py and run.py if they exist.",
)
def setup(force: bool) -> None:
    """Interactive first-time setup wizard for AI-Parrot.

    Guides you through:
      - Selecting an LLM provider and entering credentials
      - Writing credentials to the correct .env file
      - Optionally creating an Agent in AGENTS_DIR
      - Optionally generating app.py and run.py bootstrap files

    Run 'parrot setup --force' to overwrite existing app.py / run.py.
    """
    click.echo(click.style("\nWelcome to AI-Parrot Setup", bold=True))
    click.echo("Press Ctrl+C at any time to cancel.\n")

    runner = WizardRunner(force=force)
    try:
        result = runner.run()
    except KeyboardInterrupt:
        click.echo("\nSetup cancelled.")
        return

    # Summary
    click.echo()
    click.secho("Setup complete!", fg="green", bold=True)
    click.echo(f"  Provider  : {result.provider_config.llm_string}")
    click.echo(f"  Env file  : {result.env_file_path}")
    if result.agent_config:
        click.echo(f"  Agent     : {result.agent_config.file_path}")
    if result.app_bootstrapped:
        click.echo("  Generated : app.py, run.py")
    click.echo("\nNext steps:")
    click.echo("  1. Review the .env file and verify your credentials")
    if result.agent_config:
        click.echo(f"  2. Customize {result.agent_config.file_path}")
    click.echo("  3. Run: python run.py")
```

### Modification to `parrot/cli.py`
```python
# Add to existing parrot/cli.py

from parrot.setup.cli import setup   # new import

# Add after existing cli.add_command calls:
cli.add_command(setup, name="setup")
```

### `WizardRunner.__init__` update
The `WizardRunner` in TASK-276 should accept `force: bool = False` in its constructor
and pass it through to `bootstrap_app()`.

### Key Constraints
- The `setup` command docstring becomes the `parrot setup --help` text — keep it
  user-friendly.
- `KeyboardInterrupt` must be caught in the Click command (belt-and-suspenders in
  addition to the runner's own handling) so the user never sees a traceback.
- Do NOT add `--force` to the `WizardRunner.run()` signature — pass it via
  `__init__` to keep `run()` parameter-free for testability.

---

## Acceptance Criteria

- [ ] `parrot setup` is accessible (visible in `parrot --help`)
- [ ] `parrot setup --help` shows provider selection description and `--force` flag
- [ ] `parrot setup --force` passes `force=True` to `bootstrap_app()`
- [ ] `Ctrl+C` during setup prints `"Setup cancelled."` with no traceback
- [ ] Completion summary prints provider, env file, agent file (if created), and
  whether app.py/run.py were generated
- [ ] No changes to existing `parrot mcp`, `parrot autonomous`, `parrot install`,
  `parrot conf` commands
- [ ] Google-style docstrings on `setup` function and module
- [ ] No linting errors: `ruff check parrot/setup/cli.py parrot/cli.py`

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/cli-wizard-setup.spec.md` — Sections 3 Modules 4–5 and 7
2. **Check dependencies** — TASK-276, TASK-277, TASK-278 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** per scope above
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-280-setup-cli-command.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Created `parrot/setup/cli.py` with `@click.command() setup` accepting `--force` flag.
Modified `parrot/cli.py` to import and register `setup`. Verified: `parrot --help` lists setup,
`parrot setup --help` shows `--force` and full description with `\b` to preserve bullet
indentation, `KeyboardInterrupt` exits with "Setup cancelled." and exit code 0, all existing
commands (mcp, autonomous, install, conf) unaffected.
**Deviations from spec**: none
