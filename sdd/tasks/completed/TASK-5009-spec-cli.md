# TASK-5009: `wikitoolkit spec` and `wikitoolkit decisions publish` CLI (M9b)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5008
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces / §3 Module 9 fix four CLI commands:
`wikitoolkit spec governing <spec>`, `wikitoolkit spec consequences render <spec>`,
`wikitoolkit spec consequences check <spec>` and `wikitoolkit decisions publish --batch <id>`. They are the human
and `/sdd-spec` surface over the same wiring the MCP tool and gate script use (`spec_audit.open_consequence_service`,
TASK-5008), so `--json` output must equal the MCP/script report (S11). The commands live in a new module registered
lazily — the same pattern `adr`/`standup`/`entity` use — so ordinary `wikitoolkit` invocations pay no import cost.
**Exclusive** (`parallel: false`): regenerates the shared `cli_surface.json` golden.

---

## Scope

- Create `decisions/spec_cli.py` with click groups `spec` (subgroup `consequences`) and `decisions`.
- Register both lazily in `wiki/cli.py` after the existing `entity` LazyGroup block.
- Exit codes: `consequences check` exits with the report's exit matrix (`pass`/`skipped` 0, `conflict` 1,
  `invalid` 2, `incomplete` 3) and additionally exit 3 when check status is `stale`/`missing` (render is the repair);
  `render` exits with the report's code; `governing` exits 0 unless an operational error; `publish` exits 0 on
  `published`/`already-published`, 1 on `refused`.
- Regenerate `packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json` with `UPDATE_GOLDEN=1`; review the diff.
- Write `test_spec_cli.py`.

**NOT in scope**: the gate script (TASK-5010), MCP (TASK-5008), changes to the existing `adr` group, remote-proxy
support (`remote_cli.remote_aware`) — these commands need a local checkout.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_cli.py` | CREATE | `spec` and `decisions` click groups |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Lazy registration of the two groups |
| `packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json` | MODIFY | Regenerated (UPDATE_GOLDEN=1) |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_cli.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                                                   # used by wiki/cli.py and decisions/cli.py
from click.testing import CliRunner                                            # verified: tests/knowledge/wiki/decisions/test_cli.py:9
from parrot.knowledge.wiki.cli import wiki                                     # verified: tests/knowledge/wiki/decisions/test_cli.py:11
from parrot.knowledge.wiki.lazy_commands import LazyGroup                      # verified: wiki/cli.py:2659 (imported with LazyAdrGroup)
from parrot.knowledge.wiki.decisions.models import DecisionError               # verified: models.py:47
# FEAT-784 earlier tasks:
from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service, is_configured, approvals_path   # TASK-5008
from parrot.knowledge.wiki.decisions.consequences_render import render_spec, check_spec, render_governing       # TASK-5006
from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest                                          # TASK-5001
from parrot.knowledge.wiki.decisions.publish import BatchPublisher                                              # TASK-5007
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py — registration block (verified lines 2659-2683)
from parrot.knowledge.wiki.lazy_commands import LazyAdrGroup, LazyGroup  # noqa: E402  (line 2659)
wiki.add_command(LazyAdrGroup(name="adr", help=...))                      # `        name="adr",` line 2663
wiki.add_command(
    LazyGroup(
        name="entity",
        import_path="parrot.knowledge.wiki.entity_cli",
        attr="entity",                                                    # `        attr="entity",` line 2679 (occurrences 1)
        help="Manage typed wiki entities.",
    )
)                                                                         # block closes at line 2682
# No existing `spec` or `decisions` command/group in wiki/cli.py (verified: grep 'name="spec"\|name="decisions"' → none).

# packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py
class LazyGroup(click.Group):                                             # line 10
    def __init__(self, *args, import_path: str, attr: str, **kwargs)      # line 13

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py — conventions to mirror
EXIT_OK = 0; EXIT_FAILED = 1; EXIT_INVALID_ARGUMENT = 2                   # lines 31-33
def _run(coro): return asyncio.run(coro)                                  # line 154
def _emit_error(exc: DecisionError, as_json: bool) -> int                 # errors to stderr; stdout stays protocol-safe (line 36)

# packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py
GOLDEN = Path(__file__).parent / "golden" / "cli_surface.json"            # line 16; regenerate with UPDATE_GOLDEN=1 (line 36)

# TASK-5008: open_consequence_service(root, *, store=None, config=None, base_branch="dev") -> ConsequenceService;
#           raises DecisionError(ADR_SOURCE_UNAVAILABLE) on an unbuilt wiki
# TASK-5006: render_spec(service, spec_path, *, budget_tokens) -> ConsequenceReport;
#           check_spec(service, spec_path) -> CheckResult(status: current|stale|missing, report)
# TASK-5007: BatchPublisher(store, root, config, service, approvals, adapter).publish(batch_id) -> PublishResult
```

### Does NOT Exist
- ~~`wikitoolkit adr consequences` / `adr publish`~~ — the spec fixes the `spec` and `decisions` groups; do not add to `adr`.
- ~~`LazySpecGroup`~~ — use the generic `LazyGroup` with `import_path`/`attr`.
- ~~`ConsequenceService.publish()`~~ — publication is `BatchPublisher` only.
- ~~remote proxying for these commands~~ — local only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py#LazyGroup",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#wiki",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py#_emit_error"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `--json` prints exactly `report.model_dump(mode="json")` (plus `"check": <status>` for check) — identical to the
  MCP operation `data` (TASK-5008) and the gate script `--json` (TASK-5010); TASK-5015 asserts equality.
- `print` is forbidden outside CLI entry points; use `click.echo`. Errors go to stderr (protocol-safe stdout).
- Deferred imports inside command bodies (the module itself may import click + stdlib only at top level) — the
  `decisions` package import chain is cyclic with `wiki.cli` (decisions/__init__.py:13-22).
- Unconfigured repo: `spec consequences check` prints the one-line note and exits 0 (G8, AC19); `render` makes the
  spec carry the single not-configured line.
- `--path` option = project root (default: cwd), like the `adr` commands; `spec_path` argument is repo-relative.

---

## Implementation Blueprint

### Steps (in order)
1. Create `spec_cli.py` — *why*: keeps `wiki/cli.py` small (its own comment at 2653-2658 says so).
2. Add the lazy registration in `wiki/cli.py`.
3. `UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py -q`; `git diff` the golden — only the new command paths may appear.
4. Write tests; run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/spec_cli.py` (CREATE)
```python
"""``wikitoolkit spec`` / ``wikitoolkit decisions`` — decision-audit CLI (FEAT-784 M9)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

_NOT_CONFIGURED = "decision audit not configured in this repository"


def _root(path_: str | None) -> Path:
    return Path(path_ or ".").resolve()


def _service(root: Path):
    from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service

    return open_consequence_service(root)


def _fail(exc: Exception, as_json: bool) -> None:
    code = getattr(exc, "code", type(exc).__name__)
    message = getattr(exc, "message", str(exc))
    click.echo(json.dumps({"error": {"code": code, "message": message}}) if as_json else f"{code}: {message}", err=True)
    sys.exit(3)  # operational failure is never 0 (AC11)


@click.group(name="spec")
def spec() -> None:
    """Decision audit for SDD specs: governing decisions and consequences."""


@spec.command("governing")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--budget", default=3000, type=int, show_default=True, help="Token budget for the dossier text.")
@click.option("--json", "as_json", is_flag=True, help="Emit the dossier as JSON.")
def spec_governing(spec_path: str, path_: str | None, budget: int, as_json: bool) -> None:
    """Render the governing-decisions dossier to stdout (writes nothing)."""
    # FILL IN: is_configured(root) False ⇒ echo _NOT_CONFIGURED, exit 0; else service.governing + service.evaluate,
    #   echo render_governing(...) or dossier JSON; DecisionError ⇒ _fail — bounded by G1, AC19.
    raise NotImplementedError


@spec.group("consequences")
def consequences() -> None:
    """Render or check the generated ## Governing Decisions / ## Consequences sections."""


@consequences.command("render")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--budget", default=3000, type=int, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def consequences_render(spec_path: str, path_: str | None, budget: int, as_json: bool) -> None:
    """Write both generated sections into the spec; exit with the report's exit code."""
    # FILL IN: unconfigured (is_configured(root) False) ⇒ ensure the spec carries the single not-configured line
    #   WITHOUT building a service (no wiki may exist — G8): reuse TASK-5006's skipped-path helper if it exposes one,
    #   otherwise print _NOT_CONFIGURED and exit 0. Configured ⇒ report = asyncio.run(render_spec(service,
    #   Path(spec_path), budget_tokens=budget)); echo summary or JSON; sys.exit(report.exit_code).
    raise NotImplementedError


@consequences.command("check")
@click.argument("spec_path")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--json", "as_json", is_flag=True)
def consequences_check(spec_path: str, path_: str | None, as_json: bool) -> None:
    """Read-only check; exit matrix pass/skipped 0 · conflict 1 · invalid 2 · incomplete or stale/missing 3."""
    # FILL IN: unconfigured ⇒ _NOT_CONFIGURED, exit 0; else result = asyncio.run(check_spec(...)); JSON payload
    #   = {**result.report.model_dump(mode="json"), "check": result.status}; exit = report.exit_code if
    #   result.status == "current" else max(report.exit_code, 3) — bounded by AC11, AC15.
    raise NotImplementedError


@click.group(name="decisions")
def decisions() -> None:
    """Publish approved decision batches into the decision plane."""


@decisions.command("publish")
@click.option("--batch", "batch_id", required=True, help="Approval batch id from sdd/decisions/approvals.jsonl.")
@click.option("--path", "path_", default=None, help="Project root (default: current directory).")
@click.option("--json", "as_json", is_flag=True)
def decisions_publish(batch_id: str, path_: str | None, as_json: bool) -> None:
    """Publish one approved batch, all-or-nothing (AC12)."""
    # FILL IN: service = _service(root); approvals = ApprovalManifest.load(approvals_path(root));
    #   publisher = BatchPublisher(service.store, root, service.config, service, approvals, service.adapter);
    #   result = asyncio.run(publisher.publish(batch_id)); echo; exit 0 for published/already-published, 1 for refused.
    raise NotImplementedError
```
**Why this shape**: command paths and the exit matrix are fixed by spec §2/§3 M9 and AC11; `_fail` exits 3 so an
operational failure is never confused with `pass`. Group objects are module-level so `LazyGroup(attr=...)` can load them.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        attr="entity",' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py) — line 2679
# AFTER the entity registration block that contains `        attr="entity",` and closes at line 2682:
#     wiki.add_command(
#         LazyGroup(
#             name="entity",
#             import_path="parrot.knowledge.wiki.entity_cli",
#             attr="entity",
#             help="Manage typed wiki entities.",
#         )
#     )
# insert:
wiki.add_command(
    LazyGroup(
        name="spec",
        import_path="parrot.knowledge.wiki.decisions.spec_cli",
        attr="spec",
        help="Decision audit for SDD specs: governing decisions and consequences.",
    )
)
wiki.add_command(
    LazyGroup(
        name="decisions",
        import_path="parrot.knowledge.wiki.decisions.spec_cli",
        attr="decisions",
        help="Publish approved decision batches into the decision plane.",
    )
)
```
**Why**: lazy registration keeps the `claude-hook` fast path import-free (comment at cli.py:2653-2658).

### FILL IN checklist
- [ ] `spec_governing` — unconfigured note, render or JSON; bounded by G1, AC19
- [ ] `consequences_render` — skipped/unconfigured path and exit code; bounded by G8, AC11
- [ ] `consequences_check` — exit mapping incl. stale/missing ⇒ 3; bounded by AC11, AC15
- [ ] `decisions_publish` — wiring + exit; bounded by AC12
- [ ] Golden `cli_surface.json` diff reviewed — only `spec …` and `decisions …` paths added

---

## Acceptance Criteria

- [ ] `wikitoolkit spec --help` and `wikitoolkit decisions --help` list the commands; the `adr` group is unchanged.
- [ ] `spec consequences check` exit codes follow the matrix; `stale`/`missing` ⇒ non-zero.
- [ ] Unconfigured repo: `check` prints the one-line note, exit 0 (AC19).
- [ ] `--json` payload equals `ConsequenceReport.model_dump(mode="json")` (+ `check`).
- [ ] `test_cli_surface.py` passes against the regenerated golden.
- [ ] `ruff check` clean.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_spec_cli.py
import json
import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki

@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()

def test_groups_registered(runner):
    assert runner.invoke(wiki, ["spec", "--help"]).exit_code == 0
    assert "publish" in runner.invoke(wiki, ["decisions", "--help"]).output

def test_check_unconfigured_repo_is_skipped(runner, tmp_path):
    (tmp_path / "s.spec.md").write_text("# S\n\n## 2. Design\n\n## 8. Open Questions\n")
    result = runner.invoke(wiki, ["spec", "consequences", "check", "s.spec.md", "--path", str(tmp_path)])
    assert result.exit_code == 0 and "not configured" in result.output

def test_check_exit_matrix(runner, tmp_path, monkeypatch): ...   # FILL IN — monkeypatch spec_audit.open_consequence_service to a fake returning pass/conflict/invalid/incomplete reports
def test_check_stale_is_nonzero(runner, tmp_path, monkeypatch): ...  # FILL IN
def test_publish_exit_codes(runner, tmp_path, monkeypatch): ...      # FILL IN
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §2 New Public Interfaces, §3 Module 9, AC11, AC15, AC19.
3. Confirm TASK-5008 is `done` (and transitively P10, P11).
4. Verify the Codebase Contract; update first on drift.
5. This task is EXCLUSIVE (shared golden). Implement, regenerate the golden, review the diff.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5009 sdd-decision-audit verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 2 · Duration: 291s · Tokens: n/a

- Delivered files match the task list.
- Merge-tier validation: 226 passed, 1 failed — pre-existing env-gated test_backend_parity_is_reported. No review fixes.
