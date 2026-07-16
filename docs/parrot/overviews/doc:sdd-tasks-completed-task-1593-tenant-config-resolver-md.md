---
type: Wiki Overview
title: 'TASK-1593: Per-Tenant Config Resolver'
id: doc:sdd-tasks-completed-task-1593-tenant-config-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The FULL mode handler needs a resolved `FullModeConfig` for each session.
  Config
relates_to:
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.tenant_config
  rel: mentions
---

# TASK-1593: Per-Tenant Config Resolver

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1591
**Assigned-to**: unassigned

---

## Context

The FULL mode handler needs a resolved `FullModeConfig` for each session. Config
comes from two layers: env var defaults and per-tenant DB overrides. This task
creates the resolver that merges them.

Interim implementation is env-only (matching `optin.py`'s pattern). The DB
override layer is deferred until Q-tenant-config-store is resolved.

Implements spec §3 Module 3.

---

## Scope

- Create `tenant_config.py` with `resolve_fullmode_config(tenant_id: Optional[str]) -> FullModeConfig`.
- Env vars: `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`, `LIVEAVATAR_VOICE_ID`,
  `LIVEAVATAR_LANGUAGE`, `LIVEAVATAR_INTERACTIVITY_TYPE`, `LIVEAVATAR_BASE_URL`,
  `LIVEAVATAR_SANDBOX`, `LIVEAVATAR_MAX_SESSION_DURATION`.
- Interim: env-only resolution. Leave a TODO for DB override layer.
- Write unit tests.

**NOT in scope**: DB storage layer (deferred to Q-tenant-config-store), handler
endpoints (TASK-1594), opt-in gating (TASK-1597).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/tenant_config.py` | CREATE | Config resolver function |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_tenant_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.models import FullModeConfig  # added by TASK-1591
from parrot.integrations.liveavatar.models import LiveAvatarConfig  # models.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py
# Pattern reference for env-var-driven resolution:
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str] = None) -> bool:  # line 58
    # Reads LIVEAVATAR_ENABLED_TENANTS and LIVEAVATAR_ENABLED_AGENTS from os.environ
```

### Does NOT Exist
- ~~`tenant_config.py`~~ — does not exist yet; this task creates it
- ~~`resolve_fullmode_config()`~~ — does not exist yet
- ~~`TenantConfigStore`~~ — no DB-backed config store exists; env-only for now

---

## Implementation Notes

### Pattern to Follow
```python
# Follow optin.py's env-var resolution pattern:
import os
from typing import Optional
from parrot.integrations.liveavatar.models import FullModeConfig


def resolve_fullmode_config(
    tenant_id: Optional[str] = None,
) -> FullModeConfig:
    """Resolve a FullModeConfig from env defaults (+ future per-tenant DB overrides).

    Resolution order:
    1. (Future) Per-tenant DB overrides via TenantAvatarConfig.
    2. Environment variables (LIVEAVATAR_*).
    3. FullModeConfig defaults.
    """
    api_key = os.environ.get("LIVEAVATAR_API_KEY", "")
    avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "")
    if not api_key or not avatar_id:
        raise RuntimeError(
            "LIVEAVATAR_API_KEY and LIVEAVATAR_AVATAR_ID must be set"
        )

    return FullModeConfig(
        api_key=api_key,
        avatar_id=avatar_id,
        voice_id=os.environ.get("LIVEAVATAR_VOICE_ID") or None,
        language=os.environ.get("LIVEAVATAR_LANGUAGE", "en"),
        interactivity_type=os.environ.get("LIVEAVATAR_INTERACTIVITY_TYPE", "CONVERSATIONAL"),
        base_url=os.environ.get("LIVEAVATAR_BASE_URL", "https://api.liveavatar.com"),
        is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false",
        max_session_duration=_parse_int_env("LIVEAVATAR_MAX_SESSION_DURATION"),
    )
    # TODO Q-tenant-config-store: overlay per-tenant DB overrides here
```

### Key Constraints
- Must raise `RuntimeError` if required env vars are missing (consistent with
  `VoiceAvatarSession.start()` at `voice_session.py:137`)
- Optional env vars use `None` as default (not empty string)
- The function is synchronous (env reads are instant; DB layer will be async when added)

---

## Acceptance Criteria

- [ ] `resolve_fullmode_config()` returns a valid `FullModeConfig` from env vars
- [ ] Raises `RuntimeError` when `LIVEAVATAR_API_KEY` or `LIVEAVATAR_AVATAR_ID` are missing
- [ ] Optional env vars (`VOICE_ID`, `LANGUAGE`, etc.) fall back to defaults
- [ ] `is_sandbox` correctly parses "true"/"false" string
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_tenant_config.py -v`

---

## Test Specification

```python
import os
import pytest
from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config


class TestResolveFullmodeConfig:
    def test_env_defaults(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        cfg = resolve_fullmode_config()
        assert cfg.api_key == "key"
        assert cfg.avatar_id == "avatar"
        assert cfg.language == "en"
        assert cfg.interactivity_type == "CONVERSATIONAL"
        assert cfg.voice_id is None

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("LIVEAVATAR_API_KEY", raising=False)
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        with pytest.raises(RuntimeError):
            resolve_fullmode_config()

    def test_custom_env_values(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_VOICE_ID", "voice-1")
        monkeypatch.setenv("LIVEAVATAR_LANGUAGE", "es")
        monkeypatch.setenv("LIVEAVATAR_INTERACTIVITY_TYPE", "PUSH_TO_TALK")
        cfg = resolve_fullmode_config()
        assert cfg.voice_id == "voice-1"
        assert cfg.language == "es"
        assert cfg.interactivity_type == "PUSH_TO_TALK"

    def test_sandbox_parsing(self, monkeypatch):
        monkeypatch.setenv("LIVEAVATAR_API_KEY", "key")
        monkeypatch.setenv("LIVEAVATAR_AVATAR_ID", "avatar")
        monkeypatch.setenv("LIVEAVATAR_SANDBOX", "false")
        cfg = resolve_fullmode_config()
        assert cfg.is_sandbox is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 3 and §7 Configuration Reference
2. **Check dependencies** — TASK-1591 must be completed (`FullModeConfig` exists)
3. **Create** `tenant_config.py` as a new file in the liveavatar package
4. **Write tests** in a new test file
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
