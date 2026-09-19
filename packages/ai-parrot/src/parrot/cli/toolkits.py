"""`parrot toolkits` — install and manage local MCP toolkit servers (FEAT-570).

Top-level lazy Click group. The `parrot mcp` group is owned by ai-parrot-server,
so core attaches a sibling top-level command instead (precedent: `mcp-local`).

wikitoolkit is deliberately invisible here — it stays owned by `parrot claude install`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

host_option = click.option(
    "--host",
    "hosts_",
    multiple=True,
    type=click.Choice(["claude", "codex", "google"]),
    help="Target host (repeatable). Default: every detected host.",
)
yes_option = click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")


@click.group(name="toolkits")
def toolkits() -> None:
    """Install and manage local MCP toolkit servers."""


def _resolve_hosts(root: Path, hosts_: tuple[str, ...]):
    """Explicit `--host` values, else every detected host."""
    from parrot.mcp.hosts import HostKind, detect_hosts

    return [HostKind(h) for h in hosts_] if hosts_ else detect_hosts(root)


def _resolve_names(root: Path, names: tuple[str, ...], hosts) -> list[str]:
    """Return NAMES, or open the checkbox picker when none were given.

    questionary is BLOCKING and is called synchronously here, never inside async
    code (constraint documented at knowledge/wiki/cli.py:4588-4590).

    Exits 2 with the non-interactive form when stdin is not a TTY — a CI run must
    fail with instructions rather than hang on a picker.
    """
    if names:
        return list(names)
    if not sys.stdin.isatty():
        # click.UsageError (not ClickException) — its exit_code is 2, per AC2.
        raise click.UsageError(
            "No toolkit names given and stdin is not a TTY. "
            "Use the non-interactive form: parrot toolkits install <name>... [--host ...] --yes"
        )
    import questionary

    from parrot.mcp.toolkit_install import ToolkitState, inventory
    from parrot.utils.tty import restore_stdin_blocking

    rows = inventory(root, hosts)
    choices = [
        questionary.Choice(
            title=f"{row.name} — {row.summary}" + ("" if row.dist_available else " (missing distribution)"),
            value=row.name,
            checked=row.state is not ToolkitState.NOT_INSTALLED,
        )
        for row in rows
    ]
    # Without the restore, the click.confirm() that follows reads EOF and aborts.
    with restore_stdin_blocking():
        selected = questionary.checkbox("Select toolkits:", choices=choices).ask()
    return selected or []


def _warn_user_global(hosts) -> list[str]:
    """Warn for any host whose primary config is user-global (Google).

    Spec §8 Q1 interim default (a): Antigravity's `~/.gemini/config/mcp_config.json`
    is shared by every project on the machine, so the blast radius is surfaced
    before the write rather than discovered afterwards.
    """
    from parrot.mcp.hosts import get_adapter

    return [
        f"{kind.value}: writes {get_adapter(kind).config_paths(Path.cwd())[0]} — "
        f"USER-GLOBAL, affects every project on this machine"
        for kind in hosts
        if not get_adapter(kind).is_repo_scoped()
    ]


def _render(report) -> None:
    """Print actions, warnings and per-host failures; exit 1 if every host failed."""
    for action in report.actions:
        click.echo(f"  ✓ {action}")
    for warning in report.warnings:
        click.secho(f"  ⚠ {warning}", fg="yellow")
    for kind, error in report.failed_hosts.items():
        click.secho(f"  ✗ {kind.value}: {error}", fg="red")
    if report.failed_hosts and not report.actions:
        raise SystemExit(1)


@toolkits.command("list")
@host_option
def list_(hosts_: tuple[str, ...]) -> None:
    """Show every available toolkit with its state, hosts, drift and dependencies."""
    from rich.console import Console
    from rich.table import Table

    from parrot.mcp.toolkit_install import inventory

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    rows = inventory(root, hosts)

    table = Table()
    table.add_column("Name")
    table.add_column("State")
    table.add_column("Summary")
    table.add_column("Hosts")
    table.add_column("Deps")
    table.add_column("Drift")

    for row in rows:
        hosts_cell = (
            ", ".join(
                f"{h.host.value}:{'managed' if h.managed else ('foreign' if h.foreign else 'absent')}"
                for h in row.hosts
            )
            or "-"
        )
        deps_cell = ", ".join(row.requires_dist) if row.requires_dist else "-"
        if row.requires_dist and not row.dist_available:
            deps_cell += " (missing)"
        drift_cell = ", ".join(row.drift) if row.drift else "-"
        table.add_row(row.name, row.state.value, row.summary, hosts_cell, deps_cell, drift_cell)

    Console(width=200).print(table)


@toolkits.command()
@host_option
def status(hosts_: tuple[str, ...]) -> None:
    """Show each host's resolved config paths, scope and health."""
    from parrot.mcp.hosts import HostKind, get_adapter

    root = Path.cwd()
    hosts = [HostKind(h) for h in hosts_] if hosts_ else list(HostKind)

    for kind in hosts:
        adapter = get_adapter(kind)
        scope = "repo" if adapter.is_repo_scoped() else "USER-GLOBAL"
        click.echo(f"{kind.value} ({scope}):")
        for path in adapter.config_paths(root):
            state = "present" if path.exists() else "absent"
            click.echo(f"  {path} — {state}")


@toolkits.command()
@click.argument("names", nargs=-1)
@host_option
@yes_option
def install(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
    """Seed NAMES into .parrot/mcp-toolkits.yaml and register them with each host."""
    from parrot.mcp.toolkit_install import install_toolkits

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
    if not selected:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    if not yes and not click.confirm(f"Install {', '.join(selected)} into {[h.value for h in hosts]}?"):
        return
    try:
        report = install_toolkits(root, selected, hosts)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _render(report)
    click.echo("  ℹ Start a new session for the MCP servers to appear.")


@toolkits.command()
@click.argument("names", nargs=-1)
@host_option
@yes_option
def uninstall(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
    """Remove NAMES from .parrot/mcp-toolkits.yaml and deregister them from each host.

    Removes CONFIG ONLY — spec §8 Q2: operator data (scraping plans, db results)
    is never deleted.
    """
    from parrot.mcp.toolkit_install import uninstall_toolkits

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
    if not selected:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    prompt = (
        f"Remove {', '.join(selected)} (config only — operator data is never deleted) from {[h.value for h in hosts]}?"
    )
    if not yes and not click.confirm(prompt):
        return
    report = uninstall_toolkits(root, selected, hosts)
    _render(report)


@toolkits.command()
@click.argument("names", nargs=-1)
@host_option
@yes_option
def enable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
    """Enable NAMES and (re-)register them with each host."""
    from parrot.mcp.toolkit_install import set_toolkits_enabled

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
    if not selected:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    if not yes and not click.confirm(f"Enable {', '.join(selected)} for {[h.value for h in hosts]}?"):
        return
    report = set_toolkits_enabled(root, selected, True, hosts)
    _render(report)


@toolkits.command()
@click.argument("names", nargs=-1)
@host_option
@yes_option
def disable(names: tuple[str, ...], hosts_: tuple[str, ...], yes: bool) -> None:
    """Disable NAMES and deregister them from each host, keeping the section and its kwargs."""
    from parrot.mcp.toolkit_install import set_toolkits_enabled

    root = Path.cwd()
    hosts = _resolve_hosts(root, hosts_)
    selected = _resolve_names(root, names, hosts)
    if not selected:
        click.echo("Nothing selected.")
        return
    for warning in _warn_user_global(hosts):
        click.secho(f"  ⚠ {warning}", fg="yellow")
    if not yes and not click.confirm(f"Disable {', '.join(selected)} for {[h.value for h in hosts]}?"):
        return
    report = set_toolkits_enabled(root, selected, False, hosts)
    _render(report)
