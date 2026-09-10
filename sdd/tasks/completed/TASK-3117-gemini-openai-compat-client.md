# TASK-3117: `GeminiOpenAICompatClient` — Gemini through Google's OpenAI-compatible endpoint

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (client half). `GoogleGenAIClient` speaks the native GenAI SDK and
has no `_chat_completion`, so `LLMCodeDispatcher` cannot drive it. Google serves an
OpenAI-compatible endpoint at `https://generativelanguage.googleapis.com/v1beta/openai/`
that was verified live on 2026-09-10 with the dispatcher's exact tool schemas (spec §6
"Spike evidence"). This task adds the thin `OpenAIBaseClient` subclass that points there,
copying `BedrockMantleClient` structurally (endpoint + key resolution only, no model
defaults). The dispatcher half is TASK-3118.

---

## Scope

- Create `parrot/clients/google/openai_compat.py` with `GEMINI_OPENAI_BASE_URL` and `GeminiOpenAICompatClient(OpenAIBaseClient)`.
- Export it from `parrot/clients/google/__init__.py` and register the provider key `google-compat` in the package's `pyproject.toml` entry points.
- Unit tests for key resolution and the "no model defaults" rule (no network).

**NOT in scope**: the dispatcher/profile/backend (TASK-3118); any change to `GoogleGenAIClient`;
the `thought_signature` handling (lives in the dispatcher override, TASK-3118).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py` | CREATE | the compat client |
| `packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py` | MODIFY | import + `__all__` entry |
| `packages/ai-parrot-client-google/pyproject.toml` | MODIFY | `google-compat = "parrot.clients.google:GeminiOpenAICompatClient"` |
| `packages/ai-parrot-client-google/tests/unit/test_openai_compat_client.py` | CREATE | key resolution / defaults tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import config                      # verified in use: google/client.py:189 `config.get("GOOGLE_API_KEY")` — confirm the import line with `grep -n "^from navconfig" .../google/client.py`
from ..openai_base import OpenAIBaseClient        # verified: parrot/clients/openai_base.py:66 (class); mantle.py:12 uses the same relative form `...openai_base` from one level deeper
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                  # line 66
    # line 77 comment: "Intentionally NO _default_model / _fallback_model / _lightweight_model"
    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs)   # line 89-92
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any   # line 216

# TEMPLATE — packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py (142 lines)
class BedrockMantleClient(OpenAIBaseClient):                             # line 35
    def __init__(self, api_key=None, base_url=None, region=None, **kwargs):   # line 103
        resolved_key = api_key or BEDROCK_MANTLE_API_KEY or AWS_NOVA_API_KEY        # :110
        resolved_base_url = base_url or BEDROCK_MANTLE_BASE_URL or f"https://bedrock-mantle.{region}.api.aws/v1"   # :112-114
        super().__init__(api_key=resolved_key, base_url=resolved_base_url, **kwargs)   # :119-123
        self.api_key = resolved_key                                                     # :128 — re-set after super().__init__
        self.base_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}   # :139-142 — rebuilt to match the resolved key

# packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py  (lines 1-12)
from .client import GoogleGenAIClient          # :1
from .live import GeminiLiveClient             # :2
from .models import GoogleModel, VertexAIModel # :3
GoogleClient = GoogleGenAIClient               # :5
__all__ = ["GoogleGenAIClient", "GoogleClient", "GeminiLiveClient", "GoogleModel", "VertexAIModel", ...]   # :7-

# packages/ai-parrot-client-google/pyproject.toml  (lines 25-27)
[project.entry-points."parrot.clients"]
google = "parrot.clients.google:GoogleGenAIClient"
gemini-live = "parrot.clients.google:GeminiLiveClient"
```

### Does NOT Exist
- ~~`GoogleGenAIClient._chat_completion`~~ — never defined (grep across the package returns nothing); do not add it there.
- ~~`GEMINI_API_KEY` / `GOOGLE_API_KEY` in `os.environ`~~ — loaded from `env/.env` by navconfig; use `config.get(...)`.
- ~~`_default_model`, `_fallback_model`, `_lightweight_model` on this client~~ — MUST NOT be declared (FEAT-438 rule recorded in `nova.py` docstring: a fallback could otherwise retry with a `gpt-*` id on a non-OpenAI endpoint).
- ~~`GoogleModel.GEMINI_3_5_FLASH` as a default here~~ — the client carries no default model; the dispatcher profile (TASK-3118) owns `gemini-3.5-flash`.
- ~~`parrot.clients.google.openai_compat`~~ — created by this task.

---

## Implementation Notes

### Pattern to Follow
`BedrockMantleClient.__init__` (mantle.py:103-142) verbatim, minus the region logic.

### Key Constraints
- Key resolution order: explicit `api_key` → `config.get("GEMINI_API_KEY")` → `config.get("GOOGLE_API_KEY")`; none ⇒ `ValueError` naming both keys.
- Default `base_url` = `GEMINI_OPENAI_BASE_URL` (trailing slash included — Google's docs use it).
- Rebuild `self.base_headers` after `super().__init__` (mantle.py:139-142 explains why).
- Google-style docstrings; strict typing.

### References in Codebase
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py` — the template.
- `packages/ai-parrot-client-amazon/pyproject.toml:28-29` — how a compat client is registered (`bedrock-mantle = "parrot.clients.amazon:BedrockMantleClient"`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `openai_compat.py` from the Mantle template — *why*: the loop only needs an OpenAI-SDK-shaped client; nothing Gemini-specific belongs in the client.
2. Export + entry point — *why*: `LLMFactory.create("google-compat:<model>")` resolves providers through `parrot.clients` entry points (factory.py:140-152); without the entry the dispatcher cannot build the client.
3. Tests, then `pytest packages/ai-parrot-client-google/tests/unit/test_openai_compat_client.py -v`.
4. Re-install the package in editable mode if entry points are cached (`uv pip install -e packages/ai-parrot-client-google`) — *why*: `importlib.metadata.entry_points` reads installed metadata.

### `packages/ai-parrot-client-google/src/parrot/clients/google/openai_compat.py` (CREATE)
```python
"""Gemini via Google's OpenAI-compatible endpoint (FEAT-549, spec §3 M3).

Template: ``parrot.clients.amazon.nova.mantle.BedrockMantleClient``. Everything
(completions, tool calling, retry) is inherited from ``OpenAIBaseClient``; this
module only resolves endpoint + key. It deliberately declares NO
``_default_model`` / ``_fallback_model`` / ``_lightweight_model``.
"""
from __future__ import annotations

from navconfig import config                 # verified in use: google/client.py:189

from ..openai_base import OpenAIBaseClient   # verified: parrot/clients/openai_base.py:66

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiOpenAICompatClient(OpenAIBaseClient):
    """OpenAI-SDK-shaped client for Gemini models.

    Args:
        api_key: Explicit key; falls back to ``GEMINI_API_KEY`` then ``GOOGLE_API_KEY`` (navconfig).
        base_url: Defaults to :data:`GEMINI_OPENAI_BASE_URL`.
        **kwargs: Forwarded to ``OpenAIBaseClient`` (``model``, ``temperature``, ``max_tokens`` …).

    Raises:
        ValueError: When no API key resolves.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs) -> None:
        resolved_key = api_key or config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError("GeminiOpenAICompatClient needs an API key: pass api_key= or set GEMINI_API_KEY / GOOGLE_API_KEY")
        super().__init__(api_key=resolved_key, base_url=base_url or GEMINI_OPENAI_BASE_URL, **kwargs)
        self.api_key = resolved_key                                  # mantle.py:128 — re-set after super().__init__
        self.base_headers = {                                        # mantle.py:139-142 — keep headers in sync with the key
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
```
**Why this shape**: identical to Mantle so reviewers can diff the two; the `ValueError` replaces Mantle's silent `None` because the roster probe (TASK-3116) relies on construction failing loudly when keys are missing. No `FILL IN` — this file is fully decided.

### `packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from .models import GoogleModel, VertexAIModel$' packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py)
# AFTER — insert below `from .models import GoogleModel, VertexAIModel` (verified: __init__.py:3)
from .openai_compat import GEMINI_OPENAI_BASE_URL, GeminiOpenAICompatClient
# and append to __all__ (list starts at :7):  "GeminiOpenAICompatClient", "GEMINI_OPENAI_BASE_URL",
```
**Why**: spec New Public Interfaces: `from parrot.clients.google import GeminiOpenAICompatClient`.

### `packages/ai-parrot-client-google/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^gemini-live = "parrot.clients.google:GeminiLiveClient"$' packages/ai-parrot-client-google/pyproject.toml)
# AFTER — insert below `gemini-live = "parrot.clients.google:GeminiLiveClient"` (verified: pyproject.toml:27)
google-compat = "parrot.clients.google:GeminiOpenAICompatClient"
```
**Why**: `LLMFactory` discovers providers from the `parrot.clients` entry-point group (factory.py:145-152); `PROVIDER_BACKEND` (factory.py:157) needs no entry — this client has no backend switch.

### FILL IN checklist
- [ ] none — all three files are fully decided; only tests need bodies beyond the scaffold below.

---

## Acceptance Criteria

- [ ] `GeminiOpenAICompatClient(api_key="k").base_url` (or the attribute `OpenAIBaseClient` stores it under — check `openai_base.py:89-130`) equals `GEMINI_OPENAI_BASE_URL`.
- [ ] With `GEMINI_API_KEY` monkeypatched out of `config` and no `GOOGLE_API_KEY`, construction raises `ValueError` mentioning both names.
- [ ] `hasattr(GeminiOpenAICompatClient, "_default_model")` is False (same for `_fallback_model`, `_lightweight_model`) unless inherited as `None`/absent from `OpenAIBaseClient` — assert the class dict does not define them.
- [ ] `LLMFactory.list_providers()` contains `google-compat` after editable re-install.
- [ ] `pytest packages/ai-parrot-client-google/tests/unit/test_openai_compat_client.py -v` passes; `ruff`/`mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot-client-google/tests/unit/test_openai_compat_client.py
import pytest
from parrot.clients.google import GEMINI_OPENAI_BASE_URL, GeminiOpenAICompatClient
from parrot.clients.google import openai_compat as mod


def test_compat_client_key_resolution(monkeypatch):
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: {"GEMINI_API_KEY": "gk"}.get(k))
    c = GeminiOpenAICompatClient()
    assert c.api_key == "gk" and c.base_headers["Authorization"] == "Bearer gk"
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: {"GOOGLE_API_KEY": "ok"}.get(k))
    assert GeminiOpenAICompatClient().api_key == "ok"
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiOpenAICompatClient()


def test_compat_client_default_base_url():
    c = GeminiOpenAICompatClient(api_key="k")
    # FILL IN: assert the stored base url attribute == GEMINI_OPENAI_BASE_URL (name per openai_base.py:89-130)


def test_compat_client_has_no_model_defaults():
    for name in ("_default_model", "_fallback_model", "_lightweight_model"):
        assert name not in GeminiOpenAICompatClient.__dict__
```

---

## Agent Instructions

1. **Read the spec** §3 Module 3 and §6 "Spike evidence".
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — read `mantle.py:103-142` and `openai_base.py:66-130` before writing.
4. **Update status** in `sdd/tasks/index/sdd-worker-subagents.json` → `"in-progress"`.
5. **Implement** from the blueprint.
6. **Verify** all acceptance criteria (including the entry-point check).
7. **Move this file** to `sdd/tasks/completed/TASK-3117-gemini-openai-compat-client.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-10
**Notes**: Implemented `GeminiOpenAICompatClient` exactly per the (fully-decided)
blueprint, wired the `__init__.py` export and the `pyproject.toml` entry point.
4/4 unit tests pass (key resolution incl. the `ValueError` naming both keys,
default/explicit `base_url`, no model-default class attrs); `ruff`/`mypy` clean.

**Deviations from spec**: (1) Did not run the live editable-reinstall +
`LLMFactory.list_providers()` check from AC-4/this task's AC list. The
`.venv` is the **main repo's shared venv** (other concurrent Claude Code
worktree sessions use it for their own test runs); `uv pip install -e
packages/ai-parrot-client-google` from this worktree would repoint the
venv's editable install away from the main checkout for every other
session using it at the same time — an unacceptable shared-state mutation
per the project's worktree-isolation rules. Verified the entry point
statically instead: `pyproject.toml`'s `[project.entry-points."parrot.clients"]`
parses correctly via `tomllib` and contains
`google-compat = "parrot.clients.google:GeminiOpenAICompatClient"`; the live
`LLMFactory.list_providers()` check will pass once the merged `dev` branch
is reinstalled (CI / `/sdd-done` verification), which is the first point an
editable reinstall is safe. (2) The spec/task's "Does NOT Exist" claim that
`BedrockMantleClient` (mantle.py:35) "carries NO `_default_model` /
`_fallback_model` / `_lightweight_model`" is inaccurate as of this commit —
`mantle.py` actually declares `_default_model = "openai.gpt-oss-120b"` and
`_fallback_model: str | None = None` as class attributes (FEAT-438 lesson:
no *gpt-\* /claude-\** id, not no default at all). This did not change the
implementation: the blueprint's literal `GeminiOpenAICompatClient` code
never declared those attributes either, and `test_compat_client_has_no_model_defaults`
only checks `GeminiOpenAICompatClient.__dict__` (not inherited members), so
the bounded test still holds. Flagged for the spec author rather than
silently corrected.
