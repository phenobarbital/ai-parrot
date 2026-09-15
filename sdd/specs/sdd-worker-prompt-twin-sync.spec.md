---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Sync `sdd-worker` Packaged Prompt Twin

**Feature ID**: FEAT-547
**Date**: 2026-09-10
**Author**: Jesus Lara (with Claude Sonnet 5)
**Status**: approved
**Target version**: n/a — SDD tooling (`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/`); nothing ships in a package's public API
**Origin**: follow-up to FEAT-546 (Design Research Hardening). FEAT-546's own
TASK-3105 (AC-10) found `pytest packages/ai-parrot/tests/flows/dev_loop/
test_subagent_parity.py -v` failing on `test_prompt_parity[sdd-worker]`,
verified this was pre-existing and independent of FEAT-546's changes (traced to
FEAT-543/TASK-3090, commit `461b74c2e`), and — per FEAT-546's own non-goal
forbidding edits under `packages/ai-parrot/src/parrot/flows/dev_loop/` — did
not fix it, instead flagging it "as a follow-up for a human/future task" in
its Completion Note. This spec is that follow-up.

---

## 1. Motivation & Business Requirements

### Problem Statement

`sdd-worker` is dual-sourced (FEAT-377 Module 1 / TASK-1906, documented in
`_subagent_defs.py`'s own module docstring): `.claude/agents/sdd-worker.md` is
the interactive copy Claude Code loads when `setting_sources=["project"]`, but
the dev-loop's `DevelopmentNode` dispatch path only ever reads the
package-vendored copy at `packages/ai-parrot/src/parrot/flows/dev_loop/
_subagent_data/sdd-worker.md` via `load_subagent_definition("sdd-worker")` —
it never reads `.claude/agents/` at runtime. The two copies are required to
stay byte-identical, enforced by the existing
`test_subagent_parity.py::test_prompt_parity[sdd-worker]`.

Commit `461b74c2e` (FEAT-543/TASK-3090, "SDD delegation workflow across
templates, commands, skills and sdd-worker") added a new
"b2) Delegated implementation" step (24 lines) plus one verification-checklist
line to `.claude/agents/sdd-worker.md`, but never applied the matching edit to
the vendored `_subagent_data/sdd-worker.md` copy. This is the exact same class
of bug `41869c675` ("sync vendored sdd-worker prompt") already fixed once
before for a different missing section — the sync step is a manual, easy-to-
forget discipline, not an automated one.

**Effect**: every dev-loop dispatch of `sdd-worker` (via `DevelopmentNode`) is
currently missing the Delegation Contract instructions that interactive
sessions have — a dispatched worker will never attempt `writer_generate`/
`writer_apply` delegation for an eligible task, silently falling back to
always implementing normally. Not a crash, but a silent capability gap
between the two dispatch paths, and it leaves
`test_subagent_parity.py::test_prompt_parity[sdd-worker]` permanently red on
`dev`.

### Goals

- **G1** — `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/
  sdd-worker.md` is byte-identical to `.claude/agents/sdd-worker.md` again.
- **G2** — `pytest packages/ai-parrot/tests/flows/dev_loop/
  test_subagent_parity.py -v` passes in full (currently 1 failure).

### Non-Goals (explicitly out of scope)

- **Automating the sync** (e.g. a pre-commit hook, a `scripts/sdd/
  sync_subagent_twins.py` helper, or folding the four dual-sourced prompts
  into a single source of truth). This spec restores parity for the one
  prompt that drifted; a general anti-drift mechanism is a separate,
  larger design decision (there are three other dual-sourced prompts —
  `sdd-research`, `sdd-qa`, `sdd-secondopinion` — an automation would need to
  cover all four, not just this one) and is left for a human to decide
  whether it's worth the added tooling surface.
- **Any other content change to `sdd-worker.md`** beyond restoring the missing
  block verbatim — no rewording, no new sections, no opinion on the
  Delegation Contract mechanism itself (that mechanism is FEAT-543's design,
  already merged and out of scope to revisit here).
- **Changes to any other dual-sourced prompt** (`sdd-research`, `sdd-qa`,
  `sdd-secondopinion`) — `test_subagent_parity.py` reports all four are
  currently green except `sdd-worker`; only that one is touched.

---

## 2. Architectural Design

### Overview

A single-file synchronization: copy `.claude/agents/sdd-worker.md` verbatim
over `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/
sdd-worker.md`, restoring byte-parity. No Python logic changes — `.claude/
agents/sdd-worker.md` is already the source of truth per `_subagent_defs.py`'s
own docstring ("repo is the newer, edited-by-humans copy; package is what
dispatch actually uses").

### Component Diagram

```
.claude/agents/sdd-worker.md  (source of truth, edited by humans/FEAT-543)
             │
             │  full-file copy (this spec's only change)
             ▼
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
             │
             ▼
load_subagent_definition("sdd-worker")  ──►  DevelopmentNode dispatch prompt
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | modifies (full-file sync) | brought back to byte-parity with the repo twin |
| `.claude/agents/sdd-worker.md` | read only (source of truth) | unmodified — this file is already correct |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | unmodified | `load_subagent_definition()` behavior unchanged; referenced only to confirm the dispatch path reads `_subagent_data/`, never `.claude/agents/` |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` | unmodified (existing test is the verification) | `test_prompt_parity[sdd-worker]` goes from failing to passing |

### Data Models

None — this is a markdown-file sync, no new data structures.

### New Public Interfaces

None. `## 3. Module Breakdown` below marks its single module's Interface
Skeleton `n/a (markdown file sync; no code)`, the same convention FEAT-546
used for its own non-Python modules.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Sync `_subagent_data/sdd-worker.md` | yes | Exact source: `.claude/agents/sdd-worker.md` at `dev@5982d7449`. Exact target: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`. Exact operation: full-file byte-for-byte copy (no partial merge — see Implementation Notes for why). | — |

### Module 1: Sync `_subagent_data/sdd-worker.md`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`
- **Responsibility**: Restore byte-parity with `.claude/agents/sdd-worker.md`
  by replacing the entire file content with the source file's content.
- **Depends on**: none
- **Interface Skeleton**: n/a (markdown file sync; no code)

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_prompt_parity[sdd-worker]` (existing, currently failing) | Module 1 | Asserts `_subagent_data/sdd-worker.md` == `.claude/agents/sdd-worker.md` byte-for-byte |
| `test_worker_prompt_has_per_spec_index_instructions` (existing) | Module 1 (regression guard) | Confirms the dispatched body still contains the FEAT-145 per-spec-index instructions after the sync |

### Integration Tests
| Test | Description |
|---|---|
| `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` | Full file: all `test_prompt_parity[*]` cases plus the two content-assertion tests must pass |

### Test Data / Fixtures
None new — both tests above already exist and require no new fixtures.

---

## 5. Acceptance Criteria

- [ ] **AC-1** `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` is byte-identical to `.claude/agents/sdd-worker.md` (`diff` produces no output).
- [ ] **AC-2** `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` passes in full (0 failures).
- [ ] **AC-3** No file other than `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` is modified (`git diff --stat` confirms exactly one file changed).
- [ ] **AC-4** `load_subagent_definition("sdd-worker")` (imported and called directly, or exercised via the existing `test_worker_prompt_has_per_spec_index_instructions`) still returns a non-empty body containing the FEAT-145 per-spec-index instructions — confirms the sync did not corrupt frontmatter-stripping.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All anchors verified on `dev` at `5982d7449` (2026-09-10), i.e. AFTER
> FEAT-546 merged (PR #1355, merge commit `933b294bf`).

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:86
```
No new imports needed — this task is a file-content sync, not a code change.

### Existing File Anchors
```text
# .claude/agents/sdd-worker.md  (414 lines) — SOURCE, unmodified
  :1-9   frontmatter (name: sdd-worker, description: ...)
  :229-252  "### b2) Delegated implementation (ONLY when a Delegation Contract exists)"
            — present here, MISSING from the target today
  :267   "□ Delegated patch hunks were all reviewed before writer_apply?"
            — present here, MISSING from the target today

# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md  (389 lines) — TARGET, this task's only edit
  Verified via `diff .claude/agents/sdd-worker.md
  packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`:
  the ONLY delta today is the missing 24-line "b2)" block (source lines
  229-252) and the missing checklist line (source line 267) — frontmatter and
  every other line already match. A full-file copy is therefore equivalent to
  a targeted two-block insertion; the spec mandates the full-file copy because
  it is simpler to verify (byte-diff to zero) and cannot leave a third,
  undetected drift in place if one exists that a naive re-diff missed.

# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py (115 lines) — READ ONLY, not modified
  :86  def load_subagent_definition(name: str) -> str:
  :108 data_dir = files("parrot.flows.dev_loop") / "_subagent_data"
  :109 target = data_dir / f"{name}.md"

# packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py (89 lines) — READ ONLY, not modified (existing test IS the verification)
  :43-65  test_prompt_parity(name) — parametrized over all _subagent_data/*.md stems
  :81-88  test_worker_prompt_has_per_spec_index_instructions() — content regression guard
```

### Does NOT Exist (Anti-Hallucination)
- ~~A sync automation script (`scripts/sdd/sync_subagent_twins.py` or similar)~~ —
  does not exist; explicitly NOT created here (non-goal)
- ~~A pre-commit hook enforcing dual-sourced prompt parity~~ — does not exist;
  explicitly NOT created here (non-goal)
- ~~Any runtime code path that reads `.claude/agents/` from `_subagent_defs.py`~~ —
  confirmed by its own module docstring: "It does NOT read `.claude/agents/`
  at runtime."

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Full-file copy over a targeted patch**: even though today's drift is a
  single contiguous block, copy the ENTIRE source file content rather than
  hand-editing the two missing spots — a byte-for-byte copy is trivially
  verifiable (`diff` produces nothing) and immune to a second, unnoticed
  drift elsewhere in the file that a human-authored patch might miss.
- **Established precedent**: commit `41869c675` ("fix(dev-loop): sync
  vendored sdd-worker prompt; pool e2e files_changed") fixed this exact same
  class of drift once before, for a different missing section
  ("Structured Output Contract"). Same file pair, same fix shape.

### Known Risks / Gotchas
- **This bug WILL recur** unless the underlying discipline (manually syncing
  4 dual-sourced prompts on every edit to `.claude/agents/`) changes — this
  is the second time the exact same file pair has drifted. Explicitly not
  fixed by automation here (non-goal); noted for whoever eventually decides
  to invest in that tooling.
- **Frontmatter must be preserved, not stripped**: `_subagent_data/sdd-worker.md`
  keeps its own YAML frontmatter on disk; `_strip_frontmatter()` strips it
  only at read time (`_subagent_defs.py:61-83`). A full-file copy naturally
  preserves this — do not manually strip frontmatter before writing the
  target file.

### External Dependencies
None new.

---

## 8. Open Questions

- [ ] **Should the 3 other dual-sourced prompts (`sdd-research`, `sdd-qa`,
  `sdd-secondopinion`) be spot-checked for the same kind of drift while this
  is being fixed**, even though `test_subagent_parity.py` currently reports
  them green? — *Owner: Jesus Lara* — default: no, out of scope here (the
  existing test already covers all four and is the authoritative check;
  re-verifying it by hand adds no signal beyond running it).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted
> exploration doc. Model: n/a · **Status: skipped (requirements pre-sourced
> from FEAT-546's own adversarial code review, which already identified and
> triaged this exact gap as a documented follow-up — see Origin note above;
> there is no separate exploration document to run design research over, and
> the fix is a single verifiable file-sync with no design decisions left
> open)** · Transcript: n/a

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | *(skipped — see Status above)* | | | |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — the single task runs in one
  worktree (`feat-FEAT-547-sdd-worker-prompt-twin-sync`). Given the size (one
  file, one commit), a worktree is arguably heavier than needed per
  `CLAUDE.md`'s "Quick bug fixes: If the fix is a single commit, skip the
  worktree ceremony" guidance — left as `per-spec` here only for SDD-state
  consistency with every other feature; the executing agent may skip the
  worktree ceremony and fix it directly on a short-lived branch if that is
  faster, as long as the same acceptance criteria are verified.
- **Cross-feature dependencies**: none. Builds on FEAT-543 (merged,
  `461b74c2e`) and FEAT-546 (merged, PR #1355) only as historical context —
  no code from either is touched.
- **Runtime dependency**: none — no external services or credentials needed
  to implement or verify this task.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-10 | Jesus Lara (with Claude Sonnet 5) | Initial draft — follow-up to FEAT-546's documented AC-10 finding (pre-existing `sdd-worker.md` twin drift from FEAT-543/TASK-3090) |
