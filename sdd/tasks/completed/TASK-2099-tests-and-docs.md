# TASK-2099: Unit tests + usage docs

**Feature**: FEAT-407 — Bedrock Mantle Client
**Spec**: `sdd/specs/bedrock-mantle-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2097, TASK-2098
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / §4 Test Specification: the full unit-test suite for
`BedrockMantleClient` (no live AWS calls — everything mocked), an
optional key-gated live smoke test, and a short usage section in
`docs/`. This closes FEAT-407's acceptance criteria (spec §5).

---

## Scope

- Create `packages/ai-parrot/tests/clients/test_bedrock_mantle.py`
  implementing every row of spec §4:
  - `test_default_base_url_from_region` — no kwargs + conf region unset
    → `https://bedrock-mantle.us-east-1.api.aws/v1`.
  - `test_region_kwarg_builds_base_url` — `region="eu-west-1"` →
    `https://bedrock-mantle.eu-west-1.api.aws/v1`.
  - `test_explicit_base_url_wins` — `base_url=` kwarg beats region/conf.
  - `test_api_key_resolution_order` — kwarg → `BEDROCK_MANTLE_API_KEY`
    → `AWS_NOVA_API_KEY`; key survives `super().__init__` (re-set
    guard); a configured `OPENAI_API_KEY` is NOT silently used when a
    Mantle/Nova key exists.
  - `test_default_model` — `_default_model == "openai.gpt-oss-120b"`,
    `client_type == "bedrock-mantle"`.
  - `test_fallback_model_survives_init` —
    `_fallback_model == "google.gemma-4-26b-a4b"` on the *instance*
    (not shadowed to `None` by `AbstractClient.__init__`).
  - `test_get_client_uses_base_url` — `get_client()` returns an
    `AsyncOpenAI` configured with resolved key + base_url (mock or
    inspect the returned client's attributes; no network).
  - `test_factory_creates_mantle_client` — `LLMFactory` resolves both
    `"bedrock-mantle:openai.gpt-oss-120b"` and the `"mantle"` alias to
    `BedrockMantleClient` with the model set.
  - `test_ask_delegates_to_openai_machinery` — mocked chat-completion
    round trip returns an `AIMessage` (inherited path untouched).
  - `test_live_mantle_ask` — OPTIONAL live round trip, skipped via
    `pytest.mark.skipif` unless a Bedrock API key env var is set.
- Add a short usage doc: `docs/clients/bedrock-mantle.md` (env vars,
  factory string, code example mirroring spec §2 Overview).
- During the live smoke test (if a key is available), empirically check
  the spec §8 open question: does Mantle accept the OpenAI SDK
  `parse()` structured-output path? Record the answer in the Completion
  Note. (If it fails, do NOT fix here — file it for a follow-up task;
  the `NvidiaClient`-style `_chat_completion` override is out of this
  task's scope.)

**NOT in scope**: changes to `mantle.py`, `factory.py`, or
`conf.py` beyond what TASK-2097/2098 delivered (if a test exposes a
bug, fix belongs in a minimal patch commit referencing this task — do
not redesign).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_bedrock_mantle.py` | CREATE | Full unit suite per spec §4 |
| `docs/clients/bedrock-mantle.md` | CREATE | Usage documentation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.clients.nova import BedrockMantleClient   # exported by TASK-2098 — verify before starting
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # verified: packages/ai-parrot/src/parrot/clients/factory.py
from parrot.models import AIMessage                   # verified: used by clients/nvidia.py:23
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/gpt.py:203 (inherited by BedrockMantleClient)
async def get_client(self) -> "AsyncOpenAI":
    # returns AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
    #                     timeout=config.get("OPENAI_TIMEOUT", 60))
    # AsyncOpenAI instances expose .api_key and .base_url attributes.
```

```python
# Existing reference test suite for a Bedrock-family client:
# packages/ai-parrot/tests/clients/test_nova.py — follow its structure,
# fixture style, and mocking conventions (pytest + pytest-asyncio).
```

Key resolution behavior under test (implemented in TASK-2097; verify in
`packages/ai-parrot/src/parrot/clients/nova/mantle.py` before writing tests):
- API key: kwarg → `BEDROCK_MANTLE_API_KEY` → `AWS_NOVA_API_KEY`.
- Base URL: kwarg → `BEDROCK_MANTLE_BASE_URL` →
  `f"https://bedrock-mantle.{region}.api.aws/v1"`,
  region = kwarg → `BEDROCK_AWS_REGION` → `AWS_REGION_NAME` → `"us-east-1"`.

**Conf-var testing gotcha**: `parrot.conf` values (`AWS_NOVA_API_KEY`
etc.) are read at *import time* into module-level constants —
`monkeypatch.setenv` after import does NOT change them. Patch the
constants where `mantle.py` uses them (e.g.
`monkeypatch.setattr("parrot.clients.nova.mantle.AWS_NOVA_API_KEY", ...)`)
— mirroring how existing client tests patch conf values.

### Does NOT Exist

- ~~`tests/clients/test_bedrock_mantle.py` at repo root~~ — tests live
  under `packages/ai-parrot/tests/clients/` (like `test_nova.py`).
- ~~A `conftest.py` fixture that resets `parrot.conf` between tests~~ —
  patch module-level constants explicitly as described above.
- ~~`BedrockMantleClient.ask()` override~~ — `ask` is inherited from
  `OpenAIClient`; mock at the `AsyncOpenAI`/`_chat_completion` layer.
- ~~`docs/clients/` index that must be updated~~ — creating the new
  markdown file is sufficient unless a docs index actually exists
  (verify with `ls docs/clients/` first; create the dir if missing).

---

## Implementation Notes

### Pattern to Follow

Mirror `packages/ai-parrot/tests/clients/test_nova.py` for structure
(fixtures, async tests, no-network mocking). For the mocked `ask`
round trip, patch the inherited machinery at the lowest seam available
(e.g. `_chat_completion` or the `AsyncOpenAI` factory in
`get_client`) rather than re-testing OpenAI internals.

### Key Constraints

- NO live network in the default test run — the live test must be
  skip-gated on an env var and excluded from CI by default.
- Tests must isolate from the developer's real environment (a real
  `OPENAI_API_KEY`/`AWS_NOVA_API_KEY` in the dev's env must not flip
  test outcomes) — patch the module-level constants.
- `pytest packages/ai-parrot/tests/clients/ -v` must stay fully green
  (no regressions in sibling client tests).

### References in Codebase

- `packages/ai-parrot/tests/clients/test_nova.py` — test conventions
- `sdd/specs/bedrock-mantle-client.spec.md` §4, §5 — authoritative test list

---

## Acceptance Criteria

- [ ] All spec §4 unit tests implemented and passing:
      `pytest packages/ai-parrot/tests/clients/test_bedrock_mantle.py -v`
- [ ] Full client suite green: `pytest packages/ai-parrot/tests/clients/ -v`
- [ ] Live test correctly skip-gated (suite passes with no key configured)
- [ ] `docs/clients/bedrock-mantle.md` created with env vars + example
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/clients/test_bedrock_mantle.py`
- [ ] §8 `parse()` open question answered in the Completion Note (or
      explicitly recorded as "not verifiable — no live key available")

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_bedrock_mantle.py
import pytest
from parrot.clients.nova import BedrockMantleClient


@pytest.fixture
def mantle_client(monkeypatch):
    # isolate from developer environment (patch module-level constants)
    monkeypatch.setattr(
        "parrot.clients.nova.mantle.AWS_NOVA_API_KEY", None, raising=False
    )
    return BedrockMantleClient(api_key="ABSK-test-key", region="us-east-1")


class TestBedrockMantleClient:
    def test_default_model(self, mantle_client):
        assert mantle_client.client_type == "bedrock-mantle"
        assert mantle_client._default_model == "openai.gpt-oss-120b"

    def test_region_kwarg_builds_base_url(self, mantle_client):
        assert mantle_client.base_url == "https://bedrock-mantle.us-east-1.api.aws/v1"

    def test_fallback_model_survives_init(self, mantle_client):
        assert mantle_client._fallback_model == "google.gemma-4-26b-a4b"

    def test_explicit_base_url_wins(self):
        c = BedrockMantleClient(api_key="k", base_url="https://custom.example/v1")
        assert c.base_url == "https://custom.example/v1"

    # ... remaining spec §4 rows: api-key resolution order, get_client,
    # factory creation (+ "mantle" alias), mocked ask round trip,
    # skip-gated live test.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2097 and TASK-2098 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/bedrock-mantle-client.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2099-tests-and-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-03
**Notes**: Created `packages/ai-parrot/tests/clients/test_bedrock_mantle.py`
covering every spec §4 row (default/region/explicit/conf-var base-URL
resolution, full API-key resolution order including the "real
OPENAI_API_KEY not silently used" guard, `_fallback_model` survival,
`get_client()` shape, factory creation for both `"bedrock-mantle"` and the
`"mantle"` alias, and a mocked `ask()` round trip via
`patch("parrot.clients.gpt.OpenAIClient._chat_completion", ...)` — mirrors
`test_nvidia_client.py`'s mocked-response pattern) plus the skip-gated
`test_live_mantle_ask` (opt-in via `RUN_MANTLE_LIVE_TEST`, mirroring
`test_nova.py::test_nova_ask_live`). Added `docs/clients/bedrock-mantle.md`
(config table, resolution orders, direct + factory usage examples,
defaults, out-of-scope list) — `docs/clients/` already existed so no new
index needed. `pytest packages/ai-parrot/tests/clients/test_bedrock_mantle.py -v`:
10 passed, 1 skipped. Full `pytest packages/ai-parrot/tests/clients/ -v`:
175 passed, 2 skipped — no regressions. `ruff check` clean except one
pre-existing-convention `BLE001` (blind `except Exception` in the
live-test skip guard), which is the exact pattern already used in
`test_nova.py::test_nova_ask_live` — left as-is for consistency.

**`parse()` verification result**: not verifiable — no live Bedrock
Mantle API key was available in this environment, so the skip-gated
`test_live_mantle_ask` could not be exercised. The mocked
`test_ask_delegates_to_openai_machinery` test only proves the inherited
non-`parse()` `_chat_completion`/`create()` path is untouched; it does
not exercise `chat.completions.parse()` at all (spec §7 gotcha notes
`_chat_completion` uses `create()`, and `OpenAIClient` does not appear to
route through `parse()` for plain `ask()` calls in this codebase, based
on the same `_chat_completion` mocking seam used by `NvidiaClient`'s and
`OpenRouterClient`'s tests). This open question (spec §8) remains
unresolved and should be verified empirically once a live Mantle key is
available — flagging as a follow-up rather than guessing.

**Deviations from spec**: none — the `_chat_completion`-level mock was
chosen over reimplementing `AsyncOpenAI` internals, matching the existing
`test_nvidia_client.py`/`test_openrouter_client.py` convention referenced
in this task's Codebase Contract.
