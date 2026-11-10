# TASK-5438: Documentation — Bookstore retrieval, graph, Codex and PageIndex pages

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5432, TASK-5434, TASK-5435, TASK-5437
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Create/update exactly the four spec §10 wiki pages using sdd/templates/techwiki-page.md.
- Document implemented APIs, 14-tool visibility, ask/doctor flags, origin diagnostics, revision-safe rereads and actual PageIndex stop reasons.
- Explain separate locks, hash+TOC graph preservation, async readiness, snapshot fallback and identical-TOC drift limitation.
- Copy metrics/defaults from the qualified host report programmatically and include its SHA256 and fixture hash; never type inferred measurements.
- Run the required techwiki check and verify examples against final signatures. This is the single documentation task.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/bookstore-agentic-retrieval.md` | CREATE | Scoped deliverable described above |
| `wiki/knowledge/bookstore-codex.md` | MODIFY | Scoped deliverable described above |
| `wiki/knowledge/bookstore-graph.md` | MODIFY | Scoped deliverable described above |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | MODIFY | Scoped deliverable described above |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No Python imports are introduced by this documentation task.

### Existing Signatures to Use

Use `sdd/templates/techwiki-page.md` and the final implemented symbols from prerequisite tasks. Documentation introduces no code symbols.

### Dependency-produced contracts

- TASK-5432: documents toolkit/MCP retrieval and guarded read symbols
- TASK-5434: documents BookstoreOrigin and section diagnostics
- TASK-5435: documents ask_cmd/doctor_cmd and their doctor facade dependency
- TASK-5437: consumes the reviewed question fixture, actual report and measured defaults

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- The new Bookstore agentic wiki page does not exist at the base; no measured metrics may be invented.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/bookstore-agentic-retrieval.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/knowledge/bookstore-codex.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/knowledge/bookstore-graph.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/knowledge/pageindex-agentic-retrieval.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

TASK-5432: documents toolkit/MCP retrieval and guarded read symbols; TASK-5434: documents BookstoreOrigin and section diagnostics; TASK-5435: documents ask_cmd/doctor_cmd and their doctor facade dependency; TASK-5437: consumes the reviewed question fixture, actual report and measured defaults

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Create/update exactly the four spec §10 wiki pages using sdd/templates/techwiki-page.md. **Why**: All four declared pages exist, remain readable and link to actual implemented symbols/pages.
2. Document implemented APIs, 14-tool visibility, ask/doctor flags, origin diagnostics, revision-safe rereads and actual PageIndex stop reasons. **Why**: Examples and flags match final APIs; no stale 10/11/13-tool claim or invented stale stop reason remains.
3. Explain separate locks, hash+TOC graph preservation, async readiness, snapshot fallback and identical-TOC drift limitation. **Why**: Measured defaults, quality rates, denominators and report SHA256 are copied from actual host evidence.
4. Copy metrics/defaults from the qualified host report programmatically and include its SHA256 and fixture hash; never type inferred measurements. **Why**: parrot sdd techwiki check reports the declared pages present with no invalid/empty/title issues.
5. Run the required techwiki check and verify examples against final signatures. This is the single documentation task. **Why**: All four declared pages exist, remain readable and link to actual implemented symbols/pages.

### `wiki/knowledge/bookstore-agentic-retrieval.md` (CREATE)

```markdown
---
title: Bookstore Agentic Retrieval
summary: Per-book cited retrieval, multi-origin excerpts, safe re-indexing and measured budgets.
---

# Bookstore Agentic Retrieval

## Purpose
<!-- FILL IN: the implemented research funnel and its limits; AC-1. -->
## Public API
<!-- FILL IN: ref links to implemented Bookstore, BookstoreToolkit and BookstoreOrigin; AC-1. -->
## Configuration & Parameters
<!-- FILL IN: revision guard, model, limits and operation-lock settings; AC-1, AC-2. -->
## Usage Examples
<!-- FILL IN: tested ask/doctor, origin and guarded reread examples; AC-2. -->
## Gotchas
<!-- FILL IN: no-LLM, actual stop reasons, snapshot fallback, drift limitation, host evaluation; AC-2. -->
## Related
<!-- FILL IN: relative links to the three updated pages; AC-1. -->

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `wiki/knowledge/bookstore-codex.md` (MODIFY)

```markdown
<!-- occurrences: 1 (verified: grep -cF -- '#Start a session' wiki/knowledge/bookstore-codex.md)
Container/attachment anchor: #Start a session
verified: wiki/knowledge/bookstore-codex.md:35; merge scoped edits, never replace the whole container. -->
<!-- FILL IN: update the anchored section for the FEAT-858 surface assigned in spec §10.
Preserve existing examples and add accurate links/configuration, without invented metrics.
Copy evaluation numbers programmatically from qualifying report JSON and include report SHA256;
all bounded by AC-1..AC-4. -->
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `wiki/knowledge/bookstore-graph.md` (MODIFY)

```markdown
<!-- occurrences: 1 (verified: grep -cF -- '#Degradation matrix' wiki/knowledge/bookstore-graph.md)
Container/attachment anchor: #Degradation matrix
verified: wiki/knowledge/bookstore-graph.md:142; merge scoped edits, never replace the whole container. -->
<!-- FILL IN: update the anchored section for the FEAT-858 surface assigned in spec §10.
Preserve existing examples and add accurate links/configuration, without invented metrics.
Copy evaluation numbers programmatically from qualifying report JSON and include report SHA256;
all bounded by AC-1..AC-4. -->
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `wiki/knowledge/pageindex-agentic-retrieval.md` (MODIFY)

```markdown
<!-- occurrences: 1 (verified: grep -cF -- '#Related' wiki/knowledge/pageindex-agentic-retrieval.md)
Container/attachment anchor: #Related
verified: wiki/knowledge/pageindex-agentic-retrieval.md:264; merge scoped edits, never replace the whole container. -->
<!-- FILL IN: update the anchored section for the FEAT-858 surface assigned in spec §10.
Preserve existing examples and add accurate links/configuration, without invented metrics.
Copy evaluation numbers programmatically from qualifying report JSON and include report SHA256;
all bounded by AC-1..AC-4. -->
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `wiki/knowledge/bookstore-agentic-retrieval.md` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `wiki/knowledge/bookstore-codex.md` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `wiki/knowledge/bookstore-graph.md` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `wiki/knowledge/pageindex-agentic-retrieval.md` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: All four declared pages exist, remain readable and link to actual implemented symbols/pages.
- [ ] AC-2: Examples and flags match final APIs; no stale 10/11/13-tool claim or invented stale stop reason remains.
- [ ] AC-3: Measured defaults, quality rates, denominators and report SHA256 are copied from actual host evidence.
- [ ] AC-4: parrot sdd techwiki check reports the declared pages present with no invalid/empty/title issues.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.

### Documentation validation (required)

- `parrot sdd techwiki check --spec sdd/specs/bookstore-agentic-retrieval.spec.md --root .`

Run this in addition to the registered-runner command above and inspect its output: the
techwiki CLI is informational and a warning is not proof that pages are complete. This
separate section preserves the skill's required documentation check without declaring it
as a pytest/vitest/cargo runner (the repository registry does not register techwiki).

## Agent Instructions

1. Run `$sdd-start TASK-5438` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Seat glm (nova, zai.glm-4.7-flash), 1 attempt, 217s. Review found invented APIs (Bookstore(library_path=...) ctor/table that belong to BookstoreOrigin, agentic_client arg, '$bookstore agentic_retrieve' invocation), wrong relative links, unrelated markdown rewrites in bookstore-graph.md and placeholder text instead of the measured results. Orchestrator rewrote the doc from source and restored bookstore-graph.md; fix commit e19168b6d2217585cd61afda976e391d353cb0e7. Feedback coder-feedback:7418f9da4ea8959b4974b37f; review coder-review:862ffc8a638acc46a9358aba. Docs state the retain_baseline outcome with report/fixture hashes. Not validated by a docs build.
