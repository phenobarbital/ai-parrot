# TASK-4821: Wiki prefix identity, configuration and sync regressions

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4820
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement the wiki part of M5 and all parser/config/evidence/sync cases in spec §4. Reuse existing fixtures without modifying conftest; build prefixed trees locally in tests.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py` | MODIFY | FEAT-760 wiki regression coverage |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` | MODIFY | FEAT-760 wiki regression coverage |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py` | MODIFY | FEAT-760 wiki regression coverage |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` | MODIFY | FEAT-760 wiki regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path  # stdlib
import pytest  # all four existing suites
from pydantic import ValidationError  # test_models.py:6
from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias, parse_adr  # parser.py:55,236
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord  # models.py:62 and record model
from parrot.knowledge.wiki.decisions.evidence import extract_python_citations  # evidence.py:92
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions  # existing test_ingest.py:8
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # repository.py:26
from parrot.knowledge.wiki.store import BaseWikiStore  # store.py:697
```

### Existing Signatures to Use

- Existing anchors: `TestIdentity.test_alias_normalization` in test_parser.py:100, `TestDecisionConfig` in test_models.py:33, `TestPythonCitations` in test_evidence.py:39, `TestRefresh` in test_ingest.py:25.
- `packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py:191`: `adr_store(tmp_path)` yields a file-backed InMemoryWikiStore; `adr_config()` returns DecisionConfig defaults.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py:63`: `async inventory(self) -> list[DecisionRecord]`.
- TASK-4820 supplies configured refresh/extraction; its dependencies supply parser and model APIs.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#extract_python_citations`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions`; `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository`.

### Does NOT Exist

- No prefixed repository fixture exists; construct data in these test files.
- No Markdown sym-link resolution exists; test Python citations only.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#extract_python_citations",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Tests configured refresh_decisions and extract_python_citations supplied by TASK-4820; parser and config dependencies are satisfied transitively. Owns four test files and does not mutate shared conftest.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Add parser/config cases — distinguish unknown filenames from unknown prose.
2. Exercise both extraction call sites — preserve attribution and executable-string exclusion.
3. Test the full resolution matrix through refresh and stored links — avoid testing only helper return values.
4. Pin legacy outputs using fixed expectations — the new implementation cannot serve as its own compatibility oracle.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py` (MODIFY)

Anchor: `    def test_alias_normalization(self, text):` — `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py:100`, occurrences: 1 (verified with `grep -F -c`).

```python
# Keep TestIdentity and its existing parameterized methods; extend to both modes.
# Append focused typed tests; do not replace existing regression cases.
@pytest.mark.parametrize("known", [None, frozenset(), frozenset({"FS"})])
def test_unlisted_filename_is_not_identity(known: frozenset[str] | None) -> None:
    """An unknown prefixed filename contributes neither identity nor conflict."""
    # FILL IN: choose an unknown XX filename, test with/without explicit ADR-7;
    # assert exact alias and absence of conflict diagnostics (AC16).

def test_prefixed_identity_and_supersedes() -> None:
    """Recognized aliases survive precedence and supersedes parsing."""
    # FILL IN: FS/PARROT identifiers, conflicting headings/numeric filenames,
    # bare-id preservation, allowed fs-0042 filename and supersedes (AC1–3/9/16).
```

**Why**: Parser tests pin identity and the stricter filename rule separately from citation normalization.
### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py` (MODIFY)

Anchor: `class TestDecisionConfig:` — `packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py:33`, occurrences: 1 (verified with `grep -F -c`).

```python
# Add these methods to TestDecisionConfig, retaining all existing tests:
def test_effective_prefixes_includes_local(self) -> None:
    """The local prefix joins the immutable allowlist without changing fields."""
    # FILL IN: lowercase inputs, duplicate membership, defaults, round trip.

@pytest.mark.parametrize("bad", ["1FS", "F S", "", "ADR1", "adr00001", "RFC2119"])
def test_reserved_and_invalid_prefixes(self, bad: str) -> None:
    """Both prefix fields reject invalid and compact-citation names."""
    # FILL IN: both fields raise ValidationError; ADR123456 remains accepted.
```

**Why**: Configuration failures must surface before either plane uses the allowlist.
### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py` (MODIFY)

Anchor: `class TestPythonCitations:` — `packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py:36`, occurrences: 1 (verified with `grep -F -c`).

```python
# Add typed methods to TestPythonCitations:
def test_prefixed_comments_and_docstrings(self) -> None:
    """Allowlisted prefixes propagate without changing source attribution."""
    # FILL IN: FS known/unknown modes, module and symbol comments/docstrings,
    # executable string exclusion and two references preserving first-only behavior.
```

**Why**: Grammar parity alone cannot prove that both evidence call sites pass configuration.
### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py` (MODIFY)

Anchor: `class TestRefresh:` — `packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py:25`, occurrences: 1 (verified with `grep -F -c`).

```python
# Add an integration test class after TestRefresh; use existing adr_store fixture.
class TestPrefixedRefresh:
    async def test_sync_with_two_origins_links_both(self, tmp_path: Path, adr_store: BaseWikiStore) -> None:
        """Cold and partial refresh resolve two origins sharing a number."""
        # FILL IN: create PARROT/FS ADR-7 files and Python citations; inspect
        # DecisionRepository inventory for exact explains targets, not just counts.

    async def test_exact_and_local_resolution(self, tmp_path: Path, adr_store: BaseWikiStore) -> None:
        """Exact/local ambiguity and misses have deterministic outcomes."""
        # FILL IN: parameterize all AC7/8/17 rows; drive refresh, assert diagnostic
        # codes and links. Include unknown prefixes degrading to bare and no-local.

    async def test_unconfigured_repo_is_byte_identical(self, tmp_path: Path, adr_store: BaseWikiStore) -> None:
        """Unconfigured sync preserves the pre-feature records and diagnostics."""
        # FILL IN: fixed pre-change expected payloads (including hyphenated prose),
        # excluding only nondeterministic timestamps; compare records/links/diagnostics.
        # Never derive the expected result from the newly changed parser.
```

**Why**: End-to-end assertions expose missing config propagation and ambiguity guard regressions.


### FILL IN checklist

- [ ] Spec §4 wiki unit cases cover prefixed normalization, old separator matrices in both modes, filename gating, conflicting IDs, supersedes and no identity injection.
- [ ] Config tests cover invalid/reserved prefixes in both fields, uppercase normalization, defaults, local inclusion and immutability.
- [ ] Sync tests cover distinct origins, duplicate full aliases, exact hit and ambiguity precedence, local fallback ambiguity, recognized misses and unlisted degradation.
- [ ] Cold and partial refresh prove unchanged citing code is repaired and removed citations lose links; unconfigured record/link/diagnostic payloads match pre-change expectations.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] Spec §4 wiki unit cases cover prefixed normalization, old separator matrices in both modes, filename gating, conflicting IDs, supersedes and no identity injection.
- [ ] Config tests cover invalid/reserved prefixes in both fields, uppercase normalization, defaults, local inclusion and immutability.
- [ ] Sync tests cover distinct origins, duplicate full aliases, exact hit and ambiguity precedence, local fallback ambiguity, recognized misses and unlisted degradation.
- [ ] Cold and partial refresh prove unchanged citing code is repaired and removed citations lose links; unconfigured record/link/diagnostic payloads match pre-change expectations.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4821.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4821` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Pending; populated by the finalization workflow after implementation and validation.
