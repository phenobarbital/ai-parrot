# TASK-5435: Add ask and doctor command-line workflows

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5431
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Register exact ask and doctor flags from spec §2 on the existing Click group, keeping lazy heavy imports.
- Resolve the adapter through existing helper semantics; show resolved identity on stderr, never contaminate JSON stdout.
- ask delegates with draft_answer=True and renders answer/citations/grounded/stopped/chars_read or the full JSON bundle.
- doctor selects project/global, repairs before relating, and constructs without an LLM unless --relate requests it; --no-llm forces deterministic relation work.
- Use ClickException for library/configuration failures and existing asyncio.run boundary; no extra business logic.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from click.testing import CliRunner  # verified: packages/ai-parrot/tests/knowledge/bookstore/test_cli.py:7
from parrot.knowledge.bookstore.cli import bookstore  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:98
import click  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:20
from parrot.knowledge.bookstore._llm import resolve_adapter  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:42
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:98
def bookstore() -> None:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:33
def _open_bookstore(
    llm_spec: Optional[str] = None,
    require_exists: bool = False,
    scope_needed: Optional[str] = None,
    use_llm: bool = True,
) -> Any:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:42
def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
```


### Dependency-produced contracts

- TASK-5431: consumes Bookstore.doctor; agentic_retrieve is available transitively

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- bookstore ask and bookstore doctor do not exist at the base.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py#_open_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py#resolve_adapter"
  ]
}
```

## Implementation Notes

TASK-5431: consumes Bookstore.doctor; agentic_retrieve is available transitively

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Register exact ask and doctor flags from spec §2 on the existing Click group, keeping lazy heavy imports. **Why**: Both commands expose exact required flags and forward arguments to Bookstore methods.
2. Resolve the adapter through existing helper semantics; show resolved identity on stderr, never contaminate JSON stdout. **Why**: JSON stdout parses as one complete result; model identity and diagnostics use stderr.
3. ask delegates with draft_answer=True and renders answer/citations/grounded/stopped/chars_read or the full JSON bundle. **Why**: doctor --repair resolves/calls no LLM, --relate obeys --no-llm, and default scope is project.
4. doctor selects project/global, repairs before relating, and constructs without an LLM unless --relate requests it; --no-llm forces deterministic relation work. **Why**: Human ask output includes answer, citations and state/cost fields; errors are clear Click failures.
5. Use ClickException for library/configuration failures and existing asyncio.run boundary; no extra business logic. **Why**: Both commands expose exact required flags and forward arguments to Bookstore methods.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'def bookstore() -> None:' packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py)
# Container/attachment anchor: def bookstore() -> None:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:98; merge scoped edits, never replace the whole container.
@bookstore.command("ask")
@click.argument("book_id")
@click.argument("query")
@click.option("--llm", default=None)
@click.option("--budget-chars", type=int, default=None)
@click.option("--max-reads", type=int, default=None)
@click.option("--timeout", "timeout_s", type=float, default=None)
@click.option("--json", "as_json", is_flag=True)
def ask_cmd(book_id: str, query: str, llm: Optional[str], budget_chars: Optional[int],
            max_reads: Optional[int], timeout_s: Optional[float], as_json: bool) -> None:
    """Research one book with cited evidence."""
    # FILL IN: lazy resolution, stderr identity, delegation and rendering; AC-1, AC-2, AC-4.
    raise NotImplementedError

@bookstore.command("doctor")
@click.option("--global", "global_scope", is_flag=True)
@click.option("--repair", is_flag=True)
@click.option("--relate", is_flag=True)
@click.option("--no-llm", is_flag=True)
@click.option("--llm", default=None)
@click.option("--json", "as_json", is_flag=True)
def doctor_cmd(global_scope: bool, repair: bool, relate: bool, no_llm: bool,
               llm: Optional[str], as_json: bool) -> None:
    """Report recovery and drift, optionally repair cards and build missing judgements."""
    # FILL IN: model-free construction unless requested, then delegate/render; AC-1..AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py` (CREATE)

```python
"""Bookstore ask/doctor CLI contracts without live provider calls."""
from click.testing import CliRunner
from parrot.knowledge.bookstore.cli import bookstore

def test_ask_json_and_stderr_identity() -> None:
    """JSON stdout is pure while resolved model identity goes to stderr."""
    # FILL IN: mock library boundary, invoke runner, assert streams/forwarding; AC-1, AC-2.
    raise NotImplementedError

def test_doctor_repair_never_resolves_llm() -> None:
    """Deterministic repair cannot auto-select a coding-agent model."""
    # FILL IN: fail if resolver called, exercise repair/relate/no-llm combinations; AC-3.
    raise NotImplementedError

def test_human_output_and_errors() -> None:
    """Human output includes evidence and clear Click failures."""
    # FILL IN: human and failure fixtures, project/global dispatch; AC-1, AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Both commands expose exact required flags and forward arguments to Bookstore methods.
- [ ] AC-2: JSON stdout parses as one complete result; model identity and diagnostics use stderr.
- [ ] AC-3: doctor --repair resolves/calls no LLM, --relate obeys --no-llm, and default scope is project.
- [ ] AC-4: Human ask output includes answer, citations and state/cost fields; errors are clear Click failures.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_cli.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5435` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Populated by the task finalizer after implementation, validation and the exact implementation commit.
