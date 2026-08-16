# TASK-1900: `sdd-secondopinion` neutral subagent brief

**Feature**: FEAT-375 — Codex CLI Adversarial Second-Opinion Agent
**Spec**: `sdd/specs/codex-cli-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-375 (spec §3, goal G2). The adversarial reviewer needs a
neutral persona: it receives the diff, the requirements, and the review
question ONLY — never the primary agent's reasoning (which would produce
ratification, not review). Briefs are dual-sourced markdown (FEAT-323
pattern) loaded by `load_subagent_definition`.

---

## Scope

- CREATE `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md`:
  YAML frontmatter (name, description) + body defining the persona:
  - You are an independent adversarial reviewer; you receive a diff,
    requirements/acceptance criteria, and a review question.
  - Findings must be specific and falsifiable (file, line, severity, message).
  - Advisory output only — you do NOT fix, commit, or prescribe auto-apply.
  - Output conforms to the structured-output instructions appended by the
    dispatcher (CodeReviewVerdict schema) — do not restate the schema in the brief.
  - Never assume access beyond the read-only sandbox.
  - Large diffs: if the diff exceeds what you can review thoroughly, review
    the highest-risk files fully and say explicitly which files you did not
    review (resolves spec §8 diff-size question with an honest-truncation default).
- CREATE `.claude/agents/sdd-secondopinion.md` — same content (repo-level copy).
- MODIFY `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py`:
  add `"sdd-secondopinion"` to `_VALID_NAMES` (line 32-34) and to the
  docstrings listing valid names (lines 3-11 and 66-67).
- Unit tests (see Test Specification).

**NOT in scope**: profile/model changes (TASK-1899), dispatcher prompt
composition (already generic via `load_subagent_definition`), packaging config
(`_subagent_data/*.md` is already included in the wheel — verify only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md` | CREATE | package-shipped brief |
| `.claude/agents/sdd-secondopinion.md` | CREATE | repo-level copy (dual-source) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | extend `_VALID_NAMES` + docstrings |
| `packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-26 on `dev` @ `ec6e0432a`.

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition  # _subagent_defs.py:62
```

### Existing Signatures to Use
```python
# _subagent_defs.py:32-34
_VALID_NAMES: frozenset[str] = frozenset(
    {"sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"}
)  # ← add "sdd-secondopinion"

# _subagent_defs.py:62-86
def load_subagent_definition(name: str) -> str:
    # raises ValueError if name not in _VALID_NAMES        # 78-82
    # reads files("parrot.flows.dev_loop") / "_subagent_data" / f"{name}.md"  # 83-85
    # returns body with YAML frontmatter stripped (_strip_frontmatter, :37-59)

# dispatcher.py:1153-1165 — how the brief is consumed (do NOT modify here)
def _build_codex_prompt(self, profile, brief, output_model) -> str:
    body = load_subagent_definition(profile.subagent)      # 1159
```

### Does NOT Exist
- ~~`sdd-secondopinion` anywhere~~ — this task creates the files + registry entry.
- ~~a loader for `.claude/agents/`~~ in `_subagent_defs.py` — the package loader
  reads ONLY `_subagent_data/`; `.claude/agents/` is consumed by Claude Code
  itself via `setting_sources=["project"]` (docstring :13-20). Both copies must
  exist; only `_subagent_data/` matters for codex dispatch.
- ~~`load_subagent_definition(path=...)`~~ — takes a bare name only.

---

## Implementation Notes

### Pattern to Follow
Copy the structure/tone of `_subagent_data/sdd-codereview.md` (frontmatter +
role + rules + output discipline); keep the body free of any placeholder for
caller reasoning.

### Key Constraints
- The two copies must have identical bodies (a test asserts this — FEAT-323
  precedent in `test_pool_wiring.py` for dual-sourced sdd-worker.md).
- Frontmatter must parse with `_strip_frontmatter` (leading `---` fence).

### References in Codebase
- `_subagent_data/sdd-codereview.md` — closest persona to adapt
- `packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py` — dual-source test pattern

---

## Acceptance Criteria

- [ ] `load_subagent_definition("sdd-secondopinion")` returns a non-empty body, frontmatter stripped
- [ ] Unknown names still raise `ValueError`
- [ ] `_subagent_data/sdd-secondopinion.md` and `.claude/agents/sdd-secondopinion.md` bodies identical
- [ ] Brief text contains no instruction to modify files or commit
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py -v` passes
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py
import pytest
from pathlib import Path
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

def test_secondopinion_brief_loads():
    body = load_subagent_definition("sdd-secondopinion")
    assert body and not body.startswith("---")

def test_unknown_name_still_raises():
    with pytest.raises(ValueError, match="Unknown subagent name"):
        load_subagent_definition("sdd-nonexistent")

def test_dual_source_bodies_identical():
    pkg = Path("packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md")
    repo = Path(".claude/agents/sdd-secondopinion.md")
    assert pkg.read_text() == repo.read_text()

def test_brief_is_advisory_only():
    body = load_subagent_definition("sdd-secondopinion").lower()
    assert "advisory" in body
    assert "do not fix" in body or "not fix" in body
```

---

## Agent Instructions

1. **Read the spec** for full context (§3 Module 2, G2)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/codex-cli-agent.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

Implemented exactly as specified:

- Created `_subagent_data/sdd-secondopinion.md` (persona adapted from
  `sdd-codereview.md`'s structure/tone): neutral adversarial reviewer,
  read-only, advisory-only (no write tools listed, `permissionMode:
  read-only`), findings must be specific/falsifiable, honest-truncation
  rule for large diffs, defers to the dispatcher's structured-output
  schema instead of restating it.
- Created identical `.claude/agents/sdd-secondopinion.md` copy (required
  `git add -f` — `.claude/` is globally excluded via `.git/info/exclude`
  but individual agent files, e.g. `sdd-worker.md`, are already
  force-tracked; followed the same precedent).
- Extended `_subagent_defs.py`: added `"sdd-secondopinion"` to
  `_VALID_NAMES`, updated the module docstring's subagent list, the
  `load_subagent_definition` Args docstring, and fixed a now-stale
  "three known subagents" phrase in the Raises docstring to
  "the known subagents" (pre-existing text made inaccurate by this and
  the prior FEAT-250 addition — not new scope creep, just keeping the
  docstring truthful given the change this task makes).
- `test_secondopinion_brief.py`: 4 tests per the Test Specification
  (loads + frontmatter stripped, unknown name still raises, dual-source
  bodies identical, advisory-only wording present).

Verification: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q` →
618 passed, 1 pre-existing failure (`test_models_module_is_pure`, same
known test-ordering-pollution issue noted in TASK-1899, unrelated to this
change), 5 skipped. `ruff check` clean on touched files.

No divergence from the task spec; no files touched outside the declared
list.
