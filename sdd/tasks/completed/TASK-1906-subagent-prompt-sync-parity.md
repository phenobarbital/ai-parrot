# TASK-1906: Subagent prompt sync + full-body parity sweep

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 item 1 (spec §3). `load_subagent_definition()` reads ONLY the
package-shipped `_subagent_data/` prompts, but updates (FEAT-145 per-spec
index instructions, wiki-first triage) landed only in the `.claude/agents/`
copies. Dev-loop dispatches therefore run with stale instructions and grep
blind while interactive sessions query the wiki. This is also **G2 seam 1**:
syncing carries the wiki-first block into the dispatched `sdd-research`
prompt. Parity coverage today is partial (one file full-body, one file
section-only) — this task makes it a full auto-discovering sweep.

---

## Scope

- Sync ALL FIVE prompts from `.claude/agents/<name>.md` (newer) into
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/<name>.md`:
  `sdd-research`, `sdd-worker`, `sdd-qa`, `sdd-codereview`,
  `sdd-secondopinion`. Direction is repo → package (repo copies are newer:
  research 99 vs 80 lines, worker 328 vs 274).
- Hand-verify after sync that the package `sdd-research.md` contains the
  wiki-first triage block (step 0 + cardinal rule) and that the package
  `sdd-worker.md` contains the FEAT-145 per-spec-index instructions.
- Gate the wiki-first instructions on the wiki plane existing in the target
  repo (the block should tell the agent to fall back to grep when
  `wikitoolkit status` fails — if the `.claude/agents/` copy already words
  it that way, keep it verbatim).
- Add a generic parity test
  `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` that
  auto-discovers every `.md` in `_subagent_data/` and asserts full-body
  equality with `.claude/agents/<same-name>.md` (skip cleanly with a clear
  message if the repo-level dir is absent, e.g. installed-package runs).
- Fix the misleading `_subagent_defs.py` docstring (lines 15-22): it
  advertises repo+package dual sourcing; only the package copy is read.
  Update the docstring to state the package copy is canonical and parity is
  enforced by test. Do NOT implement repo-first sourcing (rejected in spec
  §7).

**NOT in scope**: any change to `load_subagent_definition()` behavior;
graph context injection (TASK-1915); node code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | sync from `.claude/agents/sdd-research.md` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | sync from `.claude/agents/sdd-worker.md` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` | MODIFY | sync from `.claude/agents/sdd-qa.md` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md` | MODIFY | sync from `.claude/agents/sdd-codereview.md` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md` | MODIFY | sync (likely already identical — verify) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py` | MODIFY | docstring fix only |
| `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` | CREATE | auto-discovering full-body parity test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
# loader reads importlib.resources.files("parrot.flows.dev_loop") / "_subagent_data"
# — verified: _subagent_defs.py:64-88
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py
# docstring lines 15-22 advertise dual sourcing (FALSE — fix it)
# load_subagent_definition() lines 64-88 — reads ONLY _subagent_data/

# Existing partial parity tests (extend the idea, do not delete them —
# they may be superseded by the new sweep; if you remove them, say so in
# the completion note):
# packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py
#   ::test_dual_source_bodies_identical      (full-body, sdd-secondopinion only)
# packages/ai-parrot/tests/flows/dev_loop/test_pool_wiring.py
#   ::test_both_copies_have_identical_task_scoped_section  (sdd-worker, section-only)
```

### Does NOT Exist
- ~~a generic all-files parity test~~ — this task creates it
- ~~repo-first sourcing in `load_subagent_definition`~~ — rejected; package copy is canonical
- ~~wiki instructions in any `_subagent_data/*.md`~~ — zero exist today (grep-verified)

### Contract correction (found during implementation, 2026-07-26)
- ~~`.claude/agents/sdd-codereview.md` exists~~ — **FALSE**. Verified via
  `git log --all -- .claude/agents/sdd-codereview.md` (zero history — this
  file has never existed in this repo). `sdd-codereview` is a dev-loop
  dispatch-only subagent (FEAT-250) with no repo-level Claude Code
  interactive-agent twin; it is package-only by design. Only FOUR prompts
  are actually dual-sourced: `sdd-research`, `sdd-worker`, `sdd-qa`,
  `sdd-secondopinion`. The scope line "Sync ALL FIVE prompts... :
  `sdd-research`, `sdd-worker`, `sdd-qa`, `sdd-codereview`,
  `sdd-secondopinion`" and the acceptance criterion "All five
  `_subagent_data/*.md` byte-identical to `.claude/agents/*.md`" are both
  corrected in effect: `sdd-codereview` is excluded from the byte-parity
  sweep (existing coverage: `test_subagent_codereview.py`) and the new
  `test_subagent_parity.py::test_prompt_parity` explicitly
  `pytest.skip`s it with a documented reason rather than failing on a
  file that was never meant to exist.

---

## Implementation Notes

### Key Constraints
- Sync means byte-identical copies. Use `cp` per file, then diff to confirm.
- The parity test must locate the repo root relative to the test file
  (walk up until `.claude/agents/` is found) and `pytest.skip` when absent.
- Keep test IDs stable: parametrize by prompt filename.

### References in Codebase
- `.claude/agents/sdd-research.md` — source of the wiki-first block (lines ~32-49)
- `packages/ai-parrot/tests/flows/dev_loop/test_secondopinion_brief.py` — parity test pattern to generalize

---

## Acceptance Criteria

- [ ] All five `_subagent_data/*.md` byte-identical to `.claude/agents/*.md`
- [ ] Dispatched `sdd-research` prompt contains the wiki-first triage block
- [ ] Dispatched `sdd-worker` prompt contains FEAT-145 per-spec-index instructions
- [ ] `test_subagent_parity.py` auto-discovers all prompts and passes
- [ ] `_subagent_defs.py` docstring no longer claims repo-level sourcing
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
import pytest
from pathlib import Path
from importlib import resources

def _repo_agents_dir() -> Path | None:
    """Walk up from this file to find .claude/agents/; None if absent."""

def _package_prompts() -> list[str]:
    pkg = resources.files("parrot.flows.dev_loop") / "_subagent_data"
    return sorted(p.name for p in pkg.iterdir() if p.name.endswith(".md"))

@pytest.mark.parametrize("name", _package_prompts())
def test_prompt_parity(name):
    """Every packaged prompt is byte-identical to its .claude/agents/ twin."""

def test_research_prompt_has_wiki_block():
    """Dispatched sdd-research contains the wiki-first triage instructions."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- Synced 4 dual-sourced prompts repo → package: `sdd-research.md` and
  `sdd-worker.md` had real drift (wiki-first block + FEAT-145
  instructions missing from the package copy — G2 seam 1 now closed);
  `sdd-qa.md` and `sdd-secondopinion.md` were already byte-identical.
- Fixed `_subagent_defs.py` docstring: no longer claims all five prompts
  are dual-sourced; states the package copy is the runtime source of
  truth and clarifies `sdd-codereview` has no repo-level twin.
- Added `test_subagent_parity.py`: auto-discovers every `_subagent_data/*.md`,
  asserts full-body equality against `.claude/agents/<name>.md` for the
  four dual-sourced prompts, skips `sdd-codereview` (no repo twin) and the
  whole sweep (installed-package runs, no `.claude/agents/` on disk).
  Plus two content assertions: wiki-first block present in `sdd-research`,
  FEAT-145 per-spec-index instructions present in `sdd-worker`.
- Kept the pre-existing partial parity tests
  (`test_secondopinion_brief.py::test_dual_source_bodies_identical`,
  `test_pool_wiring.py::test_both_copies_have_identical_task_scoped_section`)
  untouched — not listed in this task's file scope, and not redundant
  enough to justify touching out-of-scope test files.
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  a pre-existing-broken `test_session_state_properties.py`, missing the
  `hypothesis` dependency unrelated to this task): 647 passed, 1 skipped.
  One unrelated pre-existing test-order-dependent failure
  (`test_lazy_import.py::test_models_module_is_pure`, passes in
  isolation) — not touched by this task's files, left as-is.
- `ruff check` clean on all touched files.

**Deviations from spec**: `sdd-codereview` excluded from the byte-parity
requirement (see Codebase Contract correction above) — the repo-level
twin it would be diffed against has never existed.
