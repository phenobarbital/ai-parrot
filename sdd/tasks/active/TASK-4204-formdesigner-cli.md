# TASK-4204: CLI `parrot formdesigner {export | import | translate}` + lazy registration + `click` dependency

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4196, TASK-4199, TASK-4202
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (G4, AC7; codex S7/S11; resolved §8: no `--all-tenants`,
`click` in core deps). Operator doors over the three services without the
HTTP server. The group ships in parrot-formdesigner (`parrot_formdesigner/cli.py`)
and is reached through ai-parrot's `parrot` entry point via one lazy entry in
`cli._lazy_commands` + an install hint in `cli._lazy_extras`. This task is
**exclusive** (`parallel: false`): it edits `packages/parrot-formdesigner/pyproject.toml`
(dependency manifest).

---

## Scope

- `parrot_formdesigner/cli.py`: click group `formdesigner` with `export`, `import` (function `import_surface`), `translate`; `main()` for `python -m`.
- `parrot/cli/__init__.py`: `"formdesigner": "parrot_formdesigner.cli"` in `_lazy_commands`; install hint in `_lazy_extras`.
- `packages/parrot-formdesigner/pyproject.toml`: `click>=8.1.7` in core `dependencies`.
- Tests: `packages/parrot-formdesigner/tests/unit/test_cli.py` (CliRunner) and `packages/ai-parrot/tests/cli/test_formdesigner_lazy.py`.

**NOT in scope**: `--all-tenants` (removed, S7), an HTTP server, `uv lock` (not run inside the worktree).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/cli.py` | CREATE | click group |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | lazy entry + hint |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | `click` dependency |
| `packages/parrot-formdesigner/tests/unit/test_cli.py` | CREATE | CliRunner tests |
| `packages/ai-parrot/tests/cli/test_formdesigner_lazy.py` | CREATE | lazy registration test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                                                      # parrot/cli/toolkits.py:14; ai-parrot pins click>=8.1.7 (pyproject.toml:139)
from parrot_formdesigner.services.a2ui_export import A2UIExportService, ExportedSurface   # TASK-4196
from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui      # TASK-4199
from parrot_formdesigner.extractors import A2UIExtractor                          # TASK-4201 (lazy)
from parrot_formdesigner.services.registry import FormRegistry                    # services/registry.py:240
from parrot_formdesigner.services.storage import PostgresFormStorage              # services/storage.py:69
from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer    # renderers/__init__.py
from parrot_formdesigner.api._utils import _bump_version                          # api/_utils.py:61
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group): get_command() imports _lazy_commands[name]; ImportError → click.ClickException(f"'parrot {cmd}' requires {hint}") when _lazy_extras has a hint and the target module is missing (lines 56-101)
cli._lazy_commands = {... "toolkits": "parrot.cli.toolkits", ...}        # line 117 — anchor `    "toolkits": "parrot.cli.toolkits",`
cli._lazy_extras = {... "manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot[manuals]", }   # line 149 — anchor
# packages/ai-parrot/src/parrot/cli/toolkits.py:26 — `@click.group(name="toolkits")` + `def toolkits()`; LazyGroup resolves `getattr(mod, cmd_name.replace("-","_")) or getattr(mod, cmd_name)` → the group object MUST be named `formdesigner`
# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage(FormStorage): __init__(self, pool=None, dsn: str | None = None, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None, min_size=2, ...)   # 102
    async def initialize(self, *, tenant: str | None = None) -> None   # 349
    async def close(self) -> None                                        # 380
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry: __init__(storage=None, app=None, default_tenant="navigator", require_tenant=True) (275); register(form, *, persist, overwrite, tenant) (466); get (976); load_from_storage (1320)
# packages/parrot-formdesigner/pyproject.toml — core `dependencies = [` block :33-50, last entry `    "aioboto3>=12.0",` (:49)
```

### Does NOT Exist
- ~~`[project.scripts]` in parrot-formdesigner~~ — none, and none is added; the entry point stays `parrot` (ai-parrot).
- ~~`--all-tenants` / `export_all_tenants`~~ — removed (S7).
- ~~`FormStorage.list_tenants()`~~ — not available; tenants are passed explicitly.
- ~~`asyncio.run` re-entrancy inside click callbacks~~ — each command wraps ONE coroutine in `asyncio.run(...)`; no nested loops.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_cli.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/test_formdesigner_lazy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py#PostgresFormStorage",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Exit codes: 0 ok; 1 when any export row failed; 2 config error (missing DSN / missing extra); 3 import conflict without `--overwrite` (spec §3 M7).
- Output via `click.echo` (never `print`); the report file is `export-report.json` `{exported, failed, warnings}`.
- `--dsn` default from env `FORMDESIGNER_DSN`; `translate` needs no DSN.
- Storage lifecycle: `await storage.initialize(tenant=…)` once per tenant, `await storage.close()` in `finally`.

---

## Implementation Blueprint

### Steps (in order)
1. `cli.py` with the group + three commands + `main()` — *why*: S11 (importable standalone).
2. Lazy entry + hint in ai-parrot — *why*: `parrot formdesigner` must fail cleanly when the satellite is absent.
3. `click` in core deps — *why*: resolved §8.
4. Tests with `click.testing.CliRunner`; the ai-parrot test patches `importlib.import_module` to raise `ImportError(name="parrot_formdesigner")`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/cli.py` (CREATE)
```python
"""``parrot formdesigner`` — export / import / translate (FEAT-650, spec §3 M7).

Also runnable standalone: ``python -m parrot_formdesigner.cli``. Services are
imported lazily inside each command so ``--help`` never needs ai-parrot.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

dsn_option = click.option("--dsn", envvar="FORMDESIGNER_DSN", default=None, help="Postgres DSN (env FORMDESIGNER_DSN).")
tenant_option = click.option("--tenant", "tenants", multiple=True, required=True, help="Tenant slug (repeatable).")


@click.group(name="formdesigner")
def formdesigner() -> None:
    """FormDesigner dialect tools (FEAT-650)."""


async def _registry(dsn: str | None, tenant: str):
    """Build (registry, storage) for ONE tenant; caller closes storage. Exit 2 without a DSN."""
    if not dsn:
        raise click.ClickException("a Postgres DSN is required (--dsn or FORMDESIGNER_DSN)")  # exit code 1 by click; see _exit below
    from .services.registry import FormRegistry
    from .services.storage import PostgresFormStorage

    storage = PostgresFormStorage(dsn=dsn, tenant=tenant)
    await storage.initialize(tenant=tenant)
    return FormRegistry(storage=storage, default_tenant=tenant), storage


@formdesigner.command("export")
@click.option("--dialect", type=click.Choice(["a2ui", "json_schema"]), default="a2ui", show_default=True)
@tenant_option
@click.option("--form-uid", "form_uids", multiple=True, help="Restrict to these form_uids (repeatable).")
@click.option("--published-only", is_flag=True, default=False)
@click.option("--locale", default="en", show_default=True)
@click.option("--out", "out_dir", type=click.Path(file_okay=False, path_type=Path), required=True)
@dsn_option
def export(dialect: str, tenants: tuple[str, ...], form_uids: tuple[str, ...], published_only: bool, locale: str,
           out_dir: Path, dsn: str | None) -> None:
    """Write one <form_id>-<form_uid>.<dialect>.json per form plus export-report.json."""
    report = asyncio.run(_export(dialect, tenants, form_uids, published_only, locale, out_dir, dsn))
    (out_dir / "export-report.json").write_text(json.dumps(report, indent=2))
    click.echo(f"exported={report['exported']} failed={report['failed']} → {out_dir}")
    sys.exit(1 if report["failed"] else 0)


async def _export(dialect, tenants, form_uids, published_only, locale, out_dir: Path, dsn) -> dict:
    import uuid

    from .services.a2ui_export import A2UIExportService

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"exported": 0, "failed": 0, "warnings": {}}
    for tenant in tenants:
        registry, storage = await _registry(dsn, tenant)
        try:
            service = A2UIExportService(registry, dialect=dialect, locale=locale)
            uids = [uuid.UUID(u) for u in form_uids] or None
            async for row in service.export_tenant(tenant, form_uids=uids, published_only=published_only):
                # FILL IN: on row.error → report["failed"] += 1 and record; else write out_dir / f"{row.form_id}-{row.form_uid}.{dialect}.json"
                #          with row.envelope and report["exported"] += 1; row.warnings → report["warnings"][row.form_uid] — bounded by AC7
                pass
        finally:
            await storage.close()
    return report


@formdesigner.command("import")
@click.argument("surface", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--tenant", required=True)
@click.option("--form-id", default=None)
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@dsn_option
def import_surface(surface: Path, tenant: str, form_id: str | None, overwrite: bool, dry_run: bool, dsn: str | None) -> None:
    """Extract a createSurface into a FormSchema; persist unless --dry-run (exit 3 on conflict without --overwrite)."""
    code = asyncio.run(_import(surface, tenant, form_id, overwrite, dry_run, dsn))
    sys.exit(code)


async def _import(surface: Path, tenant, form_id, overwrite, dry_run, dsn) -> int:
    from .extractors import A2UIExtractor

    try:
        result = A2UIExtractor().extract(surface.read_text(), form_id=form_id, tenant=tenant)
    except RuntimeError as exc:
        raise click.ClickException(str(exc))  # missing extra → exit 2 (see _exit)
    click.echo(json.dumps({"mode": result.mode.value, "warnings": result.warnings, "dropped": [d.model_dump() for d in result.dropped]}, indent=2))
    if dry_run:
        click.echo(result.form.model_dump_json(indent=2))
        return 0
    # FILL IN: registry/storage via _registry; existing = await registry.get(form.form_uid, tenant); if existing and not overwrite → echo + return 3;
    #          bump version with api._utils._bump_version on overwrite; register(persist=True, overwrite=True, tenant=tenant); close storage — bounded by resolved §8 / TASK-4203 policy
    return 0


@formdesigner.command("translate")
@click.argument("schema_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--from", "source", type=click.Choice(["json_schema"]), default="json_schema", show_default=True)
@click.option("--to", "target", type=click.Choice(["a2ui"]), default="a2ui", show_default=True)
@click.option("--form-id", default=None)
@click.option("--tenant", default=None)
@click.option("--locale", default="en", show_default=True)
@click.option("--out", "out_file", type=click.Path(dir_okay=False, path_type=Path), default=None)
def translate(schema_file: Path, source: str, target: str, form_id, tenant, locale, out_file: Path | None) -> None:
    """JSON Schema → A2UI createSurface (stateless); warnings go to stderr."""
    from .renderers import A2UIFormRenderer
    from .services.a2ui_translate import translate_jsonschema_to_a2ui

    schema = json.loads(schema_file.read_text())
    try:
        rendered = asyncio.run(translate_jsonschema_to_a2ui(schema, form_id=form_id, tenant=tenant, locale=locale, renderer=A2UIFormRenderer()))
    except RuntimeError as exc:
        raise click.ClickException(str(exc))
    for w in rendered.warnings:
        click.echo(f"warning: {w.reason}", err=True)
    text = json.dumps(rendered.content, indent=2)
    out_file.write_text(text) if out_file else click.echo(text)


def main() -> None:
    """Entry for ``python -m parrot_formdesigner.cli``."""
    formdesigner(standalone_mode=True)


if __name__ == "__main__":
    main()
```
**Why this shape**: the group object is literally named `formdesigner` so `LazyGroup.get_command` finds it; every service import is inside a command (`--help` without ai-parrot, AC7); `--tenant` is repeatable and there is no `--all-tenants` (S7). `# FILL IN` on exit code 2: `click.ClickException` exits 1 by default — wrap `main()`/commands so config errors (missing DSN/extra) exit **2**: catch `click.ClickException` in `main()`? No — `LazyGroup` runs the group itself. Decision: raise `click.exceptions.Exit(2)` after `click.echo(msg, err=True)` for the DSN/extra cases instead of `ClickException` (document in the FILL IN checklist).

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "toolkits": "parrot.cli.toolkits",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below `    "toolkits": "parrot.cli.toolkits",` (verified: parrot/cli/__init__.py:117)
    # FEAT-650 — FormDesigner dialect tools, ships in parrot-formdesigner.
    "formdesigner": "parrot_formdesigner.cli",
# occurrences: 1 (verified: grep -c '    "manuals": "ai-parrot-tools: pip install ai-parrot-tools ai-parrot\[manuals\]",' packages/ai-parrot/src/parrot/cli/__init__.py)
# AFTER — insert below the "manuals" hint line in cli._lazy_extras (verified: parrot/cli/__init__.py:149)
    "formdesigner": "parrot-formdesigner: pip install parrot-formdesigner[ai-parrot]",
```
**Why**: `LazyGroup` turns a missing `parrot_formdesigner` into `'parrot formdesigner' requires parrot-formdesigner: ...` (S11) with zero code in the group itself.

### `packages/parrot-formdesigner/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '    "aioboto3>=12.0",' packages/parrot-formdesigner/pyproject.toml)
# AFTER — insert below `    "aioboto3>=12.0",` (last core dependency, verified: pyproject.toml:49)
    "click>=8.1.7",  # FEAT-650: parrot_formdesigner/cli.py (standalone-importable; resolved spec §8 / codex S11)
```

### `packages/parrot-formdesigner/tests/unit/test_cli.py` (CREATE)
```python
"""parrot formdesigner CLI — FEAT-650 TASK-4204."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from parrot_formdesigner.cli import formdesigner


def test_help_without_services():
    r = CliRunner().invoke(formdesigner, ["--help"])
    assert r.exit_code == 0 and "export" in r.output and "import" in r.output and "translate" in r.output


def test_export_requires_dsn(tmp_path):
    r = CliRunner().invoke(formdesigner, ["export", "--tenant", "t", "--out", str(tmp_path)], env={"FORMDESIGNER_DSN": ""})
    assert r.exit_code == 2


def test_export_writes_files_and_report(tmp_path, monkeypatch):
    # FILL IN: monkeypatch parrot_formdesigner.cli._registry to return an in-memory FormRegistry with 2 forms (one failing via a fake
    #          renderer injected through A2UIExportService monkeypatch) and a storage stub with close(); invoke export --tenant t --out tmp;
    #          assert 2 files? (1 ok + report failed=1), exit_code == 1, export-report.json keys — bounded by AC7


def test_import_dry_run_prints_report(tmp_path):
    pytest.importorskip("parrot.outputs.a2ui")
    # FILL IN: write a rendered surface (A2UIFormRenderer) to tmp; invoke import <file> --tenant t --dry-run; exit 0; output JSON has "mode" — bounded by AC7


def test_translate_writes_envelope(tmp_path):
    pytest.importorskip("parrot.outputs.a2ui")
    schema = {"type": "object", "title": "T", "properties": {"a": {"type": "string", "title": "A"}}}
    f = tmp_path / "s.json"; f.write_text(json.dumps(schema))
    r = CliRunner().invoke(formdesigner, ["translate", str(f), "--tenant", "t"])
    assert r.exit_code == 0 and "createSurface" in r.output


def test_python_m_entry():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "parrot_formdesigner.cli", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "formdesigner" in r.stdout.lower()
```

### `packages/ai-parrot/tests/cli/test_formdesigner_lazy.py` (CREATE)
```python
"""parrot formdesigner lazy registration — FEAT-650 TASK-4204."""

from __future__ import annotations

import importlib

import click
import pytest

from parrot.cli import cli


def test_lazy_entry_registered():
    assert cli._lazy_commands["formdesigner"] == "parrot_formdesigner.cli"
    assert "parrot-formdesigner" in cli._lazy_extras["formdesigner"]


def test_missing_satellite_gives_install_hint(monkeypatch):
    def _boom(name, *a, **k):
        if name == "parrot_formdesigner.cli":
            raise ImportError("no", name="parrot_formdesigner")
        return importlib.import_module(name, *a, **k)
    monkeypatch.setattr("parrot.cli.importlib.import_module", _boom)
    with pytest.raises(click.ClickException, match="requires parrot-formdesigner"):
        cli.get_command(None, "formdesigner")
```
**Why this shape**: `--help` without services proves lazy imports; the DSN test pins exit 2; the ai-parrot test pins S11's clean failure.

### FILL IN checklist
- [ ] `cli.py` — exit code 2 for config errors (`click.echo(err=True)` + `click.exceptions.Exit(2)`), replacing the two `ClickException` raises; bounded by §3 M7 exit codes.
- [ ] `cli.py::_export` — row handling/report; bounded by AC7.
- [ ] `cli.py::_import` — persist path with conflict policy; bounded by resolved §8.
- [ ] tests `FILL IN` bodies; bounded by AC7.

---

## Acceptance Criteria

- [ ] `parrot formdesigner export --tenant T [--tenant U] --out DIR` writes one file per form + `export-report.json`; `import` honours `--dry-run`/`--overwrite` (exit 3 on conflict); `translate` writes a validating envelope (AC7).
- [ ] `parrot --help` lists `formdesigner` without importing parrot-formdesigner; with the satellite missing, `parrot formdesigner` fails with the install hint (S11).
- [ ] `click>=8.1.7` is in parrot-formdesigner core `dependencies`; `python -m parrot_formdesigner.cli --help` works.
- [ ] Tests pass; `ruff check` clean on `cli.py` and `parrot/cli/__init__.py`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_cli.py -q`
- `pytest packages/ai-parrot/tests/cli/test_formdesigner_lazy.py -q`
- `pytest packages/ai-parrot/tests/cli/test_commands_context.py -q`

---

## Test Specification

See the CREATE blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M7, §9 S7/S11, `parrot/cli/__init__.py:56-150`
3. **Check dependencies** — TASK-4196, TASK-4199, TASK-4202 `"done"`
4. **Verify the Codebase Contract** — `grep -n '"toolkits": "parrot.cli.toolkits",\|"manuals": ' packages/ai-parrot/src/parrot/cli/__init__.py`; `grep -n 'aioboto3' packages/parrot-formdesigner/pyproject.toml`; `grep -n 'async def initialize\|async def close' packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`; do NOT run `uv sync`/`uv lock` inside the worktree
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the five files
9. **Close** with `scripts/sdd/close_task.sh TASK-4204 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
