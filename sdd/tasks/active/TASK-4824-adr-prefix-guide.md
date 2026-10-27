# TASK-4824: Document ADR prefixes and exact/local resolution

**Feature**: FEAT-760 - Prefixed ADR Aliases
**Spec**: `sdd/specs/adr-prefixed-aliases.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement this bounded part of FEAT-760, preserving bare ADR compatibility while allowing
configured repository prefixes. The approved spec §§2–7 defines behavior; source contracts
below were checked at `4e3ba6289`. No ADR publication, migration, or new dependencies.

## Scope

Implement M6 and AC12 from the approved spec. Document the new behavior and remove the unsupported Markdown sym-link claim identified in §6.

**NOT in scope**: files outside the table, ADR publish/pull, rewriting bare record identity,
or adding multiple wiki citations per comment/docstring. Tests assigned to another task
remain read-only here. Do not alter existing public defaults beyond this task's scope.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/guides/wiki-adr-decisions.md` | MODIFY | Prefix grammar, config examples and lookup semantics |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No Python imports needed for this documentation-only task.
```

### Existing Signatures to Use

- `docs/guides/wiki-adr-decisions.md:33`: `## What Gets Parsed`.
- `## How Decisions Attach to Code` currently claims Markdown sym links support other languages; spec §6 and source inspection show no such extraction.
- Spec §§2/5/8 define exact grammar, config defaults, lookup and the PARROT repository setting; this task consumes those approved definitions, not future implementation files.

### Does NOT Exist

- No ADR publish/pull commands or Markdown sym-link extraction exist in this feature.
- No automatic local-prefix rewriting of record identity is introduced.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/guides/wiki-adr-decisions.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Preserve async I/O and existing parser/storage boundaries; no provider calls or new dependencies.
- Use typed signatures and Google-style docstrings, Black with 120 columns, and targeted Ruff checks.
- `parallel: true`. Independent guide owner; consumes the approved spec only. Existing parser tests serve as a narrow documentation baseline; no dependency on unfinished implementation is required.
- Blueprints are planning scaffolds: complete every bounded gap in implementation, leaving no placeholders.
- No Delegation Contract: test assertions and edge-case bodies still require implementation judgment.

## Implementation Blueprint

### Steps (in order)

1. Describe grammar and repository-specific config — distinguish model defaults from ai-parrot’s chosen prefix.
2. Give exact/local examples including ambiguity and unknown prefixes — these determine whether citations resolve.
3. Correct the unsupported Markdown-link sentence — do not advertise unavailable extraction.

### `docs/guides/wiki-adr-decisions.md` (MODIFY)

Anchor: `## What Gets Parsed` — `docs/guides/wiki-adr-decisions.md:31`, occurrences: 1 (verified with `grep -F -c`).

```markdown
## ADR Prefixes and Configuration

Prefixes begin with an ASCII letter and continue with ASCII letters or digits.
They normalize to uppercase. Compact citation names such as ADR1 and RFC2119
are reserved. Bare ADR-42, ADR/042, ADR 42 and adr42 remain supported.

Example decisions settings in .parrot/wiki.json:
    "local_prefix": "FS",
    "known_prefixes": ["PARROT"]

### Resolution Order

FILL IN: show exact ambiguity -> stop; exact hit -> stop; absent bare alias ->
local fallback, again checking ambiguity before a hit. Recognized prefixed
misses never retry bare. Unknown prefixes first degrade to bare.

FILL IN: explain no-config defaults, local inclusion, manual maintenance,
PARROT for ai-parrot only, filename gating, no rewriting of bare identities,
prefixed supersedes, same-alias ambiguity, and RFC non-prefixing.
```

**Why**: The guide must make unknown-prefix degradation explicit so users do not mistake the allowlist for typo detection.


### FILL IN checklist

- [ ] AC12: guide covers grammar, both config keys, effective local membership, manual allowlists and None/empty compatibility.
- [ ] Examples distinguish recognized missing prefixes from unlisted-prefix degradation, exact ambiguity from local fallback, and exact hits from local ambiguity.
- [ ] Document filename gating, bare identity preservation, prefixed supersedes, RFC behavior and PARROT as this repository’s choice only.
- [ ] Remove the unsupported Markdown sym-link extraction claim; introduce no publish/pull promises.
- [ ] Complete all blueprint bodies; no placeholder may remain in implementation files.

## Acceptance Criteria

- [ ] AC12: guide covers grammar, both config keys, effective local membership, manual allowlists and None/empty compatibility.
- [ ] Examples distinguish recognized missing prefixes from unlisted-prefix degradation, exact ambiguity from local fallback, and exact hits from local ambiguity.
- [ ] Document filename gating, bare identity preservation, prefixed supersedes, RFC behavior and PARROT as this repository’s choice only.
- [ ] Remove the unsupported Markdown sym-link extraction claim; introduce no publish/pull promises.
- [ ] The targeted validation commands pass; Ruff is clean on modified Python files.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py -q`

## Test Specification

Use the file-level commands above. Each acceptance item names the required observable
behavior; the regression tasks add the spec §4 cases in their owned files. For production
tasks, run the existing suites now and leave the additional assertion work to those tasks.
Capture test output in `artifacts/logs/task-4824.log`. The index caches the full
spec validation contract once; do not widen this task to directory-wide pytest.

## Agent Instructions

1. Use `$sdd-start TASK-4824` to provision the feature worktree; never implement on `dev`.
2. Read the spec, check dependency completion in `sdd/tasks/index/adr-prefixed-aliases.json`, and reverify anchors/imports.
3. Implement only the declared files, then run validation and review the diff.
4. Commit scoped code and SDD state, preserving other contributors' changes.
5. Finalize through `scripts.sdd.finalize_task` with real `TaskCompletionEvidence` and
   the exact implementation HEAD, per `docs/sdd/CODEX.md`; do not hand-move this file.

## Completion Note

Pending; populated by the finalization workflow after implementation and validation.
