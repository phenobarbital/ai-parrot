# TASK-5068: Adaptive Card builders for Teams connections (in `connections.py`)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5067
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (builders), AC-4, AC-8. Pure functions returning Adaptive Card dicts, plus one send helper,
used by `TeamsConnector` (TASK-5069) and the needs-auth offer (TASK-5075). Shape and send path follow
`_connect_jira_card` / `_send_adaptive_card` (jira_commands.py:54-81, :225-248). Depends on TASK-5067 only
because both write `connections.py`.

---

## Scope

- `connect_card(provider_display, auth_url)` — TextBlock + one `Action.OpenUrl` "Connect <Provider>".
- `device_code_card(provider_display, user_code, verification_uri, expires_in)` — code + URI text and an
  `Action.OpenUrl` to `verification_uri`; no OAuth URL.
- `provider_picker_card(providers: List[Tuple[str, str]])` — one `Action.Submit {"command": "/connect <id>"}` per
  `(provider_id, display_name)`.
- `connections_status_card(rows: List[IntegrationDescriptor])` — one line per provider (status, account name);
  `Action.Submit` connect for disconnected rows, disconnect for connected ones.
- `async send_adaptive_card(turn_context, card)` — attachment send (pattern jira_commands.py:225-248).
- Tests for card shapes.

**NOT in scope**: deciding when a card is sent (TASK-5069/5075).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` | MODIFY | append card builders + send helper |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_cards.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION        # verified: jira_commands.py:34
from parrot.auth.oauth2.models import IntegrationDescriptor               # verified: auth/oauth2/models.py:21
from botbuilder.schema import Activity, Attachment                        # verified: jira_commands.py:234 (import inside the function)
```

### Existing Signatures to Use
```python
# jira_commands.py:54-81 — card skeleton
{"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
 "version": DEFAULT_ADAPTIVE_CARD_VERSION, "body": [{"type": "TextBlock", "text": ..., "wrap": True}],
 "actions": [{"type": "Action.OpenUrl", "title": "Connect Jira", "url": auth_url}]}
# jira_commands.py:84-130 — menu buttons: {"type": "Action.Submit", "title": ..., "data": {"command": "/connect_jira"}}
# jira_commands.py:225-248 — Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card); Activity(type="message", attachments=[...])

# IntegrationDescriptor fields (models.py:39+): provider, display_name, icon, default_scopes, status,
#   account_id, display_account_name, email, connected_at, channels, scopes_granted, expires_at, updated_at
```

### Does NOT Exist
- ~~`parrot.outputs.cards.teams_connect_card`~~ — no shared builder exists; write them here.
- ~~`IntegrationDescriptor.connected`~~ as a stored field — check `status == "connected"` instead (verify the model).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_cards.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#IntegrationDescriptor"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Append `_card(body, actions)` and the four builders + send helper. 2. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` (MODIFY — append at end of file)
```python
_ADAPTIVE_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"


def _card(body: List[Dict[str, Any]], actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap body/actions in the standard Adaptive Card envelope."""
    return {"type": "AdaptiveCard", "$schema": _ADAPTIVE_SCHEMA, "version": DEFAULT_ADAPTIVE_CARD_VERSION,
            "body": body, "actions": actions}


def _text(text: str) -> Dict[str, Any]:
    return {"type": "TextBlock", "text": text, "wrap": True}


def connect_card(provider_display: str, auth_url: str) -> Dict[str, Any]:
    """Card with one 'Connect <Provider>' OpenUrl button."""
    return _card(
        [_text(f"Click the button below to authorize your **{provider_display}** account:")],
        [{"type": "Action.OpenUrl", "title": f"Connect {provider_display}", "url": auth_url}],
    )


def device_code_card(provider_display: str, user_code: str, verification_uri: str,
                     expires_in: Optional[int]) -> Dict[str, Any]:
    """Device-code instructions: code + verification URI; never an OAuth redirect URL."""
    # FILL IN: body with the code (monospace/bold) and URI, an expiry hint when expires_in, one OpenUrl to verification_uri
    ...


def provider_picker_card(providers: List[Tuple[str, str]]) -> Dict[str, Any]:
    """One Action.Submit ``{"command": "/connect <id>"}`` per ``(provider_id, display_name)``."""
    # FILL IN — bounded by AC-4 (Submit data must route through MSTeamsCommandRouter like typed text)
    ...


def connections_status_card(rows: List[IntegrationDescriptor]) -> Dict[str, Any]:
    """Status line per provider; Submit connect/disconnect buttons."""
    # FILL IN: "<Provider>: connected as <name>" / "<Provider>: not connected"; empty rows → "No connections available."
    ...


async def send_adaptive_card(turn_context: "TurnContext", card: Dict[str, Any]) -> None:
    """Send ``card`` as an Adaptive Card attachment (pattern jira_commands.py:225-248)."""
    from botbuilder.schema import Activity, Attachment

    attachment = Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card)
    await turn_context.send_activity(Activity(type="message", attachments=[attachment]))
```
Extend imports: `from typing import ... List, Tuple`; `from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION`;
`from parrot.auth.oauth2.models import IntegrationDescriptor`.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_cards.py` (CREATE)
```python
"""FEAT-775 M6: Teams connection cards."""
from parrot.integrations.msteams.connections import (
    connect_card, connections_status_card, device_code_card, provider_picker_card,
)

# test_connect_card_open_url — one Action.OpenUrl with the given URL
# test_device_code_card_has_code_and_uri_no_oauth_url — user_code + verification_uri present; only URL is verification_uri
# test_provider_picker_submit_commands — data.command == "/connect jira", "/connect o365"
# test_status_card_rows — connected row shows account name + disconnect submit; disconnected row connect submit
# FILL IN: the four bodies
```

### FILL IN checklist
- [ ] three builder bodies
- [ ] four tests

---

## Acceptance Criteria

- [ ] Picker/status Submit data is `{"command": "/connect <id>"}` / `"/disconnect <id>"` (AC-4).
- [ ] Device-code card exposes code + URI only (AC-8).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_cards.py -q`

---

## Test Specification

Four tests listed in the test-file block.

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

