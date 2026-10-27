# TASK-4818: Validated ADR prefix configuration and PARROT default

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

Implement M2 and resolved Q3: add strict prefix settings, expose effective_prefixes(), and do NOT bake PARROT into the model default. (Amended by sdd-worker: `.parrot/wiki.json` is gitignored and absent from worktrees, so the PARROT opt-in is a manual local-config edit by the operator, not a committed deliverable.)

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` | MODIFY | Add validated config fields and effective prefix set |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import re  # Python stdlib; add to models.py
from pydantic import Field, field_validator  # existing models.py:13
```

### Existing Signatures to Use

- `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:62`: `DecisionConfig(_Strict)`, fields through `timeout_seconds` at :75; `_Strict` forbids extras.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:695`: nested `decisions: DecisionConfig` already exists; do not modify that file.
- `.parrot/wiki.json` already has a decisions object ending with `"timeout_seconds": 60`.
- Symbol: `sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig`.

### Does NOT Exist

- `DecisionConfig.local_prefix`, `known_prefixes`, and `effective_prefixes()` do not exist.
- No automatic imported-ADR allowlist exists; configuration is hand-maintained.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig"
  ]
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Independent models.py and repository config owner; no dependency on parser grammar implementation.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Add and validate the two model fields — invalid namespace names must fail at configuration loading.
2. Expose effective_prefixes as an immutable union — callers need the same semantics without shared mutation.
3. Set PARROT only in this repository configuration — preserve unconfigured behavior everywhere else.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py` (MODIFY)

Anchor: `    timeout_seconds: int = Field(default=60, gt=0)` — `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py:75`, occurrences: 1 (verified with `grep -F -c`).

```python
# ADD within DecisionConfig after timeout_seconds; retain the existing fields.
local_prefix: str | None = None
known_prefixes: list[str] = Field(default_factory=list)

@field_validator("local_prefix", "known_prefixes")
@classmethod
def _validate_prefixes(cls, value: str | list[str] | None) -> str | list[str] | None:
    """Uppercase prefixes and reject invalid or compact-citation names."""
    # FILL IN: validate each string with ^[A-Za-z][A-Za-z0-9]*$;
    # reject ^(?:ADR|RFC)[0-9]{1,5}$ case-insensitively (AC10).
    # Preserve None for local_prefix and the list shape for known_prefixes.

def effective_prefixes(self) -> frozenset[str]:
    """Return configured foreign prefixes plus the optional local prefix."""
    # FILL IN: union values without mutating configuration or caller lists.
```

**Why**: Keep validation in the existing strict Pydantic model and share one plain-data allowlist across both planes.
### `.parrot/wiki.json` (MODIFY)

Anchor: `    "timeout_seconds": 60` — `.parrot/wiki.json:75`, occurrences: 1 (verified with `grep -F -c`).

```jsonc
// Within the existing decisions object, preserve every other setting:
"timeout_seconds": 60,
"local_prefix": "PARROT",
"known_prefixes": []
// FILL IN: maintain valid JSON punctuation; these comments are instructions only.
```

**Why**: The local repository owns PARROT; other repositories must retain a None default.


### FILL IN checklist

- [ ] AC10: accept FS, fs, PARROT and ADR123456; uppercase accepted values; reject empty, 1FS, F S, punctuation, ADR1, adr00001 and RFC2119 in both fields.
- [ ] Defaults are local_prefix=None and known_prefixes=[]; effective_prefixes includes local prefix, deduplicates and never mutates fields.
- [ ] This repository sets local_prefix=PARROT; nested WikiProjectConfig validation and serialization remain compatible.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC10: accept FS, fs, PARROT and ADR123456; uppercase accepted values; reject empty, 1FS, F S, punctuation, ADR1, adr00001 and RFC2119 in both fields.
- [ ] Defaults are local_prefix=None and known_prefixes=[]; effective_prefixes includes local prefix, deduplicates and never mutates fields.
- [ ] This repository sets local_prefix=PARROT; nested WikiProjectConfig validation and serialization remain compatible.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_models.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4818.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4818` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Pending; populated by the finalization workflow after implementation and validation.
