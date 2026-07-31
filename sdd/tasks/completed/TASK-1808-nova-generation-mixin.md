# TASK-1808: NovaGeneration mixin — Nova Canvas image + Nova Reel video

**Feature**: FEAT-315 — Unified NovaClient for all Amazon Nova models
**Spec**: `sdd/specs/novaclient-amazon-aws.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1806
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. New capability mixin `NovaGeneration` at
`packages/ai-parrot/src/parrot/clients/nova/generation.py` covering image
(Nova Canvas) and video (Nova Reel) generation, with method names mirroring
`GoogleGeneration` (`generate_image`, `video_generation`) so callers can swap
providers. Scope is minimal parity (resolved U4): no batch variants, no reel
assembly, no speech.

AWS facts verified 2026-07-17 (spec §6 "Verified AWS Facts"):
- Canvas `amazon.nova-canvas-v1:0`: synchronous `invoke_model`,
  `taskType: "TEXT_IMAGE"`, base64 images in the response body. In-region
  only (us-east-1, eu-west-1, ap-northeast-1).
- Reel `amazon.nova-reel-v1:0`: `start_async_invoke` → `get_async_invoke`
  polling ONLY. Requires `outputDataConfig.s3OutputDataConfig.s3Uri`.

---

## Scope

- Create `nova/generation.py` with `class NovaGeneration` (plain mixin, no
  `__init__`, no base class):
  - `async def generate_image(self, prompt, *, model=None, negative_prompt=None,
    number_of_images=1, width=1024, height=1024, seed=None,
    output_directory=None, as_base64=False, **kwargs) -> AIMessage`
    — default model `"nova-canvas"`; build the Canvas payload
    (`taskType: "TEXT_IMAGE"`, `textToImageParams`, `imageGenerationConfig`);
    call `invoke_model` via the inherited per-loop aioboto3 client
    (`await self._ensure_client()`); decode base64 images; save to
    `output_directory` with `aiofiles` when given; return an `AIMessage`
    carrying file paths and/or base64 payloads.
  - `async def video_generation(self, prompt, *, model=None,
    reference_image=None, duration=6, output_directory=None,
    s3_output_uri=None, poll_interval=10.0, timeout=900.0, **kwargs) -> AIMessage`
    — default model `"nova-reel"`; resolve S3 URI: kwarg →
    `AWS_CREDENTIALS[self._aws_id]["bucket_name"]` → raise `ValueError` with
    an actionable message; `start_async_invoke` → poll `get_async_invoke`
    until `Completed`/`Failed`/timeout; download the MP4 from S3
    (aioboto3 s3 client, same credentials) into `output_directory`.
- Model IDs always resolved through `self._translate_model(model or default)`.
- Unit tests with mocked SDK clients (no AWS calls).

**NOT in scope**: `generate_image_batch`/`generate_video_batch` (non-goal),
Canvas task types other than `TEXT_IMAGE`, `NovaClient` composition
(TASK-1809), map entries for `nova-canvas`/`nova-reel` (TASK-1810 — until it
lands, `translate()` warns+passes-through; tests should pass full Bedrock IDs
or patch the map).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/generation.py` | CREATE | `NovaGeneration` mixin |
| `packages/ai-parrot/tests/clients/test_nova_generation.py` | CREATE | Canvas payload/decode + Reel poll/download tests (mocked) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import AWS_CREDENTIALS                 # conf.py:490
from parrot.models.responses import AIMessage, AIMessageFactory
# aioboto3 — import lazily inside methods (pattern: bedrock.py get_client, line 143)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/bedrock.py (post TASK-1806) — inherited by the composed client:
class BedrockConverseBase(AbstractClient):
    def _translate_model(self, model: Optional[str]) -> str: ...   # was line 179
    async def get_client(self) -> Any: ...                         # was line 143 — bedrock-runtime client
    # self._ensure_client() — AbstractClient per-loop cache, used at bedrock.py:186
    # self._aws_id, self._aws_access_key, self._aws_secret_key, self._region — bound by base __init__

# Canvas invoke payload (verified: AWS model card sample, 2026-07-17):
# client.invoke_model(modelId='amazon.nova-canvas-v1:0', body=json.dumps({
#   'taskType': 'TEXT_IMAGE',
#   'textToImageParams': {'text': prompt},                    # + 'negativeText' optional
#   'imageGenerationConfig': {'numberOfImages': 1, 'height': 1024, 'width': 1024}  # + 'seed'
# }))
# response_body = json.loads(response['body'].read()); response_body['images'][0]  # base64 str

# Reel async invoke (verified: AWS model card sample, 2026-07-17):
# client.start_async_invoke(modelId='amazon.nova-reel-v1:0', modelInput={...},
#   outputDataConfig={'s3OutputDataConfig': {'s3Uri': 's3://bucket/prefix/'}})
# then client.get_async_invoke(invocationArn=...) → status polling

# AWS_CREDENTIALS profile optional key "bucket_name" — conf.py:497 ('default'),
# conf.py:527 ('security_bucket'); precedent for bucket resolution:
# packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:328-384

# Reference mixin shape + save helpers:
# packages/ai-parrot/src/parrot/clients/google/generation.py
#   async def generate_image(...)   — line 1642 (parameter naming parity)
#   async def video_generation(...) — line 903  (parameter naming parity)
#   uses aiofiles for async file writes (module imports, top of file)
```

### Does NOT Exist
- ~~`invoke_model` / `converse` for Nova Reel~~ — Reel is StartAsyncInvoke-ONLY.
- ~~`amazon.nova-reel-v1:1`~~ — current model card lists `v1:0`; do not hard-code v1:1.
- ~~`get_async_invoke(jobId=...)`~~ — the identifier is `invocationArn`.
- ~~`PUBLIC_TO_BEDROCK["nova-canvas" | "nova-reel"]`~~ — not in the map until
  TASK-1810; `translate()` warns and passes unknown IDs through unchanged
  (models/bedrock_models.py:130-138).
- ~~Nova Canvas streaming / Converse support~~ — Invoke only.
- ~~`NovaGeneration.__init__`~~ — mixin must not define one.
- ~~`requests` / `httpx`~~ — forbidden repo-wide; S3 download via aioboto3.

---

## Implementation Notes

### Pattern to Follow
`GoogleGeneration` (`clients/google/generation.py`) — mixin methods that
log via `self.logger`, honor `output_directory: Path`, and return `AIMessage`
objects built with `AIMessageFactory`. Keep parameter names aligned with the
Google methods where semantics match (spec §2 New Public Interfaces).

### Key Constraints
- Lazy `aioboto3` import inside methods (optional-dep hygiene, bedrock.py precedent).
- Poll loop: `asyncio.sleep(poll_interval)`; overall `timeout` honored; job
  `Failed` status → raise `InvokeError` (`parrot.exceptions`, used by bedrock.py:38).
- S3 download uses the SAME resolved credentials as the runtime client.
- Reel S3 housekeeping: keep the object after download (spec §8 unresolved —
  default keep; a `cleanup_s3: bool = False` kwarg is optional).
- Async file I/O with `aiofiles` (google/generation.py precedent).

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/google/generation.py:903,1642` — parity signatures
- `packages/ai-parrot/src/parrot/clients/bedrock.py:143-230` — client construction + SDK wrapper style
- `packages/parrot-formdesigner/.../blob_storage.py:328-384` — bucket_name-from-profile precedent

---

## Acceptance Criteria

- [ ] `from parrot.clients.nova.generation import NovaGeneration` works
- [ ] `generate_image()` builds a correct `TEXT_IMAGE` payload, decodes base64 images, saves files when `output_directory` is set (mocked invoke_model)
- [ ] `video_generation()` runs start→poll→download; respects `poll_interval`/`timeout`; raises `InvokeError` on job failure (mocked)
- [ ] Missing S3 config raises `ValueError` mentioning both `s3_output_uri` and `bucket_name`
- [ ] `pytest packages/ai-parrot/tests/clients/test_nova_generation.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/nova/generation.py` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_generation.py
import base64, json
import pytest
from unittest.mock import AsyncMock
from parrot.clients.nova.generation import NovaGeneration


class Host(NovaGeneration):
    """Minimal composition host with the attributes the mixin reads."""
    _aws_id = None
    def __init__(self, client): self._client = client; self.logger = ...
    def _translate_model(self, m): return m or "amazon.nova-canvas-v1:0"
    async def _ensure_client(self): return self._client


async def test_generate_image_payload_and_decode(tmp_path):
    fake = AsyncMock()
    png = base64.b64encode(b"\x89PNG...").decode()
    fake.invoke_model.return_value = {"body": _body({"images": [png]})}
    msg = await Host(fake).generate_image("a cat", output_directory=tmp_path)
    payload = json.loads(fake.invoke_model.call_args.kwargs["body"])
    assert payload["taskType"] == "TEXT_IMAGE"
    assert payload["textToImageParams"]["text"] == "a cat"


async def test_video_generation_polls_until_complete(tmp_path): ...
async def test_video_generation_requires_s3_config():
    with pytest.raises(ValueError, match="s3_output_uri|bucket_name"): ...
async def test_video_generation_failed_job_raises(): ...
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/novaclient-amazon-aws.spec.md` (§2, §3 Module 4, §6 Verified AWS Facts, §7)
2. **Check dependencies** — TASK-1806 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/novaclient-amazon-aws.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-17
**Notes**: Created `nova/generation.py` with `class NovaGeneration` (plain
mixin, no `__init__`). `generate_image()` builds the Canvas `TEXT_IMAGE`
payload (`textToImageParams`, `imageGenerationConfig` incl.
`negativeText`/`seed`), calls `invoke_model` via `self._ensure_client()`,
decodes base64 images, saves them (async `aiofiles`) when
`output_directory` is given, returns `AIMessageFactory.from_imagen(...)`.
`video_generation()` resolves the mandatory S3 output URI (kwarg →
`AWS_CREDENTIALS[self._aws_id or 'default']["bucket_name"]` → actionable
`ValueError`), runs `start_async_invoke` → `get_async_invoke` polling
(`Completed`/`Failed`/timeout → `InvokeError`), downloads the finished MP4
from S3 (own `aioboto3` s3 client, same resolved credentials) to
`output_directory`, keeping the S3 object (spec §8 resolved: default keep).
Model IDs always resolved through `self._translate_model(...)`. Added
`tests/clients/test_nova_generation.py` (7 tests, all mocked — no AWS
calls, all passing). `ruff check` clean.

**Deviations from spec**: none
