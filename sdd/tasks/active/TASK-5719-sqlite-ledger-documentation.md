# TASK-5719: Documentation — wiki/wiki/sqlite-ledger-concurrency.md

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5713, TASK-5714, TASK-5715, TASK-5716, TASK-5717, TASK-5718
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes TASK-5713's read_cursor_in/LedgerCursorInvalid, TASK-5714's probe_cursor/sync behavior, TASK-5715's durable cancellation helper, TASK-5716's timing events, TASK-5717's benchmark CLI/schema and TASK-5718's measured report/follow-up. Writes only its page and documentation example smoke test.

## Context

Deliver spec M6 using sdd/templates/techwiki-page.md. Explain the implemented concurrency/durability guarantees and the measured persistent-connection disposition, with an executable asynchronous usage example.

## Scope

- Create the required technical wiki page with all template sections and spec-specific guarantees, recovery, timing, measurement and follow-up sections.
- Document verified public imports/ref links and distinguish SQLite writer serialization, service reuse and actual connection reuse.
- Carry the exact evidence-backed disposition from TASK-5718; link report, manifest and benchmark reproduction.
- Add a narrowly scoped smoke test that executes the page's actual cursor example on a disposable ledger.

**NOT in scope**: No new production symbols, public CLI/MCP changes, undocumented performance claims, production persistent connections or edits to generated reference files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/wiki/sqlite-ledger-concurrency.md` | CREATE | Technical wiki page |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_ledger_documentation.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
from pathlib import Path
import pytest
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.index import LedgerIndex
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24,75: LedgerStore(db_path: str, ...) and read_cursor() -> tuple[int,str | None] exist; TASK-5713 adds LedgerCursorInvalid/read_cursor_in(conn).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10: LedgerLog; TASK-5714 adds probe_cursor(offset,last_event_id).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:129,306: LedgerIndex and sync(conn=None); TASK-5715 adds the internal _append_durably.
- TASK-5716 defines wiki.sqlite.timing/wiki.ledger.stale_read; TASK-5717 supplies the benchmark CLI and TASK-5718 supplies the reports under sdd/state/FEAT-902/benchmarks/.
- sdd/templates/techwiki-page.md supplies Purpose, Public API, Configuration & Parameters, Usage Examples, Gotchas and Related headings.
- Spec docs.api_modules lists parrot.knowledge.wiki.ledger.store, parrot.knowledge.wiki.ledger.log and parrot.knowledge.wiki.ledger.index; reference these modules' actual symbols.
- .parrot/test_runners.toml has no techwiki runner; retain the mandatory documentation CLI gate separately from machine-selected pytest validation.

### Does NOT Exist

- wiki/wiki/sqlite-ledger-concurrency.md and its example test are new.
- Production persistent connections and a new DB backend are out of scope; do not document them as delivered.
- The measurement outcome is not known until TASK-5718 completes.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/wiki/sqlite-ledger-concurrency.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_sqlite_ledger_documentation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Read the delivered implementation and reports — the approved design alone is insufficient to document measured behavior.
2. Populate the technical wiki template with actual reference links and guarantees — preserve explicit cancellation and stale-read limitations.
3. Execute the page's real example in a temporary ledger — this verifies published usage rather than duplicating the implementation tests.
4. Run the documentation gate and inspect its result — a zero exit code with missing-page warnings is not acceptance.

### `wiki/wiki/sqlite-ledger-concurrency.md` (CREATE)

````markdown
---
title: SQLite concurrency for wiki and ledger
summary: Transactional cursor reads, conservative synchronization and durable cancellation.
---

# SQLite concurrency for wiki and ledger

## Purpose
FILL IN: separate wiki.db/ledger.db, connection-per-operation and scope.

## Public API
- [LedgerStore](ref:parrot.knowledge.wiki.ledger.store.LedgerStore)
- [LedgerLog](ref:parrot.knowledge.wiki.ledger.log.LedgerLog)
- [LedgerIndex](ref:parrot.knowledge.wiki.ledger.index.LedgerIndex)
FILL IN: read_cursor_in, LedgerCursorInvalid and probe_cursor references.

## Configuration & Parameters
FILL IN: existing WAL/busy/durability policy; no new runtime settings.

## Usage Examples
Pass the path of an initialized ledger database to this async function.
<!-- feat902:cursor-example -->
```python
from pathlib import Path
from parrot.knowledge.wiki.ledger.store import LedgerStore

async def read_ledger_cursor(db_path: Path) -> tuple[int, str | None]:
    """Read one coherent cursor without changing its transaction lifecycle."""
    store = LedgerStore(str(db_path))
    return await store.read_cursor()
```

## Guarantees
FILL IN: cursor coherence, bounded no-op observation and serialized mutations.

## Failure and recovery
FILL IN: invalid cursor, real DB errors, cancellation drain, replay, crash window.

## Timing and diagnostics
FILL IN: event/phase fields, DEBUG guard, stale warnings and overlapping durations.

## Measurements
FILL IN: revisions, actual results, reproduction and limitations from TASK-5718.

## Persistent-connection follow-up
FILL IN: exact recorded disposition and the evidence supporting it.

## Gotchas
FILL IN: single writer, cross-process contention, schema initialization,
no process-sharing of connections, fsync cancellation delay and no automatic retry.

## Related
- [Measurement report](../../sdd/state/FEAT-902/benchmarks/report.md)
- [Follow-up decision](../../sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md)
````

FILL IN the prose from implemented contracts and recorded results; keep the executable example and all template headings. The example uses an existing LedgerStore and opens no persistent connection.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_ledger_documentation.py` (CREATE)

```python
"""Smoke-test the public asynchronous cursor example published in the wiki."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.ledger.store import LedgerStore

@pytest.mark.asyncio
async def test_published_cursor_example(tmp_path: Path) -> None:
    """Execute the trusted repository page's example on a disposable ledger."""
    root = Path(__file__).resolve().parents[5]
    page = root / "wiki/wiki/sqlite-ledger-concurrency.md"
    # FILL IN: extract ONLY the python block following feat902:cursor-example.
    # Compile/execute that trusted local block in an isolated namespace.
    # Initialize a temporary LedgerStore using ledger_transaction; write a known
    # complete cursor via bound SQL, then await the example with the DB path.
    # Assert its tuple matches the stored cursor and malformed storage propagates
    # LedgerCursorInvalid; use the delivered TASK-5713 behavior.
    # No network, repository ledger access or implementation-source parsing.
    raise NotImplementedError
```

Exercise the literal published code against the delivered ledger API. Do not replace this with a duplicated hand-written example or a check of Markdown wording.

### FILL IN Checklist

- [ ] `wiki/wiki/sqlite-ledger-concurrency.md` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_ledger_documentation.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: The required page follows the technical wiki template and resolves API references to delivered symbols.
- [ ] AC2: Guarantees, lock/cancellation limits, failure/recovery and timing fields match implementation without unmeasured claims.
- [ ] AC3: Measurements and persistent-connection disposition link to the completed report and distinguish service reuse from connection reuse.
- [ ] AC4: The published async cursor example executes successfully against a disposable database; its errors match the cursor contract.
- [ ] AC5: The mandatory techwiki check reports no missing required pages or invalid references/modules; all validation passes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_ledger_documentation.py -q`

## Test Specification

Execute the page's actual marked code block with a temporary initialized ledger and known cursor. Include malformed cursor propagation; do not add a prose snapshot test.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Required Documentation Verification

Run `parrot sdd techwiki check --spec sdd/specs/wiki-ledger-sqlite-hardening.spec.md --root .` and retain its output in task evidence.
Require exit 0 AND an OK result with no missing required page or unresolved declared module;
the checker is advisory and exit 0 alone is insufficient. Inspect reference links and report
links as part of AC1/AC3. This is mandatory in addition to the narrow pytest command.
The runner registry has no techwiki adapter, so this gate is kept outside Validation Commands.

## Agent Instructions

1. Start with `$sdd-start TASK-5719`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.
