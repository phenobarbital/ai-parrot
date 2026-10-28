# TASK-4876: A2UI stream contract tests match the reformatted handler

**Feature**: FEAT-767 — A2UI stream contract tests match the reformatted handler
**Spec**: `sdd/specs/fixgroup-daf508b68d1c.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:46f02d0469bb`

---

## Context

Ledger `issue:46f02d0469bb`: two source-grep contract tests in
`test_agent_a2ui_stream.py` fail because `parrot/handlers/agent.py` was
reformatted from single to double quotes. The contract itself is intact.

## Scope

- Make the header, separator and final-dict envelope assertions quote-agnostic (regex with `["']`).
- Keep each assertion specific enough to fail if the contract code is removed.

**NOT in scope**: any change to `parrot/handlers/agent.py`; the non-stream and FEAT-470 tests (they pass).

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path
import re
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py (current source text)
"X-Parrot-Stream": "chunked-aimessage",
a2ui_envelope = getattr(ai_message, "a2ui_envelope", None)
envelope["a2ui_envelope"] = a2ui_envelope
```

### Does NOT Exist
- The single-quoted forms `'X-Parrot-Stream': 'chunked-aimessage'` and `getattr(ai_message, 'a2ui_envelope', None)` in the handler.

## Acceptance Criteria

- [ ] `test_chunked_wire_contract_unchanged` and `test_a2ui_envelope_added_to_final_stream_dict` pass.
- [ ] All tests in the file pass.
- [ ] No change to `parrot/handlers/agent.py`.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -q`

## Agent Instructions

Implement in the FEAT-767 worktree only; commit code, then close with `scripts/sdd/close_task.sh`.

## Completion Note

**Completed by**: Claude Code (/sdd-fix issue:46f02d0469bb)
**Date**: 2026-10-28
**Notes**: Implemented in f7da5ffbe. Root cause: `black` rewrote `parrot/handlers/agent.py` to double quotes; the contract code was intact. The header, separator and final-dict envelope assertions now use a `_has()` regex helper where `{q}` matches either quote. Reproduced 2 failed / 3 passed before; 5 passed after. Checked each pattern matches the real handler and fails when its contract snippet is mutated. ruff and black clean. `parrot/handlers/agent.py` untouched.
**Deviations from spec**: none
