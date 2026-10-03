# TASK-4041: Lazy standup and entity CLI registration with attrs status

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4040, TASK-4033
**Assigned-to**: unassigned

---

## Context

Implement M6 and AC13. Generalize LazyAdrGroup into LazyGroup(import_path, attr) and retain the old alias. The old proxy only delegates get_command/list_commands; that is insufficient for a bare standup command with options. Delegate make_context and invoke to the loaded real Click command as well, while top-level help uses static metadata. Register standup/entity adjacent to existing adr. Define standup/cli.py as a command with every option in spec section 2: --period/--date/--horizon/--team/--me/--language/--json/--no-llm/--out/--no-store/--no-file/--ns/--path/--store/--backend. Reject incompatible --team/--me with Click usage errors. Resolve config/store outside pipeline options and supply effective config plus store for --store/--backend; output clean JSON when requested. Execute async pipeline via existing CLI runner pattern without importing cli from standup/cli.py. Runtime source/model failures exit 0; store open failure exits 1; malformed CLI input remains Click exit 2. Add Attrs line to human status while retaining JSON stats. No top-level imports of entities/standup/entity_cli/decisions.cli; preserve existing ledger costs.

---

## Scope

Implement M6 and AC13. Generalize LazyAdrGroup into LazyGroup(import_path, attr) and retain the old alias. The old proxy only delegates get_command/list_commands; that is insufficient for a bare standup command with options. Delegate make_context and invoke to the loaded real Click command as well, while top-level help uses static metadata. Register standup/entity adjacent to existing adr. Define standup/cli.py as a command with every option in spec section 2: --period/--date/--horizon/--team/--me/--language/--json/--no-llm/--out/--no-store/--no-file/--ns/--path/--store/--backend. Reject incompatible --team/--me with Click usage errors. Resolve config/store outside pipeline options and supply effective config plus store for --store/--backend; output clean JSON when requested. Execute async pipeline via existing CLI runner pattern without importing cli from standup/cli.py. Runtime source/model failures exit 0; store open failure exits 1; malformed CLI input remains Click exit 2. Add Attrs line to human status while retaining JSON stats. No top-level imports of entities/standup/entity_cli/decisions.cli; preserve existing ledger costs.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` | MODIFY | Context and invocation delegation prevent standalone standup options being swallowed by an empty proxy group. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | This task follows the preceding cli.py writer and keeps registrations additive. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py` | CREATE | Click validation remains separate from nonfatal source/model diagnostics. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py` | CREATE | Use CliRunner plus fresh-process sys.modules checks for help and hook. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
import click  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.lazy_commands import LazyGroup  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py; LazyGroup planned in TASK-4041 (not yet present)
from datetime import datetime  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.standup.pipeline import StandupOptions, run  # planned in TASK-4040; not present before that task
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.cli as subject  # planned in TASK-4041; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py:21
class LazyAdrGroup(click.Group):

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2148
def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:583
def _resolve_read_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None = None,
) -> BaseWikiStore:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py#LazyAdrGroup",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_read_store"
  ]
}
```

---

## Implementation Notes

TASK-4040: consumes StandupOptions and run; TASK-4033: consumes entity command group and preceding cli.py edit

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` (MODIFY)

Anchor `class LazyAdrGroup(click.Group):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py:21`.

```python
import click
# Replace the hardcoded lazy class with a generic proxy; keep importlib lazy.
class LazyGroup(click.Group):
    """Load a real Click command/group only when its own command tree is used."""
    def __init__(self, *args: object, import_path: str, attr: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._import_path = import_path
        self._attr = attr
        self._real_group: click.Command | None = None
    def _load_real_group(self) -> click.Command:
        """Import and cache the selected command object."""
        # FILL IN: importlib.import_module plus validated attribute lookup; AC13.
        raise NotImplementedError
    def make_context(self, info_name: str | None, args: list[str], parent: click.Context | None = None, **extra: object) -> click.Context:
        """Parse actual options, including standalone command options."""
        return self._load_real_group().make_context(info_name, args, parent=parent, **extra)
    def invoke(self, ctx: click.Context) -> object:
        """Invoke the real command after lazy context construction."""
        return self._load_real_group().invoke(ctx)
    # FILL IN: typed get_command/list_commands forwarding for real groups;
    # standalone commands have no children. Keep root help import-free; AC13.
class LazyAdrGroup(LazyGroup):
    """Backward-compatible ADR proxy with the existing constructor surface."""
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, import_path="parrot.knowledge.wiki.decisions.cli", attr="adr", **kwargs)
```

**Why**: Context and invocation delegation prevent standalone standup options being swallowed by an empty proxy group.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Anchor `wiki.add_command(` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2347`.

Anchor `        click.echo(f"Env       : {effective.env} ({overlay_label})")` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2155`.

```python
from parrot.knowledge.wiki.lazy_commands import LazyGroup
# Add after the existing ADR registration:
wiki.add_command(LazyGroup(name="standup", import_path="parrot.knowledge.wiki.standup.cli", attr="standup", help="Render a daily or period brief."))
wiki.add_command(LazyGroup(name="entity", import_path="parrot.knowledge.wiki.entity_cli", attr="entity", help="Manage typed wiki entities."))
# In status, after stats is available, emit Attrs count or unsupported in human mode.
# FILL IN: use actual stats/supports_attrs, retaining existing JSON output; AC13.
```

**Why**: This task follows the preceding cli.py writer and keeps registrations additive.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py` (CREATE)

```python
"""Click entry point for the shared standup pipeline."""
from datetime import datetime
from pathlib import Path
import click
from parrot.knowledge.wiki.standup.pipeline import StandupOptions, run

@click.command(name="standup")
@click.option("--period", type=click.Choice(["day", "week", "month"]), default="day")
@click.option("--date", "date_", type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--horizon", type=click.IntRange(1, 90))
@click.option("--team", is_flag=True)
@click.option("--me")
@click.option("--language", type=click.Choice(["en", "es"]))
@click.option("--json", "as_json", is_flag=True)
@click.option("--no-llm", is_flag=True)
@click.option("--out", type=click.Path(path_type=Path))
@click.option("--no-store", is_flag=True)
@click.option("--no-file", is_flag=True)
@click.option("--ns", "namespaces")
@click.option("--path", "path_", type=click.Path(path_type=Path))
@click.option("--store", "store_opt", type=click.Path(path_type=Path))
@click.option("--backend", "backend_opt")
def standup(
    period: str, date_: datetime | None, horizon: int | None, team: bool, me: str | None,
    language: str | None, as_json: bool, no_llm: bool, out: Path | None, no_store: bool,
    no_file: bool, namespaces: str | None, path_: Path | None, store_opt: Path | None,
    backend_opt: str | None,
) -> None:
    """Render a deterministic brief, optionally storing it and adding a model summary."""
    # FILL IN: resolve explicit inputs, execute run, format JSON/Markdown; AC6/8/13.
    raise NotImplementedError
```

**Why**: Click validation remains separate from nonfatal source/model diagnostics.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.cli as subject


def test_cli_option_matrix_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify cli option matrix and status."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_lazy_dispatch_and_import_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify lazy dispatch and import budget."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_exit_codes_and_clean_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify exit codes and clean json."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use CliRunner plus fresh-process sys.modules checks for help and hook.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/lazy_commands.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Bare standup invocation and all documented flags work; JSON is not polluted by human diagnostics.
- [ ] Top-level help and claude-hook import none of the prohibited new modules; entity and adr help/dispatch still work.
- [ ] Attrs status shows count or unsupported; model/source failures retain exit 0 and store-open failure exits 1.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_cli.py -q`
- `pytest tests/knowledge/wiki/test_claude_code.py -q`
- `pytest tests/knowledge/wiki/test_cli_status_sqlite.py -q`

---

## Test Specification

- Bare standup invocation and all documented flags work; JSON is not polluted by human diagnostics.
- Top-level help and claude-hook import none of the prohibited new modules; entity and adr help/dispatch still work.
- Attrs status shows count or unsupported; model/source failures retain exit 0 and store-open failure exits 1.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4041`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
