"""``parrot sdd`` — install the SDD flow (commands, agents, rules, templates) into a repository,
and run its packaged helpers (``parrot sdd run <name>``, Q1) inside the venv the launcher resolved."""

from __future__ import annotations

import json
import pkgutil
import runpy
import sys
from pathlib import Path

import click

from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration, sdd_status, uninstall_sdd_integration

_HELPER_PACKAGE = "parrot.sdd.scripts"
_dry_run_option = click.option("--dry-run", is_flag=True, help="Print the plan and change nothing.")

_path_option = click.option(
    "--path",
    "path_",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Target repository root (default: current directory).",
)
_host_option = click.option(
    "--host",
    "hosts",
    type=click.Choice(SUPPORTED_HOSTS),
    multiple=True,
    help="Assistant host(s) to install for; repeatable (default: claude).",
)


def _root(path_: Path | None) -> Path:
    """Resolve ``--path`` (default cwd) or abort when it is not a directory."""
    root = (path_ or Path.cwd()).resolve()
    if not root.is_dir():
        raise click.ClickException(f"Not a directory: {root}")
    return root


def _echo_actions(actions: list[str]) -> None:
    for action in actions:
        if action.startswith(("warning:", "note:")):
            click.echo(f"  ! {action}", err=True)
        elif action.startswith("plan:"):
            click.echo(f"  · {action}")
        else:
            click.echo(f"  ✓ {action}")


def available_helpers() -> list[str]:
    """Names accepted by ``parrot sdd run``: every module of parrot.sdd.scripts (``sdd_meta`` included —
    TASK-4299 gives it a ``main()``; ``pkgutil`` never lists ``__init__``)."""
    import parrot.sdd.scripts as pkg  # TASK-4085 package; lazy so `parrot --help` stays cheap

    return sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.ispkg)


@click.group(name="sdd")
def sdd() -> None:
    """Spec-Driven Development flow: install / uninstall / status / run."""


@sdd.command()
@_path_option
@_host_option
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite SDD files you edited since parrot wrote them (never foreign files or seeds).",
)
@click.option(
    "--portable",
    is_flag=True,
    help=(
        "Write the bare guard-hook command (needs the global launcher on PATH); default bakes the "
        "installing venv's `parrot` when the launcher is not on PATH."
    ),
)
@_dry_run_option
def install(path_: Path | None, hosts: tuple[str, ...], force: bool, portable: bool, dry_run: bool) -> None:
    """Deploy the packaged SDD assets into the repository (upgrades untouched files, keeps your edits)."""
    try:
        _echo_actions(
            install_sdd_integration(_root(path_), hosts or ("claude",), force=force, dry_run=dry_run, portable=portable)
        )
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@_host_option
@_dry_run_option
def uninstall(path_: Path | None, hosts: tuple[str, ...], dry_run: bool) -> None:
    """Remove SDD files that parrot wrote and you have not edited (seeds and state are kept)."""
    try:
        _echo_actions(uninstall_sdd_integration(_root(path_), hosts or ("claude",), dry_run=dry_run))
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@sdd.command()
@_path_option
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(path_: Path | None, as_json: bool) -> None:
    """Show each SDD asset as current, outdated, edited, foreign or missing per host, plus seeds and state."""
    report = sdd_status(_root(path_))
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    for host, states in report["hosts"].items():
        counts = ", ".join(
            f"{len(states[name])} {name}" for name in ("current", "outdated", "edited", "foreign", "missing")
        )
        click.echo(f"{host}: {counts}")
        for name in ("outdated", "edited", "foreign"):
            for target in states[name]:
                click.echo(f"  {name}: {target}")
    for target, state in report["seeds"].items():
        click.echo(f"seed {target}: {state}")
    for flag in ("config", "gitignore", "id_ledger", "gitattributes", "ledger_hooks"):
        click.echo(f"{flag}: {'yes' if report[flag] else 'no'}")
    guard = report["guard_hook"]
    if guard["form"] is not None:
        click.echo(f"guard hook: {guard['form']} ({'resolvable' if guard['resolvable'] else 'NOT resolvable'})")
    click.echo(f"receipt version: {report['receipt_version'] or 'none'}")


@sdd.command(context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False})
@click.argument("name")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def run(name: str, args: tuple[str, ...]) -> None:
    """Run a packaged SDD helper (e.g. `parrot sdd run reserve_ids --help`) in the venv the launcher resolved.

    This is the only form shipped markdown uses (Q1): `python -m parrot.sdd.scripts.<name>` would
    run whatever `python` is first on PATH, which in a non-Python repo has no ai-parrot.
    """
    helpers = available_helpers()
    if name not in helpers:
        raise click.ClickException(f"unknown helper {name!r}; available: {', '.join(helpers)}")
    sys.argv = [f"{_HELPER_PACKAGE}.{name}", *args]
    try:
        runpy.run_module(f"{_HELPER_PACKAGE}.{name}", run_name="__main__", alter_sys=True)
    except SystemExit as exc:  # the helper's own exit code (argparse --help exits 0)
        raise click.exceptions.Exit(exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)) from exc
