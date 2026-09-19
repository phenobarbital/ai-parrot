# TASK-3458: Document `CREW_AI_KEY`

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 + AC10. `CREW_AI_KEY` is an opt-in operational control: it only does
something when an operator sets it, and its whole value proposition (metering,
budgeting and rotating crew-builder Google traffic separately from every other Google
consumer in the server) is invisible unless it is written down.

This task documents the behaviour. It touches no code and shares no file with any other
task, so it can be done at any point — the behaviour it describes is fully determined
by the approved spec, not by the implementation order.

---

## Scope

- Add a `CREW_AI_KEY` section to `docs/crew_handler.md`.
- Add `CREW_AI_KEY` to the environment-variable reference in `docs/config.md`, beside
  the existing `GOOGLE_API_KEY` entries.
- Add a small test that asserts both documents mention `CREW_AI_KEY`, so AC10 is
  checkable rather than merely asserted.

**NOT in scope**:
- `env/.env` — it is git-ignored (`.gitignore:180` matches `env/`), so there is no
  committed sample file to update. Spec §3 M4's ".env sample if one lists
  GOOGLE_API_KEY" resolves to: **there is none**. Do not create one.
- Any source change.
- Documenting `AgentsFlow` / flow-authoring crews — spec §1 Non-Goals and §8's open
  follow-up question.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/crew_handler.md` | MODIFY | New "Google Credentials (`CREW_AI_KEY`)" section |
| `docs/config.md` | MODIFY | `CREW_AI_KEY` in the env-var reference + sample block |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py` | CREATE | AC10 guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# the doc test needs only the stdlib:
from pathlib import Path
```

### Existing Signatures to Use

```markdown
<!-- docs/crew_handler.md — verified heading structure -->
## Overview                       <!-- line 7 -->
## Base URL                       <!-- line 16 -->
## Endpoints                      <!-- line 22 -->
## Execution Modes                <!-- line 335 -->
## Python Client Example          <!-- line 400 -->
## cURL Examples                  <!-- line 524 -->
## Error Handling                 <!-- line 570 -->
## Best Practices                 <!-- line 591 -->
## Integration with BotManager    <!-- line 615 -->

<!-- docs/config.md — verified anchors -->
- **`GOOGLE_API_KEY`**: API key for Google GenAI services   <!-- line 26 -->
GOOGLE_API_KEY=your_google_api_key                          <!-- line 300, inside a sample block -->
```

```python
# Repo-root resolution from the test's location
# packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py
#   parents[0]=crew  [1]=flows  [2]=bots  [3]=tests  [4]=ai-parrot  [5]=packages  [6]=<repo root>
REPO_ROOT = Path(__file__).resolve().parents[6]
```

### Behaviour to document (from the approved spec — do not re-derive it)

- `CREW_AI_KEY` applies to crews built by the AgentCrew HTTP handlers: both
  `PUT/POST /api/v1/crew` (CRUD) and crew execution.
- It covers (a) every agent in such a crew whose LLM is a Google provider —
  `google`, `gemini-live`, `google-compat` — and which declares **no** credential of
  its own, and (b) the crew's own default Google orchestration LLM, including its
  `run_loop` and executive-summary fallbacks.
- An explicit `llm_kwargs.api_key`, `credentials_file`, `credentials`, or a truthy
  `vertexai` in an agent's config **always wins**. So does passing an
  `AbstractClient` instance as `llm`.
- A top-level `api_key` in an agent's `config` is NOT a credential — only
  `llm_kwargs.api_key` counts.
- Non-Google providers are unaffected.
- When `CREW_AI_KEY` is unset, behaviour is exactly as before: clients fall back to
  `GOOGLE_API_KEY`, and one warning is logged per process.
- The key is never stored in a `CrewDefinition`, so it never reaches Redis and never
  appears in `GET /api/v1/crew`, and it is never logged.
- Programmatic `AgentCrew(...)` / `AgentCrew.from_definition(...)` use outside the
  server is unaffected — the key is opt-in via the `google_api_key` parameter, which
  only the server build paths pass.
- **Timing caveat** (spec §7): an agent class that builds its client inside
  `__init__`, or that overrides `configure()` to ignore `_llm_kwargs`, will not pick
  the key up.

### Does NOT Exist

- ~~a committed `.env.example` / `.env.sample` at the repo root~~ — `env/` is
  git-ignored (`.gitignore:180`). The only committed env sample is
  `env/.env.observability.example`, which is unrelated. Do NOT add a new sample file.
- ~~`docs/crew_ai_key.md`~~ / any existing crew-credentials doc — this is new content
  in the two existing files.
- ~~a `CREW_AI_KEY` mention anywhere in the repo today~~ — there is none.
- ~~`docs/crew_handler.md` has a "Configuration" section~~ — it does not; its headings
  are listed above. Pick an insertion point among those.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/crew_handler.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/config.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Never print a real key** in an example. Use an obvious placeholder
  (`CREW_AI_KEY=your_crew_gemini_api_key`).
- Match the surrounding Markdown style of each file — `docs/config.md` uses
  `- **\`NAME\`**: description` bullets plus a fenced sample block; `docs/crew_handler.md`
  uses `##` / `###` headings with fenced JSON and bash examples.
- State the precedence rule explicitly — "an explicit `llm_kwargs.api_key` always wins"
  is the single most likely operator question.
- Include the timing caveat. Spec §7 says document it; no fix is in scope.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `docs/crew_handler.md` section — *why*: this is the doc an operator reads when wiring up the crew API, so it carries the full behaviour.
2. Add the two `docs/config.md` entries — *why*: that file is the env-var reference; an operator looking up variables must find it there too.
3. Add the AC10 guard test — *why*: without it "documented" is unverifiable, and FEAT-563 requires this task to carry a real validation command.

### `docs/crew_handler.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Error Handling$' docs/crew_handler.md) -->
<!-- BEFORE — insert a new `## Google Credentials (CREW_AI_KEY)` section immediately
     above `## Error Handling` (verified: docs/crew_handler.md:570), so it follows the
     endpoint/mode reference and precedes the operational sections. -->

## Google Credentials (`CREW_AI_KEY`)

<!-- FILL IN: write this section from the "Behaviour to document" list in this task's
     Codebase Contract. It MUST cover, in this order: what the key is for (metering /
     budgeting / rotating crew-builder Google traffic separately from GOOGLE_API_KEY);
     what it covers (Google agents without their own credential, plus the crew's own
     orchestration LLM and its run_loop / executive-summary fallbacks); the three
     Google provider keys; the precedence rule (explicit llm_kwargs.api_key /
     credentials_file / credentials / truthy vertexai / an AbstractClient instance all
     win, and a top-level config api_key is NOT a credential); the unset behaviour
     (falls back to GOOGLE_API_KEY, one warning per process); the guarantee that it is
     never stored in a CrewDefinition and never logged; that programmatic AgentCrew use
     is unaffected; and the timing caveat. Include one short JSON snippet of an agent
     definition that opts out by supplying its own llm_kwargs.api_key.
     Bounded by AC10 and by spec §1 Goals/Non-Goals — add no behaviour the spec does
     not state. -->
```
**Why**: placing it before `## Error Handling` keeps the reference material (endpoints,
execution modes, client examples) together and the operational material together.

### `docs/config.md` (MODIFY — reference bullet)
```markdown
<!-- occurrences: 1 (verified: grep -c '^- \*\*`GOOGLE_API_KEY`\*\*: API key for Google GenAI services$' docs/config.md) -->
<!-- AFTER — insert below `- **`GOOGLE_API_KEY`**: API key for Google GenAI services`
     (verified: docs/config.md:26) -->
- **`CREW_AI_KEY`**: API key used by Google agents in crews built through the AgentCrew
  HTTP handlers, and by the crew's own default Google orchestration LLM. Unset falls
  back to `GOOGLE_API_KEY`. See `docs/crew_handler.md`.
```
**Why**: directly under the variable it overrides, so the relationship is unmissable.

### `docs/config.md` (MODIFY — sample block)
```markdown
<!-- occurrences: 1 (verified: grep -c '^GOOGLE_API_KEY=your_google_api_key$' docs/config.md) -->
<!-- AFTER — insert below `GOOGLE_API_KEY=your_google_api_key` (verified: docs/config.md:300) -->
CREW_AI_KEY=your_crew_gemini_api_key
```
**Why**: a placeholder, never a real key.

### `packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py` (CREATE)
```python
"""CREW_AI_KEY is documented (FEAT-575 AC10, TASK-3458)."""
from pathlib import Path

import pytest

# parents: [0]=crew [1]=flows [2]=bots [3]=tests [4]=ai-parrot [5]=packages [6]=repo root
REPO_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.parametrize("doc", ["docs/crew_handler.md", "docs/config.md"])
def test_crew_ai_key_is_documented(doc):
    # FILL IN: read REPO_ROOT / doc, skip the test when the file is missing (a wheel
    # checkout has no docs/ tree), and assert "CREW_AI_KEY" appears in its text —
    # bounded by AC10. Assert on the variable name only; do NOT assert on prose
    # wording, which would make the docs brittle to edit.
    raise NotImplementedError
```
**Why**: a name-presence check is the strongest assertion that will not rot. The skip
branch matters because `docs/` is not part of any installed distribution.

### FILL IN checklist
- [ ] `docs/crew_handler.md` — the `## Google Credentials (CREW_AI_KEY)` body; bounded by AC10 and the Contract's behaviour list
- [ ] `test_crew_ai_key_is_documented` — read, skip-if-missing, assert the name; bounded by AC10

---

## Acceptance Criteria

- [ ] `docs/crew_handler.md` has a `CREW_AI_KEY` section covering coverage, precedence, the unset fallback, the no-persistence/no-logging guarantee, and the timing caveat (AC10).
- [ ] `docs/config.md` lists `CREW_AI_KEY` in both the reference bullets and the sample block.
- [ ] No real API key appears in either document.
- [ ] No new `.env` sample file is created.
- [ ] `grep -rn "CREW_AI_KEY" docs/` returns hits in both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py -q`

---

## Test Specification

The blueprint's test block IS the scaffold — a two-file parametrized presence check,
nothing more. Do not assert on prose.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context — especially §1 Goals /
   Non-Goals and §7 Known Risks, which are what this document describes
2. **Check dependencies** — none. The behaviour is fixed by the approved spec; this
   task does not wait on the code
3. **Verify the Codebase Contract** — confirm the heading/line anchors in
   `docs/crew_handler.md` and `docs/config.md` still match before inserting
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3458-document-crew-ai-key.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) via seat `glm` (nova:zai.glm-4.7-flash)
**Date**: 2026-09-18
**Notes**: Added "Google Credentials (CREW_AI_KEY)" section to
`docs/crew_handler.md` (coverage, precedence, unset behavior, persistence
guarantees, timing caveats) and documented `CREW_AI_KEY` in
`docs/config.md`'s environment-variable reference. Added
`packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py`
asserting AC10. Merge-tier tests: `2 passed`.
Seat: glm · Backend: nova · Model: zai.glm-4.7-flash · Attempts: 1 · Duration: 38.774s · Tokens: 218548/2348

**Deviations from spec**: none
