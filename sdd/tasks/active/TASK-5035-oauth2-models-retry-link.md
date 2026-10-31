# TASK-5035: OAuth2 wire models — `AuthRequiredEnvelope.retry_safe` + `ChannelLinkPreview`

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and Module 5 add two server-authored wire contracts that several later tasks consume:

- `AuthRequiredEnvelope.retry_safe: bool = False` — set by AgentTalk (TASK-5051) from turn-local execution
  evidence; the UI (TASK-5055) auto-retries only when it is `true` (AC-7). Clients never compute it.
- `ChannelLinkPreview` — the read-only body of `GET /api/v1/channel-links/{nonce}` served by
  `ChannelLinksHandler` (TASK-5041) and rendered by `LinkChannel.svelte` (TASK-5056) (AC-5).

Both are generated into TypeScript by TASK-5052, so they must exist first. This task only adds models;
it does NOT remove `EnableResponse` (that is TASK-5048, gated on spec §8).

---

## Scope

- Add `retry_safe: bool = False` to `AuthRequiredEnvelope` (`parrot/auth/oauth2/models.py`), documented as
  "server-authored; absent/false means the client must not auto-resend".
- Add `class ChannelLinkPreview(BaseModel)` with fields `channel: str`, `channel_user_id: str`,
  `team_id: str`, `nav_user_id: str` (spec §2 Data Models, verbatim).
- Export `ChannelLinkPreview` from `parrot/auth/oauth2/__init__.py` (import list + `__all__`).
- Add `grant_origin: Optional[str] = None` to both `UsersIntegrationRow` (`models.py:156`) and `IntegrationDescriptor`
  (`models.py:21`), documented as "`authorization_code` | `device_code`; display/audit only (FEAT-777 M3)" — *why*: the
  panel and `test_e2e_o365_device_and_web_share_record` show it; TASK-5045 writes it on the row, TASK-5038 copies it into the
  descriptor. Default `None` keeps every existing row and test valid.
- Extend `tests/unit/integrations/oauth2/test_models.py` with tests for both.

**NOT in scope**: removing `EnableResponse` (TASK-5048); `ChannelLinkClaim` (TASK-5034);
producing `retry_safe` (TASK-5051); TS generation (TASK-5052); `AuthRequiredPayload` (S-1, `parrot/auth/credentials.py` — unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | `retry_safe` field; new `ChannelLinkPreview` |
| `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` | MODIFY | export `ChannelLinkPreview` |
| `tests/unit/integrations/oauth2/test_models.py` | MODIFY | tests for both models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, model_validator          # verified: parrot/auth/oauth2/models.py:14
from parrot.auth.oauth2.models import AuthRequiredEnvelope       # verified: models.py:118
from parrot.auth.oauth2.models import DisconnectResponse         # verified: models.py:106
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class DisconnectResponse(BaseModel):            # :106  (provider: str :114; disconnected: bool = True :115)
class AuthRequiredEnvelope(BaseModel):          # :118
    type: Literal["auth_required"] = "auth_required"   # :139
    provider: str                                       # :140
    tool_name: Optional[str] = None                     # :141
    auth_url: Optional[str] = None                      # :142
    scopes: List[str] = Field(default_factory=list)     # :143
    message: str                                        # :144
    auth_kind: Optional[str] = None                     # :145
    user_code: Optional[str] = None                     # :146
    verification_uri: Optional[str] = None              # :147
    expires_in: Optional[int] = None                    # :148  ← last field (anchor)

# packages/ai-parrot/src/parrot/auth/oauth2/__init__.py
from .models import (  # noqa: E402        # :32
    AuthRequiredEnvelope, ConnectInitRequest, ConnectInitResponse,
    DisconnectResponse,                     # :36  (anchor)
    EnableResponse, IntegrationDescriptor, UsersIntegrationRow,
)
__all__ = [ ... '"DisconnectResponse",'     # :68  (anchor) ... ]

# packages/ai-parrot-server/src/parrot/handlers/agent.py:1922 (consumer, do not edit)
envelope = AuthRequiredEnvelope(**payload.model_dump())   # payload has no retry_safe key → default False
```

### Does NOT Exist
- ~~`AuthRequiredEnvelope.retry_safe`~~ — added by this task.
- ~~`ChannelLinkPreview`~~ — added by this task; there is no `parrot.auth.channel_link.ChannelLinkPreview`.
- ~~`AuthRequiredPayload.retry_safe`~~ — must NOT be added; spec §2: the flag lives *outside* `AuthRequiredPayload`.
- ~~`ConnectionEventSink` export in `oauth2/__init__.py`~~ — not part of this task (see TASK-5032).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/__init__.py", "action": "MODIFY"},
    {"path": "tests/unit/integrations/oauth2/test_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#AuthRequiredEnvelope",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#DisconnectResponse"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pydantic v2; field default `False` so every existing producer (`agent.py:1922`) stays valid.
- `ChannelLinkPreview` never carries secrets or the nonce.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2/models.py` — model style (Google docstrings with `Attributes:`).

---

## Implementation Blueprint

### Steps (in order)
1. Append `retry_safe` after `expires_in` in `AuthRequiredEnvelope` — *why*: default False keeps old producers valid (AC-7 "absent means false").
2. Add `ChannelLinkPreview` right after `AuthRequiredEnvelope` — *why*: keeps the HTTP wire models together for TASK-5052's generator.
3. Export it from `oauth2/__init__.py` in both the import list and `__all__` — *why*: TASK-5041/TASK-5052 import from the package.
4. Add the tests; run them.

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    expires_in: Optional\[int\] = None' models.py)
# AFTER — insert below `    expires_in: Optional[int] = None` (verified: models.py:148)
    retry_safe: bool = False


class ChannelLinkPreview(BaseModel):
    """Read-only preview of a pending channel link (FEAT-777 M2/M5).

    Returned by ``GET /api/v1/channel-links/{nonce}`` before the user confirms.
    Never carries the nonce or any credential material.

    Attributes:
        channel: Channel being linked (``"slack"`` in v1).
        channel_user_id: Team-qualified channel id, ``"{team_id}:{slack_user_id}"``.
        team_id: Slack workspace id shown to the user.
        nav_user_id: Navigator user id of the logged-in session that would own the link.
    """

    channel: str
    channel_user_id: str
    team_id: str
    nav_user_id: str
```
Also add to the `AuthRequiredEnvelope` docstring `Attributes:` list:
`retry_safe: Server-authored; True only when the server proved no tool body began (AC-7). Absent/False → no automatic resend.`
**Why this shape**: spec §2 Data Models fixes these exact fields; the flag is on the envelope, not the payload.

### `packages/ai-parrot/src/parrot/auth/oauth2/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    DisconnectResponse,' __init__.py)
# BEFORE — insert above `    DisconnectResponse,` (verified: __init__.py:36)
    ChannelLinkPreview,
# occurrences: 1 (verified: grep -c '    "DisconnectResponse",' __init__.py)
# BEFORE — insert above `    "DisconnectResponse",` (verified: __init__.py:68)
    "ChannelLinkPreview",
```
**Why**: alphabetical placement inside both existing lists.

### `tests/unit/integrations/oauth2/test_models.py` (MODIFY)
```python
# Add ChannelLinkPreview to the existing `from parrot.auth.oauth2.models import (...)` block, then append:


class TestRetrySafe:
    """AuthRequiredEnvelope.retry_safe (FEAT-777 AC-7)."""

    def test_default_false(self) -> None:
        assert AuthRequiredEnvelope(provider="jira", message="m").retry_safe is False

    def test_round_trip(self) -> None:
        # FILL IN: retry_safe=True survives model_dump(mode="json") / model_validate — bounded by AC-7
        ...


class TestChannelLinkPreview:
    """ChannelLinkPreview wire model."""

    def test_fields(self) -> None:
        # FILL IN: build with channel="slack", channel_user_id="T01:U02", team_id="T01", nav_user_id="1042";
        # assert model_dump() has exactly those four keys — bounded by spec §2 Data Models
        ...
```

### FILL IN checklist
- [ ] `test_models.py::TestRetrySafe.test_round_trip` — JSON round trip; bounded by AC-7.
- [ ] `test_models.py::TestChannelLinkPreview.test_fields` — exact key set; bounded by spec §2.

---

## Acceptance Criteria

- [ ] `AuthRequiredEnvelope(provider="jira", message="m").retry_safe is False`.
- [ ] `UsersIntegrationRow` and `IntegrationDescriptor` accept `grant_origin` and default it to `None`.
- [ ] `from parrot.auth.oauth2 import ChannelLinkPreview` works.
- [ ] Existing `test_models.py` tests still pass (EnableResponse untouched).
- [ ] `ruff check` clean on both source files.

---

## Validation Commands

- `pytest tests/unit/integrations/oauth2/test_models.py -q`
- `pytest tests/unit/integrations/oauth2/test_agenttalk_envelope.py -q`

---

## Test Specification

See the `test_models.py` blueprint block above (two new classes, three tests).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src`)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5035 connections-web-slack verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
