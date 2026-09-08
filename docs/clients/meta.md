# Meta Model API Client (Muse Spark)

**Audience**: Engineers who want to call Meta's hosted Muse Spark models
(1,048,576-token context, agentic/coding tuned) through the OpenAI-compatible
wire protocol, with optional Responses-API features (search grounding, input
token counting).

**Related files**:

- `packages/ai-parrot/src/parrot/clients/meta/client.py` — `MetaClient`
- `packages/ai-parrot/src/parrot/clients/meta/models.py` — `MetaModel` catalog
- `packages/ai-parrot/src/parrot/clients/openai_base.py` — inherited `OpenAIBaseClient` machinery (FEAT-438)
- `packages/ai-parrot/src/parrot/clients/factory.py` — `LLMFactory` registration
- `tests/clients/test_meta_*.py` — unit tests
- `tests/e2e/test_meta_live.py` — live, credential-gated end-to-end suite
- `examples/clients/smoke/smoke_meta.py` — manual smoke script
- `sdd/specs/meta-llm-client.spec.md` — full design (FEAT-526)
- `docs/clients/openai-compatible.md` — the shared `OpenAIBaseClient` hierarchy (FEAT-438)

---

## What This Is

Meta Model API is Meta's hosted inference service for the **Muse Spark**
model family, reachable at `https://api.meta.ai/v1`. It is OpenAI-wire
compatible for Chat Completions, and additionally exposes an OpenAI-shaped
**Responses API** with two capabilities not available on Chat Completions:
native web-search grounding and standalone input-token counting.

`MetaClient` subclasses `OpenAIBaseClient` (FEAT-438) — the neutral
OpenAI-wire layer that declares **zero** OpenAI-provider model defaults —
following the same pattern as `OpenRouterClient`/`MoonshotClient`. Chat
Completions (`ask`/`ask_stream`/`resume`/`invoke` when `use_responses=False`)
is fully inherited, unmodified. The Responses API path is
**`MetaClient`-local** (design decision D1): `OpenAIBaseClient` has no
Responses-API support by design, so `MetaClient` overrides `ask()`/
`ask_stream()` to route there when `use_responses=True` (the default).

---

## Quickstart

```python
from parrot.clients.factory import LLMFactory

client = LLMFactory.create("meta:muse-spark-1.3")
async with client:
    response = await client.ask("Explain quantum entanglement simply.")
    print(response.output)
```

`async with client:` is required — `AbstractClient` does not auto-enter its
async context for `ask()`/`ask_stream()`/`invoke()` (only the convenience
`complete()` wrapper does).

Aliases: `"meta"`, `"muse"`, `"meta-muse"` all resolve to `MetaClient`
(`MetaClient.provider_keys == ("meta", "muse", "meta-muse")`).

---

## Credentials

Resolution order, first match wins:

1. explicit `api_key` kwarg;
2. `META_API_KEY` env var (the recommended default — `MODEL_API_KEY` is
   considered too generic a name for a library default);
3. `MODEL_API_KEY` env var (kept as a secondary fallback so upstream
   vendor examples that use this generic name work unmodified).

**⚠️ This chain never falls through to `OPENAI_API_KEY`.** The `AsyncOpenAI`
SDK reads that env var by default when no key is passed explicitly —
`MetaClient` always passes a resolved key (or `None`) explicitly to
`AsyncOpenAI`, so an OpenAI key can never be silently shipped to Meta. This
is enforced by a regression test
(`test_never_falls_back_to_openai_api_key` in `tests/clients/test_meta_client.py`).

---

## ⚠️ The Reasoning-Budget Gotcha (read this before setting `max_tokens`)

**This is the single most useful paragraph in this document.**

Muse Spark is a reasoning model: it spends a large, often *dominant* share
of its output-token budget on private, hidden reasoning **before** any
visible text is produced. Measured live against
`muse-spark-1.3-contributor` for the one-word target answer `"pong"`:

| Path | Total completion/output tokens | Reasoning tokens | Visible text tokens |
|---|---|---|---|
| Chat Completions | 210 | **199** (94.8%) | 11 |
| Responses | 153 | **142** (92.8%) | 11 |

**A conventional small `max_tokens` (e.g. 64) reliably returns EMPTY visible
text**, or raises `openai.LengthFinishReasonError` (Chat Completions,
structured-output parsing) — not because the request failed, but because
the entire budget was consumed by reasoning before any answer text could be
emitted. This was reproduced live on **both** wire protocols with
`max_tokens=64` during implementation.

Mitigations already in place:

- `MetaClient._default_timeout` is raised to **120.0s** (vs. the base's
  60s) — Muse Spark's reasoning pass is also measurably slower, not just
  token-hungry.
- Give every call a **generous** output budget. There is no safe universal
  number — the reasoning tokens scale with problem complexity, not answer
  length — but budgets under ~150–200 tokens are known to fail even for a
  single-word answer.
- `examples/clients/smoke/_runner.py`'s shared smoke harness hardcodes
  `max_tokens=64` for its `ask()` leg (by design, shared across every
  provider) — **this is known and expected to FAIL for Muse Spark**
  specifically; it is not a `MetaClient` defect. Do not "fix" this by
  loosening the harness for one provider; if you need a reliable smoke
  check for Meta specifically, call `client.ask(...)` directly with a
  larger `max_tokens` outside the shared harness.

---

## ⚠️ Contributor Tier — Training Consent

`MetaModel` includes `-contributor` variants
(`muse-spark-1.3-contributor`, `muse-spark-1.2-contributor`). These are a
**separate, cheaper tier that grants Meta permission to train on your
prompts and completions.**

- `MetaClient._default_model` is `muse-spark-1.3` (Standard tier) and is
  asserted by test never to be a `-contributor` id.
- Use a `-contributor` model **only** for synthetic end-to-end test
  prompts (see `tests/e2e/test_meta_live.py`, `examples/clients/smoke/smoke_meta.py`)
  — never for real user, company, or repository content.
- `muse-spark-1.1` has **no** contributor variant.

---

## The Two Protocols

`use_responses: bool` (constructor kwarg, default `True`) selects which
wire protocol `ask()`/`ask_stream()` route through:

| Capability | Chat Completions (`use_responses=False`) | Responses (`use_responses=True`, default) |
|---|---|---|
| `ask()` / `ask_stream()` / `resume()` / `invoke()` | ✅ fully inherited from `OpenAIBaseClient` | ✅ `MetaClient`-local override |
| Tool calling | ✅ | ✅ (full round trip via the same generic tool loop) |
| Structured output (`structured_output=`) | ✅ | ❌ not yet supported — ignored |
| `search_grounding=True` | ❌ raises `ValueError` | ✅ injects native `{"type": "web_search"}` |
| `count_input_tokens()` | ✅ (standalone endpoint, works regardless) | ✅ |
| `cached_tokens` usage observability | ❌ not currently surfaced (see note below) | ✅ `ai_message.usage.extra_usage["cached_tokens"]` |

```python
# Responses path (default) — search grounding, full tool round trip
client = LLMFactory.create("meta:muse-spark-1.3")

# Chat Completions path — needed for structured_output today
client = LLMFactory.create("meta:muse-spark-1.3", use_responses=False)
```

> **Note**: `cached_tokens` surfacing on the Chat Completions path would
> require extending the shared `CompletionUsage.from_openai()` helper
> (`parrot/models/basic.py`, used by every OpenAI-wire client) — out of
> scope for this feature; tracked as a follow-up.

### Search grounding

```python
result = await client.ask(
    "What year is it right now?",
    search_grounding=True,
)
if result.metadata.get("web_search_calls"):
    print("Answer was grounded via live web search:", result.metadata["web_search_calls"])
```

- Opt-in, defaults to `False` — it triggers live web requests and bills
  for extra model iterations.
- Requires `use_responses=True`; raises `ValueError` otherwise.
- **Citation/annotation extraction is deliberately NOT implemented.** A
  verified-good, genuinely-grounded live response (`"Spain won 2026 World
  Cup"`) returned **empty** `annotations` on every message part despite
  Meta's docs advertising inline citations. Do not build citation
  extraction against `annotations` until this is re-verified upstream.

### Input token counting

```python
count = await client.count_input_tokens(input="How many tokens is this?")
```

Standalone endpoint (`POST /v1/responses/input_tokens`) — works regardless
of `use_responses`, since it does not depend on the generation path.

---

## Constraints

- **`tool_choice` must be `"auto"`.** Any other value (`"required"`, a
  named tool) is HTTP 400: `'only "auto" is supported for `tool_choice`'`.
  Both wire protocols enforce this — `MetaClient` never sends anything
  else, even if a caller tries to override it.
- **`logprobs` is unsupported** (HTTP 400) — Muse Spark is a reasoning
  model.
- **`reasoning_content` is redacted to empty** for external API keys on
  Chat Completions. Never surface it as visible "thinking" output.
- **Recursive/`$ref`-cycle schemas → HTTP 400** on every surface, and
  under `strict: true` also `allOf`/`oneOf` anywhere and `anyOf` at the
  schema root.
- **Responses tool shape differs from Chat Completions.** `MetaClient`
  handles this internally (`_to_responses_tool()` flattens
  `{"type":"function","function":{...}}` to
  `{"type":"function","name":...,...}`), and tool-call round trips use
  top-level `function_call`/`function_call_output` input items rather
  than the Chat-Completions `role`/`content` message shape — both were
  live-verified corrections discovered during implementation. This is
  purely an internal wire-format detail; callers never construct these
  shapes directly.

---

## Model Catalog

`MetaModel` — verified live against `GET /v1/models` on 2026-09-04:

| Model | Contributor variant | Notes |
|---|---|---|
| `muse-spark-1.3` | `muse-spark-1.3-contributor` | Default (Standard tier) |
| `muse-spark-1.2` | `muse-spark-1.2-contributor` | |
| `muse-spark-1.1` | *(none)* | No contributor tier for this version |
| `muse-image-1.0` | — | Reserved; **out of scope** — no endpoint work |
| `muse-voice-transcribe-1.0` | — | Reserved; **out of scope** — no endpoint work |

- **Context window**: `1,048,576` tokens, uniform across all Muse Spark models.
- **Not on Model API at all**: Muse Glimmer (open-weight, self-hosted).
- **Deferred**: the Anthropic-shaped Messages API (`POST /v1/messages`) — a
  third protocol, not implemented here.

---

## Smoke Script and Live Tests

```bash
python examples/clients/smoke/smoke_meta.py            # with META_API_KEY
env -u META_API_KEY python examples/clients/smoke/smoke_meta.py   # -> SKIPPED, exit 0
```

The shared smoke harness's `ask` leg uses a fixed `max_tokens=64` across
every provider and is **known to FAIL for Meta** specifically — see the
reasoning-budget gotcha above. The `ask+tool` and `invoke` legs pass
normally.

```bash
pytest tests/e2e/test_meta_live.py -v   # credential-gated; skips cleanly without META_API_KEY
```

### Worktree gotcha

Running a smoke script (or any live check) directly from inside
`.claude/worktrees/<feature>/` will silently import the **main**
checkout's compiled code — the editable-install `.pth` entries point
there, and Cython-compiled `.so` files are not automatically present in a
fresh worktree. Prepend the worktree's `src` dirs via `PYTHONPATH` and
ensure the compiled `.so` files exist before trusting results:

```bash
export PYTHONPATH="$(pwd)/packages/ai-parrot/src:$PYTHONPATH"
```

---

## Out of Scope (v1)

- Muse Image and Muse Voice Transcribe — enum members reserved only.
- Muse Glimmer — not served on Model API.
- The Anthropic-shaped Messages API (`POST /v1/messages`).
- Citation/annotation extraction from search grounding (see Constraints).
- Mapping parrot's client-side `search_tools` onto Meta's native
  `tool_search` — a separate, explicitly droppable follow-on unit
  (measured slower than parrot's own client-side search).
