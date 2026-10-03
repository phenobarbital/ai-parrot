# TASK-4020: `wikitoolkit lint` CLI command + `wiki_lint` MCP tool

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4019
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (CLI/MCP half), AC1/AC9. Shared files with FEAT-569 (wikitoolkit-http-mcp): verify anchors fresh.

---

## Scope

- Add `@wiki.command("lint")` with the flags from spec §2 'New Public Interfaces'; resolve root/config/store exactly like `status` (incl. Arango connect error → ClickException, no fallback), federate via `_federate(root, config, store, ns_opt)`.
- Hand the source manager to `stale-source`: add an optional `extras: dict[str, Any] | None = None` kwarg to `LintRunner` (lint/runner.py, done by TASK-4010) and seed `ctx.extras` from it; pass `extras={"sources": _open_sources(root, config, store=store)}`.
- Default `export_dir` = config export output (`docs/wiki` when present); default report dir = `config.storage_path(root) / 'lint'`.
- Ledger via `LedgerService.from_root(root)` when `--ledger`.
- Exit code = `LintRunner.exit_code(report, fail_on)`; `--json` prints `report.model_dump_json()`.
- `WikiLintTool` (`wiki_lint`) in tools.py with `args_schema` (rules, skip, fix=False, llm=False); append to the `tools` list in `create_wiki_tools`.

**NOT in scope**: CI wiring and docs (TASK-4021).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | lint command |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | WikiLintTool + registration |
| `packages/ai-parrot/src/parrot/knowledge/lint/runner.py` | MODIFY | optional extras kwarg seeded into LintContext.extras |
| `packages/ai-parrot/tests/knowledge/lint/test_cli_mcp.py` | CREATE | CliRunner + tool registration tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.lint.runner import LintRunner  # TASK-4010
from parrot.knowledge.lint.routing import FindingRouter  # TASK-4018
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: wiki/ledger/service.py:116
```

### Existing Signatures to Use
```python
# wiki/cli.py
path_option = click.option("--path", "path_", default=None, help=...)   # :138
ns_option = click.option(...)                                           # :142
def _federate(...)                                                      # :194
def _resolve_project_effective(path: str | None) -> tuple[Path, WikiEffectiveConfig]  # :392
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore  # :464
def _open_sources(...)                                                  # :521
def _run(coro: Any) -> Any                                              # :560
@wiki.command() @path_option @ns_option ... def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None  # :2144-2148 (template for root/config/store/arango/sources/federate)
# wiki/tools.py
class WikiStatusTool(AbstractTool): name/description/args_schema; __init__(self, store); async _execute(self) -> ToolResult  # :514-527
def create_wiki_tools(store, root=None, config=None, ledger_service=None) -> list[AbstractTool]  # :807 ; `tools = [` :830 ; `return tools` :851
```

### Does NOT Exist
- ~~`wikitoolkit lint` command~~ / ~~`wiki_lint` MCP tool~~ — created by TASK-4020
- ~~a `--backend` option helper~~ — FILL IN: check whether cli.py has a shared backend option (`grep -n backend_opt wiki/cli.py`) before adding one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/runner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_cli_mcp.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#WikiStatusTool"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep anchors first — *why*: FEAT-569 may have moved cli.py/tools.py.
2. Mirror `status`'s store bootstrap verbatim — *why*: Arango fail-fast rule (spec §7).
3. Add `extras: dict[str, Any] | None = None` to `LintRunner.__init__` and copy into `ctx.extras` in `run()` — *why*: CLI must hand the source manager to `stale-source`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None:' wiki/cli.py)
# INSERT the new command ABOVE the `@wiki.command()` decorator line preceding `def status(` (verified: wiki/cli.py:2144-2148)
@wiki.command("lint")
@path_option
@ns_option
@click.option("--rules", default=None, help="Comma-separated rule ids or packs (plane,export,adr,memory,llm).")
@click.option("--skip", multiple=True, help="Rule id to skip (repeatable).")
@click.option("--fix", is_flag=True, help="Apply safe, idempotent fixes (never deletes).")
@click.option("--llm", is_flag=True, help="Run the opt-in LLM contradiction pass.")
@click.option("--llm-model", default=None, help="LLM spec; else WIKI_LINT_LLM / WIKI_EXTRACT_LLM.")
@click.option("--llm-max-pairs", default=50, show_default=True, type=int)
@click.option("--report", "report_fmt", type=click.Choice(["json", "md"]), default="md", show_default=True)
@click.option("--output", default=None, help="Report directory (default: <storage>/lint).")
@click.option("--ledger/--no-ledger", default=True, show_default=True)
@click.option("--notes/--no-notes", default=True, show_default=True)
@click.option("--fail-on", type=click.Choice(["error", "warning", "none"]), default="error", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit the report as JSON.")
def lint(path_, ns_opt, rules, skip, fix, llm, llm_model, llm_max_pairs, report_fmt, output, ledger, notes, fail_on, as_json) -> None:
    """Lint the wiki graph, export, memories and ADRs; --fix applies safe fixes."""
    from parrot.knowledge.lint import LintOptions, LintRunner
    from parrot.knowledge.lint.routing import FindingRouter

    root, effective = _resolve_project_effective(path_)
    config = effective.config
    if not config.is_built(root):
        raise click.ClickException(f"Wiki not built for {root} — run `wikitoolkit build`.")
    # FILL IN: store/arango/sources/federate exactly as status (cli.py:2161-2175);
    #          options = LintOptions(...); router = FindingRouter(read_store, report_dir=..., ledger=LedgerService.from_root(root) if ledger else None)
    #          report = _run(LintRunner(read_store, root=root, config=config, router=router, extras={"sources": sources}).run(options))
    #          print summary or JSON; sys.exit(LintRunner.exit_code(report, None if fail_on == "none" else fail_on))
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    tools = \[' wiki/tools.py)
# (a) INSERT the class ABOVE `def create_wiki_tools(` (verified: wiki/tools.py:807)
class WikiLintInput(BaseModel):
    """Arguments for wiki_lint."""

    rules: list[str] | None = Field(default=None, description="Rule ids or packs to run (default: all deterministic).")
    skip: list[str] = Field(default_factory=list, description="Rule ids to skip.")
    fix: bool = Field(default=False, description="Apply safe, idempotent fixes (never deletes).")
    llm: bool = Field(default=False, description="Run the opt-in LLM contradiction pass.")


class WikiLintTool(AbstractTool):
    """Lint the wiki knowledge graph and report broken links, duplicate slugs, stale memories and ADR conflicts."""

    name = "wiki_lint"
    description = "Lint the wiki knowledge graph: broken links, duplicate slugs, stale memories, ADR conflicts; fix=true applies safe fixes."
    args_schema = WikiLintInput

    def __init__(self, store: BaseWikiStore, storage_dir: Path | None = None):
        super().__init__(name=self.name, description=self.description)
        self._store = store
        self._storage_dir = storage_dir

    async def _execute(self, rules: list[str] | None = None, skip: list[str] | None = None, fix: bool = False, llm: bool = False) -> ToolResult:
        # FILL IN: LintRunner(self._store, router=FindingRouter(self._store, report_dir=storage_dir/"lint")).run(LintOptions(...));
        #          return ToolResult(result={"counts": report.counts, "fixed": len(report.fixed), "top": [...first 20 findings...], "report_dir": ...})
        raise NotImplementedError

# (b) APPEND `WikiLintTool(store, storage_dir=storage_dir),` inside the `tools = [` literal (verified: wiki/tools.py:830)
```

### `packages/ai-parrot/src/parrot/knowledge/lint/runner.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-4010: grep -c 'router: Router | None = None,' lint/runner.py)
# AFTER `        router: Router | None = None,` add:
        extras: dict[str, Any] | None = None,
# and in __init__: self._extras = dict(extras or {})
# and in run(), right after `ctx = LintContext(...)`: ctx.extras.update(self._extras)
# and in LintContext.invalidate callers: re-seed self._extras after ctx.invalidate() (FILL IN: invalidate clears extras)
```

**Why this shape**: AC1 — a default run must not change pages/edges; page notes are routing writes, so the AC1 test runs with `--no-notes --no-ledger` and compares store hashes. AC9 — `wiki_lint` is registered through `create_wiki_tools`. The store bootstrap is copied from `status` so ArangoDB fails fast instead of falling back (spec §7).

### FILL IN checklist
- [ ] store bootstrap copy
- [ ] summary printing
- [ ] MCP _execute
- [ ] extras re-seed after invalidate

---

## Acceptance Criteria

- [ ] `wikitoolkit lint --no-notes --no-ledger` leaves store hashes unchanged (AC1)
- [ ] Exit 1 on an error finding with default --fail-on
- [ ] `wiki_lint` in `create_wiki_tools` output (AC9)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_cli_mcp.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_cli_mcp.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_cli_mcp.py
from click.testing import CliRunner


def test_cli_lint_json(tmp_path): ...  # FILL IN: build a fixture plane in tmp_path; invoke wiki ["lint", "--path", str(tmp_path), "--json", "--no-ledger", "--no-notes"]
def test_wiki_lint_tool_registered(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4020 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
