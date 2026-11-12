---
id: FC-013
query_id: Q011
type: read
intent: "Read parrot self_ CLI to see how subcommands are added (click group, lazy registration)."
executed_at: 2026-11-12T20:42:33Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-013 — `parrot self` is a click group scoped to the managed runtime (~/.parrot), lazily mounted

## Summary

`parrot/self_/cli.py` (132 lines, core ai-parrot) defines `@click.group(name="self") self_group` with commands
`add`, `update`, `doctor`, `env`, `uninstall`; each command lazily imports its implementation module inside the
function body and maps failures to `click.ClickException`/`click.exceptions.Exit(1)`. The module exports
`self = self_group` because the root `LazyGroup` resolves the attribute named after the command. Adding
`parrot self migration` = one more `@self_group.command()` (or a nested `@self_group.group()` for verbs like
status/upgrade) importing a new implementation module. Its docstring defines the group's purpose as managing the
*managed runtime (~/.parrot)* — a DB-schema verb broadens that scope.

## Citations

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 1-19
  symbol: `self_group`
  excerpt: |
    """`parrot self` — manage the parrot-managed runtime (~/.parrot) (FEAT-633, spec §3 M3).
    Registered lazily as ``"self"`` in ``parrot.cli._lazy_commands``; LazyGroup resolves the
    module attribute named ``self`` (cli/__init__.py:99-100), aliased at the bottom.
    @click.group(name="self")
    def self_group() -> None:
        """Manage the parrot-managed runtime (~/.parrot)."""

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 58-84
  symbol: `doctor`
  excerpt: |
    @self_group.command()
    @click.option("--sdd", "sdd_scope", is_flag=True, ...)
    def doctor(sdd_scope: bool, runtime_only: bool) -> None:
        from parrot.self_.doctor import failed, run_doctor
        ...
        if failed(checks):
            raise click.exceptions.Exit(1)

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 131-132
  excerpt: |
    #: LazyGroup lookup name (cli/__init__.py:99-100: getattr(mod, "self")).
    self = self_group

- path: `packages/ai-parrot/src/parrot/self_/`
  excerpt: |
    __init__.py cli.py components.py doctor.py uv.py

## Notes

`doctor` already prints check rows with ✓/✗ and a `fix:` hint — a "pending DB migrations" doctor check would be a
natural companion (mirrors navauth's startup warning). Commands are sync (click); an async runner needs
`asyncio.run` like navauth's `main`. The ai_bots DDL lives in ai-parrot-server while `self_` is core: the core
CLI would have to discover migration sets contributed by installed satellites.
