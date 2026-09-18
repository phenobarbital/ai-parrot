# TASK-3342: VisionBackend — one vision + structured-output call over any ai-parrot client

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3337
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6: vision**. ai-parrot has **no vision method common to all clients**:
Google exposes `image_understanding()` (multi-image + `structured_output`), OpenAI / Anthropic /
Google expose `ask_to_image()` with *different* signatures, and `LocalLLMClient` exposes neither
today. Every LLM-calling stage of FEAT-565 (`prices`, `identify`, `verify`) needs exactly one
thing: *prompt + images + Pydantic schema → validated instance*, cached on disk.

This task builds that adapter. Per spec §8 **Q7** it has **two duck-typed lanes only** and must
**never** reach into a provider SDK handle. Vision for the local llama.cpp server arrives through
the separate prerequisite feature `localllm-ask-to-image` (it adds `ask_to_image()` to
`LocalLLMClient`); until it lands, a client with neither method fails fast with a clear error and
**no FEAT-565 code changes when it lands**.

It depends on TASK-3337 only for the package marker `examples/planogram/plancheck/__init__.py`
and for `examples/planogram/tests/conftest.py` (which puts `examples/planogram/` on `sys.path`).
It imports **no** model from `examples/planogram/plancheck/models.py` — it is generic over the schema type.

---

## Scope

- Implement `examples/planogram/plancheck/vision.py`: `VisionError`, `VisionBackend`
  (`__init__`, `__aenter__`, `__aexit__`, `is_local`, `ask`), `cache_key`, `cache_store`,
  plus the private helpers named in the blueprint.
- Lane 1 (checked first): `hasattr(client, "image_understanding")` → Google.
  Lane 2: `hasattr(client, "ask_to_image")` → generic. Neither → `VisionError` naming
  `localllm-ask-to-image`, raised in `__aenter__` **before** the client is entered.
- Disk cache: lookup before the call, atomic store after a validated answer, failed calls never cached.
- Validation: schema instance straight from `AIMessage.structured_output` when possible, else
  `schema.model_validate(...)`; **one** repair retry with the validation error appended; then `VisionError`.
- `parrot` is imported **lazily inside `__init__`** and only when no `client=` is injected.
- Write `examples/planogram/tests/test_plancheck_vision.py` with fake clients (no network, no parrot import).

**NOT in scope**: prompts, strips, contact sheets (TASK-3343 / TASK-3344 / TASK-3346); the
`FakeBackend` test double (already in `examples/planogram/tests/conftest.py`, TASK-3337); any change
under `packages/` (spec §5: `git diff origin/dev -- packages/` must stay empty); adding
`ask_to_image` to `LocalLLMClient` (separate feature); concurrency limiting (callers hold the semaphore).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/vision.py` | CREATE | `VisionBackend` adapter, `VisionError`, `cache_key`, `cache_store` |
| `examples/planogram/tests/test_plancheck_vision.py` | CREATE | Unit tests with duck-typed fake clients |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-09-17 on `dev`. Use these exact names. Anything not listed → verify first.

### Verified Imports
```python
# stdlib + pydantic only at module top level:
import hashlib, json, logging, os, tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar
from pydantic import BaseModel, ValidationError

# LAZY — inside VisionBackend.__init__ only, and only when no client is injected:
from parrot.clients.factory import LLMFactory   # verified: packages/ai-parrot/src/parrot/clients/factory.py:257 (create)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:   # :174  "provider:model" → split(":", 1), both stripped; no ":" → (llm, None)
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient:   # :257
    # model_args keys honoured: temperature, top_k, top_p, max_tokens; **kwargs merged LAST (`init_params.update(kwargs)` :336)
    # → base_url= / api_key= reach the client constructor. Unknown provider → ImportError.

# packages/ai-parrot/src/parrot/clients/base.py   (READ-ONLY)
class AbstractClient:
    async def __aenter__(self):                             # :1155  opens aiohttp session if use_session, awaits _ensure_client()
    async def __aexit__(self, exc_type, exc_val, exc_tb):   # :1167

# packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py  (GoogleAnalysis, mixed into GoogleGenAIClient, client.py:101)
async def image_understanding(self, prompt: str,
    images: Union[str, Path, bytes, Image.Image, List[Union[str, Path, bytes, Image.Image]]],
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_3_FLASH_PREVIEW,   # NOT the client's model → ALWAYS pass model=
    prompt_instruction: Optional[str] = None, user_id=None, session_id=None, stateless: bool = True,
    timeout: Optional[int] = 600, temperature: Optional[float] = None, detect_objects: bool = False,
    response_schema: Optional[Any] = None,
    structured_output: Union[type, StructuredOutputConfig, None] = None) -> AIMessage:   # :438
# bytes are accepted: _get_image_from_input handles bytes via Image.open(io.BytesIO(...)) (:1663-1670).
# str/Path inputs > 5 MB are uploaded through the File API (:485) → pass BYTES, never paths.
# structured_output applied at :512-514; parsed result handed to AIMessageFactory.from_gemini(structured_output=…) (:611).

# ask_to_image — COMMON SUBSET of the three implementations (use ONLY these keyword names):
#   prompt, image, reference_images=None, model=…, max_tokens=None, temperature=None, structured_output=None
# packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py:1468      model default OpenAIModel.GPT5_MINI.value
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:1307 model default ClaudeModel.SONNET_4 — has NO `no_memory` kwarg
# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:4999       model default None
#   → the model default is NOT the client's configured model on OpenAI/Anthropic: pass model= whenever the llm string has one.

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):            # :75
    output: Any                        # :80
    structured_output: Optional[Any]   # :148
    is_structured: bool                # :151
```

### Created by dependency tasks (exist only after they land)
- `examples/planogram/plancheck/__init__.py` — package marker (TASK-3337).
- `examples/planogram/tests/conftest.py` — inserts `examples/planogram/` into `sys.path`; tests do
  `from plancheck.vision import …` (TASK-3337). Its `FakeBackend` is for *other* modules' tests — this task tests the real class.

### Does NOT Exist
- ~~`AbstractClient.ask_to_image`~~ / ~~`AbstractClient.image_understanding`~~ — no vision method on the base client.
- ~~`LocalLLMClient.ask_to_image`~~ / ~~`OpenAIBaseClient.ask_to_image`~~ — not defined today; `LocalLLMClient.invoke()` is text-only. Duck-type it, never assume it.
- ~~`client.ask(prompt, files=[image])` as a vision path~~ — `_encode_file` emits a `"document"` block; `OpenAIBaseClient.ask` uploads files. Not an image path.
- ~~a third "OpenAI-compatible" lane~~ — removed by spec §8 Q7. This module must not contain the strings `chat.completions`, `get_client`, `_encode_image_for_openai` or `.client.`, and must not import `openai`, `anthropic` or `google.genai`.
- ~~`no_memory=` on every `ask_to_image`~~ — Anthropic's does not accept it; do not pass it.
- ~~`from parrot.models.google import GoogleModel`~~ — ImportError; and this module does not need `GoogleModel` at all (pass the model **string**).
- ~~`plancheck.vision` importing `plancheck.models`~~ — not needed; keep it generic.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/vision.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_vision.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.parse_llm_string",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.__aenter__",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py#GoogleAnalysis.image_understanding",
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient.ask_to_image",
    "sym:packages/ai-parrot-client-openai/src/parrot/clients/openai/client.py#OpenAIClient.ask_to_image",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient.ask_to_image",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never touch an SDK handle** (spec §8 Q7, §5): only call *methods of the parrot client object*
  (`image_understanding`, `ask_to_image`, `__aenter__`, `__aexit__`). Name the attribute
  `self._llm_client` so the source never contains the substring `.client.`.
- **`import parrot` side effect**: navconfig `chdir`s to the repo root. Resolve `cache_dir` to an
  absolute path **before** the lazy import.
- **Lane order matters**: `GoogleGenAIClient` has *both* methods → check `image_understanding` first.
- **Always pass `model=`** when the llm string carries a model (defaults differ per client, see contract).
  When it does not (`--llm anthropic`), omit `model` and log one warning.
- Pass `base_url` / `api_key` to `LLMFactory.create` **only when not `None`** — not every client constructor accepts them.
- Images are `bytes` end to end (PNG). No PIL import needed here.
- Provider/transport exceptions → `VisionError` immediately (clients already retry internally).
  Only *validation* failures get the single repair retry. The cache key always uses the **original** prompt.
- A corrupt or schema-incompatible cache file is ignored (logged at WARNING) and overwritten.
- `logging.getLogger(__name__)`; no `print`; no `requests`/`httpx`; black line length 120.
- In a worktree the tests need no `PYTHONPATH` prefix: they never import `parrot`.

### References in Codebase
- `examples/planogram/inkcheck/inkcheck/vision.py:25-40` — cache-key recipe this adapts (reference only; do not import `inkcheck`).
- `packages/ai-parrot-client-local/src/parrot/clients/local/client.py:66` — local provider keys `("local","localllm","ollama","llamacpp")`;
  `packages/ai-parrot-client-vllm/src/parrot/clients/vllm/client.py:92` — `("vllm",)`.

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:`. Never change a
> signature or name fixed here.

### Steps (in order)
1. Create `vision.py` part 1 (constants, `VisionError`, `split_llm`, cache helpers) — *why*: they are pure and the tests for them need no client.
2. Add part 2 (`VisionBackend`) — *why*: it composes the helpers; keep the three call sites (`_call_google`, `_call_generic`, `_extract`) tiny so each lane is testable with a fake.
3. In `__init__`, resolve `cache_dir` **before** the lazy `parrot` import — *why*: importing parrot changes the working directory, which would re-anchor a relative cache path.
4. In `__aenter__`, run the lane check **before** entering the client — *why*: the CLI must exit 1 before any work and without leaking an aiohttp session.
5. Write the tests with fake clients injected through the keyword-only `client=` seam — *why*: no network and no parrot import in the unit suite.
6. Run the validation command, then `ruff check` on both files.

### `examples/planogram/plancheck/vision.py` (CREATE) — part 1/2
```python
"""Vision backend adapter for the planogram compliance check (FEAT-565, Module 6).

One coroutine — prompt + images + Pydantic schema -> validated instance — over any ai-parrot
client, with a disk cache. Two duck-typed lanes; provider SDK objects are never touched here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

LOCAL_PROVIDERS: frozenset[str] = frozenset({"local", "localllm", "ollama", "llamacpp", "vllm"})
PREREQUISITE_FEATURE: str = "localllm-ask-to-image"


class VisionError(RuntimeError):
    """Provider, transport or schema failure after the repair retry."""


def split_llm(llm: str) -> tuple[str, str | None]:
    """Split ``"provider:model"`` into (lower-cased provider, model or None).

    Mirrors ``LLMFactory.parse_llm_string`` without importing parrot.
    """
    # FILL IN: split on the FIRST ":" only, strip both parts, lower-case the provider,
    #          empty model -> None — bounded by factory.py:174 semantics and test_is_local
    raise NotImplementedError


def cache_key(llm: str, base_url: str | None, max_tokens: int, stage: str, prompt_version: str,
              prompt: str, schema: type[BaseModel], images: Sequence[bytes]) -> str:
    """Return the sha256 hex digest of a canonical JSON of ALL arguments (images by their sha256)."""
    # FILL IN: json.dumps(..., sort_keys=True, separators=(",", ":")) over a dict holding every
    #          argument; schema -> schema.model_json_schema(); images -> [sha256 hex of each] IN ORDER
    #          — bounded by test_cache_key_stable_and_sensitive (any single change -> new key)
    raise NotImplementedError


def cache_store(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write ``payload`` as JSON: temp file in the same directory + ``os.replace``."""
    # FILL IN: mkdir(parents=True, exist_ok=True); serialise FIRST (json.dumps) so a serialisation
    #          error leaves nothing on disk; tempfile.NamedTemporaryFile(dir=path.parent, delete=False);
    #          os.replace(tmp, path); on any exception unlink the temp file and re-raise
    #          — bounded by test_cache_store_atomic
    raise NotImplementedError


def _cache_load(path: Path, schema: type[T]) -> T | None:
    """Return the cached, re-validated instance, or None when absent, corrupt or incompatible."""
    # FILL IN: read JSON, schema.model_validate(payload["parsed"]); on OSError / ValueError /
    #          KeyError / ValidationError log a WARNING and return None (never raise)
    raise NotImplementedError
```
**Why this shape**: `cache_key` / `cache_store` signatures are fixed by the spec skeleton (design-research S10: the key
must cover base URL, generation params and the *full* prompt text; writes are atomic). `split_llm` exists so `is_local`
works without importing parrot. `_cache_load` is a private convenience; it must swallow every cache defect because a
bad cache entry must never fail a run.

### `examples/planogram/plancheck/vision.py` (CREATE) — part 2/2
```python
class VisionBackend:
    """Adapter: prompt + images + Pydantic schema -> validated instance."""

    def __init__(self, llm: str, *, cache_dir: Path, base_url: str | None = None,
                 api_key: str | None = None, max_tokens: int = 8192, client: Any | None = None) -> None:
        """Create (or accept) the ai-parrot client.

        Args:
            llm: ``"provider:model"`` string understood by ``LLMFactory``.
            cache_dir: Response cache directory (resolved to an absolute path immediately).
            base_url: Optional server URL for OpenAI-compatible/local providers.
            api_key: Optional API key override.
            max_tokens: Generation cap, also part of the cache key.
            client: TEST SEAM — a pre-built client; when given, parrot is never imported.
        """
        self.llm = llm
        self.provider, self.model = split_llm(llm)
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.cache_dir = Path(cache_dir).resolve()  # BEFORE the lazy parrot import (navconfig chdir)
        if client is None:
            from parrot.clients.factory import LLMFactory  # lazy: verified factory.py:257

            kwargs: dict[str, Any] = {}
            # FILL IN: add base_url / api_key to kwargs ONLY when not None
            client = LLMFactory.create(llm, model_args={"temperature": 0.0, "max_tokens": max_tokens}, **kwargs)
        self._llm_client: Any = client

    @property
    def is_local(self) -> bool:
        """True for provider keys local/localllm/ollama/llamacpp/vllm."""
        return self.provider in LOCAL_PROVIDERS

    async def __aenter__(self) -> "VisionBackend":
        """Fail fast when the client has no vision method, then enter the client."""
        # FILL IN: if neither hasattr(self._llm_client, "image_understanding") nor "ask_to_image":
        #          raise VisionError(f"client {type(self._llm_client).__name__} has no vision method; "
        #          f"it needs feature '{PREREQUISITE_FEATURE}'") — BEFORE entering the client.
        #          Then, if the client defines __aenter__, await it. Return self.
        raise NotImplementedError

    async def __aexit__(self, *exc: object) -> None:
        """Exit the client context when it has one."""
        # FILL IN: await self._llm_client.__aexit__(*exc) when present (pass three Nones if exc is empty)
        raise NotImplementedError

    async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str,
                  prompt_version: str) -> T:
        """Cache lookup -> lane dispatch -> validate -> one repair retry -> cache store.

        Raises:
            ValueError: ``images`` is empty.
            VisionError: provider failure, or the answer is invalid after the repair retry.
        """
        # FILL IN (in this order; bounded by spec §3 M6 + the six tests of this task):
        #   1. key = cache_key(self.llm, self.base_url, self.max_tokens, stage, prompt_version, prompt, schema, images)
        #      path = self.cache_dir / f"{key}.json"; hit -> return it (logger.debug).
        #   2. attempt 1 with `prompt`; on validation failure attempt 2 with
        #      prompt + "\n\nYour previous answer was rejected: <error>. Return ONLY valid JSON for the schema."
        #   3. any exception raised BY THE CLIENT -> raise VisionError(...) from exc, no retry, nothing cached.
        #   4. success -> cache_store(path, {"llm","stage","prompt_version","parsed": result.model_dump(mode="json")}).
        #   5. second validation failure -> VisionError, nothing cached.
        raise NotImplementedError

    async def _call(self, prompt: str, images: Sequence[bytes], schema: type[T]) -> Any:
        """Dispatch to lane 1 (``image_understanding``) or lane 2 (``ask_to_image``); return the AIMessage."""
        model_kw: dict[str, Any] = {"model": self.model} if self.model else {}
        if hasattr(self._llm_client, "image_understanding"):  # lane 1 — Google (analysis.py:438)
            return await self._llm_client.image_understanding(
                prompt, images=list(images), structured_output=schema, temperature=0.0, stateless=True, **model_kw
            )
        return await self._llm_client.ask_to_image(  # lane 2 — generic common subset
            prompt, image=images[0], reference_images=list(images[1:]) or None, structured_output=schema,
            temperature=0.0, max_tokens=self.max_tokens, **model_kw
        )

    @staticmethod
    def _extract(message: Any, schema: type[T]) -> T:
        """Turn an AIMessage into a ``schema`` instance (raises ValidationError / ValueError)."""
        # FILL IN: candidates in order: message.structured_output, message.output.
        #   isinstance(c, schema) -> return; BaseModel -> schema.model_validate(c.model_dump());
        #   dict/list -> schema.model_validate(c); str -> strip ```json fences, json.loads, validate.
        #   Nothing usable -> raise ValueError("no structured output in response").
        raise NotImplementedError
```
**Why this shape**: the `client=` keyword is an additive, test-only seam (defaults keep the spec signature valid). `_call`
is given complete because its keyword names are the verified *common subset* — do not add `no_memory`, `history`,
`count_objects` or `timeout`. Lane 3 of the first spec draft is gone: there is deliberately no `else` branch that reaches
into an SDK object; the missing-method case is handled once, in `__aenter__`.

### `examples/planogram/tests/test_plancheck_vision.py` (CREATE)
```python
"""Unit tests for plancheck.vision (FEAT-565, TASK-3342). No network, no parrot import."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from plancheck import vision
from plancheck.vision import VisionBackend, VisionError, cache_key, cache_store


class Answer(BaseModel):
    value: int


class _Msg:
    def __init__(self, structured_output: Any = None, output: Any = None) -> None:
        self.structured_output = structured_output
        self.output = output


class FakeGoogle:
    """Has BOTH methods, like GoogleGenAIClient — lane 1 must win."""
    def __init__(self, replies: list[Any]) -> None:
        self.replies, self.calls = replies, []
    async def image_understanding(self, prompt: str, images: Any, **kw: Any) -> Any:
        self.calls.append(("image_understanding", prompt, images, kw)); return self._next()
    async def ask_to_image(self, prompt: str, image: Any, **kw: Any) -> Any:
        self.calls.append(("ask_to_image", prompt, image, kw)); return self._next()
    def _next(self) -> Any:
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeGeneric:
    """Exposes ONLY ask_to_image (OpenAI / Anthropic / future LocalLLMClient). Do NOT subclass FakeGoogle:
    ``hasattr`` would still see ``image_understanding``."""
    def __init__(self, replies: list[Any]) -> None:
        self.replies, self.calls = replies, []
    async def ask_to_image(self, prompt: str, image: Any, **kw: Any) -> Any:
        self.calls.append(("ask_to_image", prompt, image, kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class NoVision:
    """Like LocalLLMClient today: no vision method."""


def test_cache_key_stable_and_sensitive() -> None: ...       # FILL IN: same args -> same key; changing image bytes, prompt, schema, base_url, max_tokens, stage or prompt_version -> different key
def test_cache_store_atomic(tmp_path: Path) -> None: ...     # FILL IN: payload with a non-serialisable value -> raises AND tmp_path holds no file at all
def test_is_local() -> None: ...                             # FILL IN: llamacpp:x / vllm:y / ollama -> True; google:gemini-3.8-flash -> False (client=object())
@pytest.mark.asyncio
async def test_lane_dispatch(tmp_path: Path) -> None: ...    # FILL IN: FakeGoogle -> image_understanding called with images list + model kw; generic -> image=first, reference_images=rest (None when single), model kw, max_tokens
@pytest.mark.asyncio
async def test_no_vision_method_is_clear_error(tmp_path: Path) -> None: ...  # FILL IN: `async with VisionBackend("llamacpp:x", cache_dir=tmp_path, client=NoVision())` -> VisionError mentioning "localllm-ask-to-image"
@pytest.mark.asyncio
async def test_repair_retry_then_error_not_cached(tmp_path: Path) -> None: ...  # FILL IN: two invalid replies -> VisionError, 2 client calls, second prompt contains the rejection text, cache dir empty
@pytest.mark.asyncio
async def test_repair_retry_succeeds_and_caches(tmp_path: Path) -> None: ...    # FILL IN: invalid then valid -> Answer; a second ask() makes ZERO client calls
@pytest.mark.asyncio
async def test_provider_exception_is_vision_error(tmp_path: Path) -> None: ...  # FILL IN: reply RuntimeError("boom") -> VisionError, exactly 1 call, nothing cached
@pytest.mark.asyncio
async def test_extract_accepts_instance_dict_and_json_string(tmp_path: Path) -> None: ...  # FILL IN: structured_output=Answer(...), ={"value":1}, output='```json\n{"value":1}\n```'


def test_vision_module_never_touches_sdk_handle() -> None:
    source = Path(vision.__file__).read_text(encoding="utf-8")
    for needle in ("chat.completions", "get_client", "_encode_image_for_openai", ".client."):
        assert needle not in source, needle
    assert not re.search(r"^\s*(?:import|from)\s+(?:openai|anthropic|google\.genai)\b", source, re.M)
```
**Why this shape**: test names come from spec §4 (M6 rows) plus four that pin decisions made in this task (cache hit,
provider exception, extraction forms, `is_local`). The last test is given complete because it *is* the §8 Q7 guard —
do not weaken it; if it fails, fix `vision.py`, not the test.

### FILL IN checklist
- [ ] `vision.py::split_llm` — first-colon split, lower-cased provider; bounded by factory.py:174
- [ ] `vision.py::cache_key` — canonical JSON over every argument; bounded by `test_cache_key_stable_and_sensitive`
- [ ] `vision.py::cache_store` — serialise first, temp + `os.replace`, clean up on failure; bounded by `test_cache_store_atomic`
- [ ] `vision.py::_cache_load` — never raises
- [ ] `VisionBackend.__init__` — kwargs only when not None
- [ ] `VisionBackend.__aenter__` / `__aexit__` — lane check first; bounded by `test_no_vision_method_is_clear_error`
- [ ] `VisionBackend.ask` — 5-step flow; bounded by the repair/caching tests
- [ ] `VisionBackend._extract` — four accepted forms
- [ ] every `...` test body in `test_plancheck_vision.py`

---

## Acceptance Criteria

- [ ] `pytest examples/planogram/tests/test_plancheck_vision.py -q` passes without network and without importing `parrot`.
- [ ] `ruff check examples/planogram/plancheck/vision.py examples/planogram/tests/test_plancheck_vision.py` is clean.
- [ ] Exactly two lanes; a client with neither method raises `VisionError` naming `localllm-ask-to-image` in `__aenter__`, before the client is entered (spec §5, §8 Q7).
- [ ] `vision.py` contains none of `chat.completions`, `get_client`, `_encode_image_for_openai`, `.client.` and imports no provider SDK (`test_vision_module_never_touches_sdk_handle`).
- [ ] `parrot` is imported only inside `__init__` and only when `client` is `None`; `cache_dir` is absolute before that import.
- [ ] `model=` is forwarded on both lanes whenever the llm string has a model.
- [ ] Cache key covers llm, base_url, max_tokens, stage, prompt_version, full prompt, schema JSON and image hashes; writes are atomic; failed calls leave no cache file; a second identical `ask()` makes zero client calls.
- [ ] One repair retry on validation failure only; provider exceptions are not retried.
- [ ] No `print`, no `requests`/`httpx`; nothing under `packages/` is modified.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_vision.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint — the function names there are the required
minimum. Expected behaviours, one line each:

| Test | Asserts |
|---|---|
| `test_cache_key_stable_and_sensitive` | determinism + sensitivity to every argument (spec §4, S10) |
| `test_cache_store_atomic` | no partial/temp file when serialisation raises |
| `test_lane_dispatch` | lane 1 wins when both methods exist; lane 2 splits `image` / `reference_images` |
| `test_no_vision_method_is_clear_error` | `VisionError` + feature name, raised on enter |
| `test_vision_module_never_touches_sdk_handle` | source-level guard for §8 Q7 |
| `test_repair_retry_then_error_not_cached` | 2 calls, `VisionError`, empty cache |
| `test_repair_retry_succeeds_and_caches` | cache hit → zero calls |
| `test_provider_exception_is_vision_error` | no retry on transport/provider errors |
| `test_extract_accepts_instance_dict_and_json_string` | the accepted answer forms |
| `test_is_local` | provider-key classification |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 6, §6, §7, §8 Q7) for full context.
2. **Check dependencies** — TASK-3337 must be in `sdd/tasks/completed/` (`examples/planogram/plancheck/__init__.py` and `examples/planogram/tests/conftest.py` exist).
3. **Verify the Codebase Contract** — re-grep the cited lines before writing code; update the contract first if anything moved.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
6. **Verify** all acceptance criteria; run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3342-vision.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (native, model sonnet, attempt_uid be2224b90998409e98052bf37754afaf)
**Date**: 2026-09-17
**Notes**: Created `examples/planogram/plancheck/vision.py` (VisionError, split_llm,
cache_key, cache_store, _cache_load, VisionBackend with `__aenter__`/`__aexit__`/`ask`/
`_call`/`_extract`) and `examples/planogram/tests/test_plancheck_vision.py` with 10
tests using duck-typed fake clients (no network, no parrot import in tests). Verified
`git diff origin/dev -- packages/` empty (spec §5 constraint honored — vision.py never
touches provider SDK internals). `pytest examples/planogram/tests/test_plancheck_vision.py -q`
→ 10 passed. Coder flagged 2 ruff E702 findings inside blueprint-verbatim test code;
engine lint autofix (commit `f3ff7f84a`) resolved them. Post-merge full suite → 64
passed. Review recorded: `coder-review:f777e1fed07550039cb00209`, no corrections needed.

**Seat**: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
