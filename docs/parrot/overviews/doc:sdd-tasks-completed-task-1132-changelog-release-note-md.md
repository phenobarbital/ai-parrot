---
type: Wiki Overview
title: 'TASK-1132: CHANGELOG Release Note for FEAT-164'
id: doc:sdd-tasks-completed-task-1132-changelog-release-note-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 9** of FEAT-164 (spec §3 "Module 9"). Per the
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
---

# TASK-1132: CHANGELOG Release Note for FEAT-164

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1128, TASK-1130
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of FEAT-164 (spec §3 "Module 9"). Per the
resolved Open Question #1, the release note lands in
`packages/ai-parrot/CHANGELOG.md` (the only package-level changelog,
following Keep-a-Changelog with an existing `[Unreleased]` section).

The note documents the breaking surface so downstream Navigator
consumers see the change cleanly:

- `AbstractDBAgent` is deleted (TASK-1130).
- `DatabaseAgent` base class changed: `AbstractBot` → `BasicAgent`.
- `DatabaseAgent.__init__` parameter `enable_retry: bool` hard-renamed
  to `retry_config: Optional[QueryRetryConfig]` (Open Question #2
  resolution).
- New structured-output contract: `QueryResponse` + `QueryDataset`.
- New internal toolkit: `DatabaseAgentToolkit`.

---

## Scope

- Append a release note under the existing `## [Unreleased]` section of
  `packages/ai-parrot/CHANGELOG.md`, following the Keep-a-Changelog
  format already used in that file.
- Mention each of the 5 user-visible changes (base class, ask() flow,
  structured-output, deleted abstract.py, retry_config rename).
- Include a short "Migration" sub-bullet for downstream consumers.

**NOT in scope**:
- Touching any other CHANGELOG (e.g. the top-level repo CHANGELOG, if
  it exists).
- Bumping the version number (handled at release-time by the
  maintainer).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/CHANGELOG.md` | MODIFY | Append a `### Added / ### Changed / ### Removed` block under `[Unreleased]`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified File Layout

At task-creation time (2026-05-13), `packages/ai-parrot/CHANGELOG.md`:

- Line 1: `# Changelog`
- Line 9: `## [Unreleased]`
- Line 11: `### Added` — already contains the FEAT-133 entry.
- Existing FEAT entries use this shape (verified against FEAT-133):
  ```
  - **FEAT-NNN** — short summary.

    Body paragraph(s) describing the change, with sub-bullets for code
    references.
  ```

### Existing Signatures (none — this task is doc-only)

### Does NOT Exist

- ~~A top-level `CHANGELOG.md` at the repo root~~ — verified absent.
  All changelog entries go to the package-level file.
- ~~`docs/releases/` directory~~ — not used in this repo.

---

## Implementation Notes

### Entry Template

Append the following under the `## [Unreleased]` section, within the
appropriate `### Added` / `### Changed` / `### Removed` subsections
(creating subsections if missing):

```markdown
### Changed

- **FEAT-164** — `DatabaseAgent` homologated to the `PandasAgent` shape.

  `DatabaseAgent` now inherits from `BasicAgent` (was `AbstractBot`) and
  exposes a real LLM-backed `ask()` flow that returns a strict structured
  `QueryResponse` instead of a free-text blob.

  - New base class: `parrot.bots.database.DatabaseAgent` is now a
    `parrot.bots.agent.BasicAgent` subclass.
  - System prompts assembled via a class-level
    `_prompt_builder = _build_database_prompt_builder()` mirroring
    `PandasAgent`.
  - Structured output contract: `ask()` returns an `AIMessage` whose
    `output` is a `parrot.bots.database.QueryResponse` Pydantic model
    (with optional `QueryDataset` payload). Free-text fallback when the
    provider does not honour the schema.
  - `QueryRetryConfig` is now wired end-to-end: pass
    `retry_config=QueryRetryConfig(...)` to the constructor and the agent
    re-asks the LLM after a retryable `execute_query` failure (up to
    `max_retries` attempts).

  **Breaking**: the `enable_retry: bool` parameter on `DatabaseAgent.ask`
  is removed. Pass `retry_config=QueryRetryConfig(...)` to the constructor
  instead (or omit it to disable retries entirely). No deprecation shim
  is shipped.

### Added

- **FEAT-164** — `parrot.bots.database.QueryResponse` and
  `parrot.bots.database.QueryDataset` Pydantic models defining the
  `DatabaseAgent` structured-output contract.
- **FEAT-164** — `parrot.bots.database.toolkits.DatabaseAgentToolkit`, an
  internal `AbstractToolkit` collecting 16 helpers ported from the
  deleted `AbstractDBAgent` (explain-plan formatting, optimization tips,
  SQL extraction, schema docs, etc.). Auto-registered by
  `DatabaseAgent.configure()`; individual tools are gated by the
  active `OutputComponent` flags of each request.

### Removed

- **FEAT-164** — `parrot.bots.database.abstract.AbstractDBAgent` (3067 LOC,
  legacy). All still-useful helpers were migrated to
  `DatabaseAgentToolkit`. No backwards-compatibility shim is provided.
```

### Migration Note for Navigator Consumers

Add this short paragraph at the end of the entry:

```markdown
**Migration path**: no production code currently imports
`AbstractDBAgent`. Downstream code calling
`DatabaseAgent(..., enable_retry=True)` must switch to
`DatabaseAgent(..., retry_config=QueryRetryConfig())`. Code that read
`AIMessage.response` for a string answer continues to work; code that
wants the structured payload should read `AIMessage.output` (a
`QueryResponse`).
```

### Key Constraints

- Place the entry chronologically AFTER existing `[Unreleased]` entries
  (do not reshuffle).
- Use the FEAT-NNN bold-prefix style established by FEAT-133.
- No emoji, no marketing tone — stick to engineering facts.

### References in Codebase

- `packages/ai-parrot/CHANGELOG.md` lines 9–30 — the FEAT-133 entry is
  the formatting template.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/CHANGELOG.md` contains a `FEAT-164` entry
      under `[Unreleased]`.
- [ ] The entry covers the 5 user-visible changes listed in Context.
- [ ] Migration paragraph present.
- [ ] No other CHANGELOG files modified.
- [ ] Markdown is well-formed (no broken headers, no trailing
      whitespace).

---

## Test Specification

This is a documentation-only task; no Python tests required. The
acceptance check is a visual review + a grep:

```bash
grep -n "FEAT-164" packages/ai-parrot/CHANGELOG.md
# Should return at least three lines (Changed / Added / Removed entries).
```

---

## Agent Instructions

1. Verify TASK-1128 (agent rewrite) and TASK-1130 (delete abstract.py)
   are complete — both are listed as dependencies because the
   CHANGELOG should reflect actually-landed changes.
2. Read the current `[Unreleased]` section to match its formatting
   exactly.
3. Append the FEAT-164 entry under the right subsections.
4. Move this file to `sdd/tasks/completed/` and update the per-spec
   index.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: Appended FEAT-164 entry under `[Unreleased]` in `packages/ai-parrot/CHANGELOG.md`. Covers all 5 user-visible changes: base class change (AbstractBot → BasicAgent), ask() structured-output flow, QueryResponse/QueryDataset models, DatabaseAgentToolkit, and AbstractDBAgent removal. Migration paragraph included inline under the Changed entry.
**Deviations from spec**: The Added sub-entries (QueryResponse/QueryDataset and DatabaseAgentToolkit) were placed inside the existing `### Added` block established by FEAT-133 rather than opening a duplicate `### Added` header, to keep the `[Unreleased]` section well-formed.
