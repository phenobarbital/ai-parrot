# TypeSafe System One Client (`JevClient`)

**Audience**: Engineers who want typed, calibrated decisions from an LLM
call — routing, ranking, extraction, verification — without parsing prose.

**Related files**:

- `packages/ai-parrot-client-jev/src/parrot/clients/jev/client.py` — `JevClient`
- `packages/ai-parrot-client-jev/src/parrot/clients/jev/models.py` — question
  primitives (`Noul`, `Choice`, `Score`), answers, `SystemOneResponse`
- `packages/ai-parrot-client-jev/src/parrot/clients/jev/schema.py` — Pydantic
  `output_type` ⇄ questions mapping used by `invoke()`
- `tests/clients/test_jev_client.py`

**Install**: `pip install ai-parrot[jev]` (or `ai-parrot-client-jev`), then set
`TYPESAFE_API_KEY`. Provider keys for `LLMFactory`: `jev`, `typesafe`.

## What Jev is (and is not)

[Jev](https://typesafe.ai) is TypeSafe AI's first *System One* model. It has
string-based input and **structured outputs only**: you send **state** (text
or a JSON document) plus a map of typed **questions**, and it answers all of
them in one parallel pass with values that are guaranteed to lie in the answer
space you declared, each with a probability distribution and (for choice and
score) a confidence. It never generates free text, has no sampling
parameters, no streaming, no tool loop and no conversation memory of its own.

| Primitive | Ask for                              | Answer                                             |
|-----------|--------------------------------------|----------------------------------------------------|
| `Noul`    | whether a condition holds            | `noul`: probability of *yes*                       |
| `Choice`  | one label out of a fixed set (≤ 255) | `choice`, `confidence`, `probabilities` per label  |
| `Score`   | a position on an ordered rubric      | `score` (expected level), `confidence`, `legend`, `probabilities` per level |

Wire protocol: `POST https://api.typesafe.ai/v1/systemone` with
`{"state", "model", "questions"}` and a `Bearer` token; `GET /v1/models`.
The client implements it over `aiohttp` (the vendor SDK is `httpx2`-based,
which this codebase forbids) with `tenacity` retries on 408/429/5xx and
connection errors, honouring `retry-after` / `retry-after-ms`.

## Raw API: `system_one()`

The official quickstart, verbatim (the same request/response bodies are
asserted in `tests/clients/test_jev_client.py`):

```python
from parrot.clients.jev import JevClient, Choice, Noul, Score

client = JevClient()                      # TYPESAFE_API_KEY from the environment
ticket = (
    "Hi, I've been trying to connect my Stripe account for 3 days and it keeps "
    "failing. I'm losing sales. Please help ASAP."
)
response = await client.system_one(
    state=ticket,
    questions={
        "department": Choice(
            instructions="Which team should handle this",
            criteria={
                "billing": "Payment or subscription issues",
                "technical": "Bugs or integration problems",
                "sales": "Pricing or account questions",
            },
        ),
        "frustration": Score(
            instructions="How frustrated the customer appears",
            criteria=["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
        ),
        "is_urgent": Noul(instructions="The message conveys urgency or time-sensitivity"),
    },
)
response.answers["department"].choice          # "billing"
response.choices["department"].probabilities   # {"billing": 0.84, "technical": 0.159, "sales": 0.001}
response.scores["frustration"].score           # 1.035  (legend: 0 calm, 1 frustrated, 2 very angry)
response.nouls["is_urgent"].noul               # 0.999
response.values()                              # {"department": "billing", "frustration": 1.035, "is_urgent": 0.999}
```

Questions may also be plain dicts (`{"type": "choice", "criteria": {...}}`);
extra fields are forwarded untouched so new API options need no client
release.

## Models

All models are served by the same endpoint; the `model` field (or
`JevClient(model=...)`) selects one. `JevModel` enumerates them:

| Name          | Kind      | Notes                                                                 |
|---------------|-----------|-----------------------------------------------------------------------|
| `jev-latest`  | alias     | Most recent stable release; the default. Currently `jev-1.13.0`.      |
| `jev-preview` | alias     | Most recent release, preview or not. Currently the same as `jev-latest`. |
| `jev-1.13.0`  | versioned | Jev 1.13. Pin this when confidence thresholds were tuned against it.  |

Jev 1.13: text input only (string, JSON object, or array of text values);
64k tokens per request for `state` plus all questions, 32k for `state` plus
the longest question; charged per input token ($0.042 / Mtok), output free;
rate limits of 250k tokens/s and 1,200 requests/min return `429`, which the
client retries with backoff honouring `retry-after`. `MODEL_ALIASES`,
`MAX_REQUEST_TOKENS` and `MAX_STATE_PLUS_QUESTION_TOKENS` expose these as
constants. `list_models()` (`GET /v1/models`) currently returns the aliases;
versioned IDs are accepted whether or not they are listed, and the
response's `model` field always reports the versioned ID that answered.

## `AbstractClient` surface

| Method         | Behaviour                                                                                           |
|----------------|-----------------------------------------------------------------------------------------------------|
| `ask()`        | Prompt → state (`system_prompt` → `state["context"]`, `history` → `state["conversation"]`). Questions from `questions=`, a Pydantic `structured_output`, or `JevClient(questions=...)`. Returns an `AIMessage`: `output`/`structured_output` is the typed instance or the `SystemOneResponse`, `data` the plain values, `response` their JSON, `metadata["answers"]` the full detail. |
| `invoke()`     | `output_type=MyModel` derives the questions from the model's fields and validates the answers back into it (see below). |
| `ask_stream()` | Pseudo-stream: one text chunk (the JSON values) then the final `AIMessage`.                          |
| `batch_ask()`  | Concurrent `ask()` calls.                                                                            |
| `list_models()`| `GET /v1/models`.                                                                                    |
| `resume()`     | Raises `NotImplementedError` — there is no tool call to resume.                                      |

`max_tokens`, `temperature`, `files` and `tools` are accepted for interface
parity and ignored (files/tools log a warning).

## Pydantic models as questions (`invoke`)

```python
from typing import Literal
from pydantic import BaseModel, Field

class Triage(BaseModel):
    category: Literal["billing", "technical", "other"] = Field(description="What is this ticket about?")
    urgent: bool = Field(description="Does the customer need an answer today?")
    severity: int = Field(
        description="How badly is the customer affected?",
        json_schema_extra={"criteria": ["Cosmetic", "Degraded", "Blocked"]},
    )

result = await client.invoke("I was charged twice. Please fix this ASAP.", output_type=Triage)
result.output                      # Triage(category="billing", urgent=True, severity=2)
result.raw_response["answers"]     # probabilities + confidence per field
```

| Field annotation                            | Primitive | Coercion                                   |
|---------------------------------------------|-----------|--------------------------------------------|
| `bool`                                      | noul      | `noul >= noul_threshold` (default 0.5)     |
| `Literal[...]` / `str`-valued `Enum`        | choice    | the selected label                         |
| `int` / `float` + `criteria=[levels]`       | score     | rounded level for `int`, raw for `float`   |

`Field(description=...)` is the question text (field names are never sent to
the model). `json_schema_extra={"criteria": ...}` adds label descriptions,
`{"true": .., "false": ..}` outcome descriptions, or the ordered score levels;
`json_schema_extra={"question": Choice(...)}` overrides the derivation. Any
other annotation raises `JevSchemaError` — Jev cannot produce free text.

## Errors

All errors derive from `JevError` (a `ParrotError`): `JevConfigurationError`
(no key / no questions / bad state), `JevSchemaError`, `JevConnectionError`,
and `JevAPIError` with `status`, `body`, `request_id`, `retry_after` — mapped
to `JevBadRequestError` (400/422), `JevAuthenticationError` (401/403),
`JevNotFoundError` (404), `JevRateLimitError` (429), `JevServerError` (5xx).
`invoke()` wraps everything in `InvokeError` (`.original` holds the cause).

## Related: Jev-guided compaction in Claude Code

`parrot claude install` also enables the
[fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction)
plugin, which uses the same `POST /v1/systemone` noul questions to prune a
Claude Code session's tool calls verbatim instead of summarising them. See
`docs/wiki-claude-code.md` § fast-jev-compaction.

## Design notes

- Prompts and history are *state*, not a chat transcript: keep only the
  context the questions need (TypeSafe's own guidance on context rot).
- Ask independent questions in one call; they run in parallel and cannot see
  each other's answers.
- Confidence summarises distribution concentration, not correctness. Pick
  thresholds on your own data and route low-confidence cases to a person or a
  reasoning model.
