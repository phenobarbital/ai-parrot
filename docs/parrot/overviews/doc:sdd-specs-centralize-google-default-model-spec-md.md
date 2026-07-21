---
type: Wiki Overview
title: 'Feature Specification: Centralize Google Default Model'
id: doc:sdd-specs-centralize-google-default-model-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The framework already exposes a single global alias for the latest Google
relates_to:
- concept: mod:parrot.bots.chatbot
  rel: mentions
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.models
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Centralize Google Default Model

**Feature ID**: FEAT-188
**Date**: 2026-05-19
**Author**: Juan2coder
**Status**: draft
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

The framework already exposes a single global alias for the latest Google
Gemini model — `GoogleModel.GEMINI_FLASH_LATEST` in
`parrot/models/google.py:15` — currently pointing to
`"gemini-3-flash-preview"`. However, ~14 code paths bypass that alias and
hardcode the literal `"gemini-2.5-flash"` (or `GoogleModel.GEMINI_2_5_FLASH`)
as a fallback default. This produces the following observable failure:

- The `sql_analyst` agent declares `model = "gemini-3-flash-preview"` on the
  class, but logs show every turn running on `gemini-2.5-flash`. Root cause:
  `chatbot.py:367` previously hardcoded `default='gemini-2.5-flash'` when
  reading from the `navigator.bots` row, overriding the class attribute.
- Two of the hardcodes already fixed in this branch's WIP (`conf.py:429`
  and `chatbot.py:367`) prove the migration pattern; the remaining sites
  must follow the same rule so the global is the **only** source of truth.

Without this cleanup, future model bumps require editing N files instead of
one, and bug-for-bug parity between agents drifts as some inherit the new
default while others stay pinned to 2.5.

### Goals

- Make `GoogleModel.GEMINI_FLASH_LATEST` (and the env-driven
  `DEFAULT_LLM_MODEL` in `parrot/conf.py`) the **only** authoritative
  default for "the latest Gemini Flash" across the codebase.
- Eliminate every hardcoded `"gemini-2.5-flash"` literal that exists as a
  *fallback default*. Explicit model selections (e.g. retry-with-cheaper
  model paths, image analysis pinned to a specific version) stay pinned.
- Preserve backward compatibility: existing env (`LLM_MODEL`) and DB
  (`navigator.bots.model`) overrides keep winning over the global.

### Non-Goals

- Do **not** change `GoogleModel.GEMINI_FLASH_LATEST`'s pointed value as
  part of this work — that bump is a separate decision.
- Do **not** touch references that intentionally pin to a specific Gemini
  version for capability reasons (e.g. `analysis.py:771` retry path that
  explicitly falls back to 2.5-flash on 5xx from Pro; image plugins that
  use `GEMINI_2_5_FLASH` because the 3-flash-preview lacks image
  capabilities at time of writing).
- Do **not** migrate non-Google clients (Claude/GPT/Grok) — each has its
  own default and is out of scope.
- Do **not** rename or remove `GoogleModel.GEMINI_2_5_FLASH` from the enum
  — it remains a valid explicit choice.

---

## 2. Architectural Design

### Overview

Single rule: any place that previously read "use 2.5-flash if no override"
must now read `DEFAULT_LLM_MODEL` (from `parrot.conf`) or
`GoogleModel.GEMINI_FLASH_LATEST.value` directly. The two are equivalent —
`DEFAULT_LLM_MODEL` resolves to the `LLM_MODEL` env var, falling back to
`GoogleModel.GEMINI_FLASH_LATEST.value`.

Choose between them by context:

- **`DEFAULT_LLM_MODEL`** for runtime/agent fallbacks that an operator may
  want to override via env without touching code.
- **`GoogleModel.GEMINI_FLASH_LATEST.value`** for tight, library-level
  defaults inside the Google client itself (where importing `conf` would
  invert the dependency arrow).

### Component Diagram

```
                    parrot.models.google.GoogleModel
                                 │
                  GEMINI_FLASH_LATEST = "gemini-3-flash-preview"
                                 │
                                 ▼
                          parrot.conf.py
              DEFAULT_LLM_MODEL = LLM_MODEL env or LATEST
                                 │
              ┌──────────────────┴────────────────────┐
              ▼                                       ▼
       Agent layer (chatbot.py,            Client layer (clients/google/*)
       bots/base.py, voice.py,             default kwargs in method
       scraper.py, ...)                    signatures + internal fallbacks
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.conf.DEFAULT_LLM_MODEL` | reuse | Already wired to `GEMINI_FLASH_LATEST` after WIP fix. |
| `parrot.models.google.GoogleModel.GEMINI_FLASH_LATEST` | reuse | Source of truth; not modified. |
| `parrot.clients.google.client.GoogleGenAIClient._default_model` | reuse | Already points to `GEMINI_FLASH_LATEST.value`. |
| `parrot.bots.chatbot.Chatbot._llm_model` | already migrated | WIP fix uses class attr → `DEFAULT_LLM_MODEL`. |

### Data Models

No new data structures. This is a code-hygiene migration.

### New Public Interfaces

None. The constant `DEFAULT_LLM_MODEL` is already public in
`parrot.conf`. No new symbols are introduced.

---

## 3. Module Breakdown

### Module 1: `parrot/conf.py`
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Replace `ONTOLOGY_AQL_MODEL`'s hardcoded
  `'gemini-2.5-flash'` fallback (line 142) with `DEFAULT_LLM_MODEL` so the
  ontology AQL generator inherits the global default unless explicitly
  overridden via the `ONTOLOGY_AQL_MODEL` env var.
- **Depends on**: existing `DEFAULT_LLM_MODEL` constant (already in place).

### Module 2: Agent-layer fallbacks
- **Path**:
  - `packages/ai-parrot/src/parrot/bots/base.py` (lines 342, 344)
  - `packages/ai-parrot/src/parrot/bots/voice.py` (line 249)
  - `packages/ai-parrot/src/parrot/bots/scraper/scraper.py` (line 98)
- **Responsibility**: Replace literal `'gemini-2.5-flash'` with
  `DEFAULT_LLM_MODEL` import from `parrot.conf` so agent-level fallbacks
  go through the global.
- **Depends on**: Module 1 (no circular import risk — `conf` is
  already imported by `bots/chatbot.py`).

### Module 3: Google client internal fallbacks
- **Path**: `packages/ai-parrot/src/parrot/clients/google/client.py`
  (lines 1842, 2666, 3145)
- **Responsibility**: Replace `GoogleModel.GEMINI_2_5_FLASH.value`
  fallback with `GoogleModel.GEMINI_FLASH_LATEST.value` so that when
  neither the caller nor the client instance specify a model, the client
  uses the same default that `_default_model` advertises.
- **Depends on**: nothing new (already imports `GoogleModel`).

### Module 4: Memory & deployment templates
- **Path**:
  - `packages/ai-parrot/src/parrot/memory/episodic/reflection.py` (line 94)
  - `packages/ai-parrot/src/parrot/autonomous/deploy/templates.py`
    (lines 188, 199)
  - `packages/ai-parrot/src/parrot/setup/providers/google.py` (line 16)
  - `packages/ai-parrot/src/parrot/voice/models.py` (line 193)
  - `packages/ai-parrot/src/parrot/handlers/google_generation.py` (line 95)
- **Responsibility**: Same migration. The deployment templates produce
  generated configs — keep the literal string but read it from
  `DEFAULT_LLM_MODEL` at template-render time so future bumps propagate
  to new deployments without code changes.
- **Depends on**: nothing new.

### Module 5: Verification harness
- **Path**: new `packages/ai-parrot/tests/unit/test_default_model_centralization.py`
- **Responsibility**: A static-analysis test that greps the codebase
  for any new occurrences of the literal `"gemini-2.5-flash"` or
  `GoogleModel.GEMINI_2_5_FLASH` used as a *default* (parameter default
  value or OR-fallback) and fails if found outside the explicit allow-list
  in §1 Non-Goals. Allow-list driven by an in-test constant so reviewers
  see exactly which files are intentionally pinned.
- **Depends on**: nothing new.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_default_llm_model_is_latest` | Module 1 | `parrot.conf.DEFAULT_LLM_MODEL` equals `GoogleModel.GEMINI_FLASH_LATEST.value` when `LLM_MODEL` env is unset. |
| `test_chatbot_inherits_class_model` | Module 2 | A `Chatbot` subclass with `model = "gemini-3-flash-preview"` and no DB row resolves `_llm_model` to `"gemini-3-flash-preview"`. |
| `test_chatbot_falls_back_to_global` | Module 2 | A `Chatbot` with no class `model` attr and no DB row resolves `_llm_model` to `DEFAULT_LLM_MODEL`. |
| `test_google_client_internal_fallback` | Module 3 | `GoogleGenAIClient(model=None).ask(...)` (with mocked SDK) sends `gemini-3-flash-preview`, not `gemini-2.5-flash`. |
| `test_no_orphan_2_5_defaults` | Module 5 | Static grep test fails if any non-allow-listed file introduces `gemini-2.5-flash` as a default. |

### Integration Tests

| Test | Description |
|---|---|
| `test_sql_analyst_uses_latest_model` | Boot `SQLAnalyst` with an empty `navigator.bots` row → confirm the structured-output log line reports `gemini-3-flash-preview`, not `gemini-2.5-flash`. |
| `test_env_override_still_wins` | Set `LLM_MODEL=gemini-2.5-pro`, re-import `conf`, confirm `DEFAULT_LLM_MODEL == "gemini-2.5-pro"`. |

### Test Data / Fixtures

```python
@pytest.fixture
def empty_bot_row(monkeypatch):
    """Mock BotModel.get returning an object with no `model` field."""
    class _Row:
        model = None
        llm = None
    monkeypatch.setattr(
        "parrot.handlers.models.BotModel.get",
        lambda **_: _Row(),
    )
```

---

## 5. Acceptance Criteria

- [ ] `parrot.conf.DEFAULT_LLM_MODEL` resolves to
      `GoogleModel.GEMINI_FLASH_LATEST.value` when `LLM_MODEL` env is unset
      (already satisfied by WIP commit; preserve in this work).
- [ ] `parrot.bots.chatbot.Chatbot.from_database` falls back to the agent
      class's `model` attribute when DB has no model, then to
      `DEFAULT_LLM_MODEL` (already satisfied by WIP commit).
- [ ] Every file listed in §3 Modules 1–4 reads its default from
      `DEFAULT_LLM_MODEL` or `GoogleModel.GEMINI_FLASH_LATEST` — no new
      literals of `"gemini-2.5-flash"` as a fallback default.
- [ ] The allow-list in `test_no_orphan_2_5_defaults` documents every
      remaining intentional pin (analysis retry path, image plugins,
      etc.).
- [ ] `sql_analyst` log output during a real query shows
      `Using model: gemini-3-flash-preview` (manual smoke-test evidence
      captured in PR description).
- [ ] `pytest packages/ai-parrot/tests/unit/test_default_model_centralization.py -v`
      passes.
- [ ] No regression: existing Google client unit + integration tests pass.

---

## 6. Codebase Contract

### Verified Imports

```python
# parrot/conf.py
from .models.google import GoogleModel   # verified: conf.py:430 (added in WIP commit)
DEFAULT_LLM_MODEL = config.get(
    'LLM_MODEL', fallback=GoogleModel.GEMINI_FLASH_LATEST.value,
)  # verified: conf.py:431-433

# Downstream consumers (already importing conf):
from parrot.conf import DEFAULT_LLM_MODEL   # verified working at runtime
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/models/google.py
class GoogleModel(Enum):
    GEMINI_FLASH_LATEST = "gemini-3-flash-preview"   # line 15
    GEMINI_2_5_FLASH = "gemini-2.5-flash"            # line 18
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"  # line 14

# packages/ai-parrot/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient):
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value  # line 105
    # ↓ these three lines are the migration targets in Module 3
    # line 1842: model = self.model or GoogleModel.GEMINI_2_5_FLASH.value
    # line 2666: ... or (self.model or GoogleModel.GEMINI_2_5_FLASH.value)
    # line 3145: model = self.model or GoogleModel.GEMINI_2_5_FLASH.value

# packages/ai-parrot/src/parrot/bots/chatbot.py
class Chatbot(BaseBot):
    async def from_database(self, bot):  # line ~344
        # WIP commit fixed line 367:
        self._llm_model = self._from_db(
            bot, 'model',
            default=getattr(self, 'model', None) or DEFAULT_LLM_MODEL,
        )

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):
    async def ask(self, ...):  # line ~280
        # Migration targets:
        # line 342: kwargs['model'] = 'gemini-2.5-flash'   ← replace
        # line 344: kwargs['model'] = 'gemini-2.5-flash'   ← replace
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Module 1` (conf.py:142) | `DEFAULT_LLM_MODEL` | constant reference | `conf.py:431` |
| `Module 2` (bots/base.py) | `DEFAULT_LLM_MODEL` | import from `..conf` | `chatbot.py:17-21` (same import pattern) |
| `Module 3` (google/client.py) | `GoogleModel.GEMINI_FLASH_LATEST` | enum lookup | `google/client.py:105` (already imported) |
| `Module 5` (test) | static grep | filesystem walk | new file |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.conf.GEMINI_DEFAULT_MODEL`~~ — does not exist; use `DEFAULT_LLM_MODEL`.
- ~~`GoogleModel.LATEST`~~ — does not exist; use `GEMINI_FLASH_LATEST`.
- ~~`GoogleGenAIClient.default_model_str`~~ — does not exist; access via
  the `default_model` property on `AbstractClient` (base.py:784) which
  reads `_default_model`.
- ~~A central registry mapping providers → default models~~ — does not
  exist and is out of scope for this spec. Each provider client owns its
  own `_default_model`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Import `DEFAULT_LLM_MODEL` from `parrot.conf` for agent-layer code; do
  not re-import the enum unless you also need an explicit alternative
  model.
- Inside `parrot/clients/google/` use `GoogleModel.GEMINI_FLASH_LATEST.value`
  directly — importing `conf` from a client would invert the dependency.
- For places that compare model strings (e.g. capability gates), prefer
  comparing against `GoogleModel.GEMINI_2_5_FLASH.value` explicitly rather
  than the literal string, to keep the enum the source of truth.
- Logger usage: when changing a default that may surprise an operator
  (e.g. ontology AQL model), log the resolved model at boot once via
  `self.logger.info(...)`.

### Known Risks / Gotchas

- **DB rows with stale model values**: a row like
  `navigator.bots(name='sql_analyst', model='gemini-2.5-flash')` will
  still override the global. Document this in the PR and ship a
  side-script (out of scope to run automatically) to null those rows.
- **Image-capability mismatch**: `gemini-3-flash-preview` does not (yet)
  support image input on all paths. Image plugins are intentionally
  pinned to `GEMINI_2_5_FLASH`; do not migrate them.
- **Retry fallback paths**: `clients/google/analysis.py:771-774`
  intentionally falls back from Pro → 2.5-flash on rate-limit. Keep that
  literal — it's a *deliberate* downgrade, not a default.
- **Deployment templates**: `autonomous/deploy/templates.py` writes the
  string into generated YAML configs at template-render time, not import
  time. Migrating to `DEFAULT_LLM_MODEL` will cause re-deployments to
  inherit future bumps automatically — confirm that's desired.
- **Env semantics**: `LLM_MODEL` is the env override. After this spec,
  setting `LLM_MODEL=gemini-2.5-flash` is the supported way to pin an
  entire deployment back to 2.5.

### External Dependencies

None. This is a refactor; no new packages.

---

## 8. Open Questions

- [ ] Should we also bump `GoogleModel.GEMINI_FLASH_LATEST` to point to a
      future GA model name once 3-flash exits preview, or wait for an
      explicit decision? — *Owner: Juan2coder*
- [ ] Do we want the static-grep test (Module 5) to live in
      `tests/unit/` or under a dedicated `tests/lint/` directory so it
      can be skipped in fast test runs? — *Owner: Juan2coder*
- [ ] Should `setup/providers/google.py:16` (`default_model = "gemini-2.5-flash"`)
      be removed entirely (forcing callers to pass `model`) or migrated
      like the rest? — *Owner: Juan2coder*

---

## Worktree Strategy

- **Default isolation unit**: per-spec.
- All tasks (Modules 1–5) touch independent files but share the same
  test harness, so running them sequentially in one worktree is simpler
  than parallelizing. Estimated 5 small commits, one per module.
- **Cross-feature dependencies**: none. The WIP commits on `conf.py` and
  `chatbot.py` from the originating session must land first (either as
  the first commit of this feature branch, or merged separately into
  `dev` before branching).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-19 | Juan2coder | Initial draft. |
