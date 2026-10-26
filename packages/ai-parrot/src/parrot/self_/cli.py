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
    from parrot.self_.components import update_runtime

    try:
        _echo_log(update_runtime(version))
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc


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
