# TASK-1755: Integration tests, import isolation, and docs

**Feature**: FEAT-303 — UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)
**Spec**: `sdd/specs/ux-custom-engine-copilot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1751, TASK-1752, TASK-1753, TASK-1754
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of FEAT-303 (spec §3). Per-module unit tests already
land with TASK-1751..1754; this task adds the cross-module verification: the
end-to-end card turn (send card → simulated click → second ask), the
import-isolation guarantee (new modules importable without
`microsoft-agents-*`), a full-suite regression run, and the agent-developer
documentation.

---

## Scope

- **E2E integration test**
  (`packages/ai-parrot-integrations/tests/unit/test_msagent_card_e2e.py`):
  - Stub bot whose `ask()` returns an AIMessage-like object with
    `structured_output` set to a `SemanticUIResult` (table with 2 actions).
  - Drive `on_turn()` with a message activity → assert ONE sent activity with
    an adaptive attachment, `text` equal to `render_text(result)`, and both
    actions present in the card JSON (one messageBack Action.Submit, one
    Action.OpenUrl).
  - Simulate the click: construct the messageBack `message` activity whose
    `text` is the filled prompt, drive `on_turn()` again → assert the stub
    bot's `ask()` received the prompt as `question`.
  - Same flow via the `adaptiveCard/action` invoke path.
- **Import isolation test** — extend the existing pattern in
  `packages/ai-parrot-integrations/tests/test_import_isolation.py` (or add a
  sibling test module if that file's structure doesn't fit): with
  `microsoft_agents` absent from `sys.modules` (and blocked via a meta-path
  finder or `sys.modules[name] = None` trick), assert
  `import parrot.integrations.msagentsdk.semantic` and
  `import parrot.integrations.msagentsdk.cards` succeed, and that
  `parrot.integrations.msagentsdk.__getattr__("SemanticUIResult")` resolves.
- **Full-suite regression**: run
  `pytest packages/ai-parrot-integrations/tests/ -v` and record the result in
  the completion note (spec AC: existing tests pass unmodified).
- **Docs**: create `docs/integrations/msagentsdk-semantic-cards.md` — an
  agent-developer guide covering: what `SemanticUIResult` is, the four result
  types with a JSON example each, how to return it
  (`ask(structured_output=SemanticUIResult)` / setting it on the response),
  the action round-trip semantics (prompt templates), the config knobs
  (`enable_semantic_cards`, `max_table_rows`, `max_card_bytes`), and the
  fallback behavior. Link it from the closest existing docs index if one
  exists (check `docs/` for an integrations index; if none, standalone file
  is acceptable).

**NOT in scope**: any change to `src/` production code (if e2e testing reveals
a bug, STOP and report it in the completion note — fixes belong to the owning
task's follow-up, not silent scope creep here). Live-tenant validation
(spec §8 open questions) is explicitly out of scope for CI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/unit/test_msagent_card_e2e.py` | CREATE | End-to-end card turn + click round-trip |
| `packages/ai-parrot-integrations/tests/test_import_isolation.py` | MODIFY (or CREATE sibling) | Import isolation for semantic/cards |
| `docs/integrations/msagentsdk-semantic-cards.md` | CREATE | Agent-developer usage guide |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, class names, and method signatures.
> Do NOT invent, guess, or assume anything not listed here. Baseline verified
> 2026-07-14 against `dev` @ 16b30ee1a; TASK-1751..1754 outputs MUST be
> re-verified in the worktree before writing tests.

### Verified Imports
```python
# Feature modules (created by TASK-1751/1752 — verify they exist in the worktree):
from parrot.integrations.msagentsdk.semantic import SemanticUIResult, UIAction, TablePayload
from parrot.integrations.msagentsdk.cards import render_card, render_text, build_card_attachment

# Existing test doubles to reuse:
# packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py:43  class FakeTurnContext
# packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py:69  def _make_agent(...)
# plus the parrot.utils stubbing helpers (lines 25-36) that avoid the Cython chain.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py
class ParrotM365Agent:                          # line 21 (pre-TASK-1753 numbering)
    async def on_turn(self, context) -> None:   # routes message + invoke
    # After TASK-1753/1754: card seam in _handle_message; adaptiveCard/action
    # route; constructor kwargs enable_semantic_cards / max_table_rows /
    # max_card_bytes. RE-VERIFY exact names with grep before use.

# Existing import-isolation test file to extend:
# packages/ai-parrot-integrations/tests/test_import_isolation.py — read it
# first and follow its existing mechanism for simulating a missing SDK.
```

### Does NOT Exist
- ~~`packages/ai-parrot-integrations/tests/integrations/msagentsdk/`~~ — no
  such directory; msagentsdk tests live flat in `tests/unit/` as
  `test_msagent_*.py`.
- ~~`docs/integrations/` index file~~ — NOT verified to exist; check first
  and only link the new doc if an index actually exists (do not invent one).
- ~~A live Bot Framework / Copilot test harness in CI~~ — all "integration"
  tests here are in-process with fakes; no network calls.
- ~~pytest markers `@pytest.mark.integration` in this package~~ — not
  verified; check `pyproject.toml` / `pytest.ini` markers before adding any.

---

## Implementation Notes

### Pattern to Follow
```python
# Click simulation: after asserting the card, pull the filled prompt straight
# from the rendered card JSON (single source of truth):
card = sent_activity.attachments[0]["content"]
submit = next(a for a in card["actions"] if a["type"] == "Action.Submit")
prompt = submit["data"]["msteams"]["text"]
# then drive a fresh message activity with text=prompt through on_turn()
```

### Key Constraints
- No production-code edits. No network. Deterministic tests only.
- The e2e test must assert on BEHAVIOR (activities sent, ask() calls), not on
  internal helper names — TASK-1753's private helpers may be named freely.
- Docs follow the repo's existing docs style (check a recent file under
  `docs/` such as `docs/migration/feat-201-ai-parrot-embeddings.md` for tone);
  code examples in the doc must import only names exported via
  `parrot.integrations.msagentsdk` lazy exports.

### References in Codebase
- `packages/ai-parrot-integrations/tests/test_import_isolation.py` — the
  existing isolation mechanism (READ before extending).
- `packages/ai-parrot-integrations/tests/unit/test_msagent_cards.py` — doubles
  and stubs.
- `sdd/specs/ux-custom-engine-copilot.spec.md` §4 — the two integration-test
  rows this task implements.

---

## Acceptance Criteria

- [ ] E2E test: card turn + messageBack click + invoke click all pass
- [ ] Import isolation: `semantic` and `cards` import with the SDK blocked
- [ ] Full suite green: `pytest packages/ai-parrot-integrations/tests/ -v`
  (result recorded in completion note)
- [ ] `docs/integrations/msagentsdk-semantic-cards.md` created; examples
  import only lazily-exported names; all four result types shown
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/tests/unit/test_msagent_card_e2e.py`
- [ ] No production code modified in this task

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/unit/test_msagent_card_e2e.py

class TestCardTurnEndToEnd:
    async def test_card_turn_then_messageback_click(self):
        """message → card with actions → simulated click → second ask()."""
        ...

    async def test_card_turn_then_invoke_click(self):
        """message → card → adaptiveCard/action invoke → 200 + second ask()."""
        ...

    async def test_plain_bot_unaffected(self):
        """bot without structured_output → single plain-text activity."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1751..1754 must ALL be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Re-verify the shapes produced by TASK-1752/1753/1754 in the worktree
     (`grep -n "feat303_prompt\|adaptiveCard/action\|enable_semantic_cards"`)
   - Read `test_import_isolation.py` to follow its mechanism
4. **Update status** in `sdd/tasks/index/ux-custom-engine-copilot.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1755-integration-tests-docs.md`
8. **Update index** → `"done"` and set the feature's `completed_at` if this
   is the last task
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
