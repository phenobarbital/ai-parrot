# TASK-3727: parrot manuals click group (M13)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3703, TASK-3713, TASK-3714, TASK-3720, TASK-3726
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 13** (`cli.py`, `__main__.py`), AC16 and AC22. Operators drive the manuals plane from a **click** group `manuals` (not the contracts argparse CLI — proposal F018): `add`, `add-video`, `refresh`, `verify`, `queue`, `relink-tips`, `export` (curator-only, Q9), `spike {figures,media,video,tips}` (M0). The CLI is a transport like any other: every command builds a trusted operator `RequestContext` from explicit `--user`/`--role`/`--tenant` options and passes the shared `ProcedureRetrieval.authorize` gate (TASK-3720) — write/curator commands with `curator_only=True`. Services come from an **injected** `build_library` factory (contracts `main(factory=)` precedent) so tests never touch Postgres.

Lazy registration in `parrot/cli/__init__.py` and the `manuals` extra are TASK-3728, not here.

Covers spec §4 test `test_cli_export_is_curator_only`; contributes to AC16, AC22.

---

## Scope

- Create `parrot_tools/procedures/cli.py`: click group `manuals` (attribute name **`manuals`** — `LazyGroup.get_command` reads `cmd_name.replace("-", "_")`, `parrot/cli/__init__.py:98-99`), the eight commands, a default `build_library(...)` factory, `_context(...)`, `_run(coro)` (single `asyncio.run` per command).
- Create `parrot_tools/procedures/__main__.py` so `python -m parrot_tools.procedures` runs the group.
- Write `test_cli.py` using `click.testing.CliRunner` with an injected fake factory.

**NOT in scope**: registering `manuals` in `cli._lazy_commands`/`_lazy_extras`, the pyproject extra (TASK-3728); the operator docs (TASK-3729); implementing any library/export/spike behaviour (TASK-3713/3714/3726 — only call them).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/cli.py` | CREATE | click group `manuals` + commands + default factory |
| `packages/ai-parrot-tools/src/parrot_tools/procedures/__main__.py` | CREATE | `python -m parrot_tools.procedures` entrypoint |
| `packages/ai-parrot-tools/tests/procedures/test_cli.py` | CREATE | CliRunner tests with an injected factory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import asyncio, json, logging
from pathlib import Path
from typing import Any, Callable, Optional
import click                                                             # verified: parrot/cli/toolkits.py:14 (click group precedent :26)
from click.testing import CliRunner                                      # tests only; verified: packages/ai-parrot/tests/cli/test_toolkits_cli.py:7
# created by TASK-3720 (packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py)
from parrot_tools.procedures.retrieval import AuthorizationDenied, ProcedureRetrieval, RequestContext
# created by TASK-3703 / 3713 / 3714 / 3726 — import LAZILY inside the default factory / commands
# from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog
# from parrot.knowledge.manuals.library import ManualLibrary
# from parrot.knowledge.manuals.export import export_bundle
# from parrot.knowledge.manuals import spikes
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):
    def get_command(self, ctx, cmd_name):   # line 71-100 — importlib.import_module(module_path); attr = cmd_name.replace("-", "_")
cli._lazy_commands = {                      # line 109 — TASK-3728 adds "manuals": "parrot_tools.procedures.cli"
cli._lazy_extras = {                        # line 139

# packages/ai-parrot/src/parrot/cli/toolkits.py:26 — `@click.group(name="toolkits")` precedent

# packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py — TEMPLATE (argparse; do not import)
def _context(args, tenant_id) -> RequestContext   # line 160-172 — operator identity from explicit --user/--role/--tenant, never from a model
def main(argv=None, *, factory=None)              # line 362-388 — injected service factory; no factory ⇒ explicit error

# created by TASK-3713 — ManualLibrary: add_manual(source, *, equipment, revision, source_uri=None, force=False) -> IngestResult;
#   add_folder(...); add_video(manual_id, *, uri, transcript=None, local_path=None, force=False) -> AlignmentReport;
#   refresh(manual_id, source, *, revision) -> IngestResult; verify_procedure(manual_id, procedure_id, *, user, expected_revision=None)
# created by TASK-3702/3703 — catalog.get(manual_id), catalog.verification_queue(limit=...); PostgresManualCatalog(dsn, *, tenant_id, ...)
# created by TASK-3712 — ManualGraphLoader.publish_all(); tips relink via tips.relink_tips
# created by TASK-3714 — export_bundle(card, *, file_manager, out_dir, include_tips=True, zip_bundle=True, tips=()) -> ExportReport
# created by TASK-3726 — spikes.spike_figures/spike_video/spike_tips/spike_media -> SpikeReport (writes artifacts/logs/FEAT-601/)
```

### Does NOT Exist
- ~~`parrot contracts` click subcommand~~ — contracts is argparse behind `python -m parrot_tools.contracts` (F018); do not model on a click contracts group.
- ~~A default DSN / credentials in code~~ — `--dsn` or env var `GRAPHINDEX_PG_DSN` only (never a hard-coded default).
- ~~Module-level imports of `asyncpg`/`library`~~ — import inside the factory so `parrot manuals --help` works without the DB extras.
- ~~`manuals` already registered in `cli._lazy_commands`~~ — TASK-3728.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/__main__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup.get_command",
    "sym:packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py#main"
  ]
}
```

---

## Implementation Notes

### Decisions fixed here
- Group options (on `manuals`): `--tenant` (required), `--user` (required), `--role` (multiple), `--dsn` (default `$GRAPHINDEX_PG_DSN`), `--storage-root`, `--evidence-root`. The factory is taken from `ctx.obj["factory"]` when present (tests), else the module-level `build_library`.
- Command → gate: `add`, `add-video`, `refresh`, `verify`, `relink-tips`, `export` ⇒ `curator_only=True`; `queue`, `spike` ⇒ `curator_only=True` as well (operator surfaces); nothing in this CLI is a technician read.
- Output: one JSON document per command on stdout (`click.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))`); `AuthorizationDenied` ⇒ `click.ClickException(reason)` (exit code 1).
- `export <manual_id> --out <dir> --zip/--no-zip --include-tips/--no-include-tips` loads the card from the catalog; tips via the graph store only when `--include-tips` (TASK-3714 takes them as an argument).
- `spike {figures,media,video,tips} --corpus <dir>` dispatches to TASK-3726 functions; the report path is printed.
- Single `asyncio.run(...)` per command invocation; always close the catalog (`await catalog.close()`) in `finally`.

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/toolkits.py` — click group style
- `packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py` — operator context + injected factory
- `packages/ai-parrot/tests/cli/test_toolkits_cli.py` — CliRunner test style

---

## Implementation Blueprint

### Steps (in order)
1. Write the factory/context helpers and the group (block 1) — *because* every command needs the same trusted context and factory resolution.
2. Write the ingest commands (block 2) and the curator/export/spike commands (block 3).
3. Write `__main__.py`.
4. Write CliRunner tests with a fake factory; assert a technician context cannot export.

### `packages/ai-parrot-tools/src/parrot_tools/procedures/cli.py` (CREATE) — block 1/3
```python
"""``parrot manuals`` — operator commands for the procedures plane (FEAT-601 M13)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import click

from parrot_tools.procedures.retrieval import AuthorizationDenied, ProcedureRetrieval, RequestContext

logger = logging.getLogger(__name__)


def build_library(*, dsn: str, tenant: str, storage_root: Path, evidence_root: Path, adapter: Any | None) -> Any:
    """Default factory: PostgresManualCatalog + ManualLibrary for ``tenant`` (imports are lazy)."""
    from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog
    from parrot.knowledge.manuals.library import ManualLibrary

    catalog = PostgresManualCatalog(dsn, tenant_id=tenant)
    # FILL IN: file manager (S3FileManager via FileManagerInterface, per tenant config), vision client, graph loader —
    #          bounded by the ManualLibrary.__init__ signature (TASK-3713); no credentials in code
    return ManualLibrary(catalog=catalog, storage_root=storage_root, evidence_root=evidence_root, adapter=adapter,
                         file_manager=None)


def _context(obj: dict[str, Any]) -> RequestContext:
    """Trusted operator context from explicit CLI options — never from a model."""
    return RequestContext(authenticated=True, tenant_id=obj["tenant"], user_id=obj["user"], employee_id=obj["user"],
                          roles=frozenset(obj["roles"]), channel="cli")


def _gate(library: Any, obj: dict[str, Any], *, curator_only: bool = True) -> RequestContext:
    """Run the shared ProcedureRetrieval gate for this operator; raise ClickException on denial."""
    context = _context(obj)
    gate = ProcedureRetrieval(catalog=library.catalog, graph_store=None, tenant_context=None, ontology=None,
                              authorization=None)
    try:
        gate.authorize(context, curator_only=curator_only)
    except AuthorizationDenied as exc:
        raise click.ClickException(exc.reason) from exc
    return context


def _run(obj: dict[str, Any], body: Callable[[Any], Awaitable[Any]]) -> None:
    """Build the library, run ``body`` once under asyncio, print JSON, always close the catalog."""
    factory = obj.get("factory") or build_library

    async def _main() -> Any:
        library = factory(dsn=obj["dsn"], tenant=obj["tenant"], storage_root=obj["storage_root"],
                          evidence_root=obj["evidence_root"], adapter=None)
        try:
            return await body(library)
        finally:
            await library.catalog.close()

    result = asyncio.run(_main())
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@click.group(name="manuals")
@click.option("--tenant", required=True, help="Tenant id.")
@click.option("--user", required=True, help="Authenticated operator id.")
@click.option("--role", "roles", multiple=True, help="Role granted by the deployment (repeatable).")
@click.option("--dsn", default=lambda: os.environ.get("GRAPHINDEX_PG_DSN", ""), help="Postgres DSN.")
@click.option("--storage-root", type=click.Path(path_type=Path), default=Path("manuals_storage"))
@click.option("--evidence-root", type=click.Path(path_type=Path), default=Path("manuals_evidence"))
@click.pass_context
def manuals(ctx: click.Context, tenant: str, user: str, roles: tuple[str, ...], dsn: str, storage_root: Path,
            evidence_root: Path) -> None:
    """Manuals: ingest assembly manuals, align videos, curate procedures."""
    ctx.ensure_object(dict)
    ctx.obj.update(tenant=tenant, user=user, roles=roles, dsn=dsn, storage_root=storage_root,
                   evidence_root=evidence_root)
```

### `cli.py` — block 2/3: ingest commands
```python
@manuals.command("add")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--equipment", multiple=True, required=True)
@click.option("--revision", required=True)
@click.option("--source-uri", default=None)
@click.option("--force", is_flag=True)
@click.pass_obj
def add(obj: dict[str, Any], source: Path, equipment: tuple[str, ...], revision: str, source_uri: Optional[str],
        force: bool) -> None:
    """Ingest one manual (PDF/DOCX) for the given equipment and revision."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        return await library.add_manual(source, equipment=list(equipment), revision=revision, source_uri=source_uri,
                                        force=force)
    _run(obj, body)


@manuals.command("add-video")
@click.argument("url")
@click.option("--manual", "manual_id", required=True)
@click.option("--transcript", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--force", is_flag=True)
@click.pass_obj
def add_video(obj: dict[str, Any], url: str, manual_id: str, transcript: Optional[Path], force: bool) -> None:
    """Align a training video's transcript to a manual's steps."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        data = json.loads(transcript.read_text(encoding="utf-8")) if transcript else None
        return await library.add_video(manual_id, uri=url, transcript=data, force=force)
    _run(obj, body)


@manuals.command("refresh")
@click.argument("manual_id")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--revision", required=True)
@click.pass_obj
def refresh(obj: dict[str, Any], manual_id: str, source: Path, revision: str) -> None:
    """Re-ingest a new manual revision; tips are re-linked and orphans reported."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        return await library.refresh(manual_id, source, revision=revision)
    _run(obj, body)
```

### `cli.py` — block 3/3: curator, export, spike
```python
@manuals.command("verify")
@click.argument("manual_id")
@click.argument("procedure_id")
@click.pass_obj
def verify(obj: dict[str, Any], manual_id: str, procedure_id: str) -> None:
    """Mark a procedure verified (curator)."""
    async def body(library: Any) -> Any:
        context = _gate(library, obj)
        return await library.verify_procedure(manual_id, procedure_id, user=context.user_id)
    _run(obj, body)


@manuals.command("queue")
@click.option("--limit", default=50, show_default=True)
@click.pass_obj
def queue(obj: dict[str, Any], limit: int) -> None:
    """List the curator verification queue."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        return [entry.model_dump(mode="json") for entry in await library.catalog.verification_queue(limit=limit)]
    _run(obj, body)


@manuals.command("relink-tips")
@click.argument("manual_id")
@click.pass_obj
def relink_tips(obj: dict[str, Any], manual_id: str) -> None:
    """Re-run the idempotent tip re-link for one manual."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        # FILL IN: call the library/graph-loader relink entry point (TASK-3712/3713) and return its RelinkReport
        raise NotImplementedError
    _run(obj, body)


@manuals.command("export")
@click.argument("manual_id")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), required=True)
@click.option("--zip/--no-zip", "zip_bundle", default=True)
@click.option("--include-tips/--no-include-tips", default=True)
@click.pass_obj
def export(obj: dict[str, Any], manual_id: str, out_dir: Path, zip_bundle: bool, include_tips: bool) -> None:
    """Write an offline bundle for one manual revision (curator only)."""
    async def body(library: Any) -> Any:
        _gate(library, obj, curator_only=True)
        from parrot.knowledge.manuals.export import export_bundle

        card = await library.catalog.get(manual_id)
        if card is None:
            raise click.ClickException(f"manual {manual_id!r} not found")
        # FILL IN: active tips from the graph when include_tips (else ()) — bounded by AC22
        return await export_bundle(card, file_manager=library.file_manager, out_dir=out_dir,
                                   include_tips=include_tips, zip_bundle=zip_bundle, tips=())
    _run(obj, body)


@manuals.command("spike")
@click.argument("name", type=click.Choice(["figures", "media", "video", "tips"]))
@click.option("--corpus", type=click.Path(exists=True, path_type=Path), required=True)
@click.pass_obj
def spike(obj: dict[str, Any], name: str, corpus: Path) -> None:
    """Run one M0 spike and write its report under artifacts/logs/FEAT-601/."""
    async def body(library: Any) -> Any:
        _gate(library, obj)
        # FILL IN: dispatch to parrot.knowledge.manuals.spikes.spike_<name>(...) with the arguments its signature
        #          requires (TASK-3726); return the SpikeReport — bounded by AC1
        raise NotImplementedError
    _run(obj, body)
```
**Why this shape**: every command is `gate → one library call → JSON`, so the only behaviour here is transport; the gate is the same one the agent path uses (AC9).

### `packages/ai-parrot-tools/src/parrot_tools/procedures/__main__.py` (CREATE)
```python
"""``python -m parrot_tools.procedures`` entrypoint (FEAT-601 M13)."""
from __future__ import annotations

from .cli import manuals

if __name__ == "__main__":  # pragma: no cover - process entrypoint
    manuals(prog_name="python -m parrot_tools.procedures")
```

### `packages/ai-parrot-tools/tests/procedures/test_cli.py` (CREATE)
Start from the Test Specification below.

### FILL IN checklist
- [ ] `build_library` — file manager / vision client / graph loader wiring; bounded by TASK-3713 signature, no secrets
- [ ] `relink-tips` — relink entry point (TASK-3712/3713)
- [ ] `export` — tips source; AC22
- [ ] `spike` — dispatch per TASK-3726 signatures; AC1

---

## Acceptance Criteria

- [ ] `manuals --help` lists `add`, `add-video`, `refresh`, `verify`, `queue`, `relink-tips`, `export`, `spike`.
- [ ] A technician-only operator gets a non-zero exit and the denial reason for `export` (AC22) and for every write command.
- [ ] `export` with a curator role calls `export_bundle` once and prints its report JSON.
- [ ] No DB driver or library module is imported at module import time (`--help` works without `asyncpg`).
- [ ] The group object is importable as `parrot_tools.procedures.cli.manuals`.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_cli.py
from click.testing import CliRunner

from parrot_tools.procedures.cli import manuals

BASE = ["--tenant", "t1", "--user", "op1"]


class FakeLibrary:
    # FILL IN: catalog (tenant_id="t1", async get/verification_queue/close), file_manager, async add_manual/refresh/...
    ...


def _factory(library):
    return lambda **_: library


def test_help_lists_commands():
    result = CliRunner().invoke(manuals, ["--help"])
    for name in ("add", "add-video", "refresh", "verify", "queue", "relink-tips", "export", "spike"):
        assert name in result.output


def test_cli_export_is_curator_only(tmp_path):
    """technician context ⇒ AuthorizationDenied (non-zero exit, reason printed)."""
    lib = FakeLibrary()
    result = CliRunner().invoke(manuals, [*BASE, "--role", "technician", "export", "m1", "--out", str(tmp_path)],
                                obj={"factory": _factory(lib)})
    assert result.exit_code != 0 and "manual_curator" in result.output


def test_cli_export_with_curator_calls_export_bundle(tmp_path, monkeypatch):
    # FILL IN: monkeypatch parrot.knowledge.manuals.export.export_bundle with an AsyncMock returning a report
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3727
- Feature: training-agent
- Implementation SHA: b264c8b56668ffe1a7613b75fe03de2243403a3f
- Closed at (UTC): 2026-09-25T18:23:41+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet(native) - Backend: native - Model: sonnet - Attempts: 1 - Duration: ~626s - Tokens: n/a |
