# TASK-4817: Prefix-aware ADR grammar and document identity

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement M1: optional prefixes with reserved compact-citation protection, allowlist normalization, filename gating, and supersedes parsing.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | MODIFY | Grammar, normalization, splitting and ADR identity |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import re  # stdlib; existing parser.py:14
from parrot.knowledge.wiki.decisions.codec import documented_decision_id, normalize_rel_path  # codec.py:104,95
from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionLink, DecisionRecord, EvidenceRef  # existing parser.py:17–24
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py:55`: `normalize_adr_alias(text: str) -> str | None` uses the first regex search.
- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py:236`: `parse_adr(rel_path: str, text: str) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]`.
- Identity precedence block at :290–306, supersedes block :332–340; both call normalization.
- Symbol IDs: `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias`, `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr`.

### Does NOT Exist

- `split_decision_alias` and prefix arguments do not exist yet; create them here.
- Parser has no local-prefix injection or Markdown `sym:` extraction; add neither.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#normalize_adr_alias",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py#parse_adr"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Independent parser.py owner; consumes no new symbols from another task.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Update the two regexes and cross-reference comment — preserve digit and separator limits and protect compact references.
2. Add optional allowlist normalization and canonical splitting — preserve the no-config API behavior.
3. Thread the allowlist through document identity and supersedes — retain precedence and conflict diagnostics.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` (MODIFY)

Anchor: `def normalize_adr_alias(text: str) -> str | None:` — `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py:55`, occurrences: 1 (verified with `grep -F -c`).

```python
# REPLACE the existing regex constants at lines 45 and 48 and refresh their comments.
ADR_REFERENCE_RE = re.compile(
    r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?ADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE
)
FILENAME_ID_RE = re.compile(r"^(?:([A-Za-z][A-Za-z0-9]*)-)?0*(\d+)[-_]")

def normalize_adr_alias(text: str, known_prefixes: frozenset[str] | None = None) -> str | None:
    """Return the first canonical alias, honoring only configured prefixes."""
    # FILL IN: search, normalize number, uppercase prefix; unlisted -> bare (AC1–3).

def split_decision_alias(alias: str) -> tuple[str | None, int]:
    """Split a canonical alias into its optional prefix and numeric identifier."""
    # FILL IN: split canonical bare/prefixed forms without reapplying an allowlist.

def parse_adr(
    rel_path: str, text: str, known_prefixes: frozenset[str] | None = None
) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]:
    """Parse an ADR with frontmatter, heading, then filename identity precedence."""
    # MODIFY only identity/supersedes logic inside the existing body:
    # pass known_prefixes into normalization for frontmatter, H1 and supersedes.
    # FILL IN: numeric filenames remain bare; prefixed filename is a candidate
    # only when its uppercased prefix is allowed (AC16); never inject local prefix.
    # Preserve path-derived IDs, conflict diagnostics, evidence and status handling.
```

**Why**: Both planes must share the same lexical boundaries. Filename identity is deliberately stricter than prose normalization.


### FILL IN checklist

- [ ] AC1–3: recognized prefixes uppercase; unlisted prefixes degrade to bare; old separators and first-match behavior remain.
- [ ] AC9/16: bare identities stay bare; unknown prefixed filenames add no identity or conflict, while numeric filenames retain old behavior.
- [ ] Frontmatter FS-ADR-7 versus numeric filename 0007 still diagnoses conflicting identities; prefixed supersedes links retain full aliases.
- [ ] ADR1-ADR-2, RFC1-ADR-2 and ADR1-RFC-2 retain old ADR matches; canonical split returns (None, n) or (PREFIX, n).
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC1–3: recognized prefixes uppercase; unlisted prefixes degrade to bare; old separators and first-match behavior remain.
- [ ] AC9/16: bare identities stay bare; unknown prefixed filenames add no identity or conflict, while numeric filenames retain old behavior.
- [ ] Frontmatter FS-ADR-7 versus numeric filename 0007 still diagnoses conflicting identities; prefixed supersedes links retain full aliases.
- [ ] ADR1-ADR-2, RFC1-ADR-2 and ADR1-RFC-2 retain old ADR matches; canonical split returns (None, n) or (PREFIX, n).
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4817.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4817` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, merged. Parser grammar accepts optional prefix; known_prefixes gate prefixed ids/filenames. Merge-tier validation: 90 passed.
