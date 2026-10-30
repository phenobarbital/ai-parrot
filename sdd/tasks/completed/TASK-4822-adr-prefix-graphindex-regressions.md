# TASK-4822: GraphIndex prefix labels, stable IDs and CLI regressions

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4819
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement the GraphIndex part of M5: pin real citation nodes, both scanning paths, unchanged unconfigured IDs and production config propagation.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py` | MODIFY | Extractor labels, IDs and RFC compatibility |
| `packages/ai-parrot/tests/knowledge/graphindex/test_cli.py` | MODIFY | Production config wiring and per-root isolation |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import json  # existing test_cli.py:8
from pathlib import Path  # existing test_cli.py:9
import pytest  # both suites
from parrot.knowledge.graphindex import cli  # test_cli.py:13
from parrot.knowledge.graphindex.extractors.code import CodeExtractor  # test_graphify_parity.py:17
```

### Existing Signatures to Use

- `packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py`: `_extract(src: str)` uses CodeExtractor; `TestCitationExtraction` covers titles, edges and dedup.
- `packages/ai-parrot/tests/knowledge/graphindex/test_cli.py`: `TestBuildCodeGraph` calls async build_code_graph and inspects graph.json `nodes[*].name`.
- TASK-4819 adds the optional known_prefixes constructor argument and per-root loading.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor`, `sym:packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py#build_code_graph`.

### Does NOT Exist

- No known-prefix parameter exists on the test helper yet; construct CodeExtractor directly in new cases.
- RFC namespaces are not supported or introduced.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/graphindex/test_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/cli.py#build_code_graph"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Consumes CodeExtractor known_prefixes and build_code_graph config wiring from TASK-4819. GraphIndex test files are disjoint from the wiki regression suites.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Assert actual node metadata and IDs in comment and docstring cases — match-span tests alone miss labeling bugs.
2. Pin old outputs with fixed expected values — preserve compatibility independently of the new normalizer.
3. Exercise build_code_graph with root-specific configuration — catch missing propagation and cross-root leakage.

### `packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py` (MODIFY)

Anchor: `class TestCitationExtraction:` — `packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py:109`, occurrences: 1 (verified with `grep -F -c`).

```python
# Add methods to TestCitationExtraction; call CodeExtractor(known_prefixes=...).
@pytest.mark.asyncio
async def test_graphindex_prefix_labels_and_rfc(self) -> None:
    """Only allowed ADR prefixes change citation labels and identifiers."""
    # FILL IN: comments and docstrings; FS-ADR-3, see-ADR-3, FS-RFC-2119;
    # assert title, citation_ref, citation_kind, node_id, dedup and reference edges.

@pytest.mark.asyncio
async def test_graphindex_unconfigured_ids_unchanged(self) -> None:
    """None and empty allowlists preserve fixed pre-change citation payloads."""
    # FILL IN: literal expected IDs/titles/refs for old separators, hyphenated
    # prose and compact adjacent references; do not call new normalization as oracle.
```

**Why**: Byte-stable IDs and tags require real extractor tests, beyond regex matching.
### `packages/ai-parrot/tests/knowledge/graphindex/test_cli.py` (MODIFY)

Anchor: `class TestBuildCodeGraph:` — `packages/ai-parrot/tests/knowledge/graphindex/test_cli.py:95`, occurrences: 1 (verified with `grep -F -c`).

```python
# Add methods to TestBuildCodeGraph; use json and Path already imported.
@pytest.mark.asyncio
async def test_configured_prefixes_reach_extractor(self, tmp_path: Path) -> None:
    """The production build loads local and foreign ADR prefixes from config."""
    # FILL IN: write .parrot/wiki.json and citing Python; call cli.build_code_graph;
    # inspect graph.json nodes. Exercise configured, absent and invalid config.

@pytest.mark.asyncio
async def test_multiple_roots_keep_allowlists_isolated(self, tmp_path: Path) -> None:
    """One input root cannot grant an ADR prefix to another input root."""
    # FILL IN: two roots with disjoint configured prefixes and distinct filenames;
    # check graph payload per source. Also cover an individual-file input.
```

**Why**: A forgotten production allowlist silently loses labels even when unit tests pass.


### FILL IN checklist

- [ ] AC11/14/15: recognized ADR labels qualify, unknown labels degrade, RFCs never qualify; assert IDs and citation_ref as well as titles.
- [ ] None/empty configuration matches pre-change citation outputs, including compact adjacent references and hyphenated prose.
- [ ] CLI loads local/known prefixes, respects missing config defaults, fails on invalid config and isolates multiple input roots.
- [ ] Both comment/docstring consumers and existing dedup/reference-edge behavior are covered.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC11/14/15: recognized ADR labels qualify, unknown labels degrade, RFCs never qualify; assert IDs and citation_ref as well as titles.
- [ ] None/empty configuration matches pre-change citation outputs, including compact adjacent references and hyphenated prose.
- [ ] CLI loads local/known prefixes, respects missing config defaults, fails on invalid config and isolates multiple input roots.
- [ ] Both comment/docstring consumers and existing dedup/reference-edge behavior are covered.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_graphify_parity.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_cli.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4822.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4822` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Implemented by seat gpt-5.6-sol (codex), 1 attempt, merged; merge-tier validation 117 passed.
