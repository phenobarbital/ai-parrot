---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns (FEAT-576).
projects: [ai-parrot, ai-parrot-tools, ai-parrot-integrations]
# tags: free-form kebab-case keywords (FEAT-576).
tags: [sdd-tooling, docs, testing, ledger-fix]
---

# Feature Specification: Correct FEAT-601 AC19's declared multi-distribution pytest command

**Feature ID**: FEAT-607 (reserved by `/sdd-fix` on 2026-09-26, ledger label `fixgroup-73ca3aa6613f`)
**Date**: 2026-09-26
**Author**: Jesus Lara (drafted with Claude, via `/sdd-fix issue:59c2804dc17a`)
**Status**: approved
**Target version**: next minor release

---

## 1. Motivation & Business Requirements

### Problem Statement

`sdd/specs/training-agent.spec.md` (FEAT-601, merged to `dev`) declares, as its
**AC19**:

```
pytest packages/ai-parrot/tests/knowledge/manuals packages/ai-parrot/tests/knowledge/common packages/ai-parrot-tools/tests/procedures packages/ai-parrot-integrations/tests -q
```

This single composite command **fails to even collect** when run verbatim:

```
ImportPathMismatchError: ('tests.conftest',
  '.../packages/ai-parrot-integrations/tests/conftest.py',
  PosixPath('.../packages/ai-parrot/tests/conftest.py'))
```

This repo is a uv workspace: every distribution (`ai-parrot`, `ai-parrot-tools`,
`ai-parrot-integrations`, …) has its own `tests/` directory with its own
`conftest.py`, and none of them declare `tests/__init__.py`. Under pytest's
default `prepend` import mode, the FIRST `tests/conftest.py` pytest imports
claims the bare module name `tests.conftest`; every subsequent distribution's
`tests/conftest.py` collides under that same name and pytest raises
`ImportPathMismatchError`. This was confirmed pre-existing (not introduced by
FEAT-601) during FEAT-601's adversarial code review, and filed as
`issue:59c2804dc17a` (severity `low`, kind `tech_debt`) in the SDD ledger.

A second, independent problem in the same AC line was found while fixing this
(TASK for this feature): the declared command also names the **whole**
`packages/ai-parrot-integrations/tests` directory, which is far broader than
what FEAT-601 actually touches — that directory also contains unrelated,
already-red suites (e.g. `tests/voice/test_voice_demo_multibrowser.py`, 28
collection errors / 25 failures on current `dev`, entirely pre-existing and
unrelated to FEAT-601). Naming the whole directory in AC19 makes the
acceptance criterion untestable in isolation from unrelated pre-existing
red tests.

### Goals

- **G1** — AC19 in the merged `training-agent.spec.md` names commands that
  actually pass, verified fresh against current `dev`.
- **G2** — AC19 scopes the `ai-parrot-integrations` slice to the specific test
  files FEAT-601 introduced/touched, not the whole distribution's test tree.
- **G3** — Close `issue:59c2804dc17a` with real evidence (a diff to the spec
  file + a passing validation run), never by assertion alone.

### Non-Goals (explicitly out of scope)

- Fixing the underlying repo-wide multi-distribution `conftest.py` collision
  itself (e.g. adding `--import-mode=importlib` repo-wide, adding
  `tests/__init__.py` per distribution, or splitting `rootdir` per package).
  That is a structural, repo-wide pytest configuration change with its own
  blast radius across every distribution's test suite — a `low` severity,
  single-spec ledger issue about one acceptance criterion's wording is not
  the right vehicle for it. `--import-mode=importlib` alone was verified
  during this fix to be **insufficient** anyway (a second, deeper conftest
  identity collision remains even with that flag — see Codebase Contract).
- Fixing any of the pre-existing unrelated failures in
  `packages/ai-parrot-integrations/tests` (voice/multibrowser and others) —
  out of scope for this spec; not caused by FEAT-601.

---

## 2. Architectural Design

### Overview

This is a documentation-only fix: replace AC19's single composite `pytest`
invocation with three separate, correctly-scoped invocations (one per
distribution boundary), each with its own `PYTHONPATH`, matching the pattern
already used throughout `.claude/rules/worktree-management.md` and every
other task in FEAT-601 itself. No source code changes; no test code changes.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `sdd/specs/training-agent.spec.md` §5 AC19 | modifies (text only) | replaces the composite command with three scoped invocations |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: AC19 text correction | yes | Exact replacement text fixed below; no code, no design decision left open | — |

### Module 1: Correct AC19 in `training-agent.spec.md`
- **Path**: `sdd/specs/training-agent.spec.md`
- **Responsibility**: Replace the single-line AC19 with the three verified,
  separately-scoped `pytest` invocations below (exact text, do not rephrase):

  ```
  - [ ] **AC19** Each of the following three invocations passes on its own
    (a single composite command across distributions cannot collect — same-
    named top-level `tests` packages under `packages/*/tests/` collide even
    under `--import-mode=importlib`, per `packages/ai-parrot/tests/conftest.py`
    vs `packages/ai-parrot-integrations/tests/conftest.py`); live
    Arango/Postgres tests skip cleanly without credentials:
    ```bash
    PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src \
      pytest packages/ai-parrot/tests/knowledge/manuals packages/ai-parrot/tests/knowledge/common -q
    PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src \
      pytest packages/ai-parrot-tools/tests/procedures -q
    PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src \
      pytest packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py \
             packages/ai-parrot-integrations/tests/test_media_download.py \
             packages/ai-parrot-integrations/tests/test_media_urls.py \
             packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py \
             packages/ai-parrot-integrations/tests/test_media_urls_telegram.py \
             packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py -q
    ```
  ```

  (The exact file list for the third invocation is fixed — do not substitute
  `packages/ai-parrot-integrations/tests` as a bare directory; that directory
  contains unrelated pre-existing red suites.)

---

## 4. Test Specification

### Validation (this spec has no unit/integration tests of its own — it edits
a Markdown acceptance criterion; validation is running the three commands
above and confirming the exit codes / pass counts below)

| Command | Expected result |
|---|---|
| manuals + common | `128 passed, 3 skipped` |
| procedures | `44 passed` |
| integrations (6 named files) | `23 passed` |

### E2E Scenarios

Not applicable — no `e2e` frontmatter key, no E2E surface.

---

## 5. Acceptance Criteria

- [ ] **AC1** `sdd/specs/training-agent.spec.md`'s AC19 line is replaced with
  the exact three-invocation text from §3 Module 1 — nothing else in the
  spec file is touched.
- [ ] **AC2** Each of the three invocations passes with the pass counts in
  §4, run fresh against the merged FEAT-601 code on `dev`.
- [ ] **AC3** `issue:59c2804dc17a` closes with `resolved_by task:TASK-<NNN>`
  and a diff touching `sdd/specs/training-agent.spec.md`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified on `dev` @ `643c7feba`
> (2026-09-26, post FEAT-601 merge via PR #1500).

### Verified Imports

Not applicable — no source code is touched by this feature.

### Does NOT Exist (Anti-Hallucination)

- ~~`--import-mode=importlib` alone fixing the composite AC19 command~~ —
  verified NOT sufficient: `pytest --import-mode=importlib <all four dirs>`
  still raises `ValueError: Plugin already registered under a different
  name: .../packages/ai-parrot-integrations/tests/conftest.py=<module
  'tests.conftest' from '.../packages/ai-parrot/tests/conftest.py'>`, because
  a root-level `conftest.py` and per-package `packages/<dist>/conftest.py`
  files also participate in the same collision. Do not propose this flag as
  a one-line fix for AC19; it was tried and confirmed insufficient.

### Edit Sites (Blueprint Anchors)

Verified against: `643c7feba` (dev, post FEAT-601 merge)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `sdd/specs/training-agent.spec.md` | MODIFY | `- [ ] **AC19** \`pytest packages/ai-parrot/tests/knowledge/manuals packages/ai-parrot/tests/knowledge/common packages/ai-parrot-tools/tests/procedures packages/ai-parrot-integrations/tests -q\` passes; live Arango/Postgres tests skip cleanly without credentials.` | `training-agent.spec.md:913` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Match the `PYTHONPATH=...` invocation style already used throughout this
  repo's worktree/task validation commands (see
  `.claude/rules/worktree-management.md` §4).
- Do not attempt to fix the underlying conftest collision — see Non-Goals.

### Known Risks / Gotchas
- The compiled `parrot.utils.types` Cython extension (`.so`) is a gitignored
  build artifact — a fresh worktree checkout will raise
  `ModuleNotFoundError: No module named 'parrot.utils.types'` on the first
  two invocations until it (and `parrot/utils/parsers/toml.*.so`) is copied
  in from the main checkout, per the documented worktree gotcha. This is an
  environment step, not a code fix, and needs no spec/task text — just do it
  before running the validation commands.

### External Dependencies

None — no new dependency.

---

## 8. Open Questions

None.

---

## 9. Design Research Cross-Check

Skipped (reason: single-line documentation fix, `codex` review not
warranted for a spec-text correction with pre-verified, reproducible
evidence).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-26 | Claude (via `/sdd-fix`) | Initial draft — fixes `issue:59c2804dc17a` |
