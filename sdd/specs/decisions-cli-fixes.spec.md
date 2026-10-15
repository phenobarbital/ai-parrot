---
type: feature
base_branch: dev
feature_id: FEAT-675
projects: [ai-parrot]
tags: [wiki, decisions, adr, cli, namespaces]
---

# Feature Specification: Decisions CLI `--ns` write-path verification and single-namespace enforcement

**Feature ID**: FEAT-675
**Date**: 2026-10-15
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:6500603d22d4 (discovered from spec:FEAT-578).

---

## 1. Motivation & Business Requirements

### Problem Statement
FEAT-578 commit `c85837ae4` fixed `wikitoolkit adr ... --ns <foreign>` silently
reading the local plane: `_resolve_scoped_store` now federates and unknown
namespaces raise `ADR_INVALID_ARGUMENT`. `--ns` was added to the write
commands `sync` / `generate` / `review` and to `export`, but only the read
path (`lookup` / `why`) was integration-tested against a live foreign
namespace. The write-command `--ns` behaviour has no end-to-end CLI coverage.

A prototype CLI run against a real local plane plus a registered foreign
namespace (`wikitoolkit ns add other --project <dir>`) confirmed:

- `sync`/`generate`/`review --ns other` are refused with `ADR_INVALID_ARGUMENT`
  (exit 2) before any write — correct.
- `export --ns other` reads the foreign record; `--ns nope` is refused — correct.
- **Defect**: a comma-list selector (`--ns local,other`) is accepted by the
  read commands and broadcasts across namespaces — `why` returns hits from
  both planes, and `export ID --ns local,other` silently returns the LOCAL
  record for an id that also exists in `other`. FEAT-578 spec §2 Module 6
  says read commands accept "one `--ns`" and "lookup/why target one
  namespace per call". For write commands the comma list is refused, but
  with a misleading "foreign namespace has no local root" message.

### Goals
- End-to-end CLI tests (click `CliRunner`, real sqlite planes, a registered
  foreign namespace) for `sync` / `generate` / `review` / `export --ns`.
- Reject a multi-namespace selector (comma list) in `_resolve_scoped_store`
  with `ADR_INVALID_ARGUMENT` for every `adr` command.

### Non-Goals
- The MCP tool surface (`decisions/tools.py` `service_factory`) — tracked
  separately if it shares the comma-list flaw.
- Any change to generic `wiki` `--ns` broadcast semantics (`wiki query`).

---

## 2. Architectural Design

### Overview
A guard in `_resolve_scoped_store`: after the `all` check, strip the selector
and, if it contains a comma, raise
`DecisionError(ADR_INVALID_ARGUMENT, "decisions target exactly one namespace per call ...")`.
Everything else (federation through `_federate`, writable rejection of a
foreign scope) is unchanged.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.wiki.cli._federate` | uses | unchanged |
| `wikitoolkit ns add` | test fixture | registers the foreign namespace |

---

## 3. Module Breakdown

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: single-namespace guard + write-path e2e tests | yes | guard in `_resolve_scoped_store`, error code `ADR_INVALID_ARGUMENT`, exit 2 | — |

### Module 1: `--ns` single-namespace guard and e2e tests
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py`
  (modifies `_resolve_scoped_store`, line 50);
  `packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli_namespace_writes.py` (new)
- **Responsibility**: reject multi-namespace selectors; prove write commands
  never touch a foreign plane and never fall back to the local plane.

---

## 4. Test Specification

### Integration Tests
| Test | Description |
|---|---|
| `test_write_commands_reject_foreign_namespace` | `sync`, `generate`, `review --ns other` → exit 2, `ADR_INVALID_ARGUMENT`, JSON envelope on stderr |
| `test_rejected_review_leaves_both_planes_untouched` | after a refused foreign review, the foreign and local records keep revision 1 / unreviewed |
| `test_write_commands_reject_unknown_namespace` | `--ns nope` → exit 2 with the unknown-namespace message |
| `test_write_commands_accept_explicit_local` | `sync --ns local` succeeds like the default |
| `test_export_reads_the_selected_namespace` | `export ID --ns other` prints the foreign record, default prints the local one |
| `test_multi_namespace_selector_is_rejected` | `why`/`lookup`/`export`/`sync --ns local,other` → exit 2, `ADR_INVALID_ARGUMENT` |

---

## 5. Acceptance Criteria

- [ ] All new tests pass; existing `tests/knowledge/wiki/decisions/` suite passes.
- [ ] `--ns a,b` is rejected with `ADR_INVALID_ARGUMENT` (exit 2) by every `adr` command.
- [ ] Write commands with a foreign `--ns` exit 2 and mutate neither plane.
- [ ] `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.cli import wiki  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1457
from parrot.knowledge.wiki.decisions.models import ADR_INVALID_ARGUMENT, DecisionError  # verified: decisions/cli.py:16
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py
def _resolve_scoped_store(path_: str | None, namespace: str | None, *, writable: bool) -> tuple[BaseWikiStore, Path | None, WikiProjectConfig]:  # line 50
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
def _selected_namespaces(ns_opt: str | None) -> set[str] | None:  # line 182 (splits on ',')
def _federate(root, config, local, ns_opt) -> BaseWikiStore:  # line 205
```

### Does NOT Exist
- ~~`wikitoolkit adr --ns all`~~ support — refused in v1.

### Edit Sites (Blueprint Anchors)
Verified against: 49828eb0c

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py` | MODIFY | `    effective_ns = namespace or "local"` | `cli.py:90` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_cli_namespace_writes.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints
- Tests that invoke the CLI are sync `def` tests (the commands call `asyncio.run`).
- The worktree lacks the Cython `parrot.utils.types` build; run tests from the
  main-checkout venv with `PYTHONPATH=<worktree>/packages/ai-parrot/src` and
  fall back to verifying the decisions module is identical if collection fails.

## 8. Open Questions
- [ ] Does `decisions/tools.py` `service_factory` need the same comma-list guard? — *Owner: maintainer* (out of scope here).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | sdd-fix | Initial draft |
