# TASK-1806: Extract BedrockConverseBase + fix aws_id credential resolution

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. `NovaClient` (TASK-1809) must inherit the Bedrock
Converse text engine instead of delegating to a second client object. The
engine currently lives monolithically in `BedrockConverseClient`
(`packages/ai-parrot/src/parrot/clients/bedrock.py`, 1130 lines). Resolved at
spec time: the base **stays in `bedrock.py`** — no new module.

This task also fixes a latent bug shipped in commit `3672eb2f4`: the `aws_id`
branch reads the wrong `AWS_CREDENTIALS` keys and leaves credential attributes
unbound when the profile is missing (spec §1 Problem Statement, §2.2 of the
proposal).

---

## Scope

- Refactor `packages/ai-parrot/src/parrot/clients/bedrock.py`:
  - Introduce `class BedrockConverseBase(AbstractClient)` carrying EVERYTHING
    that is model-family-agnostic: `__init__` (credentials/region/guardrails/
    retries), `get_client`, `_translate_model`, `_is_capacity_error`,
    `_sdk_create`, `_sdk_stream`, `_prepare_messages`,
    `_to_bedrock_content_block`, `_to_bedrock_messages`, `_prepare_tools`,
    `_parse_json_schema_output`, `apply_guardrail_text`, `_invoke_native`,
    `ask`, `ask_stream`, `resume`, `invoke`.
  - Reduce `class BedrockConverseClient(BedrockConverseBase)` to the
    family-specific surface: `client_type`, `client_name`, `_default_model`,
    `_fallback_model`, `_min_cache_tokens` and any Claude/Anthropic-specific
    constants — public behavior byte-compatible.
- Fix the `aws_id` credential branch in the (now base) `__init__`:
  - Read keys `aws_key` / `aws_secret` / `region_name` (tolerate
    `aws_access_key_id` / `aws_secret_access_key` alternates, exactly like
    `interfaces/aws.py:53-54`).
  - When `AWS_CREDENTIALS.get(aws_id)` misses, fall back to the `'default'`
    profile; ALWAYS bind `_aws_access_key`, `_aws_secret_key`,
    `_aws_session_token`, `_region` (env/kwarg fallbacks as today).
- Add unit tests for the credential fix and a public-surface regression guard.

**NOT in scope**: the `nova/` subpackage (TASK-1807..1809), factory/model-map
changes (TASK-1810), any call-site migration (TASK-1811).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/bedrock.py` | MODIFY | Split into `BedrockConverseBase` + thin `BedrockConverseClient`; fix aws_id branch |
| `packages/ai-parrot/tests/clients/test_bedrock_credentials.py` | CREATE | aws_id resolution tests (correct keys, default fallback, always-bound attrs) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient          # clients/base.py:244
from parrot.conf import (
    AWS_CREDENTIALS,                                    # conf.py:490 — dict of profiles
    AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_SESSION_TOKEN,
    AWS_REGION_NAME, BEDROCK_AWS_REGION,                # conf.py:480
)
from parrot.models.bedrock_models import translate as translate_bedrock_model  # models/bedrock_models.py:100
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/bedrock.py
class BedrockConverseClient(AbstractClient):            # line 45
    _min_cache_tokens: int = 1024                       # line 61
    def __init__(self, aws_id=None, region=None, profile=None,
        region_prefix=None, guardrail_id=None, guardrail_version=None,
        max_retries: int = 4, read_timeout: int = 120,
        aws_access_key=None, aws_secret_key=None,
        aws_session_token=None, **kwargs): ...          # lines 64-140
    # ⚠ BUG at lines 109-120: credentials.get("access_key")/("secret_key")/
    #   ("session_token")/("region") — WRONG keys; else-branch attrs unbound on miss.
    # Workaround to PRESERVE at line ~135: kwargs.setdefault('fallback_model', self._fallback_model)
    async def get_client(self) -> Any: ...              # line 143 (lazy aioboto3 import)
    def _translate_model(self, model) -> str: ...       # line 179
    async def _sdk_create(self, payload: dict) -> Dict[str, Any]: ...      # line 217
    async def _sdk_stream(self, payload: dict) -> AsyncIterator[...]: ...  # line 221
    def _prepare_tools(self, filter_names=None) -> List[Dict[str, Any]]:   # line 330
    async def apply_guardrail_text(self, text, source="OUTPUT") -> str:    # line 400
    async def _invoke_native(self, messages, model, max_tokens, temperature, system_prompt):  # line 439
    async def ask(...): ...                             # line 494
    async def ask_stream(...): ...                      # line 780
    async def resume(...): ...                          # line 916
    async def invoke(...): ...                          # line 1046

# packages/ai-parrot/src/parrot/conf.py:490-531 — AWS_CREDENTIALS profiles:
# keys per profile: use_credentials, aws_key, aws_secret, region_name (+optional bucket_name)
# profile names: default, monitoring, cloudwatch, backend, security, security_bucket

# packages/ai-parrot/src/parrot/interfaces/aws.py:52-64 — CANONICAL resolver to copy:
credentials = AWS_CREDENTIALS.get(aws_id, {})
if not credentials or credentials == 'default':
    credentials = AWS_CREDENTIALS.get('default', {...})
access_key = credentials.get('aws_key') or credentials.get('aws_access_key_id')
secret_key = credentials.get('aws_secret') or credentials.get('aws_secret_access_key')
```

### Does NOT Exist
- ~~`parrot.conf.AWS_ID`~~ — the bedrock.py docstring mentions "AWS_ID" but no
  such config variable exists; do not invent it.
- ~~`AWS_CREDENTIALS[...]["access_key" | "secret_key" | "region" | "session_token"]`~~
  — those keys are the BUG, not the schema.
- ~~`BedrockConverseBase`~~ — does not exist yet; this task creates it.
- ~~`parrot/clients/_converse.py`~~ — rejected at spec time; do NOT create a new module.
- ~~top-level `parrot/clients/bedrock.py`~~ — real file is under
  `packages/ai-parrot/src/parrot/clients/`.

---

## Implementation Notes

### Pattern to Follow
The split is mechanical: move method bodies unchanged into
`BedrockConverseBase`; `BedrockConverseClient` keeps only class attributes and
docstring. Mirror how `AbstractClient` subclasses declare family constants
(`client_type`, `_default_model`).

### Key Constraints
- **Public surface byte-compatible**: every existing
  `tests/clients/test_bedrock_*.py` must pass UNMODIFIED.
- Preserve the `kwargs.setdefault('fallback_model', ...)` workaround in the
  base `__init__` (AbstractClient shadows `_fallback_model` — spec §7 gotcha).
- Credential resolution order (spec §1 Goals): explicit kwargs → `aws_id`
  profile (correct keys, `'default'` fallback) → env constants → SDK chain
  (attributes may be `None`, but must be BOUND).
- Google-style docstrings, type hints, `self.logger`.

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/aws.py:35-70` — credential resolver to replicate
- `packages/ai-parrot/tests/clients/test_bedrock_*.py` — regression suite

---

## Acceptance Criteria

- [ ] `BedrockConverseBase` exists in `bedrock.py`; `BedrockConverseClient(BedrockConverseBase)` is a thin subclass
- [ ] `from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient` works
- [ ] `BedrockConverseClient(aws_id='monitoring')` picks up `aws_key`/`aws_secret`/`region_name` from that profile
- [ ] Unknown `aws_id` falls back to the `'default'` profile; `_aws_access_key`/`_aws_secret_key`/`_aws_session_token`/`_region` are always bound
- [ ] All existing tests pass unmodified: `pytest packages/ai-parrot/tests/clients/test_bedrock_*.py -v`
- [ ] New tests pass: `pytest packages/ai-parrot/tests/clients/test_bedrock_credentials.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/bedrock.py` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_bedrock_credentials.py
import pytest
from parrot.clients.bedrock import BedrockConverseBase, BedrockConverseClient


@pytest.fixture
def patched_profiles(monkeypatch):
    profiles = {
        "default": {"aws_key": "DEF-K", "aws_secret": "DEF-S", "region_name": "us-east-1"},
        "monitoring": {"aws_key": "MON-K", "aws_secret": "MON-S", "region_name": "eu-west-1"},
    }
    monkeypatch.setattr("parrot.clients.bedrock.AWS_CREDENTIALS", profiles)
    return profiles


class TestAwsIdResolution:
    def test_named_profile_correct_keys(self, patched_profiles):
        c = BedrockConverseClient(aws_id="monitoring")
        assert c._aws_access_key == "MON-K"
        assert c._aws_secret_key == "MON-S"
        assert c._region == "eu-west-1"

    def test_missing_profile_falls_back_to_default(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        assert c._aws_access_key == "DEF-K"

    def test_attributes_always_bound(self, patched_profiles):
        c = BedrockConverseClient(aws_id="nope")
        for attr in ("_aws_access_key", "_aws_secret_key", "_aws_session_token", "_region"):
            assert hasattr(c, attr)

    def test_subclass_surface_unchanged(self):
        assert issubclass(BedrockConverseClient, BedrockConverseBase)
        assert BedrockConverseClient.client_type == "bedrock-converse"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§2 Overview, §3 Module 1, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-17
**Notes**: Split `BedrockConverseClient` into `BedrockConverseBase`
(engine) + thin `BedrockConverseClient(BedrockConverseBase)` (Claude/Llama/
Mistral family defaults only) in `bedrock.py`. Fixed the `aws_id`
credential branch to read `aws_key`/`aws_secret`/`region_name` (tolerating
`aws_access_key_id`/`aws_secret_access_key`), fall back to the `'default'`
profile when the named profile is missing, and always bind
`_aws_access_key`/`_aws_secret_key`/`_aws_session_token`/`_region`.
Resolution order implemented per spec §1 Goals: explicit kwargs → `aws_id`
profile → env constants → SDK chain. Added
`tests/clients/test_bedrock_credentials.py` (6 tests, all passing). Full
existing Bedrock suite (57 tests across `test_bedrock_*.py` +
`test_factory_bedrock.py`) passes unmodified. `ruff check` clean.

**Deviations from spec**: none
