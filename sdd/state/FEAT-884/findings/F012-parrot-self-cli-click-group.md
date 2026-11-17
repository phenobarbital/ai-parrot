---
id: F012
query_id: Q011, Q004
type: read + wiki_page
intent: "Read parrot self_ CLI to see how subcommands are added (click group, lazy registration). | Read the `parrot self` CLI group page — subcommand registration (lazy), runtime scope (~/.parrot)."
executed_at: 2026-11-12T20:42:33Z
duration_ms: 1800
parent_id: null
depth: 0
merged_from: [FC-013, FW-003]
---

# F012 — `parrot self` is a click group scoped to the managed runtime (~/.parrot), lazily mounted

## Summary

`parrot/self_/cli.py` (132 lines, core ai-parrot) defines `@click.group(name="self") self_group` with commands
`add`, `update`, `doctor`, `env`, `uninstall`; each command lazily imports its implementation module inside the
function body and maps failures to `click.ClickException`/`click.exceptions.Exit(1)`. The module exports
`self = self_group` because the root `LazyGroup` resolves the attribute named after the command. Adding
`parrot self migration` = one more `@self_group.command()` (or a nested `@self_group.group()` for verbs like
status/upgrade) importing a new implementation module. Its docstring defines the group's purpose as managing the
*managed runtime (~/.parrot)* — a DB-schema verb broadens that scope.

`file:packages/ai-parrot/src/parrot/self_/cli.py` (score 0.98; FEAT-633 spec §3 M3) defines `@click.group(name="self")
self_group` — "Manage the parrot-managed runtime (~/.parrot)" — with commands `add` (install a component into the
managed venv), `update` (upgrade ai-parrot + ai-parrot-tools in the managed venv), `doctor` (runtime/host/SDD
readiness checks, exit 1 on failure), `env` (resolved venv + versions; `--init` creates ~/.parrot/env/.env and
~/.parrot/etc/config.ini) and `uninstall`. It is registered lazily as `"self": "parrot.self_.cli"` in
`cli._lazy_commands` (packages/ai-parrot/src/parrot/cli/__init__.py:170-194), and every command imports its
implementation inside the function body. **Scope fit**: today `parrot self` is entirely about the local
install/runtime (venv, uv, Python, PATH, navconfig files) — none of its commands touches a database. navauth's
`self` means "manage this navigator-auth installation", which includes its DB schema; putting a `migration`
verb under parrot's `self` is consistent with that wording but widens the group from "runtime" to
"installation incl. database". Naming: `parrot self update` already exists (runtime upgrade), so the navauth verb
`upgrade` would be confusingly close to it — the requested `migration` avoids that collision.

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

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 48-55
  symbol: `update`
  excerpt: |
    def update(version: str | None) -> None:
        """Upgrade the base runtime (ai-parrot + ai-parrot-tools) in the managed venv."""
        from parrot.self_.components import update_runtime

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 170-194
  symbol: `cli._lazy_commands`
  excerpt: |
    cli._lazy_commands = {
        ...
        "self": "parrot.self_.cli",
        ...
        "sdd": "parrot.sdd.cli",

## Notes

`doctor` already prints check rows with ✓/✗ and a `fix:` hint — a "pending DB migrations" doctor check would be a
natural companion (mirrors navauth's startup warning). Commands are sync (click); an async runner needs
`asyncio.run` like navauth's `main`. The ai_bots DDL lives in ai-parrot-server while `self_` is core: the core
CLI would have to discover migration sets contributed by installed satellites.

`parrot self` lives in the core distribution (ai-parrot); the ai_bots DDL (`creation.sql`) and the Studio migration
runner (F010) live in ai-parrot-server, BotModel in core (F003) — a `parrot self migration` command in core
must find SQL that may ship from a satellite package. `doctor` is a natural place for a read-only
"pending schema migrations" check. Docstring notes LazyGroup resolves the module attribute `self` (cli/__init__.py:99-100).
