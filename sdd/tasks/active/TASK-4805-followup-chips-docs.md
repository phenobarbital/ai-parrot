# TASK-4805: Docs — `docs/agents/followup-suggestion-chips.md`

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4800, TASK-4802, TASK-4804, TASK-4807, TASK-4808, TASK-4810, TASK-4811, TASK-4812
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, §7 "Docs (M7; sections)", G7. One page for agent authors, operators and frontend developers
(navigator-frontend-next consumes the wire contract without reading Python). It documents shipped behaviour, so it
waits for the bot wiring (TASK-4800), the server wire (TASK-4802), the admin UI (TASK-4804) and the rev 0.3 work:
stream trailer (TASK-4806/4807/4808), Telegram buttons (TASK-4809/4810) and Agent Studio settings (TASK-4811/4812).

---

## Scope

Write `docs/agents/followup-suggestion-chips.md` with exactly these sections (spec §7 "Docs", rev 0.3):
1. **What you get** — description + the JSON sample from spec §2 "Wire contract".
2. **Opt-in per agent** — `enable_suggestions`, `suggest_followups`, `suggestion_timeout_s`, `max_suggestions`,
   `suggestion_model` (rev 0.2), `presentation_modes`; Python constructor and YAML agent definition examples
   (YAML kwargs are forwarded verbatim — Q4).
3. **Skill-declared chips** — frontmatter example; emitted when the skill is the turn's skill (`/trigger`), tenant
   shadowing / `global_only` unchanged.
4. **Writing a provider** — `SuggestionProvider` protocol, lanes, `register_suggestion_provider(provider, prepend=...)`,
   a FEAT-756-style sketch ("vs last month" provider).
5. **Wire contract** — JSON body and final stream envelope; key omitted when empty; client click contract
   (`kind != action` → new turn with `output_mode`; `action == "explain"` → explain request with `turn_id` + `data`;
   clients that cannot run explain hide `kind=action` chips).
6. **Channel behaviour** — admin UI renders; Telegram renders non-action chips as inline buttons when
   `suggestion_buttons: true` (TTL `suggestion_button_ttl_s`, private chats only, explain chips skipped, a press
   replays the prompt for the same user); Teams / A2A ignore the field (why: spec §2 "Channel degradation").
7. **Cost, latency and metadata** — LLM lane = one `invoke()` on the lightweight model (or `suggestion_model`),
   `max_tokens=256`, timeout, stream-tail latency note, `metadata["suggestions"]` shape.
8. **Stream trailer** — request flag `suggestions_trailer: true`, header `chunked-aimessage+suggestions`, frame format
   `text \n\x00 {envelope} \n\x00 {"suggestions", "turn_id"}`, envelope carries no `suggestions` on this path, how a
   client parses frames (TASK-4808's `stream.ts` as reference), backward compatibility.
9. **Agent Studio** — the Capabilities-tab group, DB columns, and the operator step: apply
   `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` before deploying (a missing column breaks `BotModel` reads).

**NOT in scope**: code changes; README/index edits other than this page.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/agents/followup-suggestion-chips.md` | CREATE | Feature documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource  # TASK-4794
from parrot.bots.suggestions import (SuggestionContext, SuggestionEngine, SuggestionProvider,  # TASK-4797 / TASK-4800
    SkillSuggestionProvider, PresentationSuggestionProvider, ExplainSuggestionProvider, LLMSuggestionProvider)
from parrot.skills.tenancy import current_turn_skill                                     # TASK-4795
```

### Existing Signatures to Use
- Spec §2 Data Models / Wire contract / New Public Interfaces and §7 binding rules are the source; re-read the merged
  code of TASK-4800 / TASK-4802 / TASK-4804 before writing and document what shipped, not the spec, where they differ.
- Existing doc folder: `docs/agents/` (contains `fireflies-insights.md`).
- Shipped files to read for sections 8-9: `packages/ai-parrot-server/ui/src/lib/api/stream.ts` (trailer parsing,
  TASK-4808), `packages/ai-parrot-server/ui/src/pages/agents/form/TabsCapabilities.svelte` and
  `packages/ai-parrot-server/ui/src/lib/agents/fields.ts` (Studio group, TASK-4812),
  `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (TASK-4810),
  `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` (TASK-4811).

### Does NOT Exist
- ~~Teams `suggestedActions` / A2A chip parts / Telegram group-chat buttons~~ — not implemented; do not document
  them as available.
- ~~persisted chips on conversation reload~~ — live turn only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/agents/followup-suggestion-chips.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged code of TASK-4800, TASK-4802, TASK-4804 — *why*: document shipped names and defaults.
2. Write the page with the nine sections below — *why*: section list is binding (spec §7).
3. Run the Validation Command (smoke: the documented wire schema, incl. `suggestions`, still validates).

### `docs/agents/followup-suggestion-chips.md` (CREATE)
```markdown
# Follow-up Suggestion Chips (FEAT-752)

Agents can attach a short row of follow-up "chips" to every answer ...

## 1. What you get
<!-- FILL IN: two sentences + JSON sample (spec §2 Wire contract) -->

## 2. Opt-in per agent
<!-- FILL IN: kwargs table (name, default, effect) + Python and YAML examples -->

## 3. Skill-declared chips
<!-- FILL IN: frontmatter example (spec §2) + "turn skill" rule -->

## 4. Writing a provider
<!-- FILL IN: protocol, lanes table, register_suggestion_provider, FEAT-756-style sketch -->

## 5. Wire contract and click contract
<!-- FILL IN -->

## 6. Channel behaviour
<!-- FILL IN -->

## 7. Cost, latency and metadata
<!-- FILL IN: metadata["suggestions"] shape (spec §7 Engine metadata) -->

## 8. Stream trailer
<!-- FILL IN -->

## 9. Agent Studio settings
<!-- FILL IN: include the migration operator step -->
```

### FILL IN checklist
- [ ] All nine sections written from shipped code.

---

## Acceptance Criteria

- [ ] Page exists with the nine sections in order; every code sample uses names that exist after TASK-4800.
- [ ] No claim that Teams/A2A render chips; Telegram documented as opt-in buttons (private chats).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_chat_models.py -q`

---

## Test Specification

None (documentation). The validation command is a smoke check on the documented wire schema (TASK-4801).

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`; commit only the doc; `scripts/sdd/close_task.sh TASK-4805 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
