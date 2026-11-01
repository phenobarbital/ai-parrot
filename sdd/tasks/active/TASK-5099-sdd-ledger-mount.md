# TASK-5099: `parrot sdd ledger` — lazy re-mount of the `wikitoolkit ledger` group

**Feature**: FEAT-633 — parrot-installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.8, amendment C26 item 4 — proposal rev 0.9)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4091, TASK-5095, TASK-5096 (serialized: both edit `cli.py`)
**Assigned-to**: unassigned

---

## Context

The work ledger (`wikitoolkit ledger open|ready|list|show|claim|acknowledge|close|plan-fix|unclaim|
retract-feedback|context|blockers|export|export-log|import-log|rotate-log|sync|rebuild|ingest-sdd|compact|
audit|outbox prepare|status|integrate`) is part of the SDD cycle but unreachable from `parrot sdd`. C26 item 4
mounts the **same click group object** under `parrot sdd ledger` as a second spelling. Decision (Jesus Lara,
2026-11-01): `wikitoolkit`, `wikitoolkit ledger`, the light entry (TASK-3673), the `parrot-ledger` git hooks
and the MCP tools stay exactly as they are, and the 87 shipped `wikitoolkit ledger` references are **not**
rewritten.

---

## Scope

- Add a lazy proxy group `ledger` to `parrot.sdd.cli` that resolves `parrot.knowledge.wiki.cli:ledger` on
  first use (listing or invoking a subcommand), so `parrot sdd --help` and every other noun never import the
  wiki CLI.
- Tests: `parrot sdd ledger --help` lists exactly the commands `wikitoolkit ledger --help` lists; laziness
  (`parrot.knowledge.wiki.cli` absent from `sys.modules` after `parrot sdd --help`); one round trip
  (`parrot sdd ledger list --json` == `wikitoolkit ledger list --json` on the same temp ledger).

**NOT in scope**: rewriting any `wikitoolkit ledger` reference; changing the ledger commands; the git hooks
`hooks install` renders (Q-C26-2 resolved: they keep `wikitoolkit`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `_LazyProxyGroup` + `ledger` mount |
| `packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py` | CREATE | parity, laziness, round trip |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `feat-FEAT-633-parrot-installer` @ `54868dcb2d` (2026-11-01).

### Verified Imports
```python
import click                                                            # cli.py:12
from parrot.knowledge.wiki.cli import ledger                            # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3272-3274 (`@wiki.group(name="ledger")` / `def ledger() -> None`)
from click.testing import CliRunner                                     # tests/sdd/test_sdd_cli.py:8
from parrot.cli import cli                                              # tests/sdd/test_sdd_cli.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@wiki.group(name="ledger")                                              # :3272
def ledger() -> None: """Manage the SDD work ledger, discovered work, and spec graph."""   # :3273-3274
@ledger.command("open") … @ledger.command("audit")                      # :3277-4106 (21 commands)
@ledger.group("outbox") → @ledger_outbox.command("prepare"|"status"|"integrate")   # :3727, :3775, :3833, :3886
# packages/ai-parrot/src/parrot/cli/__init__.py:124 — `@click.group(cls=LazyGroup)`; "wiki": "parrot.knowledge.wiki.cli" (the heavy module)
# packages/ai-parrot/src/parrot/sdd/cli.py (after TASK-5095): `sdd` group; nouns added by the VERBS loop
# click.Group API used by the proxy: list_commands(ctx) -> list[str]; get_command(ctx, name) -> Command | None
```

### Does NOT Exist
- ~~`parrot.sdd.cli._LazyProxyGroup`~~ — created by this task.
- ~~a `ledger` entry in `VERBS`~~ — the ledger is a group, not a passthrough verb; do not add it to the table (the mount-completeness test only covers `parrot.sdd.scripts` modules).
- ~~`wikitoolkit` depending on `parrot.cli`~~ — the light entry is `parrot.knowledge.wiki.entry:main`; this task does not touch it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger",
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#sdd"
  ]
}
```

---

## Implementation Notes

- **Context objects.** The `wiki` parent group may populate `ctx.obj` (root path, store) that ledger commands
  read. Before writing the proxy, read `parrot/knowledge/wiki/cli.py` around the `wiki` group callback and the
  first ledger command (`open`, :3277) and check whether they use `ctx.obj` / `ctx.parent`. If they do, the
  proxy's `invoke` must call the `wiki` callback (or replicate its minimal setup) before delegating — the round
  trip test is the proof. Record what you found in the Completion Note.
- Delegation only: `list_commands` and `get_command` forward to the real group; the proxy owns no commands.
- `parrot sdd ledger --help` must list the same 22 names (21 commands + `outbox`) as `wikitoolkit ledger --help`.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_LazyProxyGroup` and mount it — *why*: C26 item 4 without importing the wiki CLI on every `parrot sdd`.
2. Write the three tests — *why*: parity, laziness and the context-object question are the three ways this can silently break.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-5095: grep -c '^for _noun, _verbs in VERBS.items():' packages/ai-parrot/src/parrot/sdd/cli.py)
# BEFORE — insert above the `for _noun, _verbs in VERBS.items():` loop
class _LazyProxyGroup(click.Group):
    """A click group that resolves `module:attr` on first use and delegates listing/lookup to it (C26 item 4)."""

    def __init__(self, name: str, target: str, **kwargs: object) -> None:
        super().__init__(name, **kwargs)
        self._target = target
        self._real: click.Group | None = None

    def _resolve(self) -> click.Group:
        if self._real is None:
            module, _, attr = self._target.partition(":")
            self._real = getattr(importlib.import_module(module), attr)
        return self._real

    def list_commands(self, ctx: click.Context) -> list[str]:
        return self._resolve().list_commands(ctx)

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        return self._resolve().get_command(ctx, name)
    # FILL IN: override invoke() ONLY if the ledger commands read ctx.obj set by the `wiki` group callback — bounded by AC-3.


sdd.add_command(
    _LazyProxyGroup("ledger", "parrot.knowledge.wiki.cli:ledger",
                    help="Work ledger (same commands as `wikitoolkit ledger`; both spellings are valid)."),
)
```
**Why this shape**: `parrot.cli` is already a `LazyGroup`, but it lazily loads `parrot.sdd.cli` as a whole; a
plain `add_command(ledger)` here would import `parrot.knowledge.wiki.cli` (4,000+ lines) on every
`parrot sdd …`, which is what TASK-3673's light entry exists to avoid. The proxy keeps that import behind the
`ledger` noun.

### `packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py` (CREATE)
```python
"""C26 item 4: `parrot sdd ledger` is a second spelling of `wikitoolkit ledger` — same commands, lazily loaded."""
from __future__ import annotations

import sys

from click.testing import CliRunner

from parrot.cli import cli


def test_sdd_help_does_not_import_wiki_cli() -> None:
    sys.modules.pop("parrot.knowledge.wiki.cli", None)
    assert CliRunner().invoke(cli, ["sdd", "--help"]).exit_code == 0
    assert "parrot.knowledge.wiki.cli" not in sys.modules


def test_ledger_commands_match_wikitoolkit() -> None:
    from parrot.knowledge.wiki.cli import ledger
    from parrot.sdd.cli import sdd

    ctx = cli.make_context("parrot", ["sdd", "ledger"])
    assert sdd.get_command(ctx, "ledger").list_commands(ctx) == ledger.list_commands(ctx)


def test_ledger_list_round_trip(tmp_path) -> None:
    # FILL IN: initialise a temp ledger the way tests/sdd/test_ledger_lifecycle_acceptance.py does, then assert
    # `parrot sdd ledger list --json` == `wikitoolkit ledger list --json` — bounded by AC-3.
    raise NotImplementedError
```

### FILL IN checklist
- [ ] `ctx.obj` dependency of the ledger commands (see Implementation Notes); bounded by AC-3.
- [ ] round-trip fixture from the existing ledger acceptance test; bounded by AC-3.

---

## Acceptance Criteria
- [ ] AC-1 `parrot sdd ledger --help` lists the same command names as `wikitoolkit ledger --help`.
- [ ] AC-2 `parrot sdd --help` and every non-ledger noun leave `parrot.knowledge.wiki.cli` unimported.
- [ ] AC-3 `parrot sdd ledger list --json` and `wikitoolkit ledger list --json` print the same document on the same ledger.
- [ ] AC-4 No `wikitoolkit ledger` reference anywhere in the repo is changed by this task (`git diff --stat` touches only the two files).

---

## Validation Commands
- `pytest packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Test Specification
```python
# packages/ai-parrot/tests/sdd/test_sdd_ledger_mount.py — see blueprint (three tests).
```

---

## Agent Instructions
- Work inside `.claude/worktrees/feat-FEAT-633-parrot-installer`; `PYTHONPATH=packages/ai-parrot/src`.
- Commit: `feat(parrot-installer): TASK-5099 — parrot sdd ledger re-mounts the wikitoolkit ledger group`.

---

## Completion Note
_(filled by the implementer)_
