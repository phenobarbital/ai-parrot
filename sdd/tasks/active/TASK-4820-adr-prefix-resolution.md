# TASK-4820: Wiki prefix propagation and ambiguity-safe alias resolution

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4817, TASK-4818
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement M4: preserve full aliases in evidence, resolve exact then local aliases with ambiguity checked before each lookup, and use this path for cold and incremental sync.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` | MODIFY | Thread prefix allowlist through comment/docstring extraction |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` | MODIFY | Exact/local lookup and refresh configuration propagation |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path  # stdlib; existing ingest.py import
from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias, parse_adr  # parser.py:55,236
from parrot.knowledge.wiki.decisions.evidence import extract_python_citations  # evidence.py:92
from parrot.knowledge.wiki.decisions.models import ADR_REFERENCE_AMBIGUOUS, ADR_REFERENCE_MISSING, DecisionConfig, DecisionDiagnostic, DecisionRecord  # models.py:33–34,62
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py:92`: `extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]`; normalization sites :147/:160.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py:62`: `_alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]` drops ambiguous aliases.
- `_resolve_citations(root: Path, code_paths: list[str], inventory: list[DecisionRecord])` at :84 and caller at :277; `_ResolvedLinks` is the module-local dict alias at :42.
- `Citation` is the existing local evidence.py dataclass at :47; preserve its fields.
- `refresh_decisions(store, root, config, paths=None)` parses at :248 and checks `alias_map or ambiguous_aliases` at :274.
- Future APIs: TASK-4817 adds known_prefixes arguments; TASK-4818 adds effective_prefixes and local_prefix.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#extract_python_citations`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig`; `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#_alias_index`.

### Does NOT Exist

- `_lookup_alias` does not exist; add it here.
- Wiki extraction still returns only the first alias in each comment/docstring; do not broaden it.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#extract_python_citations",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#refresh_decisions",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py#_alias_index"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Consumes normalize_adr_alias/parse_adr known_prefixes signatures from TASK-4817 (parser.py) and effective_prefixes/local_prefix from TASK-4818 (models.py).
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Thread the optional allowlist through extraction — code ownership and first-match semantics stay intact.
2. Add ambiguity-first lookup — missing recognized aliases must never resolve to a different namespace.
3. Wire refresh configuration into parsing and resolution — incremental link repair must obey the same rules as cold sync.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` (MODIFY)

Anchor: `def extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]:` — `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py:92`, occurrences: 1 (verified with `grep -F -c`).

```python
def extract_python_citations(
    rel_path: str, source: str, known_prefixes: frozenset[str] | None = None
) -> tuple[list[Citation], list[DecisionDiagnostic]]:
    """Find configured ADR aliases in Python comments and docstrings."""
    # Retain parsing, attribution, diagnostic and first-match behavior.
    # In the token loop: alias = normalize_adr_alias(token.string, known_prefixes)
    # In the docstring loop: alias = normalize_adr_alias(docstring, known_prefixes)
    # FILL IN: refresh Citation's bare-only comments to describe canonical aliases.
```

**Why**: Only normalization changes; attribution and evidence spans must not change.
### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py` (MODIFY)

Anchor: `def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:` — `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py:62`, occurrences: 1 (verified with `grep -F -c`).

```python
# Preserve _alias_index behavior; update its docstring to full canonical aliases.
# Add immediately after _alias_index:
def _lookup_alias(
    alias: str, alias_map: dict[str, str], ambiguous_aliases: set[str],
    local_prefix: str | None,
) -> tuple[str | None, str | None]:
    """Return (decision_id, None) or (None, diagnostic_code)."""
    # FILL IN AC7/8/17: exact ambiguity -> stop; exact hit -> stop;
    # absent bare alias only -> local candidate; same ambiguity-first checks.
    # Recognized prefixed aliases never retry as bare.

async def _resolve_citations(
    root: Path, code_paths: list[str], inventory: list[DecisionRecord],
    config: DecisionConfig | None = None,
) -> tuple[_ResolvedLinks, list[DecisionDiagnostic]]:
    """Resolve Python citations using exact and optional local-prefix aliases."""
    settings = config if config is not None else DecisionConfig()
    # Retain existing body with the following bounded modifications.
# Thread settings.effective_prefixes() into extract_python_citations.
# For each citation, call _lookup_alias(alias, alias_map, ambiguous_aliases,
#                                    settings.local_prefix).
# FILL IN: preserve existing diagnostic text/path for each returned failure code,
# and existing grouped evidence/links on success.
# In refresh_decisions, pass config.effective_prefixes() to parse_adr and
# pass config=config to _resolve_citations. Keep alias_map or ambiguous_aliases guard.
```

**Why**: Ambiguity is terminal, including local fallback; both cold and incremental refresh already converge through this shared path.


### FILL IN checklist

- [ ] AC5/6: different prefixes with the same number resolve independently; duplicate identical full aliases remain ambiguous.
- [ ] AC7/8/17: exact hit wins; exact ambiguity stops; only absent bare aliases try local; local ambiguity is ambiguous; recognized prefixed misses never retry bare.
- [ ] Unlisted XX-ADR-3 degrades to bare before exact/local lookup; absence without local config is missing.
- [ ] Cold and partial sync share resolution and preserve evidence indices, stale-link repair and ambiguity-only code walking.
- [ ] Comments and docstrings honor effective prefixes; executable strings are still excluded; default callers remain compatible.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC5/6: different prefixes with the same number resolve independently; duplicate identical full aliases remain ambiguous.
- [ ] AC7/8/17: exact hit wins; exact ambiguity stops; only absent bare aliases try local; local ambiguity is ambiguous; recognized prefixed misses never retry bare.
- [ ] Unlisted XX-ADR-3 degrades to bare before exact/local lookup; absence without local config is missing.
- [ ] Cold and partial sync share resolution and preserve evidence indices, stale-link repair and ambiguity-only code walking.
- [ ] Comments and docstrings honor effective prefixes; executable strings are still excluded; default callers remain compatible.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_ingest.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4820.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4820` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Pending; populated by the finalization workflow after implementation and validation.
