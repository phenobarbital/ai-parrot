"""``parrot sdd`` — install the SDD flow (commands, agents, rules, templates) into a repository,
and expose its packaged helpers as ``parrot sdd <noun> <verb>`` (C30) inside the venv the launcher resolved."""

from __future__ import annotations

import importlib
import json
from typing import Any
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


@click.group(name="sdd")
def sdd() -> None:
    """Spec-Driven Development flow: install / uninstall / status, <noun> <verb>."""


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
@click.option("--base-branch", "base_branch", default=None, help="SDD base branch to seed and prepare (default: dev).")
@click.option("--push-base", is_flag=True, help="Also `git push -u origin <base-branch>` when origin lacks it.")
@click.option(
    "--hotfix-base",
    "hotfix_base",
    default=None,
    help="Hotfix branch to seed (default: main); required with --base-branch main.",
)
@click.option(
    "--no-dangerous-guard",
    is_flag=True,
    help="Do not register the PreToolUse dangerous-actions guard in .claude/settings.json.",
)
@_dry_run_option
def install(
    path_: Path | None,
    hosts: tuple[str, ...],
    force: bool,
    portable: bool,
    base_branch: str | None,
    push_base: bool,
    hotfix_base: str | None,
    no_dangerous_guard: bool,
    dry_run: bool,
) -> None:
    """Deploy the packaged SDD assets into the repository (upgrades untouched files, keeps your edits)."""
    try:
        _echo_actions(
            install_sdd_integration(
                _root(path_),
                hosts or ("claude",),
                force=force,
                dry_run=dry_run,
                portable=portable,
                base_branch=base_branch,
                push_base=push_base,
                hotfix_base=hotfix_base,
                dangerous_guard=not no_dangerous_guard,
            )
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


#: C30 item 1 — normative command ↔ module map: noun → verb → (module, argv prefix, one-line help).
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {
    "worktree": {
        "ensure": ("ensure_worktree", (), "Create or reuse the feature/hotfix worktree (idempotent)."),
        "status": ("worktree_status", (), "Discover SDD worktrees and report task state and health."),
        "guard": ("worktree_environment", (), "Serve the PreToolUse shared-environment guard (--hook)."),
    },
    "task": {
        "close": ("close_task", (), "Close a task: move it to completed/ and stamp the per-spec index."),
        "finalize": ("finalize_task", (), "Finalize a task from its evidence file."),
        "heal": ("heal_orphans", (), "Re-attach orphaned task files to their per-spec index."),
        "graph": ("check_task_graph", (), "Validate a per-spec index task graph."),
        "state": ("check_task_state", (), "Read-only backstop for stalled task files."),
        "review": ("review_checkpoint", (), "Review checkpoint: prepare | validate."),
    },
    "ids": {
        "reserve": ("reserve_ids", (), "Reserve TASK/FEAT ids on the git-native ledger."),
        "check": ("check_id_collisions", (), "Scan for TASK/FEAT id collisions."),
        "ledger": ("id_ledger", (), "Inspect or bootstrap the TASK/FEAT id counter."),
    },
    "spec": {
        **{
            v: ("spec_tools", (v,), f"spec_tools {v}")
            for v in (
                "init-run",
                "render-brief",
                "stamp-run",
                "validate-suggestions",
                "check-path",
                "commit-intake",
                "existing-feature-id",
            )
        },
        "prune-intake": ("prune_intake", (), "Prune stale /sdd-spec intake staging."),
        "consequences": ("check_spec_consequences", (), "Decision-audit gate for a spec (FEAT-784)."),
    },
    "brief": {v: ("brief_meta", (v,), f"brief_meta {v}") for v in ("plan", "write-index")},
    "docs": {
        **{v: ("sdd_meta", (v,), f"Document flow metadata: {v}") for v in ("parse", "taxonomy", "resolve-flow")},
        "list": ("doc_taxonomy", (), "List SDD docs by projects/tags frontmatter."),
        "backfill": ("backfill_taxonomy", (), "Infer projects frontmatter for existing SDD docs."),
        "migrate-index": ("migrate_index", (), "One-shot monolith → per-spec index migration."),
    },
    "tests": {
        "select": ("select_tests", (), "Select the tests a task/feature must run."),
        "report": ("test_report", (), "Test report: render | decide-rerun."),
        "contract": ("cache_test_contract", (), "Cache a spec's Validation Contract into its index."),
        "e2e-closeout": ("check_e2e_closeout", (), "E2E evidence gate for the closeout surfaces."),
    },
    "closeout": {
        "run": ("run_closeout_hooks", (), "Dispatch /sdd-done closeout hooks."),
        "resolve-issues": ("close_resolved_issues", (), "Close the ledger issues a finished feature fixed."),
    },
    "hooks": {
        "install": ("install_hooks", (), "Install the SDD git hooks."),
        "dangerous-actions": ("dangerous_actions", (), "Serve the PreToolUse dangerous-actions guard (--hook)."),
    },
}
#: Packaged modules with a main() that are deliberately NOT mounted (C22: /sdd-insight does not ship).
# `native_claude_sandbox.main()` serves the `launch-worker` script entry; its CLI is `parrot sdd launch worker`.
_UNMOUNTED: frozenset[str] = frozenset({"native_claude_sandbox"})
_PASSTHROUGH = {"ignore_unknown_options": True, "allow_interspersed_args": False}


def mounted_modules() -> set[str]:
    """Return every ``parrot.sdd.scripts`` module reachable through a verb."""
    return {module for verbs in VERBS.values() for module, _, _ in verbs.values()}


def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None:
    """Mount ``noun verb [args…]`` → ``parrot.sdd.scripts.<module>.main([*prefix, *args])`` (C30 item 2)."""

    @noun.command(name=verb, help=help_, add_help_option=False, context_settings=_PASSTHROUGH)
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def _verb(args: tuple[str, ...]) -> None:
        main = importlib.import_module(f"{_HELPER_PACKAGE}.{module}").main
        try:
            code = main([*prefix, *args])
        except SystemExit as exc:  # the helper's own exit (argparse --help exits 0)
            code = exc.code
        raise click.exceptions.Exit(code if isinstance(code, int) else (0 if code is None else 1))


class _LazyProxyGroup(click.Group):
    """A click group that resolves `module:attr` on first use and delegates listing/lookup to it (C30 item 4).

    The ledger commands read only `ctx.obj["remote"]`, which `remote_aware` fills itself, so no `wiki` group
    callback has to run first and no `invoke()` override is needed.
    """

    def __init__(self, name: str, target: str, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self._target = target
        self._real: click.Group | None = None

    def _resolve(self) -> click.Group:
        if self._real is None:
            module, _, attr = self._target.partition(":")
            self._real = getattr(importlib.import_module(module), attr)
        return self._real

    def list_commands(self, ctx: click.Context) -> list[str]:
        """Forward to the real group."""
        return self._resolve().list_commands(ctx)

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        """Forward to the real group."""
        return self._resolve().get_command(ctx, name)


sdd.add_command(
    _LazyProxyGroup(
        "ledger",
        "parrot.knowledge.wiki.cli:ledger",
        help="Work ledger (same commands as `wikitoolkit ledger`; both spellings are valid).",
    ),
)

from parrot.sdd.launch_cli import launch as _launch  # noqa: E402  light: click only; parrot.flows loads inside

sdd.add_command(_launch)

for _noun, _verbs in VERBS.items():
    _group = sdd.group(name=_noun, help=f"SDD {_noun} helpers.")(lambda: None)
    for _verb, (_module, _prefix, _help) in _verbs.items():
        _mount(_group, _verb, _module, _prefix, _help)
