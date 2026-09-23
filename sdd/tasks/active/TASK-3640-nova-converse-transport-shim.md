# TASK-3640: Nova Converse transport shim (`NovaVisionClient`)

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3639
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2 — the only new AWS-facing code in FEAT-592.

`VisionAdapter` is duck-typed: it accepts any client exposing `ask_to_image`
(`hasattr` check at `vision.py:157-161`), and its own docstring says "on **any**
client exposing `ask_to_image`". This task supplies that client for Nova so the
whole planogram identification path can run on Bedrock without changing one line
under `packages/` (spec G3).

Two decisions from the design-research pass shape it (spec §9): the shim
**composes a `NovaClient`** rather than re-resolving credentials (S3), and it
**refuses to send a request carrying no image block** (S9 / §8 Q1) — a text-only
Converse call returns plausible JSON and would silently turn the experiment into
a measurement of nothing.

---

## Scope

- Implement `NovaAnswer`, a minimal `AIMessage`-like carrier exposing `.output`.
- Implement `NovaVisionClient` with `client_name = "nova"`, an async
  `create()` factory, `resolved_model_id`, `ask_to_image()`, `_assert_has_image()`
  and `aclose()`.
- Write unit tests for `_assert_has_image` — a pure static validator, testable
  with no AWS and no network.

**NOT in scope**: any change under `packages/` (spec G3 / AC6); the prompt
builder (TASK-3641); the strip loop (TASK-3642); the CLI (TASK-3643); a test of
the live Converse round-trip — §8 Q1 resolved to a runtime guard instead.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/aws/nova_vision.py` | CREATE | `NovaAnswer` + `NovaVisionClient` |
| `examples/planogram/tests/test_nova2_shim.py` | CREATE | Unit tests for the `_assert_has_image` guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.amazon.nova.client import NovaClient   # verified: packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py:34
from pydantic import BaseModel                             # v2, repo standard
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py
class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):   # line 34
    client_type: str = "nova"
    client_name: str = "nova"
    _default_model: str = "nova-2-lite"
    _fallback_model: str = "nova-lite"
    def __init__(self, ..., region_prefix: Optional[str] = "us", ...)   # line 93

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
async def get_client(self) -> Any: ...      # line 338 — loop-local aioboto3 bedrock-runtime client
async def close(self) -> None: ...          # line 673
# lines 300-313 — credential chain, ALREADY IMPLEMENTED, do not duplicate:
#   aws_id → AWS_CREDENTIALS[profile] → AWS_CREDENTIALS['default'] → explicit kwargs
#   → bearer token; region: kwarg → profile.region_name → BEDROCK_AWS_REGION
#   → AWS_REGION_NAME → "us-east-1"
# line 434 — return translate_bedrock_model(raw, self._region_prefix)

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/models.py
"nova-2-lite": "amazon.nova-2-lite-v1:0"    # line 150 — alias map; region_prefix adds "us."

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
_COMMON: FrozenSet[str] = frozenset(        # line 21 — the EXACT kwarg set this shim receives
    {"model", "max_tokens", "temperature", "structured_output", "reference_images"})
SUPPORTED_KWARGS: Dict[str, FrozenSet[str]] = {...}   # line 22-27 — keys: google, claude, openai ONLY
#   line 52: supported = SUPPORTED_KWARGS.get(client_name, _COMMON)   ← "nova" lands on _COMMON
#   None values are dropped before the call, so `model` may arrive absent
class VisionAdapter:                        # line 131
    #   line 157-161: raises VisionError unless hasattr(client, "ask_to_image")
    #   line 165:     self.client_name = str(getattr(client, "client_name", "") or "").lower()
    #   line 269-271: await self.client.ask_to_image(prompt=final_prompt, image=images[0], **kwargs)
    @staticmethod
    def _extract(message: Any, schema: Type[T]) -> T: ...   # line 278
    #   line 280: reads `.structured_output` then `.output`
    #   line 291-297: a str is accepted; ``` / ```json fences stripped before json.loads
```

### Does NOT Exist
- ~~`BedrockConverseBase.ask_to_image`~~ / ~~`NovaClient.ask_to_image`~~ — **does not exist**; implemented only at `anthropic/client.py:1329`, `google/client.py:5011`, `openai/client.py:1468`. This is the whole reason this shim exists.
- ~~Bedrock Converse image content blocks in the parrot client~~ — `bedrock.py:725-745` logs a warning and DROPS every file; `_to_bedrock_content_block` (`bedrock.py:747`) returns `None` for unsupported types.
- ~~a `structured_output` parameter on `bedrock-runtime.converse`~~ — Converse takes `modelId`, `messages`, `system`, `inferenceConfig`, `toolConfig`. **Never forward the Pydantic class to AWS** (spec §9 S2).
- ~~`SUPPORTED_KWARGS["nova"]`~~ — not registered; the `_COMMON` fallback is correct and needs NO edit to `vision.py`.
- ~~`NovaAnswer` / `NovaVisionClient`~~ — created by this task.
- ~~`examples/planogram/aws/`~~ — the directory does not exist yet; create it.
- ~~sync `boto3` / `requests` / `httpx`~~ — banned (`.claude/rules/codebase-conventions.md`, ruff TID251). Use the composed client's `aioboto3` session.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/aws/nova_vision.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_nova2_shim.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py#NovaClient",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; the only AWS call is `await client.converse(...)` on the
  loop-local client returned by `NovaClient.get_client()`.
- `client_name` MUST be exactly `"nova"` — `VisionAdapter` lowercases it and uses
  it to pick the kwarg set.
- `ask_to_image` MUST accept exactly the `_COMMON` kwargs and tolerate `model`
  being absent (`normalise_kwargs` drops `None`).
- Return a plain object with `.output` as a `str`; `_extract` handles fences and
  validation. The shim parses no JSON itself.
- `structured_output` is consumed locally via `model_json_schema()` and rendered
  into the prompt — never sent to AWS.
- Module logger (`logging.getLogger(__name__)`), never `print`.

### References in Codebase
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/generation.py:345-376` —
  the repo's existing `aioboto3` session/client-kwargs pattern.
- `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:5011` —
  the `ask_to_image` signature this shim mirrors.

---

## Implementation Blueprint

### Steps (in order)
1. Create the `examples/planogram/aws/` package directory — *why*: no file of this feature exists yet and TASK-3639 has already made the path trackable.
2. Write `NovaAnswer` with `output`, `usage` and `image_bytes` — *why*: `VisionAdapter._extract` reads `.output`, and `image_bytes` is what the CLI aggregates into `RunStats.image_bytes_sent` for AC15.
3. Write `NovaVisionClient.create()` so it builds a `NovaClient` and reads the resolved model id back off it — *why*: spec §9 S3/S10; re-deriving credentials or the `us.` prefix here would drift from `bedrock.py:300-313,434` and split the response cache.
4. Write `_assert_has_image` as a pure static method returning the image byte total — *why*: it is the §8 Q1 guard AND the only part of this module testable without AWS, so it carries the task's validation command.
5. Write `ask_to_image` to assemble blocks, call the guard, then `converse` — *why*: the guard must run before the network call, not after, or a text-only request still reaches Bedrock.
6. Write the guard tests — *why*: AC15 requires the refusal to be demonstrable.

### `examples/planogram/aws/nova_vision.py` (CREATE)
```python
"""Bedrock Converse image transport for Nova — the ``ask_to_image`` shim (FEAT-592).

Prototype for the eventual ``BedrockConverseBase`` image support; today that client
drops image attachments outright (verified: bedrock.py:725-745).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Type

from pydantic import BaseModel

from parrot.clients.amazon.nova.client import NovaClient  # verified: nova/client.py:34

logger = logging.getLogger(__name__)

_GEO_PREFIXES = ("us.", "eu.", "jp.", "global.")


class NovaAnswer:
    """Minimal AIMessage-like carrier. ``VisionAdapter._extract`` reads ``.output``."""

    def __init__(self, output: str, usage: Dict[str, int], image_bytes: int) -> None:
        self.output = output
        self.usage = usage
        self.image_bytes = image_bytes


class NovaVisionClient:
    """``ask_to_image``-compatible Bedrock Converse image transport for Nova."""

    client_name: str = "nova"  # read by VisionAdapter — verified: vision.py:165

    def __init__(self, nova: NovaClient, model_id: str) -> None:
        """Bind an already-configured NovaClient and its fully resolved model id."""
        self._nova = nova
        self._model_id = model_id
        self.logger = logger

    @classmethod
    async def create(
        cls,
        *,
        aws_id: Optional[str] = None,
        region: Optional[str] = None,
        model: str = "nova-2-lite",
        region_prefix: Optional[str] = "us",
    ) -> "NovaVisionClient":
        """Build a NovaClient, resolve the geo-prefixed model id, open the runtime client.

        Raises:
            RuntimeError: the resolved model id carries no geo/global prefix.
        """
        # FILL IN: construct NovaClient(model=model, aws_id=aws_id, region=region,
        #   region_prefix=region_prefix), await nova.get_client(), and read the
        #   resolved id back off the client — bounded by: never re-resolve
        #   credentials, region or the alias here (verified: bedrock.py:300-313,434)
        raise NotImplementedError

    @property
    def resolved_model_id(self) -> str:
        """The exact id sent to Bedrock, e.g. ``us.amazon.nova-2-lite-v1:0``."""
        return self._model_id

    @staticmethod
    def _assert_has_image(blocks: Sequence[Dict[str, Any]]) -> int:
        """Guard: the request must carry an image block; return its total bytes.

        Raises:
            RuntimeError: no block in ``blocks`` is an ``{"image": ...}`` block.
        """
        total = sum(len(b["image"]["source"]["bytes"]) for b in blocks if "image" in b)
        if total == 0:
            raise RuntimeError(
                "Converse request carries no image block - refusing to send a "
                "text-only vision call"
            )
        return total

    @staticmethod
    def _schema_instruction(schema: Type[BaseModel]) -> str:
        """Render ``schema.model_json_schema()`` into a 'reply with only this JSON' rule."""
        # FILL IN: one short instruction + json.dumps of the schema — bounded by
        #   AC3: the answer must validate into the schema via _extract
        raise NotImplementedError

    async def ask_to_image(
        self,
        *,
        prompt: str,
        image: bytes,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        structured_output: Optional[Type[BaseModel]] = None,
        reference_images: Optional[List[bytes]] = None,
    ) -> NovaAnswer:
        """One Converse call with a PNG image block; returns the raw answer text.

        Raises:
            RuntimeError: the assembled request carries no image content block, or
                Converse returned no text content block.
        """
        # FILL IN: build content blocks — the schema instruction appended to `prompt`
        #   as {"text": ...}, then {"image": {"format": "png", "source": {"bytes": ...}}}
        #   for `image` and each of `reference_images` — bounded by: structured_output
        #   is NEVER passed to AWS (spec §9 S2)
        # FILL IN: call _assert_has_image(blocks) BEFORE converse — bounded by AC15
        # FILL IN: await client.converse(modelId=..., messages=[...],
        #   inferenceConfig={"maxTokens": max_tokens, "temperature": temperature})
        #   and extract the first text block — bounded by: raise RuntimeError when absent
        raise NotImplementedError

    async def aclose(self) -> None:
        """Close the composed NovaClient — verified: bedrock.py:673 ``async def close``."""
        await self._nova.close()
```
**Why this shape**: `client_name`, the `ask_to_image` kwarg list and the `.output`
attribute are fixed by `VisionAdapter` (`vision.py:21,52,165,269-271,280`) and are
**not renegotiable** — changing any of them breaks the duck-type silently. The
composed `NovaClient` is the single source of credentials, region and the resolved
model id (spec §9 S3/S10). `_assert_has_image` is deliberately a pure static method
taking already-assembled blocks: that is what makes it testable without AWS and what
lets this task carry a truthful validation command. Do not move the guard after the
`converse` call.

### `examples/planogram/tests/test_nova2_shim.py` (CREATE)
```python
"""Unit tests for the Nova Converse transport guard (FEAT-592, TASK-3640).

Pure-function tests only: no AWS, no network, no credentials. Per spec §8 Q1 the
live Converse round-trip is guarded at runtime, not covered by a test.
"""
from __future__ import annotations

import pytest

from examples.planogram.aws.nova_vision import NovaVisionClient


def _image_block(payload: bytes) -> dict:
    """A Converse image content block carrying ``payload``."""
    return {"image": {"format": "png", "source": {"bytes": payload}}}


def test_assert_has_image_returns_total_bytes() -> None:
    """A request with image blocks reports the summed payload size."""
    # FILL IN: assert _assert_has_image([{"text": "..."}, _image_block(b"abc")]) == 3
    #   — bounded by AC15
    raise NotImplementedError


def test_assert_has_image_sums_multiple_blocks() -> None:
    """reference_images contribute to the total."""
    # FILL IN: two image blocks; assert the sum — bounded by AC5 (image_bytes_sent)
    raise NotImplementedError


def test_assert_has_image_refuses_text_only_request() -> None:
    """A request with no image block is refused before it can reach Bedrock."""
    with pytest.raises(RuntimeError, match="no image block"):
        NovaVisionClient._assert_has_image([{"text": "describe this shelf"}])


def test_assert_has_image_refuses_empty_block_list() -> None:
    """An empty block list is refused, not silently treated as valid."""
    # FILL IN: pytest.raises(RuntimeError) on [] — bounded by AC15
    raise NotImplementedError
```
**Why**: these four cases pin the one safety property that spec §8 Q1 chose over a
full transport test. `_assert_has_image` is static and takes plain dicts, so the
tests need no `NovaClient`, no credentials and no event loop. The `match=` string
must stay aligned with the message raised in `nova_vision.py`.

### FILL IN checklist
- [ ] `nova_vision.py::NovaVisionClient.create` — build + open the NovaClient and read back the resolved id; bounded by: never re-resolve credentials/region/alias (`bedrock.py:300-313,434`)
- [ ] `nova_vision.py::NovaVisionClient.create` — geo-prefix assertion; bounded by: reject an id not starting with one of `us. eu. jp. global.`
- [ ] `nova_vision.py::NovaVisionClient._schema_instruction` — the instruction text; bounded by AC3
- [ ] `nova_vision.py::NovaVisionClient.ask_to_image` — block assembly, guard call, `converse` call, text extraction; bounded by AC15 and spec §9 S2
- [ ] `test_nova2_shim.py` — three test bodies; bounded by AC15

---

## Acceptance Criteria

- [ ] `NovaVisionClient` satisfies the duck-type: `hasattr(NovaVisionClient, "ask_to_image")` is True and `client_name == "nova"`.
- [ ] `ask_to_image` accepts every `_COMMON` kwarg and tolerates `model` being absent.
- [ ] `structured_output` is never included in the Converse request payload (spec §9 S2).
- [ ] A request assembled without an image block raises `RuntimeError` before any AWS call — spec AC15.
- [ ] `NovaAnswer.image_bytes` equals the total image payload transmitted.
- [ ] `resolved_model_id` returns the geo-prefixed id (e.g. `us.amazon.nova-2-lite-v1:0`) — spec AC5.
- [ ] No file under `packages/` is modified — spec AC6.
- [ ] `ruff check examples/planogram/aws/` and `black --check --line-length 120 examples/planogram/aws/` pass — spec AC12.
- [ ] No `requests`, `httpx`, sync `boto3`, `print(...)` or LangChain import — spec AC13.

---

## Validation Commands

- `pytest examples/planogram/tests/test_nova2_shim.py -q`

---

## Test Specification

See the `test_nova2_shim.py` blueprint block above — four cases over the pure
`_assert_has_image` validator. No fixtures, no AWS, no event loop.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview, §3 Module 2, §9 S2/S3/S9/S10).
2. **Check dependencies** — TASK-3639 must be in `sdd/tasks/completed/`: without its `.gitignore` negation block, `git add` of your new files under `examples/planogram/aws/` silently does nothing. (TASK-3639 makes the path trackable; if it has not
   landed yet, your files still work — you just cannot commit them until it does.)
3. **Verify the Codebase Contract** — confirm `NovaClient.get_client`/`close` and the
   `_COMMON` kwarg set still read as listed before writing code.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — start from the blueprint blocks, complete every `# FILL IN:`, and
   never change a signature, class name or file path the blueprint fixes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3640-nova-converse-transport-shim.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
