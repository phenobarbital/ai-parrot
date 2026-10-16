# TASK-4395: `wikitoolkit migrate` command (refusals, exit codes, report)

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md` (§3 Module 12 CLI skeleton, AC26, AC2)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4394
**Assigned-to**: unassigned

---

## Context

TASK-4394 ships the engine (`wiki/migrate.py`). This task adds the single `migrate` command to the `wiki` click
group, right after `export`, mapping options to the engine, owning the checkpoint file location
(`<root>/.parrot/migrate/<plane>.<from>-<to>.json`), the refusals (exit 2, before any write), report printing
(text or `--json`, optional `--report PATH`) and the exit code (0 only when `ok`, 1 otherwise). It never edits
`wiki.json`; it prints the `backend:` switch the operator must make.

AC2 forbids the literal `"helixdb"` in `wiki/cli.py`: every backend name flows from `wiki_backend_names()`
(`_BackendChoice`) and every store is opened through existing registry-driven helpers.

---

## Scope

- Add `@wiki.command("migrate")` after `export` in `wiki/cli.py` with the spec's options:
  `--to` (required, `_BackendChoice`), `--from` (default: configured backend), `--plane [wiki|schema|graphindex|all|ledger|pageindex|bookstore]`
  (default `wiki`; the last three exist only to be refused with the documented alternative), `--tenant`,
  `--batch-size 500`, `--resume`, `--replace`, `--dry-run`, `--allow-partial`, `--sample 50`, `--json`, `--report PATH`.
- Regenerate the CLI surface golden (`UPDATE_GOLDEN=1`).
- Tests `tests/knowledge/wiki/test_migrate_cli.py` (refusals / exit codes / sqlite→sqlite happy path).

**NOT in scope**: engine logic (TASK-4394); docs (TASK-4397); live roundtrip (TASK-4397); `--to` for the ledger.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `migrate` command after `export` |
| `packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json` | MODIFY | regenerated with the new command |
| `packages/ai-parrot/tests/knowledge/wiki/test_migrate_cli.py` | CREATE | CLI refusals + exit codes |

---

## Codebase Contract (Anti-Hallucination)

Verified 2026-10-16 on `dev` @ `1c239a5ca`.

### Verified Imports
```python
# already imported at wiki/cli.py top level:
import click, json, asyncio                                         # cli.py:27-43
from parrot.knowledge.wiki import remote_cli                         # cli.py:104
#   wiki_backend_names                                               # cli.py:117 (in the store import block)
# lazy inside the command (pattern of `export`, cli.py:3916):
from parrot.knowledge.wiki.migrate import (MigrationCheckpoint, MigrationRefused, migrate_graphindex,
                                           migrate_schema_plane, migrate_wiki_plane, open_schema_store,
                                           stats_fingerprint)          # TASK-4394
from parrot.knowledge.wiki.runtime import persistence_for_project       # wiki/runtime.py:34 (async)
from parrot.knowledge.graphindex.factory import make_stub_tenant_context  # graphindex/factory.py:45 (used at cli.py:4049)
from parrot.knowledge.wiki.project import PARROT_DIR                    # project.py:45 (".parrot")
from click.testing import CliRunner                                     # tests
```

### Existing Signatures to Use
```python
# wiki/cli.py
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")   # :157
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]                                  # :386
def _require_built(root: Path, config: WikiProjectConfig) -> BaseWikiStore                                # :476
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore                                   # :483 — arangodb branch, else create_wiki_store(storage, wiki_name, backend=config.backend, sqlite_policy=…)
def _open_sources(root: Path, config: WikiProjectConfig, store=None) -> SourceCollectionManager           # :540 — sqlite / arangodb / json fallback
def _run(coro: Any) -> Any                                                                               # :579 — asyncio.run
class _BackendChoice(click.ParamType)                                                                    # :689 — validates against wiki_backend_names()
@wiki.command() @path_option @click.option("--output", "-o", …) @remote_cli.remote_aware(proxied=False)
def export(path_: str | None, output: str) -> None:                                                      # :3897-3910 (def at :3910)
# SourceCollectionManager._backend — the registry SourceManifestBackend (sources.py:157); no public accessor

# tests/knowledge/wiki/test_cli_surface.py — golden at tests/knowledge/wiki/golden/cli_surface.json;
#   regenerate: UPDATE_GOLDEN=1 pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py
```

### Does NOT Exist
- ~~A `"helixdb"` literal anywhere in `wiki/cli.py`~~ — AC2 grep must stay empty.
- ~~`wikitoolkit reproject`~~ — the refusal message names the projection API (`PageIndexToolkit(helix_settings=…)` re-persist / `Bookstore.reproject(scope)`), not a CLI command.
- ~~A public `SourceCollectionManager.backend_impl`~~ — use `manager._backend` (document the private access with a comment).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_migrate_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#export",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_open_sources",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_BackendChoice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py#persistence_for_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py#make_stub_tenant_context"
  ]
}
```

---

## Implementation Notes

### Decided behaviour
- **Opening stores**: `src_cfg = config.model_copy(update={"backend": from_})`, `dst_cfg = …{"backend": to}`;
  wiki planes via `_open_store(root, cfg)`; schema via `open_schema_store(name, root, config)`; graphindex via
  `await persistence_for_project(cfg, root, tenant_id=tenant)` with `ctx = make_stub_tenant_context(tenant or config.wiki_name)`.
- **Sources**: passed only when both sides are SQLite/ArangoDB-backed managers from `_open_sources`; otherwise the
  part is reported `skipped` with detail "sources manifest not migratable for <backend> from the CLI" (TASK-4392
  drift 4 — `_open_sources` has no helix branch; a follow-up wires it).
- **Refusals (exit 2, before opening a writer)**: `--plane ledger` → message names `wikitoolkit ledger rebuild`;
  `--plane pageindex|bookstore` → names "reproject"; `--to == --from` and same location → refuse; non-empty target
  without `--replace` and stale checkpoint → `MigrationRefused` from the engine, caught → exit 2.
- **Checkpoint**: path `root / PARROT_DIR / "migrate" / f"{plane}.{from_}-{to}.json"`; `--resume` loads it (missing →
  exit 2); without `--resume` a fresh checkpoint with `fingerprint = await stats_fingerprint(source)` (wiki/schema)
  is created; `--dry-run` uses none. The checkpoint file is deleted after an `ok` run.
- **`--plane all`** = wiki, schema, graphindex in that order; overall exit 0 only when every report is `ok`.
- **Output**: text = one line per part `part status source→written/target detail`, then mismatches + lint; `--json`
  prints `[report.model_dump(mode="json"), …]`; `--report PATH` writes the same JSON. Finally echo
  `Set "backend": "<to>" in .parrot/wiki.json to switch.` (never edits it).
- **Exit**: `ok` → 0; not ok → `sys.exit(1)` (`raise SystemExit(1)`); refusals → `raise SystemExit(2)` after
  `click.echo(msg, err=True)`. Use `SystemExit`, not `click.ClickException` (which exits 1).

### Key Constraints
- Closing: close every store / persistence opened (`close()` where defined) in a `finally`.
- Golden: the new command adds exactly the `wiki migrate` entry; regenerate and review the diff (only additions).

---

## Implementation Blueprint

### Steps (in order)
1. Insert the command after `export`. 2. Regenerate the golden. 3. Write CLI tests. 4. Validate + AC2 grep.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'def export(path_: str | None, output: str) -> None:' wiki/cli.py) — line 3910
# AFTER — insert after the END of `export` (its final `click.echo(...)` ending line 3935), before the
#   "# Authoring / persistent-memory commands" banner (line 3938):


@wiki.command("migrate")
@path_option
@click.option("--to", "to", required=True, type=_BackendChoice(), help="Target backend.")
@click.option("--from", "from_", default=None, type=_BackendChoice(), help="Source backend (default: configured).")
@click.option(
    "--plane",
    type=click.Choice(["wiki", "schema", "graphindex", "all", "ledger", "pageindex", "bookstore"]),
    default="wiki",
    show_default=True,
)
@click.option("--tenant", default=None, help="GraphIndex tenant (default: wiki name).")
@click.option("--batch-size", default=500, show_default=True, type=click.IntRange(1, 100_000))
@click.option("--resume", is_flag=True, help="Continue from the checkpoint under .parrot/migrate/.")
@click.option("--replace", is_flag=True, help="Allow writing into a non-empty target.")
@click.option("--dry-run", is_flag=True, help="Count rows only; write nothing.")
@click.option("--allow-partial", is_flag=True, help="Unsupported parts warn instead of failing.")
@click.option("--sample", default=50, show_default=True, type=click.IntRange(0, 10_000))
@click.option("--json", "as_json", is_flag=True, help="Print the report(s) as JSON.")
@click.option("--report", "report", default=None, type=click.Path(dir_okay=False), help="Also write the JSON report here.")
@remote_cli.remote_aware(proxied=False)
def migrate(
    path_: str | None,
    to: str,
    from_: str | None,
    plane: str,
    tenant: str | None,
    batch_size: int,
    resume: bool,
    replace: bool,
    dry_run: bool,
    allow_partial: bool,
    sample: int,
    as_json: bool,
    report: str | None,
) -> None:
    """Copy a plane between two registered backends (pages, edges, attrs, symbols, meta, embeddings, sources;
    schema columns; GraphIndex graph + commit history), resumably, and verify the copy.

    Exit codes: 0 ok · 1 copy finished but not ok · 2 refused before any write.
    """
    if plane == "ledger":
        click.echo("migrate: the ledger is never copied — switch backend and run `wikitoolkit ledger rebuild`.", err=True)
        raise SystemExit(2)
    if plane in ("pageindex", "bookstore"):
        click.echo(f"migrate: {plane} is a projection — reproject it from its canonical files instead.", err=True)
        raise SystemExit(2)
    root, config = _resolve_project(path_)
    source_name = from_ or config.backend
    if source_name == to:
        click.echo(f"migrate: --to {to} equals the source backend; nothing to copy.", err=True)
        raise SystemExit(2)
    planes = ["wiki", "schema", "graphindex"] if plane == "all" else [plane]
    # FILL IN: for each plane: build the checkpoint (path root/PARROT_DIR/"migrate"/f"{p}.{source_name}-{to}.json";
    #   --resume loads it or exits 2; dry-run uses none), open source/target (wiki: _open_store on model_copy'd configs;
    #   schema: open_schema_store; graphindex: persistence_for_project + make_stub_tenant_context), call the engine via
    #   _run(...), catch MigrationRefused → echo + SystemExit(2), close everything in finally, collect reports;
    #   delete the checkpoint after an ok run — bounded by AC26 and the "Decided behaviour" list above
    reports: list[Any] = []
    # FILL IN: print text or JSON, write --report, echo the backend-switch hint, SystemExit(0 if all ok else 1)
```
**Why**: decorator stack and lazy-import style copy `export` (`cli.py:3897-3916`); `_BackendChoice` keeps the
choice list registry-driven (AC2).

### `packages/ai-parrot/tests/knowledge/wiki/golden/cli_surface.json` (MODIFY)
```text
Regenerate, do not hand-edit:
UPDATE_GOLDEN=1 PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py -q
Expected diff: one new "wiki migrate" key with the 14 option strings above (+ "--path"); nothing else changes.
```

### FILL IN checklist
- [ ] `cli.py::migrate` plane loop — bounded by AC26.
- [ ] `cli.py::migrate` output + exit code — bounded by AC26 "exit 0 only when ok".

---

## Acceptance Criteria

- [ ] AC26 (CLI half): the command and all options exist; non-empty target without `--replace` ⇒ exit 2 with no write; `--plane ledger` ⇒ exit 2 naming `wikitoolkit ledger rebuild`; `--plane pageindex|bookstore` ⇒ exit 2 naming reproject; checkpoint under `<root>/.parrot/migrate/`; exit 0 only when `ok`.
- [ ] AC2: `grep -rn '"helixdb"' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` returns nothing.
- [ ] `test_cli_surface.py` passes against the regenerated golden.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_migrate_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_surface.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_migrate_cli.py
"""FEAT-670 M12 CLI — refusals and exit codes (sqlite → sqlite; no HelixDB needed)."""
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki

# fixture: a tmp repo with .parrot/wiki.json (backend sqlite) and a built SQLite plane holding 2 pages —
#   reuse the project-fixture helpers of tests/knowledge/wiki/test_cli.py.


def test_refuses_ledger_plane(tmp_repo):
    result = CliRunner().invoke(wiki, ["migrate", "--path", str(tmp_repo), "--to", "memory", "--plane", "ledger"])
    assert result.exit_code == 2 and "ledger rebuild" in result.output


def test_refuses_projection_planes(tmp_repo): ...          # pageindex + bookstore → exit 2, "reproject"
def test_refuses_same_backend(tmp_repo): ...               # --to sqlite with sqlite configured → exit 2
def test_refuses_non_empty_target_without_replace(tmp_repo): ...   # target pre-seeded → exit 2, target unchanged
def test_dry_run_writes_nothing(tmp_repo): ...             # exit 0, no checkpoint file, target empty
def test_json_report_and_exit_zero(tmp_repo, tmp_path): ...  # --json --report r.json → parseable, ok True, exit 0
def test_resume_without_checkpoint_refused(tmp_repo): ...  # --resume with no file → exit 2
```
(Pick a `--to` target that needs no server, e.g. a second SQLite location via `--from`/`--to` combinations the
registry offers, or `memory`; HelixDB-target CLI coverage is in TASK-4397's live suite.)

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`
2. **Read the spec** §3 M12 CLI skeleton and TASK-4394's shipped `migrate.py`.
3. **Check dependencies** — TASK-4394 `done`.
4. **Verify the Codebase Contract** — re-run the `grep -c -F` on the `export` anchor (FEAT-633 may have moved lines).
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`; regenerate the golden.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, plus the AC2 grep.
8. **Commit the code** — only the three listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4395 helixdb-provider verified`.
10. **Fill in the Completion Note**, then commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
