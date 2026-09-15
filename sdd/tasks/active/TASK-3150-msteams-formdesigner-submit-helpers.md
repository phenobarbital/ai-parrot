# TASK-3150: Bot-side pure helpers (`formdesigner_submit.py`) + `MSTeamsAgentConfig` fields — parse, verify (SSRF guard), answers, POST, reply card, dedupe

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3147
**Assigned-to**: unassigned
**Parallel**: true — new module + `models.py` + a new test file in `ai-parrot-integrations`; no file overlap with TASK-3148/3149 (parrot-formdesigner). Only import from TASK-3147 is `TeamsSubmitEnvelope`/`RESERVED_CONTROL_KEYS`/`ENVELOPE_KEY`.

---

## Context

Spec §3 Module 4 (first half; codex S3, S5, S6, S9, S10 confirmed). All verification, HTTP and
reply-card logic lives in a **botbuilder-free** module so it is fully unit-testable in the dev venv
(`botbuilder` is not installed locally — `tests/msteams/test_a2ui_submit.py:30` skips). The wrapper
branch (TASK-3151) is a thin caller. Security rule from S3: `activity.value` is user-controlled, so
`submit_url` is never trusted until it passes scheme → allowlist → path/tenant/uid → signature.

---

## Scope

- `msteams/formdesigner_submit.py`: `EnvelopeRejected`, `parse_envelope`, `verify_envelope`, `extract_answers`, `SubmitOutcome`, `post_submission`, `build_reply_card`, `RecentActivityCache`.
- `msteams/models.py`: four `MSTeamsAgentConfig` fields + `from_dict` + `__post_init__` env fallbacks (`{NAME}_FORMDESIGNER_ALLOWED_HOSTS` comma-separated, `{NAME}_FORMDESIGNER_SUBMIT_TOKEN`, `{NAME}_FORMDESIGNER_SUBMIT_SECRET`).
- Unit tests with an in-process aiohttp test server for `post_submission`.

**NOT in scope**: touching `wrapper.py` (TASK-3151); any Teams-side value coercion (S5 — forward raw).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` | CREATE | pure helpers |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | 4 config fields + from_dict + env fallbacks |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py` | CREATE | unit tests (no botbuilder) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope   # TASK-3147; integrations depends on parrot-formdesigner (pyproject.toml:55, :174)
from parrot.outputs.cards import CardSpec, TextSection, render                        # cards/__init__.py:59 (CardSpec), :42-57 (sections incl. TextSection), :41 (render)
import aiohttp                                                                        # already used: msteams/graph.py:116-136
from pydantic import BaseModel, ValidationError
from urllib.parse import urlparse
import time, collections, logging
# models.py existing imports
from dataclasses import dataclass, field ; from typing import TYPE_CHECKING, Dict, List, Optional, Any ; from navconfig import config   # models.py:4-6
```

### Existing Signatures to Use
```python
# msteams/models.py
@dataclass class MSTeamsAgentConfig:                                                   # 13-14
    allowed_conversation_ids: Optional[List[str]] = None; allowed_user_ids: Optional[List[str]] = None   # 43-44
    adaptive_card_version: str = DEFAULT_ADAPTIVE_CARD_VERSION                          # 46
    jira_client_id / jira_client_secret / jira_redirect_uri: Optional[str] = None       # 51-53  (precedent for feature-scoped fields)
    def __post_init__(self)                                                             # 55 ; jira env fallbacks :70-76 ; `if not self.jira_redirect_uri:` :75 ; comment "# Resolve whitelists from env vars (comma-separated)" :77
    @classmethod def from_dict(cls, name, data) -> 'MSTeamsAgentConfig'                 # 114-150 ; last kwargs jira_* :146-149
# msteams/graph.py (pattern)
self._session: Optional[aiohttp.ClientSession] = None :116 ; async def _get_session(self) :120-128 ; async def close(self) :130-136
# parrot.outputs.cards
class CardSpec(BaseModel): version: str = DEFAULT_ADAPTIVE_CARD_VERSION ...            # spec.py:15-21
def render(spec: CardSpec) -> dict                                                      # renderer.py (exported cards/__init__.py:41)
# renderers/teams.py (TASK-3147)
class TeamsSubmitEnvelope: v, wire, form_uid, tenant, form_version, is_public, submit_url: HttpUrl, form_url: HttpUrl, sig ; verify(secret) -> bool
RESERVED_CONTROL_KEYS == frozenset({"_action", "_formdesigner"})
# parrot_formdesigner submit contract (server side, unchanged)
POST {api}/{tenant}/forms/{form_uid}/data  -> 200 {"submission_id", "is_valid": True, "forwarded", ...} | 422 {"is_valid": False, "errors": {field_id: [msg,...]}} (may include "__unknown__") | 403 (private form) | 404   # handlers.py:1464-1530, spec §6
```

### Does NOT Exist
- ~~`parrot.integrations.msteams.formdesigner_submit`~~ — created by THIS task.
- ~~`MSTeamsAgentConfig.formdesigner_*`~~ — added by THIS task.
- ~~a Teams-side FieldType→coercion map~~ — forbidden (S5); `FormValidator._coerce_value` (validators.py:586) handles `"true"`, numeric strings, `"a,b"`.
- ~~`TextSection(text=...)` exact kwargs~~ — VERIFY the section model fields in `parrot/outputs/cards/sections.py` before use (`grep -n "class TextSection" -A 8`); if uncertain, build the reply card as a raw Adaptive Card dict (`{"type": "AdaptiveCard", "version": DEFAULT_ADAPTIVE_CARD_VERSION, "body": [TextBlock...]}`) — both are acceptable.
- ~~`hmac` verification in this module~~ — call `env.verify(secret)`; the algorithm lives in `TeamsSubmitEnvelope`.
- ~~redis in this task~~ — `RecentActivityCache` is in-process only (Redis is an optional follow-up).

---

## Implementation Notes

### Pattern to Follow
```python
# graph.py:120-128 — but the SESSION is owned by the wrapper (TASK-3151); helpers take it as a parameter.
async def post_submission(session: aiohttp.ClientSession, ...): ...
```

### Key Constraints
- `verify_envelope` order is fixed: https → host allowlist (lowercase exact match) → path equality → sig (only when secret given). Each failure raises `EnvelopeRejected` with a short user-facing reason.
- `post_submission`: `allow_redirects=False`, `timeout=aiohttp.ClientTimeout(total=timeout)`, read at most `max_response_bytes` (`await resp.content.read(max_response_bytes + 1)`, reject if longer), JSON-decode best-effort; on `aiohttp.ClientError`/`asyncio.TimeoutError` → `SubmitOutcome(status=0, body=None, error=str(exc))`.
- Never log the bearer token or secret.

---

## Implementation Blueprint

### Steps (in order)
1. Add config fields + `from_dict` keys + env fallbacks in `models.py` — *why*: wrapper reads them; env fallbacks follow the Jira precedent so ops config is uniform.
2. Create `formdesigner_submit.py` — *why*: S3/S6/S9/S10 all land here as pure, testable functions.
3. Tests with `aiohttp.test_utils` (`AioHTTPTestCase` or the `aiohttp_client` fixture from `pytest-aiohttp`, already used by parrot-formdesigner tests) — *why*: exercise real HTTP paths (200/422/403/timeout/redirect refused).

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'jira_redirect_uri: Optional\[str\] = None' msteams/models.py)
# AFTER — insert below `    jira_redirect_uri: Optional[str] = None` (verified: models.py:53)

    # FormDesigner card submissions — FEAT-551
    # The bot forwards `_formdesigner` Action.Submit envelopes to POST .../forms/{uid}/data.
    formdesigner_allowed_hosts: Optional[List[str]] = None   # None/[] disables the branch
    formdesigner_submit_token: Optional[str] = None           # Authorization: Bearer (private forms)
    formdesigner_submit_secret: Optional[str] = None          # HMAC secret; envelopes must carry a valid sig when set
    formdesigner_submit_timeout: float = 15.0

# occurrences: 1 (verified: grep -c 'if not self.jira_redirect_uri:' msteams/models.py)
# AFTER — insert below the 2-line `if not self.jira_redirect_uri:` block (verified: models.py:75-76)
        # FormDesigner env fallbacks (FEAT-551)
        if not self.formdesigner_submit_token:
            self.formdesigner_submit_token = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_TOKEN")
        if not self.formdesigner_submit_secret:
            self.formdesigner_submit_secret = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET")
        if not self.formdesigner_allowed_hosts:
            raw_hosts = config.get(f"{self.name.upper()}_FORMDESIGNER_ALLOWED_HOSTS")
            if raw_hosts:
                self.formdesigner_allowed_hosts = [h.strip().lower() for h in str(raw_hosts).split(",") if h.strip()]

# occurrences: 1 (verified: grep -c "jira_redirect_uri=data.get('jira_redirect_uri')," msteams/models.py)
# AFTER — insert below `            jira_redirect_uri=data.get('jira_redirect_uri'),` (verified: models.py:149)
            # FormDesigner (FEAT-551)
            formdesigner_allowed_hosts=data.get('formdesigner_allowed_hosts'),
            formdesigner_submit_token=data.get('formdesigner_submit_token'),
            formdesigner_submit_secret=data.get('formdesigner_submit_secret'),
            formdesigner_submit_timeout=float(data.get('formdesigner_submit_timeout', 15.0)),
```
**Why**: same shape as the Jira OAuth fields (`:51-53`, `:70-76`, `:146-149`) so `from_dict`/env behaviour is predictable.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` (CREATE)
```python
"""Pure helpers for forwarding FormDesigner Teams-card submissions (FEAT-551 M4).

No botbuilder import here on purpose: everything is unit-testable without the ``msteams`` extra.
The wrapper (``wrapper.py``) owns the aiohttp session and calls these in order:
parse_envelope -> verify_envelope -> RecentActivityCache.seen -> extract_answers -> post_submission -> build_reply_card.
"""
from __future__ import annotations

import asyncio, collections, logging, time
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ValidationError

from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION       # verified: cards/spec.py:12
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope   # TASK-3147

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES: int = 1_048_576


class EnvelopeRejected(Exception):
    """User-facing reason why a card submission was refused."""


def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope:
    """Validate ``submitted_data["_formdesigner"]``; raise EnvelopeRejected when missing/malformed."""
    raw = submitted_data.get(ENVELOPE_KEY)
    if not isinstance(raw, dict):
        raise EnvelopeRejected("This card does not carry a valid FormDesigner envelope.")
    try:
        return TeamsSubmitEnvelope.model_validate(raw)
    except ValidationError as exc:
        logger.warning("formdesigner envelope rejected: %s", exc.error_count())
        raise EnvelopeRejected("This card's FormDesigner envelope is malformed.") from exc


def verify_envelope(env: TeamsSubmitEnvelope, *, allowed_hosts: list[str], secret: str | None,
                    api_base_path: str = "/api/v1") -> None:
    """SSRF guard (spec S3). Order: https -> host allowlist -> path/tenant/uid -> signature."""
    url = urlparse(str(env.submit_url))
    if url.scheme != "https":
        raise EnvelopeRejected("Submission target must use https.")
    if (url.hostname or "").lower() not in {h.lower() for h in allowed_hosts}:
        raise EnvelopeRejected("Submission target host is not allowed for this bot.")
    expected_path = f"{api_base_path.rstrip('/')}/{env.tenant}/forms/{env.form_uid}/data"
    if url.path != expected_path:
        raise EnvelopeRejected("Submission target does not match the form in the envelope.")
    if secret is not None and not env.verify(secret):
        raise EnvelopeRejected("Submission envelope signature is invalid.")


def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]:
    """Raw card values minus exactly the reserved control keys (spec S5/S6 — no coercion here)."""
    return {k: v for k, v in submitted_data.items() if k not in RESERVED_CONTROL_KEYS}


class SubmitOutcome(BaseModel):
    """Result of the forwarding POST. ``status == 0`` means the request never completed."""
    status: int
    body: dict[str, Any] | None = None
    error: str | None = None


async def post_submission(session: aiohttp.ClientSession, env: TeamsSubmitEnvelope, answers: dict[str, Any], *,
                          bearer_token: str | None, timeout: float,
                          max_response_bytes: int = MAX_RESPONSE_BYTES) -> SubmitOutcome:
    """POST the legacy JSON body to ``env.submit_url`` (no redirects, bounded timeout and body size)."""
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    # FILL IN: async with session.post(str(env.submit_url), json=answers, headers=headers, allow_redirects=False,
    #   timeout=aiohttp.ClientTimeout(total=timeout)) as resp: raw = await resp.content.read(max_response_bytes + 1);
    #   if len(raw) > max_response_bytes -> SubmitOutcome(status=resp.status, error="response too large");
    #   body = json.loads(raw) if raw else None (best-effort, dict only); return SubmitOutcome(status=resp.status, body=body)
    #   except (aiohttp.ClientError, asyncio.TimeoutError) as exc: return SubmitOutcome(status=0, error=type(exc).__name__)
    #   — bounded by S10 (never raise, never log the token)
    raise NotImplementedError


def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]:
    """Map the outcome to an Adaptive Card dict (spec §3 M4 mapping: 200 / 422 / 401-403 / 404 / 0-5xx)."""
    # FILL IN: build body TextBlocks per status; 422 lists body["errors"] items as "- field: msg" (incl. "__unknown__");
    #   return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    #           "version": DEFAULT_ADAPTIVE_CARD_VERSION, "body": [...]} — bounded by spec §3 M4 build_reply_card docstring
    raise NotImplementedError


class RecentActivityCache:
    """Best-effort in-process TTL set of Bot Framework activity ids (spec S9)."""

    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._seen: "collections.OrderedDict[str, float]" = collections.OrderedDict()

    def seen(self, activity_id: str) -> bool:
        """Return True if ``activity_id`` was recorded within the TTL; otherwise record it and return False."""
        # FILL IN: evict expired (now - ts > ttl) and oldest beyond max_items; then check/insert — bounded by S9
        raise NotImplementedError
```
**Why this shape**: every function is pure or takes its I/O dependency as a parameter, so the wrapper test (TASK-3151) can mock them and this task's tests can hit a real aiohttp test server. `verify_envelope` is the only place the S3 policy is encoded.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py` (CREATE)
```python
"""Unit tests for msteams.formdesigner_submit (FEAT-551 TASK-3150) — no botbuilder needed."""
import uuid
import pytest
from aiohttp import web
from parrot.integrations.msteams.formdesigner_submit import (
    EnvelopeRejected, RecentActivityCache, SubmitOutcome, build_reply_card, extract_answers, parse_envelope,
    post_submission, verify_envelope,
)
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, TeamsSubmitEnvelope

pytestmark = pytest.mark.asyncio
FORM_UID = uuid.uuid4()


def _env(**over) -> TeamsSubmitEnvelope:
    base = dict(form_uid=FORM_UID, tenant="navigator", form_version="1.0", is_public=True,
                submit_url=f"https://forms.test/api/v1/navigator/forms/{FORM_UID}/data",
                form_url=f"https://forms.test/navigator/forms/{FORM_UID}")
    base.update(over)
    return TeamsSubmitEnvelope(**base)


def test_parse_envelope_rejects_malformed():
    with pytest.raises(EnvelopeRejected):
        parse_envelope({"_action": "submit"})
    with pytest.raises(EnvelopeRejected):
        parse_envelope({ENVELOPE_KEY: {"form_uid": "nope"}})
    assert parse_envelope({ENVELOPE_KEY: _env().model_dump(mode="json")}).tenant == "navigator"


@pytest.mark.parametrize("over,reason", [
    ({"submit_url": f"http://forms.test/api/v1/navigator/forms/{FORM_UID}/data"}, "https"),
    ({"submit_url": f"https://evil.test/api/v1/navigator/forms/{FORM_UID}/data"}, "not allowed"),
    ({"submit_url": f"https://forms.test/api/v1/other/forms/{FORM_UID}/data"}, "does not match"),
    ({"submit_url": f"https://forms.test/api/v1/navigator/forms/{uuid.uuid4()}/data"}, "does not match"),
])
def test_verify_envelope_rules(over, reason):
    with pytest.raises(EnvelopeRejected, match=reason):
        verify_envelope(_env(**over), allowed_hosts=["forms.test"], secret=None)


def test_verify_envelope_signature():
    signed = _env().sign("s3cr3t")
    verify_envelope(signed, allowed_hosts=["FORMS.test"], secret="s3cr3t")
    with pytest.raises(EnvelopeRejected, match="signature"):
        verify_envelope(_env(), allowed_hosts=["forms.test"], secret="s3cr3t")


def test_extract_answers_keeps_underscore_field_ids():
    data = {"_action": "submit", ENVELOPE_KEY: {}, "_department": "ops", "age": "42", "ok": "true"}
    assert extract_answers(data) == {"_department": "ops", "age": "42", "ok": "true"}


async def test_post_submission_outcomes(aiohttp_client):
    # FILL IN: aiohttp app with POST handler returning 200/422/403 by a marker in the JSON body, a 302 redirect route,
    #   and a slow route (asyncio.sleep) for timeout; build a client, monkeypatch env.submit_url to the test server
    #   (use http:// here — verify_envelope is NOT called in this test); assert statuses, redirect not followed (status 302),
    #   timeout -> status 0, bearer header present iff token — bounded by S10
    raise NotImplementedError


def test_build_reply_card_mapping():
    # FILL IN: 200 -> contains submission_id; 422 -> lists "email"; 403 -> "private"; 0 -> "could not reach" — bounded by spec §3 M4
    raise NotImplementedError


def test_recent_activity_cache():
    c = RecentActivityCache(ttl_seconds=60)
    assert c.seen("a") is False and c.seen("a") is True and c.seen("b") is False


def test_config_from_dict_formdesigner_fields():
    cfg = MSTeamsAgentConfig.from_dict("bot", {"formdesigner_allowed_hosts": ["forms.test"], "formdesigner_submit_timeout": "5"})
    assert cfg.formdesigner_allowed_hosts == ["forms.test"] and cfg.formdesigner_submit_timeout == 5.0
    assert MSTeamsAgentConfig.from_dict("bot", {}).formdesigner_allowed_hosts in (None, [])
```
**Why**: pins the S3 order and messages, S6 key handling, and the HTTP bounds independent of the bot.

### FILL IN checklist
- [ ] `formdesigner_submit.py::post_submission` — bounded by S10 (no raise, no token in logs, redirects off, size cap).
- [ ] `formdesigner_submit.py::build_reply_card` — bounded by the spec §3 M4 mapping; verify `parrot.outputs.cards` section kwargs before using them, else raw dict.
- [ ] `formdesigner_submit.py::RecentActivityCache.seen` — bounded by S9.
- [ ] tests `test_post_submission_outcomes`, `test_build_reply_card_mapping`.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_submit.py -v` (runs WITHOUT botbuilder)
- [ ] `grep -c "botbuilder" packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` prints `0`
- [ ] No linting errors: `ruff check` on the three files
- [ ] `verify_envelope` rejects http, non-allowlisted host, path/tenant/uid mismatch, bad/missing sig when a secret is set — in that order
- [ ] `extract_answers` preserves `_department`-style field ids and removes exactly `_action` and `_formdesigner`
- [ ] `MSTeamsAgentConfig.from_dict({})` keeps backward-compatible defaults

---

## Test Specification

See blueprint block for `test_formdesigner_submit.py`.

---

## Agent Instructions

1. Read spec §3 M4, §6, §7 (Known Risks).
2. Check TASK-3147 is in `sdd/tasks/completed/` (in the feature worktree or merged).
3. Verify anchors (`grep -n "jira_redirect_uri" msteams/models.py`; `grep -n "class TextSection" -A 8 packages/ai-parrot/src/parrot/outputs/cards/sections.py`).
4. Update index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-3150-msteams-formdesigner-submit-helpers.md`; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
