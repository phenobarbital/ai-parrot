# TASK-3106: Sync `_subagent_data/sdd-worker.md` with its repo twin

**Feature**: FEAT-547 — Sync `sdd-worker` Packaged Prompt Twin
**Spec**: `sdd/specs/sdd-worker-prompt-twin-sync.spec.md` (§3 Module 1)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`sdd-worker` is dual-sourced: `.claude/agents/sdd-worker.md` is the
interactive copy Claude Code loads; `packages/ai-parrot/src/parrot/
flows/dev_loop/_subagent_data/sdd-worker.md` is the package-vendored copy
`load_subagent_definition("sdd-worker")` actually dispatches at runtime.
They are required to be byte-identical
(`test_subagent_parity.py::test_prompt_parity[sdd-worker]`).

Commit `461b74c2e` (FEAT-543/TASK-3090) added a 24-line "b2) Delegated
implementation" section plus one checklist line to `.claude/agents/
sdd-worker.md` but never applied the matching edit to the vendored copy.
This was discovered (not fixed — out of scope there) by FEAT-546's own
TASK-3105 AC-10 check. This task restores byte-parity.

---

## Scope

- Replace the full content of `packages/ai-parrot/src/parrot/flows/
  dev_loop/_subagent_data/sdd-worker.md` with the full content of
  `.claude/agents/sdd-worker.md` (byte-for-byte copy — see Implementation
  Notes for why a full-file copy, not a targeted patch).

**NOT in scope**: any change to `.claude/agents/sdd-worker.md` (it is
already correct — the source of truth); any change to `_subagent_defs.py`;
any change to the other 3 dual-sourced prompts (`sdd-research`, `sdd-qa`,
`sdd-secondopinion`); building a sync-automation script (spec Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY (full-file replace) | Restore byte-parity with `.claude/agents/sdd-worker.md` |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` at `0ce2eb142` (2026-09-10), after FEAT-546 merged
> (PR #1355, merge commit `933b294bf`). Re-grep before editing — line
> numbers may shift if either file changes between now and execution.

### Verified Imports
```python
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:86
```
No new imports — this task is a file-content sync, not a code change; it
does not touch any `.py` file.

### Existing Signatures to Use
Not applicable — no Python is modified. The only relevant "signature" is
the file-pair contract itself:
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_defs.py:108-110
data_dir = files("parrot.flows.dev_loop") / "_subagent_data"
target = data_dir / f"{name}.md"
text = target.read_text(encoding="utf-8")
```

### Does NOT Exist
- ~~A sync automation script~~ — does not exist; not created by this task
  (spec non-goal)
- ~~Any runtime read of `.claude/agents/` from `_subagent_defs.py`~~ —
  confirmed absent by that module's own docstring
- ~~A `## Delegation Contract` for this task~~ — intentionally omitted; a
  full-file byte-for-byte copy is simpler to specify and verify directly
  than to encode as a delegation packet (see Implementation Blueprint)

---

## Implementation Notes

### Pattern to Follow
Established precedent: commit `41869c675` ("fix(dev-loop): sync vendored
sdd-worker prompt; pool e2e files_changed") fixed this exact same class of
drift once before (a different missing section, same file pair, same fix
shape — read the source file in full, write it verbatim to the target
path).

### Key Constraints
- Copy the ENTIRE file, not just the missing block(s) — verified today
  (`diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/
  flows/dev_loop/_subagent_data/sdd-worker.md`) to differ by exactly one
  contiguous 24-line block (source lines 229-252, "### b2) Delegated
  implementation...") plus one checklist line (source line 267) — but a
  full-file copy is mandated regardless, so a byte-diff to zero is the
  verification, immune to any other undetected drift.
- Do NOT hand-edit `.claude/agents/sdd-worker.md` — it is already correct
  (the source of truth per `_subagent_defs.py`'s own docstring: "repo is
  the newer, edited-by-humans copy; package is what dispatch actually
  uses").
- Preserve the target file's YAML frontmatter as part of the full-file
  copy — do not strip it. (`_strip_frontmatter()` in `_subagent_defs.py`
  only strips it at *read* time; the file on disk keeps it, and both
  files' frontmatter already match today, so a full copy carries it over
  correctly without any special handling.)

### References in Codebase
- `.claude/agents/sdd-worker.md` — the full source content to copy
- `packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py:43-65` —
  the existing test that verifies the fix (byte-equality assertion)

---

## Implementation Blueprint

> This task has no code blocks to fill in — it is a full-file content copy,
> not new logic. The "block" below is the exact operation to perform, not a
> code skeleton with `FILL IN` markers.

### Steps (in order)
1. Read the full content of `.claude/agents/sdd-worker.md` — *why*: it is
   the source of truth and must be copied verbatim, not retyped or
   paraphrased (spec AC-1).
2. Write that exact content, unchanged, to `packages/ai-parrot/src/parrot/
   flows/dev_loop/_subagent_data/sdd-worker.md`, overwriting its current
   content — *why*: restores byte-parity (spec AC-1, AC-2).
3. Verify with `diff .claude/agents/sdd-worker.md packages/ai-parrot/
   src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` — expect no
   output — *why*: this is the acceptance check the existing
   `test_prompt_parity[sdd-worker]` also performs (spec AC-1, AC-2).

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (MODIFY — full-file replace)
```text
# operation: overwrite this file's entire content with the verbatim
# content of .claude/agents/sdd-worker.md (414 lines as of dev@0ce2eb142).
# Do not summarize, reformat, or partially merge — full replace only.
# Suggested command (equivalent to a Read of the source + Write of the
# target with identical content):
cp .claude/agents/sdd-worker.md \
   packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
```
**Why this shape**: the spec (§7 Implementation Notes) mandates a full-file
copy over a targeted two-block patch specifically because it is trivially
verifiable (`diff` → empty) and cannot leave a third, unnoticed drift in
place — a hand-applied patch could silently miss something a naive re-diff
overlooked. This is not new code, so there is nothing to fill in.

### FILL IN checklist
- [ ] none — this is a mechanical full-file copy with no judgement calls
  left open.

---

## Acceptance Criteria

- [ ] `diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` produces no output (spec AC-1)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` passes in full, 0 failures (spec AC-2)
- [ ] `git diff --stat` shows exactly one file changed: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (spec AC-3)
- [ ] `python -c "from parrot.flows.dev_loop._subagent_defs import load_subagent_definition; b = load_subagent_definition('sdd-worker'); assert 'FEAT-145' in b and 'per-spec index' in b"` succeeds without error (spec AC-4)

---

## Test Specification

No new test file — the existing `test_subagent_parity.py` is the
verification (spec §4). Run with the venv active:
```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v
diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
```

---

## Agent Instructions

1. Read spec §3 Module 1 and §7 Implementation Notes.
2. Dependencies: none.
3. Re-verify the Codebase Contract's `diff` claim (source drift may have
   changed since this task was written) before copying.
4. Update status in `sdd/tasks/index/sdd-worker-prompt-twin-sync.json` →
   `"in-progress"`.
5. Perform the full-file copy exactly as the Implementation Blueprint
   describes.
6. Verify every acceptance criterion; commit only the one target file.
7. Move this file to `sdd/tasks/completed/`, update index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
