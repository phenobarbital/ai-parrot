# TASK-1875: Wire custom_llm_url into /full/start response

**Feature**: FEAT-247 — LiveAvatar FULL Mode Custom LLM
**Spec**: `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1874
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The existing `/api/v1/avatar/fullmode/{agent_id}/start`
handler (FEAT-248) returns `{session_id, livekit_url, livekit_client_token}`.
For LiveAvatar Custom LLM integration, the response must also include the
per-session OpenAI-compat URL so the frontend can pass it to LiveAvatar's
Custom LLM configuration.

---

## Scope

- Modify `_start_fullmode_session()` in `handlers/avatar_fullmode.py` to:
  - Compute `custom_llm_url` from the request's base URL + session_id + agent:
    `{scheme}://{host}/v1/chat/completions/{session_id}?agent={agent_id}`
  - Include `custom_llm_url` in the JSON response alongside existing fields
- Add test verifying the new response field

**NOT in scope**: the OpenAI-compat endpoint itself (TASK-1874), route
registration (TASK-1876), any LiveAvatarClient changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` | MODIFY | Add `custom_llm_url` to start response (~line 181-185) |
| `packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py` | MODIFY | Add test for `custom_llm_url` in response (or create if absent) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handlers/avatar_fullmode.py — already imported/used:
from aiohttp import web
```

### Existing Signatures to Use
```python
# handlers/avatar_fullmode.py:60
async def _start_fullmode_session(request: web.Request) -> web.Response:
    # ...
    # line 180-185 — current response:
    return web.json_response({
        "session_id": session_id,
        "livekit_url": handle.livekit_url,
        "livekit_client_token": handle.livekit_client_token,
    })
```

### Does NOT Exist
- ~~`custom_llm_url` in the start response~~ — this task adds it
- ~~`LiveAvatarClient.create_full_session(custom_llm_url=...)` param~~ — the
  client does not accept custom_llm_url; we only add it to the HTTP response

---

## Implementation Notes

### Pattern to Follow
```python
# In _start_fullmode_session, after creating the session handle:
base_url = f"{request.scheme}://{request.host}"
agent_id = request.match_info["agent_id"]
custom_llm_url = (
    f"{base_url}/v1/chat/completions/{session_id}"
    f"?agent={agent_id}"
)

return web.json_response({
    "session_id": session_id,
    "livekit_url": handle.livekit_url,
    "livekit_client_token": handle.livekit_client_token,
    "custom_llm_url": custom_llm_url,
})
```

### Key Constraints
- Do NOT break existing consumers of `/full/start` — the new field is additive
- `request.host` includes port if non-standard; `request.scheme` respects
  `X-Forwarded-Proto` if aiohttp is behind a reverse proxy (verify)
- Consider env var override for the base URL (e.g. `OPENAI_COMPAT_BASE_URL`)
  in case the public-facing URL differs from the internal `request.host`

---

## Acceptance Criteria

- [ ] `/full/start` response JSON includes `custom_llm_url` with correct session_id and agent
- [ ] Existing fields (`session_id`, `livekit_url`, `livekit_client_token`) unchanged
- [ ] Test verifies `custom_llm_url` format
- [ ] `ruff check` clean on modified file

---

## Test Specification

```python
async def test_start_returns_custom_llm_url():
    """POST /fullmode/{agent}/start includes custom_llm_url in response."""
    # Mock the LiveAvatar client, call _start_fullmode_session
    # Assert response contains custom_llm_url matching pattern:
    # /v1/chat/completions/{session_id}?agent={agent_id}
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/liveavatar-full-mode-custom-llm.spec.md`
2. **Check dependencies** — TASK-1874 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — re-read `avatar_fullmode.py:180-185`
4. **Update status** in `sdd/tasks/index/liveavatar-full-mode-custom-llm.json` → `"in-progress"`
5. **Implement** the response modification + test
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
8. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
