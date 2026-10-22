# TASK-4349: Enforce single-namespace `--ns` in the adr CLI and e2e-test write-command `--ns`

**Feature**: FEAT-675 — decisions-cli-fixes
**Spec**: `sdd/specs/decisions-cli-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

Resolves ledger issue:6500603d22d4.

---

## Context
Spec §1: write-command `--ns` (sync/generate/review/export) lacks end-to-end
coverage against a live foreign namespace, and a comma-list selector
(`--ns local,other`) is silently accepted as a broadcast by the read commands,
violating FEAT-578 §2 Module 6 (one namespace per call).

---

## Scope
- In `_resolve_scoped_store`, reject a selector containing `,` with
  `DecisionError(ADR_INVALID_ARGUMENT, ...)`; strip surrounding whitespace.
- Create `test_cli_namespace_writes.py` with the six tests in spec §4.

**NOT in scope**: `decisions/tools.py`; generic `wiki --ns` semantics.

---

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py` | MODIFY | single-namespace guard in `_resolve_scoped_store` |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli_namespace_writes.py` | CREATE | end-to-end CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.cli import wiki  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1457
from click.testing import CliRunner
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py:50
def _resolve_scoped_store(path_: str | None, namespace: str | None, *, writable: bool) -> tuple[BaseWikiStore, Path | None, WikiProjectConfig]:
# CLI: wikitoolkit ns add NAME --project DIR --path ROOT  (cli.py:2944)
```

### Does NOT Exist
- ~~`adr --ns all`~~ — refused in v1.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli_namespace_writes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py#_resolve_scoped_store"
  ]
}
```

---

## Acceptance Criteria
- [ ] Every `adr` command refuses `--ns a,b` with `ADR_INVALID_ARGUMENT` (exit 2).
- [ ] `sync`/`generate`/`review --ns <foreign>` exit 2 and mutate neither plane.
- [ ] `export --ns <foreign>` prints the foreign record.
- [ ] New tests and the existing decisions suite pass; `ruff check` clean.

## Validation Commands
```bash
pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli_namespace_writes.py -q
pytest packages/ai-parrot/tests/knowledge/wiki/decisions/ -q
```

## Completion Note
Completed 2026-10-15 (sdd-fix lane, ledger issue:6500603d22d4). Implementing commit c87da7595.

- Write-command `--ns` verified end-to-end with a real local sqlite plane plus a
  second built project registered via `wikitoolkit ns add other --project`:
  `sync`/`generate`/`review --ns other` exit 2 with `ADR_INVALID_ARGUMENT` and
  mutate neither plane; `--ns nope` is refused; `--ns local` writes land only in
  the local plane; `export --ns other` reads the foreign record.
- Defect found and fixed in `_resolve_scoped_store`: a comma-list selector
  (`--ns local,other`) was accepted by `why`/`lookup`/`export` as a broadcast
  (export silently resolved a shared id to the LOCAL record). Now rejected with
  `ADR_INVALID_ARGUMENT` for every `adr` command; the selector is also stripped.
  The 3 multi-selector tests fail on pre-fix code and pass after.
- Tests: `test_cli_namespace_writes.py` 9 passed; decisions suite 244 passed.
  The only failures are `test_backend_parity.py` live Postgres/ArangoDB tests
  (connection refused / env unset) — environmental, pre-existing.
- Follow-up (out of scope, not verified): `decisions/tools.py` `service_factory`
  may accept the same comma-list selector on the MCP surface.
