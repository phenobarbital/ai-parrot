# TASK-5075: Adaptive-Card connect action for tool needs-auth (`_offer_connections`)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5060, TASK-5069, TASK-5072
**Assigned-to**: unassigned

---

## Context

Spec §2 "Connect card (M6)", §3 Module 6, AC-8, AC-15, AC-16. When any tool in a Teams turn reports needs-auth,
the wrapper sends the agent's response first, then one card per provider: a Connect button minted through
`TeamsConnector.connect_guarded` (so the OAuth state carries the conversation reference and bot app id), or the
device-code instructions. The tool's own `auth_url` is **never** used. The same personal + live-principal guard
as the commands runs **before either branch**; refusal = at most one reply per turn, no card/code/URL, no service
call. Depends on TASK-5072 because it edits `wrapper.py` after it (serialized wrapper chain).

---

## Scope

- Wrap each orchestrator call site (text, voice, card resume, deep-link resume — the `_agent_context` sites from
  TASK-5071) in `with collect_auth_requirements() as pending:`; after the response for that turn has been sent,
  `await self._offer_connections(turn_context, pending)` (skip when `result.needs_form` started a dialog).
- `_offer_connections(turn_context, pending)`:
  1. empty → return; `self._connector is None` → log and return;
  2. `guard = await self._connector.require_guard(turn_context)`; `None` → return (the guard already replied once);
  3. group payloads by `provider`; a provider with mixed `auth_kind` (device_code vs other) → one safe reply
     "Couldn't start <Provider> sign-in — please try again." and skip it;
  4. `device_code` → `device_code_card` from **one complete challenge** (first payload having both `user_code` and
     `verification_uri`; never combine fields across payloads); no `start_connect`; never log codes;
  5. otherwise → `connector.connect_guarded(turn_context, guard, provider, scopes=sorted(union of payload scopes))`
     (empty union → `None`, i.e. provider defaults).
- Tests in `test_msteams_needs_auth_card.py`.

**NOT in scope**: `clients/base.py` (FEAT-776 M2 owns the LLM-facing message), auto-retry after connect (S-3a).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | collector around agent calls; `_offer_connections` |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_needs_auth_card.py` | CREATE | unit/integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.pending import collect_auth_requirements                  # TASK-5060 (or the shared module already on dev)
from parrot.auth.credentials import AuthRequiredPayload                    # verified: credentials.py:114
from parrot.integrations.msteams.connections import device_code_card, send_adaptive_card   # TASK-5068
from parrot.integrations.msteams.commands.connect_commands import TeamsGuard              # TASK-5069
```

### Existing Signatures to Use
```python
# AuthRequiredPayload: provider, auth_url, scopes, tool_name, message, auth_kind, user_code, verification_uri, expires_in
# TeamsConnector.require_guard(turn_context) -> Optional[TeamsGuard]                      # TASK-5069
# TeamsConnector.connect_guarded(turn_context, guard, provider_id, *, scopes=None)        # TASK-5069
# device_code_card(provider_display, user_code, verification_uri, expires_in)             # TASK-5068
# wrapper: self._connector (TASK-5070), self._agent_context(...) call sites (TASK-5071)
#   normal path: result = await self.form_orchestrator.process_message(...)  → has_error / needs_form / raw_response branches
#   (on_message_activity ~:810-860; voice handler ~:1160-1200; card resume ~:560-580; deep-link `inject` closure ~:518-530)
```

### Does NOT Exist
- ~~`AuthRequiredPayload.auth_url` in the card~~ — forbidden (state lacks the conversation reference).
- ~~a second device flow via `start_connect`~~ — forbidden for `device_code` payloads.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_needs_auth_card.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_offer_connections` (below `_remember_conversation`). 2. Wrap each call site; insert the offer after the
response send of that path. 3. Tests.

### `.../msteams/wrapper.py` (MODIFY) — method
```python
    async def _offer_connections(self, turn_context: TurnContext, pending: List[AuthRequiredPayload]) -> None:
        """After the response: guard once, then one connect/device-code card per provider (spec §2 M6)."""
        if not pending:
            return
        if self._connector is None:
            self.logger.info("Needs-auth in a Teams turn but no connection providers are registered")
            return
        guard = await self._connector.require_guard(turn_context)
        if guard is None:
            return
        by_provider: Dict[str, List[AuthRequiredPayload]] = {}
        for payload in pending:
            by_provider.setdefault(payload.provider, []).append(payload)
        for provider_id, payloads in by_provider.items():
            kinds = {p.auth_kind == "device_code" for p in payloads}
            if len(kinds) > 1:
                # FILL IN: one safe retry reply naming the provider; continue — bounded by spec §2 ("Reject conflicting auth kinds")
                ...
            if True in kinds:
                # FILL IN: first payload with both user_code and verification_uri → send device_code_card; none → safe reply.
                # Never log user_code — bounded by AC-8, AC-16
                ...
            else:
                scopes = sorted({s for p in payloads for s in p.scopes})
                await self._connector.connect_guarded(turn_context, guard, provider_id, scopes=scopes or None)
```

### Same file — call sites (pattern)
```python
        with collect_auth_requirements() as pending:
            async with self._formdesigner_turn(turn_context):
                result = await self.form_orchestrator.process_message(..., context=await self._agent_context(...))
                await self._flush_formdesigner_cards_if_ok(turn_context, result)
        # ... existing has_error / needs_form / response branches ...
        # FILL IN: call `await self._offer_connections(turn_context, pending)` after the response (and after the
        # error text) is sent; not when a form dialog was started — bounded by AC-8 ("sends the agent's response, then")
```
FILL IN: disambiguate each of the four sites by enclosing method (anchors repeat: `                context=` lines).

### `.../tests/integrations/msteams/test_msteams_needs_auth_card.py` (CREATE)
```python
"""FEAT-775 M6: needs-auth connect cards (AC-8, AC-15, AC-16)."""
# test_offer_connections_dedupes_and_mints_own_url — two jira payloads → one connect_guarded call; URL from start_connect,
#   never payload.auth_url
# test_teams_connect_scope_union_and_upgrade — scopes ["b","a"] + ["a","c"] → scopes=["a","b","c"]
# test_offer_connections_device_code_card — device_code payload → device_code_card, no start_connect
# test_device_code_challenges_not_mixed — payload1 code-only, payload2 complete → card uses payload2 only
# test_conflicting_auth_kinds_safe_reply — oauth + device_code for one provider → one safe reply, no card
# test_automatic_cards_share_personal_guard — group / channel / unknown type → one hint, no card/code/URL/service call
# test_automatic_cards_require_live_principal — expired/missing session → one login hint, no card/service call
# test_teams_tool_needs_auth_card — agent tool raising AuthorizationRequired inside a real ToolManager during a
#   wrapper turn → response sent first, then exactly one Connect card
```

### FILL IN checklist
- [ ] conflict and device-code branches
- [ ] four call sites with correct ordering
- [ ] eight tests

---

## Acceptance Criteria

- [ ] Response first, then one card per provider requiring consent; URL from `start_connect(channel="msteams")` (AC-8).
- [ ] Scopes unioned per provider; sufficient grants get an account reply (AC-15, via the connector).
- [ ] Guard runs before both branches; group/unknown/unauthenticated expose no URL/code (AC-16).
- [ ] `clients/base.py` untouched; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_needs_auth_card.py -q`

---

## Test Specification

Eight tests listed in the test-file block.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

