# TASK-4945: ToolManager and AgentTalk convert both needs-auth signals; AuthRequiredEnvelope superset fields

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4944
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 catch sites (G5, S8, AC-6). `ToolManager.execute_tool` catches only `AuthorizationRequired`
(manager.py:2273); `CredentialRequired` falls into the generic `except Exception`. AgentTalk (handlers/agent.py:1916)
likewise. Both must convert either signal to the same payload. `AuthRequiredEnvelope` gains the device-code fields.
High blast radius: every tool call goes through `execute_tool` — change only the except clause.

---

## Scope

- `tools/manager.py`: import `CredentialRequired`; `except (AuthorizationRequired, CredentialRequired) as auth_exc:` →
  `payload = auth_exc.to_payload()` (pass `tool_name=tool_name` for `CredentialRequired`) →
  `ToolResult(success=False, status="authorization_required", result=None, error=payload.message, metadata=payload.model_dump())`.
- `handlers/agent.py`: same tuple; `AuthRequiredEnvelope(**payload.model_dump())`.
- `oauth2/models.py`: `AuthRequiredEnvelope` optional `auth_kind`, `user_code`, `verification_uri`, `expires_in`.
- Tests: `test_toolmanager_catches_credential_required`, `test_auth_required_payload_superset` (ToolResult half),
  update `test_agenttalk_envelope.py` and `test_tool_credential_seam.py` expectations.

**NOT in scope**: any other ToolManager behaviour; removing the FEAT-083 placeholder tool (S-3a).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | catch both signals |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | AgentTalk catch both signals |
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | AuthRequiredEnvelope superset fields |
| `tests/unit/integrations/oauth2/test_agenttalk_envelope.py` | MODIFY | both signals → same envelope |
| `packages/ai-parrot/tests/unit/test_tool_credential_seam.py` | MODIFY | CredentialRequired → ToolResult |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from ..auth.exceptions import AuthorizationRequired          # verified: tools/manager.py:19 (anchor)
from ..auth.credentials import CredentialRequired            # verified: credentials.py:113 (relative from parrot/tools)
from parrot.auth.credentials import CredentialRequired       # server handler (absolute, like :52 imports)
from parrot.auth.oauth2.models import AuthRequiredEnvelope   # verified: handlers/agent.py:52
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
from ..auth.exceptions import AuthorizationRequired                                  # :19
async def execute_tool(self, tool_name, parameters, permission_context=None, *, return_tool_result=False)  # :1787
        except AuthorizationRequired as auth_exc:                                    # :2273 → ToolResult(... metadata={auth_url,
                                                                                     #   provider, scopes, tool_name}) :2279-2290
        except Exception as e:                                                       # :2291
# packages/ai-parrot-server/src/parrot/handlers/agent.py
from ..auth.exceptions import AuthorizationRequired                                  # :51
from parrot.auth.oauth2.models import AuthRequiredEnvelope                           # :52
        except AuthorizationRequired as exc:                                         # :1916 → envelope + json_response(status=200)
# packages/ai-parrot/src/parrot/auth/oauth2/models.py
class AuthRequiredEnvelope(BaseModel):  # :117 type="auth_required", provider, tool_name=None, auth_url=None, scopes, message
# packages/ai-parrot/src/parrot/tools/abstract.py:1194-1197 — AbstractTool.execute re-raises CredentialRequired
```

### Does NOT Exist
- ~~`ToolManager` catching `CredentialRequired`~~ — added here (today only `AuthorizationRequired`, manager.py:2273).
- ~~`AuthRequiredEnvelope.auth_kind` etc.~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/unit/integrations/oauth2/test_agenttalk_envelope.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_tool_credential_seam.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.execute_tool",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#AuthRequiredEnvelope"
  ]
}
```

---

## Implementation Notes

- Run `wikitoolkit symbols blast ToolManager.execute_tool` before editing (wide fan-in) and keep the diff to the except clause + import.
- `metadata=payload.model_dump()` keeps the old keys (`auth_url`, `provider`, `scopes`, `tool_name`) — existing consumers keep working.
- `AuthRequiredEnvelope` must accept `**payload.model_dump()`: ensure its field names match the payload (it has `type` too — leave the default).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Import + except tuple in `tools/manager.py` (block A) — *why*: AC-6.
2. AgentTalk except tuple (block B) — *why*: AC-6 web surface.
3. Envelope fields (block C) — *why*: device-code fields survive to the frontend.
4. Update/add tests.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..auth.exceptions import AuthorizationRequired' tools/manager.py → :19)
# AFTER — insert below it:
from ..auth.credentials import CredentialRequired

# occurrences: 1 (verified: grep -c '        except AuthorizationRequired as auth_exc:' tools/manager.py → :2273)
# REPLACE the whole except block (:2273-2290) WITH:
        except (AuthorizationRequired, CredentialRequired) as auth_exc:
            payload = (auth_exc.to_payload(tool_name=tool_name) if isinstance(auth_exc, CredentialRequired)
                       else auth_exc.to_payload())
            self.logger.info("Authorization required for tool %s: provider=%s", tool_name, payload.provider)
            return ToolResult(success=False, status="authorization_required", result=None,
                              error=payload.message, metadata=payload.model_dump())
```
FILL IN: confirm `parrot.auth.credentials` imports nothing from `parrot.tools` (no cycle) — it imports only stdlib +
pydantic at module level (credentials.py:27-36).

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        except AuthorizationRequired as exc:' handlers/agent.py → :1916)
# REPLACE the except block (:1916-1927) WITH:
        except (AuthorizationRequired, CredentialRequired) as exc:
            # Structured envelope so the web frontend renders a "Connect" pill (HTTP 200 — the chat call succeeded).
            payload = exc.to_payload() if isinstance(exc, AuthorizationRequired) else exc.to_payload(tool_name=None)
            envelope = AuthRequiredEnvelope(**payload.model_dump())
            return web.json_response(envelope.model_dump(), status=200)
# FILL IN: add `from parrot.auth.credentials import CredentialRequired` next to the :51-52 imports
```

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class AuthRequiredEnvelope(BaseModel):' oauth2/models.py → :117)
# INSIDE AuthRequiredEnvelope — after `message: str` add:
    auth_kind: Optional[str] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None
```
FILL IN: if `message` has no default and the payload's message is `""`, keep it valid (`""` is a str — fine).

### FILL IN checklist
- [ ] verify no import cycle tools.manager → auth.credentials
- [ ] AgentTalk import line
- [ ] `test_toolmanager_catches_credential_required` in test_tool_credential_seam.py
- [ ] test_agenttalk_envelope.py: CredentialRequired case returns the same envelope shape

---

## Acceptance Criteria

- [ ] AC-6: `ToolManager.execute_tool` converts both `AuthorizationRequired` and `CredentialRequired` to `ToolResult(status='authorization_required', metadata=AuthRequiredPayload)`
- [ ] AgentTalk returns `AuthRequiredEnvelope` (HTTP 200) for both; device-code fields survive
- [ ] Old metadata keys (`auth_url`, `provider`, `scopes`, `tool_name`) still present

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_tool_credential_seam.py -q`
- `pytest tests/unit/integrations/oauth2/test_agenttalk_envelope.py -q`
- `pytest packages/ai-parrot/tests/unit/test_auth_required.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_tool_credential_seam.py (add)
@pytest.mark.asyncio
async def test_toolmanager_catches_credential_required():
    ...  # FILL IN: register a tool whose execute raises CredentialRequired("o365","https://dev","device_code",
         #          user_code="ABCD"); execute_tool(..., return_tool_result=True) → status "authorization_required",
         #          metadata["user_code"] == "ABCD", metadata["provider"] == "o365"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
