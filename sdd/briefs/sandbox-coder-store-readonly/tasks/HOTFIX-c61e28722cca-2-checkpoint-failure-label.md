# HOTFIX-c61e28722cca-2: Give the engine-path checkpoint failure its own label

**Feature**: brief `sandbox-coder-store-readonly` (ledger `issue:c61e28722cca`)
**Spec**: `sdd/briefs/sandbox-coder-store-readonly.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

When `parrot sdd task review prepare` failed on the read-only store, the worker
reported `checkpoint: unsupported_host` and went on to code review. That label
is reserved for the **no-engine** path — the Fallback loop, where there is no
settlement to checkpoint against and the absence is correct and expected. An
engine-path write failure is a different condition with a different meaning: a
checkpoint *should* exist and does not, so the review that follows is not
covered by neutral evidence.

The prompt offers no label for that case, so the worker reached for the nearest
one. The result reads as a host limitation in the completion summary when it is
a bug — exactly the kind of misreport that hides a defect.

HOTFIX-c61e28722cca-1 removes the cause that triggered it here. This task makes
the next unrelated store failure report itself honestly.

---

## Scope

- In the Completion section's engine-path bullet, add an explicit branch for
  "the engine settled, but the checkpoint could not be persisted or reloaded",
  labelled `checkpoint: evidence_persistence_failed`.
- State that the review proceeds but is **not** covered by neutral evidence, and
  that the worker must say so in the completion summary.
- State that `unsupported_host` is for the no-engine path only and must not be
  reused for a store failure.
- Apply the identical edit to both twins of the prompt.

**NOT in scope**:

- Any change to `review_checkpoint.py`, `checkpoint.py` or the engine. The
  label is a reporting contract in the prompt, not a new code path.
- The `unsupported_host` usages in `sdd-start.md`, `sdd-start/SKILL.md`,
  `sdd/CODEX.md` and `.agent/agents/sdd-worker/agent.md`. Those are about
  *compaction* on an unverified host — a genuinely different condition, and
  those files carry no engine-path checkpoint bullet (verified: grep for
  `review prepare` matches only the two Claude twins).
- The sandbox bind — that is HOTFIX-c61e28722cca-1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Add the engine-path failure branch (`git add -f`) |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | Byte-identical twin |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Assert the new label and that both labels coexist |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# test_worker_prompt_orchestrator.py already provides both helpers it needs:
#   load_subagent_definition("sdd-worker")
#   _completion_section(...)
# verified in use at test_worker_prompt_orchestrator.py:191-193
```

### Existing Signatures to Use

```text
# .claude/agents/sdd-worker.md:633-639 and its twin
# packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md:633-639
#
#   633:     `parrot sdd task review prepare --feature <FEAT-ID> --worktree <path> --execution-id <uuid>`.
#   635:     fails with `checkpoint_busy` if any child/reservation/validation has not durably settled. …
#   637:   - **No-engine variant (Fallback loop, or the MCP server was never available).** …
#   639:     path never calls. Do not invent a substitute settlement API. Record `checkpoint: unsupported_host` in your
```

Both files are byte-identical today (verified:
`diff -q .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`).

### Existing tests that must stay green

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:191-196
def test_worker_prompt_completion_has_explicit_no_engine_variant():
    completion = _completion_section(load_subagent_definition("sdd-worker"))
    assert "No-engine variant" in completion
    assert "unsupported_host" in completion
    assert "parrot sdd task review validate" in completion

# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:185-188
#   the Fallback loop section must NOT mention "task review prepare" /
#   "review_checkpoint prepare" -- so the new branch belongs in the ENGINE
#   bullet of the Completion section, never in the Fallback loop section.
```

The change is **additive**: `unsupported_host` stays in the no-engine bullet,
so both tests above keep passing unchanged.

### Does NOT Exist

- ~~a `checkpoint:` label vocabulary listed anywhere in the prompt~~ — the only
  label present is `unsupported_host` at line 639.
- ~~`evidence_persistence_failed` in `sdd-worker.md`~~ — the string exists only
  in engine source and docs today; this task introduces it to the prompt.
- ~~an engine-path checkpoint bullet in `.agent/agents/sdd-worker/agent.md`~~ —
  that Codex prompt has no `review prepare` mention at all.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key constraints

- **Both twins, byte-identical.** `.claude/agents/sdd-worker.md` is covered by
  a `.gitignore` rule and needs `git add -f`. A prompt edit applied to only one
  twin is a silent divergence: the installed asset and the live agent drift
  apart with nothing failing.
- **Engine bullet only.** `test_worker_prompt_completion_rejects_engine_calls_in_fallback`
  (`test_worker_prompt_orchestrator.py:185-188`) asserts the Fallback loop
  section never mentions `task review prepare`. Putting the new branch there
  would break it — and would be wrong anyway.
- Keep the existing imperative register of the surrounding bullets ("Do not
  invent a substitute settlement API", "Never invoke `/compact` through Bash").
- `evidence_persistence_failed` is the name the engine already uses for this
  condition (`_resolve_durable_root`'s warning,
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:590-625`).
  Reuse it rather than coining a new word.

---

## Implementation Blueprint

### Steps (in order)

1. Insert the new sub-bullet in both twins, immediately after the engine-path
   bullet that ends with the `checkpoint_busy` / `checkpoint_id` sentence
   (line 636) and before `- **No-engine variant …` (line 637) — *why*: it is a
   failure mode of the bullet above it, and it must not land in the Fallback
   section.
2. Amend the no-engine bullet to say `unsupported_host` is for that path only.
3. Add the test.
4. Confirm the twins are still byte-identical.

### `.claude/agents/sdd-worker.md` and its asset twin (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'No-engine variant' .claude/agents/sdd-worker.md)
# BEFORE — insert above the line beginning
#   `   - **No-engine variant (Fallback loop, or the MCP server was never available).**`
#   (verified: .claude/agents/sdd-worker.md:637)
   - **Checkpoint could not be persisted (engine path).** The engine settled, but `review prepare` (or the
     `validate` that follows) failed to write or reload the checkpoint — an unwritable or unreachable durable
     evidence store, for example. This is NOT `unsupported_host`: a checkpoint was due and is missing, so the
     review that follows is not covered by neutral evidence. Record `checkpoint: evidence_persistence_failed`
     plus the verbatim error in your completion summary, say in that summary that the review ran without a
     persisted checkpoint, and continue to code review. Do not retry in a loop and do not fabricate a
     `checkpoint_id`.
```

**Why this shape**: it mirrors the two bullets around it (bold lead-in, the
condition, the label, the explicit "do not" list). Naming
`unsupported_host` inside it is what stops the next worker from reaching for
the wrong label, which is the whole point of the task.

```markdown
# occurrences: 1 (verified: grep -c 'Record `checkpoint: unsupported_host`' .claude/agents/sdd-worker.md)
# AFTER — append to the sentence at .claude/agents/sdd-worker.md:639-641 that ends
#   "...and continue straight to code review below on the current worktree state."
     This label means "this host/path has no engine settlement to checkpoint", nothing else — never use it for
     an engine-path failure to write or reload the checkpoint.
```

### FILL IN checklist

- [ ] Re-wrap both inserts to the file's existing column width and indentation
      before committing; match the surrounding bullets exactly.

---

## Acceptance Criteria

- [ ] The Completion section contains an engine-path branch labelled
      `checkpoint: evidence_persistence_failed`.
- [ ] That branch states the review is not covered by neutral evidence and must
      be reported as such.
- [ ] The no-engine bullet still records `unsupported_host` and now says it is
      for that path only.
- [ ] The Fallback loop section still contains no `task review prepare` /
      `review_checkpoint prepare` mention.
- [ ] `diff .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`
      is empty.
- [ ] `test_worker_prompt_completion_has_explicit_no_engine_variant` and
      `test_start_optimization_contract.py`'s `unsupported_host` assertions pass
      unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_start_optimization_contract.py -q`

Run with `PYTHONPATH=<worktree>/packages/ai-parrot/src` (absolute).

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py


def test_worker_prompt_completion_labels_engine_checkpoint_failure():
    """An engine-path store failure has its own label: `unsupported_host` means
    'no engine settlement exists', never 'the checkpoint write failed'."""
    completion = _completion_section(load_subagent_definition("sdd-worker"))
    assert "evidence_persistence_failed" in completion
    # Both labels coexist: the no-engine bullet keeps unsupported_host.
    assert "unsupported_host" in completion
    # The new branch belongs to the engine path, not the Fallback loop.
    fallback = _fallback_loop(load_subagent_definition("sdd-worker"))
    assert "evidence_persistence_failed" not in fallback


def test_sdd_worker_prompt_twins_are_identical():
    """A prompt edit applied to one twin only drifts silently."""
    # FILL IN: read both paths from the repo root and assert equal text.
    #   .claude/agents/sdd-worker.md
    #   packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md
```

---

## Agent Instructions

1. **Work in the brief worktree** —
   `.parrot/worktrees/fix-c61e28722cca-sandbox-coder-store-readonly`.
2. **Read the brief** at `sdd/briefs/sandbox-coder-store-readonly.brief.md`.
3. **Verify the Codebase Contract** — re-check the line numbers; `dev` moves.
4. **Implement** the three files listed, nothing else.
5. **Validate** — the two Validation Commands with an absolute `PYTHONPATH`.
6. **Commit** — `fix(sdd-worker): HOTFIX-c61e28722cca-2 — label engine-path checkpoint failures`.
   `.claude/agents/sdd-worker.md` needs `git add -f`.
7. **Fill in the Completion Note** below and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from brief**: none | describe if any
