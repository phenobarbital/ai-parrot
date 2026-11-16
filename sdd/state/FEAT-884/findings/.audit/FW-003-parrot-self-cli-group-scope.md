---
id: FW-003
query_id: Q004
type: wiki_page
intent: "Read the `parrot self` CLI group page — subcommand registration (lazy), runtime scope (~/.parrot)."
executed_at: 2026-11-12T20:41:06Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FW-003 — `parrot self` is a Click group for the ~/.parrot managed runtime (add/update/doctor/env/uninstall), lazily registered

## Summary

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
  lines: 18-19
  symbol: `self_group`
  excerpt: |
    @click.group(name="self")
    def self_group() -> None:
        """Manage the parrot-managed runtime (~/.parrot)."""

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 48-55
  symbol: `update`
  excerpt: |
    def update(version: str | None) -> None:
        """Upgrade the base runtime (ai-parrot + ai-parrot-tools) in the managed venv."""
        from parrot.self_.components import update_runtime

- path: `packages/ai-parrot/src/parrot/self_/cli.py`
  lines: 61-84
  symbol: `doctor`
  excerpt: |
    def doctor(sdd_scope: bool, runtime_only: bool) -> None:
        """Diagnose the managed runtime, host configs, toolkit requirements and SDD readiness.
        Exit 1 only when a non-informational check in the selected scope fails."""

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

`parrot self` lives in the core distribution (ai-parrot); the ai_bots DDL (`creation.sql`) and the Studio migration
runner (FW-006) live in ai-parrot-server, BotModel in core (FW-004) — a `parrot self migration` command in core
must find SQL that may ship from a satellite package. `doctor` is a natural place for a read-only
"pending schema migrations" check. Docstring notes LazyGroup resolves the module attribute `self` (cli/__init__.py:99-100).
