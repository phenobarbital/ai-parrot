# TASK-4823: Shared ADR corpus and cross-plane parity gate

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4817, TASK-4819
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement the cross-plane part of M5 using the exact §4 corpus. Pin spans, extracted pairs, labels, RFC preservation and compact-reference boundaries.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py` | MODIFY | Add shared parity corpus without changing defaults |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py` | CREATE | All-match lexical and label parity tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations  # stdlib; existing neighboring test modules
import pytest  # existing decisions/conftest.py:11
from parrot.knowledge.wiki.decisions.parser import ADR_REFERENCE_RE, normalize_adr_alias  # parser.py:45,55
from parrot.knowledge.graphindex.extractors.code import _CITATION_RE, CodeExtractor  # code.py:35,65
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py:45,55`: ADR_REFERENCE_RE and normalize_adr_alias; TASK-4817 changes captures to prefix/number.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:35,65`: _CITATION_RE and CodeExtractor; TASK-4819 changes captures to prefix/kind/number.
- `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py:184–194`: existing adr_config/adr_store fixtures; append without mutating them.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias`, `sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor`.

### Does NOT Exist

- test_alias_grammar.py and parity_corpus do not exist yet.
- The design probe is not a production-test substitute; import actual production regexes and extractor.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias",
    "sym:packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py#CodeExtractor"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: false`. Consumes prefix-aware ADR_REFERENCE_RE/normalize_adr_alias from TASK-4817 and _CITATION_RE/CodeExtractor from TASK-4819. Exclusive because decisions/conftest.py is loaded by other tasks’ test suites.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Append the exact shared corpus — preserve the accepted compact-reference and near-miss design evidence.
2. Compare every lexical ADR span and pair — equal first matches are insufficient.
3. Exercise real extraction with the same allowlists — label parity must survive production normalization.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py` (MODIFY)

Anchor: `def adr_config() -> DecisionConfig:` — `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py:185`, occurrences: 1 (verified with `grep -F -c`).

```python
# Append a NEW standalone fixture; do not change adr_config or adr_repo.
@pytest.fixture
def parity_corpus() -> list[str]:
    """Minimum FEAT-760 all-match grammar and compatibility corpus."""
    return [
        "ADR-42", "ADR/042", "ADR 42", "adr42",
        "FS-ADR-3", "parrot-ADR-7", "PARROT-adr/007",
        "ADR_42", "ADR--42", "ADR - 42",
        "see-ADR-3 for why", "RFC 4180", "FS-RFC-2119",
        "ADR1-ADR-2", "RFC1-ADR-2", "ADR1-RFC-2", "ADR1-RFC2",
        "FS-ADR1-ADR-2", "ADR-99999", "ADR-123456",
        'x = "see ADR-42"',
    ]
```

**Why**: The approved corpus must be shared across the lexical and label tests without changing existing fixture defaults.
### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py` (CREATE)

Verified absent at planning time. Whole-file starting point:

```python
"""Cross-plane ADR lexical parity and configured-label compatibility."""
from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.parser import ADR_REFERENCE_RE, normalize_adr_alias
from parrot.knowledge.graphindex.extractors.code import _CITATION_RE, CodeExtractor


def test_lexical_parity_wiki_vs_graphindex(parity_corpus: list[str]) -> None:
    """Compare all ADR match spans and extracted prefix/number pairs."""
    # FILL IN: finditer both regexes; GraphIndex group 2 selects ADR, group 1
    # is prefix and group 3 number; wiki groups are prefix and number.
    # Compare every match's span and normalized extracted pair, not just search().


@pytest.mark.asyncio
async def test_graphindex_allowlist_matches_wiki_labels(parity_corpus: list[str]) -> None:
    """Configured extraction agrees with wiki labels without losing RFCs."""
    # FILL IN: None, empty, FS-only and FS/PARROT allowlists; each corpus string
    # embedded separately in a comment and function docstring. Compare all ADR
    # labels against normalization of each wiki regex match; preserve first-only
    # semantics of normalize_adr_alias itself. Explicitly assert RFC expected labels.
    # Assert reserved compact strings retain ALL known old references.
    # Separately place the executable-string corpus as code and assert no citation.
```

**Why**: Span parity and full-node label parity are different guarantees. Comparing only
the first match would miss the compact-citation regression from the design review.


### FILL IN checklist

- [ ] AC4: every ADR finditer span and (prefix, number) pair matches between planes over the full spec corpus.
- [ ] AC14/15: matching allowlists yield the same ADR labels; GraphIndex keeps every expected RFC reference without prefixing it.
- [ ] Compact-reference cases assert expected old references explicitly; two broken regexes must not pass merely by agreeing.
- [ ] Executable string literals remain non-citations when parsed as code; old separator near-misses remain excluded.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC4: every ADR finditer span and (prefix, number) pair matches between planes over the full spec corpus.
- [ ] AC14/15: matching allowlists yield the same ADR labels; GraphIndex keeps every expected RFC reference without prefixing it.
- [ ] Compact-reference cases assert expected old references explicitly; two broken regexes must not pass merely by agreeing.
- [ ] Executable string literals remain non-citations when parsed as code; old separator near-misses remain excluded.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_alias_grammar.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4823.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4823` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, merged. Merge-tier run: real test step 92 passed; the run's overall outcome read `failed` solely because the selector passed conftest.py as a pytest target (exit 5, no tests collected) — selector artifact, not a code failure.
