# TASK-2296: OpenAIBaseClient skeleton — new module, neutral hooks, no OpenAI defaults

**Feature**: FEAT-438 — OpenAI-Compatible Client Base (OpenAIBaseClient)
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. FEAT-438 inserts an abstract layer — `OpenAIBaseClient` —
between `AbstractClient` and every OpenAI-wire client so subclasses can inherit
the OpenAI wire protocol without inheriting OpenAI-the-provider defaults
(`gpt-*` model ids caused a production 404 on Bedrock Mantle). This task creates
the module shell and its neutral hooks. Wire-method extraction from
`OpenAIClient` happens in TASK-2297/2298 — here the base is standalone and not
yet used by any client.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/openai_base.py` with
  `class OpenAIBaseClient(AbstractClient)`:
  - Class attrs: `tool_format: ToolFormat = ToolFormat.OPENAI`. Do NOT declare
    `model`, `_default_model`, `_fallback_model`, `_lightweight_model`,
    `client_type`, or `client_name` values beyond what `AbstractClient` gives
    (spec G1 — the class must contain no `gpt-*` string anywhere).
  - `__init__(self, api_key: str = None, base_url: str = None, **kwargs)` —
    generic version of gpt.py:100: store `api_key`/`base_url`, build
    `self.base_headers` (Content-Type + Bearer), call
    `self._normalize_model()` on a `model` kwarg if present, then
    `super().__init__(**kwargs)`. No env-var default here — providers supply
    their own in their `__init__`.
  - `async def get_client(self) -> Any` — lazy-import `openai.AsyncOpenAI`,
    return `AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
    timeout=...)`. Timeout: accept a `timeout` kwarg stored in `__init__`
    (default 60); do NOT read `OPENAI_TIMEOUT` here (that is OpenAI-specific
    and stays in gpt.py's override until TASK-2297 decides otherwise).
  - `def _normalize_model(self, model) -> str` — identity: coerce Enum→value/
    str and return; no deprecation logic, no warnings.
  - `def _resolve_model(self, model) -> str` — same chain as gpt.py:108:
    `self._normalize_model(model or self.model or self.default_model)`; raise
    `ValueError("no model configured for <ClassName>")` if the chain resolves
    to `None`/empty (spec: fail fast, never send `model=None`).
  - `def _is_responses_model(self, model_str: str) -> bool` — return `False`.
  - `@staticmethod def _with_extra_body(payload, extra_body) -> Dict` — copy of
    the pure dict-merge at gpt.py:514 (it moves here for real in TASK-2298;
    for now implement it in the base — TASK-2298 deletes the gpt.py copy).
- Export: add `OpenAIBaseClient` to `packages/ai-parrot/src/parrot/clients/__init__.py`.
- Write unit tests in `tests/clients/test_openai_base.py`:
  no-model-defaults, identity normalize, fail-fast ValueError, tool_format,
  `"gpt"` not in module source (literal scan of the file).

**NOT in scope**: moving any method out of gpt.py (TASK-2297/2298); rebasing
any client; touching base.py (TASK-2299); factory changes (none in FEAT-438).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | CREATE | `OpenAIBaseClient` skeleton |
| `packages/ai-parrot/src/parrot/clients/__init__.py` | MODIFY | export `OpenAIBaseClient` |
| `tests/clients/test_openai_base.py` | CREATE | skeleton unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient   # clients/base.py:250
from parrot.tools.manager import ToolFormat      # tools/manager.py:47 (OPENAI/ANTHROPIC/GOOGLE/GROQ/VERTEX/GENERIC/BEDROCK)
from openai import AsyncOpenAI                   # lazy import inside get_client (pattern: gpt.py:230-236)
```

### Existing Signatures to Use
```python
# clients/base.py:250
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"                 # :256
    tool_format: Optional[ToolFormat] = None     # :268
    _lightweight_model: Optional[str] = None     # :272 (None → invoke falls to self.model, :1832-1847)
    @property
    def default_model(self) -> str:              # :906 → getattr(self, '_default_model', None)
    # Abstract methods the base will eventually satisfy (TASK-2297/2298):
    #   get_client :946, ask :1644, ask_stream :1682, resume :1711, invoke :1733

# clients/gpt.py:100 — pattern for __init__ (generic parts only):
def __init__(self, api_key: str = None, base_url: str = "https://api.openai.com/v1", **kwargs):
    self.api_key = api_key or config.get("OPENAI_API_KEY")   # ← env default is OpenAI-specific, DO NOT copy
    self.base_url = base_url
    self.base_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
    if "model" in kwargs:
        kwargs["model"] = self._normalize_model(kwargs["model"])
    super().__init__(**kwargs)

# clients/gpt.py:108 — _resolve_model chain to replicate (plus fail-fast):
#   return self._normalize_model(model or self.model or self.default_model)
# clients/gpt.py:514 — _with_extra_body (pure dict merge, static)
# clients/gpt.py:230 — get_client pattern (lazy import + ImportError message "pip install ai-parrot[openai]")
```

### Does NOT Exist
- ~~`parrot/clients/openai_base.py`~~ — this task creates it; nothing imports it yet.
- ~~`OpenAICompatibleClient`~~ — wrong name; the class is `OpenAIBaseClient`.
- ~~`ToolFormat.OPENAI_COMPATIBLE`~~ — only the 7 members listed above.
- ~~an abstract `embed()` on `AbstractClient`~~ — no embed surface anywhere.
- Note: `AbstractClient` declares `ask/ask_stream/resume/invoke/get_client` as
  `@abstractmethod` — until TASK-2297/2298 move implementations in,
  `OpenAIBaseClient` is still abstract. Tests must use a trivial test-only
  subclass or instantiate via `__new__`-free patterns (e.g. a `_StubClient`
  defining minimal overrides) — do NOT try `OpenAIBaseClient()` directly.

---

## Implementation Notes

### Pattern to Follow
```python
# Lazy SDK import pattern (gpt.py:230):
async def get_client(self) -> "AsyncOpenAI":
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise ImportError("...requires the 'openai' SDK...") from exc
    return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self._timeout)
```

### Key Constraints
- Google-style docstrings + strict type hints on every method.
- The module source must not contain the substring `gpt-` (test-enforced).
- `self.logger` (inherited) for any logging; no prints.
- Do not modify `AbstractClient`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/gpt.py:84-130` — attribute/init layout being generalized.
- `packages/ai-parrot/src/parrot/clients/base.py:250-360` — parent init contract.

---

## Acceptance Criteria

- [ ] `from parrot.clients import OpenAIBaseClient` and
  `from parrot.clients.openai_base import OpenAIBaseClient` both work
- [ ] Class declares no model attribute values; `_default_model`/`_fallback_model`/
  `_lightweight_model` resolve to `None` on a stub subclass
- [ ] `_normalize_model` is identity (no DeprecationWarning ever)
- [ ] `_resolve_model(None)` with no `model` configured raises `ValueError`
- [ ] `tool_format is ToolFormat.OPENAI`
- [ ] Module source contains no `gpt-` literal (test asserts)
- [ ] All tests pass: `pytest tests/clients/test_openai_base.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/openai_base.py`

---

## Test Specification

```python
# tests/clients/test_openai_base.py
import pathlib
import pytest
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.tools.manager import ToolFormat


class _Stub(OpenAIBaseClient):
    """Minimal concrete subclass for instantiation (abstract methods stubbed)."""
    client_type = "stub"
    # stub ask/ask_stream/resume/invoke/get_client as no-ops


def test_no_model_defaults():
    s = _Stub(api_key="k", base_url="http://x/v1")
    assert s._lightweight_model is None
    assert getattr(s, "_default_model", None) is None


def test_normalize_model_identity():
    s = _Stub(api_key="k", base_url="http://x/v1")
    assert s._normalize_model("whatever-model") == "whatever-model"


def test_resolve_model_fails_fast_without_model():
    s = _Stub(api_key="k", base_url="http://x/v1")
    with pytest.raises(ValueError, match="no model configured"):
        s._resolve_model(None)


def test_tool_format_is_openai():
    assert OpenAIBaseClient.tool_format is ToolFormat.OPENAI


def test_module_has_no_gpt_literal():
    src = pathlib.Path("packages/ai-parrot/src/parrot/clients/openai_base.py").read_text()
    assert "gpt-" not in src
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/openai-compatible-clients.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2296-openai-base-skeleton.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-08-21
**Notes**: Created `OpenAIBaseClient(AbstractClient)` in
`packages/ai-parrot/src/parrot/clients/openai_base.py` with `tool_format =
ToolFormat.OPENAI` and no model-default attributes; `__init__` mirrors
gpt.py:100's generic parts (api_key/base_url/base_headers, `model` kwarg
normalization via `_normalize_model`, `timeout` kwarg stored as
`self._timeout` for `get_client()`, default 60). `get_client()` lazily
imports `AsyncOpenAI`. `_resolve_model` fails fast with `ValueError` when
no model resolves. `_is_responses_model` returns `False`. `_with_extra_body`
is a static copy of gpt.py:514's dict-merge. Exported `OpenAIBaseClient`
from `parrot.clients`. Added 9 unit tests in
`tests/clients/test_openai_base.py`, all passing; `ruff check` clean.

One test-only adaptation: the spec's test-spec used a cwd-relative
`pathlib.Path("packages/...")` to scan the module source for a `"gpt-"`
literal. Importing any `parrot.*` module triggers `navconfig`'s settings
bootstrap, which `os.chdir()`s to the MAIN repo checkout (a pre-existing,
documented cross-worktree gotcha — see
`packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py`).
Resolved the path via the imported module's own `__file__` instead so the
test is worktree-correct; behavior/assertion unchanged.

Full `tests/clients/` suite run: 291 passed, 10 pre-existing failures
(Anthropic/Google fallback-model catalog drift, unrelated to this task —
confirmed identical failures with this task's changes `git stash`d).

**Deviations from spec**: none (test path-resolution adaptation only, no
behavior change).
