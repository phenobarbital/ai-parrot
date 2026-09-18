# TASK-3427: `AbstractPipeline` — `UNSET`-sentinel constructor, `resolved_backend`, `open_image(enhance=)`

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3426
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**, second half (goals G11, G12, and the "untouched full-resolution image"
decision). `AbstractPipeline.__init__` today hard-defaults `llm_provider="google"`, so a
configuration-level backend could never win over an argument the caller did not even pass. This
task wires the resolver from TASK-3426 into the pipeline base:

- constructor arguments default to the `UNSET` sentinel;
- a keyword-only `config_backend` carries `PlanogramConfig.llm_backend`;
- the outcome is stored on `self.resolved_backend` (later tasks read `.model` at every vision call
  site and record it in the run result);
- `open_image` gains `enhance: bool = True` so the new cycle can load the image **untouched**
  while the legacy adapter path keeps today's brightness/contrast enhancement.

**Deliberate deviation from the spec skeleton's "NO roi_client" note**: `self.roi_client` is
**KEPT** in this task. Every planogram type still calls it; it is deleted by TASK-3432 only after
the type files stop using it, so every intermediate merge stays green (spec revision 0.2).

---

## Scope

- Change `AbstractPipeline.__init__` to the signature in the blueprint; resolve the backend with
  `resolve_backend(...)`; store `self.resolved_backend`.
- When `llm` is `None`, build the client from the **resolved** backend through the existing
  `self._get_llm(provider, model, **kwargs)`; when `llm` is a `"provider:model"` string, do the
  same (today a string `llm` would crash on `.client_name`).
- Keep `self.llm_provider` semantics (lower-cased provider name) and keep `self.roi_client`.
- Add `enhance: bool = True` (keyword-only) to `open_image`.
- Unit tests.

**NOT in scope**: deleting `roi_client` or the `GoogleGenAIClient` import (TASK-3432); changing
`PlanogramCompliance.__init__` / `PlanogramCompliancePipeline.__init__` (they keep passing
`llm_provider="google"` explicitly for now — the run-template task switches `PlanogramCompliance`
to the sentinel and passes `config_backend`); `_get_llm`, `_enhance_image`, `_downscale_image`
bodies; any call site of `open_image`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py` | MODIFY | Sentinel-aware constructor, `resolved_backend`, `open_image(enhance=)` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
# Already at the top of abstract.py (:1-8) — do not duplicate:
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Tuple, Union
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from navconfig.logging import logging
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611
from parrot.clients.factory import LLMFactory

# NEW import for this task — created by TASK-3426 (dependency):
from parrot_pipelines.planogram.backend import UNSET, ResolvedBackend, _Unset, resolve_backend
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py  (172 lines)
class AbstractPipeline(ABC):                                                        # :13-172
    def __init__(self, llm: Any = None, llm_provider: str = "google",
                 llm_model: Optional[str] = None, **kwargs: Any):                   # :16  (single line today)
        self.llm = llm                                                              # :26
        self.llm_provider = None                                                    # :27
        self.logger = logging.getLogger(f"parrot.pipelines.{self.__class__.__name__}")  # :28
        self._json = JSONContent()                                                  # :29
        if not llm:                                                                 # :30
            self.llm_provider = llm_provider.lower()                                # :31
            self.llm = self._get_llm(llm_provider, llm_model, **kwargs)             # :32
        else:                                                                       # :33
            self.llm_provider = llm.client_name.lower()                             # :34
        from parrot.clients.google import GoogleGenAIClient                         # :38  (lazy)  — KEEP
        self.roi_client = GoogleGenAIClient(model="gemini-3-flash-preview", temperature=0.0,
                                            max_retries=2, timeout=20)              # :40          — KEEP

    def _get_llm(self, provider: str, model: Optional[str] = None, **kwargs: Any) -> Any   # :42-71
        # LLMFactory.supported_clients() lookup; unknown provider → ValueError(f"Unsupported LLM provider: {provider}")
        # client = client_class(model=model, **kwargs); sets self.llm_provider = client.client_name.lower()

    def open_image(self, image_path: Union[Path, Image.Image]) -> Image.Image:     # :73-87
        #   :82  img = self._enhance_image(img)      ← the ONLY enhancement call
    def _enhance_image(self, pil_img, brightness: float = 1.10, contrast: float = 1.20)   # :134-144

# Subclasses calling super().__init__ (must keep working UNCHANGED):
#   planogram/plan.py:53      super().__init__(llm=llm, llm_provider=llm_provider, llm_model=llm_model, **kwargs)
#   planogram/legacy.py:1293  super().__init__(llm=llm, llm_provider=llm_provider, llm_model=llm_model, **kwargs)
#   both forward their own default llm_provider="google" explicitly.

# Created by TASK-3426 (dependency) — packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py
class _Unset(Enum): UNSET = "unset"
UNSET = _Unset.UNSET
DEFAULT_LLM_BACKEND: str                       # f"google:{parrot.conf.DEFAULT_LLM_MODEL}"
class ResolvedBackend(BaseModel):
    provider: str
    model: Optional[str]                       # None ⇒ provider default
    origin: Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]
    def as_string(self) -> str: ...
def resolve_backend(llm: Any, llm_provider: Union[str, _Unset], llm_model: Union[str, None, _Unset],
                    config_backend: Optional[str]) -> ResolvedBackend: ...
#   precedence: llm instance → llm string → explicit provider/model over (config | package default)
```

### Does NOT Exist
- ~~`AbstractPipeline.resolved_backend`~~ — added by this task.
- ~~an `enhance` parameter on `open_image`~~ — added by this task; today enhancement is unconditional (`abstract.py:82`).
- ~~`config_backend` being a client-constructor kwarg~~ — it must be consumed by `__init__` and **never** forwarded in `**kwargs` to `_get_llm` (the provider client would reject it).
- ~~support for `llm="provider:model"` strings today~~ — `abstract.py:34` would raise `AttributeError` on `.client_name`; this task adds it.
- ~~a `conftest.py` / fake-LLM fixture usable here~~ — this task does not depend on the shared-conftest task; patch `_get_llm` inline.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline.__init__",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline._get_llm",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline.open_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py#AbstractPipeline._enhance_image"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Historical behaviour preserved**: a caller passing nothing still gets a Google client
  (`resolve_backend` falls to the package default, provider `"google"`). A caller passing
  `llm=<client instance>` still gets `self.llm is <that instance>` and
  `self.llm_provider == llm.client_name.lower()`.
- The client is built with `self._get_llm(resolved.provider, resolved.model, **kwargs)` — reuse the
  existing method, do not call `LLMFactory.create`. `_get_llm` overwrites `self.llm_provider` itself.
- `self.resolved_backend` must be set on **every** path (instance, string, none).
- `config_backend` is keyword-only and popped before `**kwargs` reaches `_get_llm`.
- `roi_client` block (`abstract.py:35-40`) stays byte-identical.
- `open_image(..., enhance=False)` must still convert to RGB; only the `_enhance_image` call is skipped.
- Importing `parrot_pipelines.planogram.backend` from `abstract.py` is cycle-free:
  `parrot_pipelines/planogram/__init__.py` is a lazy `__getattr__` module and `backend.py` imports
  nothing from this package.
- Google-style docstrings, strict type hints, `self.logger` (no `print`).
- Run tests inside the worktree with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
  Never `uv sync` in the worktree.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:45-69` — the main subclass constructor (unchanged here)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then complete
> every `# FILL IN:` marker. Never change a signature, class name or path the blueprint fixes.

### Steps (in order)
1. Add the backend import (block A) — *why*: the sentinel and resolver live in the dependency's module; importing at module scope is cycle-free (see Key Constraints).
2. Replace the constructor head and the client-selection `if/else` (block B), leaving the `roi_client` block untouched — *why*: resolution must happen before the client is built so provider **and** model both come from the resolved backend.
3. Add `enhance` to `open_image` (block C) — *why*: migrated types must perceive, OCR and crop from the untouched image; legacy callers pass nothing and keep enhancement.
4. Write the tests (block D) and run the Validation Command plus the two existing suites named in the Acceptance Criteria — *why*: both subclasses forward `llm_provider="google"` explicitly and must not notice the change.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py` (MODIFY) — block A: import
```python
# occurrences: 1 (verified: grep -c '^from parrot.clients.factory import LLMFactory$' abstract.py)
# AFTER — insert below `from parrot.clients.factory import LLMFactory` (verified: abstract.py:8)
from parrot_pipelines.planogram.backend import UNSET, ResolvedBackend, _Unset, resolve_backend
```
**Why**: `_Unset` is needed only for the type annotations of the new signature.

### `abstract.py` (MODIFY) — block B: constructor
```python
# occurrences: 1 (verified: grep -c 'llm_provider: str = "google",' abstract.py)  → the `def __init__` line, abstract.py:16
# REPLACE the `def __init__(...)` line (abstract.py:16) WITH:
    def __init__(
        self,
        llm: Any = None,
        llm_provider: Union[str, _Unset] = UNSET,
        llm_model: Union[str, None, _Unset] = UNSET,
        *,
        config_backend: Optional[str] = None,
        **kwargs: Any,
    ):
# and rewrite its docstring (abstract.py:17-25) in Google style documenting llm (instance or
# "provider:model" string), llm_provider, llm_model, config_backend and the precedence order.

# occurrences: 1 (verified: grep -c 'self.llm_provider = None' abstract.py)
# REPLACE the block abstract.py:30-34:
#         if not llm:
#             self.llm_provider = llm_provider.lower()
#             self.llm = self._get_llm(llm_provider, llm_model, **kwargs)
#         else:
#             self.llm_provider = llm.client_name.lower()
# WITH:
        self.resolved_backend: ResolvedBackend = resolve_backend(llm, llm_provider, llm_model, config_backend)
        if llm is None or isinstance(llm, str):
            # No client instance given: build it from the resolved backend (FEAT-574).
            self.llm = self._get_llm(self.resolved_backend.provider, self.resolved_backend.model, **kwargs)
        else:
            self.llm_provider = llm.client_name.lower()
        self.logger.debug("Resolved LLM backend: %s (%s)", self.resolved_backend.as_string(),
                          self.resolved_backend.origin)
# DO NOT touch abstract.py:35-40 (the lazy GoogleGenAIClient import and self.roi_client) — TASK-3432 owns that.
```
**Why this shape**: the signature is fixed by the spec Module 5 skeleton. `config_backend` is declared as a
named keyword-only parameter, so it can never leak into `**kwargs` → `_get_llm` → the provider client.
`_get_llm` already sets `self.llm_provider` from the built client (`abstract.py:70`); keep
`self.llm_provider = None` at `:27` as the initial value. `if not llm` becomes `llm is None or isinstance(llm, str)`
because a `"provider:model"` string is truthy but is not a client.

### `abstract.py` (MODIFY) — block C: `open_image`
```python
# occurrences: 1 (verified: grep -c 'def open_image(self, image_path: Union\[Path, Image.Image\]) -> Image.Image:' abstract.py)
# REPLACE that line (abstract.py:73) and its one-line docstring WITH:
    def open_image(self, image_path: Union[Path, Image.Image], *, enhance: bool = True) -> Image.Image:
        """Open an image from a file path (or pass a PIL image through) as RGB.

        Args:
            image_path: Path/str to an image file, or an already opened PIL image.
            enhance: When True (default, legacy behaviour) apply ``_enhance_image``
                (brightness/contrast). The FEAT-574 cycle passes False so perception, OCR and
                LLM crops use the untouched full-resolution image.

        Returns:
            The RGB image.
        """
# occurrences: 1 (verified: grep -c 'img = self._enhance_image(img)' abstract.py)
# REPLACE `            img = self._enhance_image(img)` (abstract.py:82) WITH:
            if enhance:
                img = self._enhance_image(img)
```
**Why**: `enhance` is keyword-only with default `True`, so all three existing call sites in the package keep
their behaviour without edits.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py` (CREATE) — block D
```python
"""AbstractPipeline backend resolution and open_image(enhance=) (FEAT-574, spec Module 5)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from parrot_pipelines.abstract import AbstractPipeline
from parrot_pipelines.planogram.backend import UNSET


class _Pipe(AbstractPipeline):
    """Minimal concrete pipeline."""

    async def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}


@pytest.fixture(autouse=True)
def _no_google_client():
    """roi_client is still built in __init__ (kept until TASK-3432): stub the class so no SDK/credentials are needed."""
    with patch("parrot.clients.google.GoogleGenAIClient", MagicMock()):
        yield


def _build(**kwargs: Any):
    """Construct _Pipe with _get_llm patched; returns (pipe, get_llm_mock)."""
    fake = SimpleNamespace(client_name="Fake", model=None)
    with patch.object(_Pipe, "_get_llm", return_value=fake) as get_llm:
        return _Pipe(**kwargs), get_llm

# FILL IN: test bodies per the Test Specification below.
#          If patching "parrot.clients.google.GoogleGenAIClient" does not intercept the lazy import at
#          abstract.py:38, patch the attribute on the imported module object instead — bounded by
#          "tests must run offline with no credentials".
```
**Why**: `_get_llm` is patched because it instantiates a real provider client; asserting on its call args is
exactly the contract ("client built from the resolved backend").

### FILL IN checklist
- [ ] `abstract.py::__init__` docstring — Google style, precedence order spelled out
- [ ] `test_pipeline_base.py` — six test bodies; bounded by the Test Specification
- [ ] `test_pipeline_base.py::_no_google_client` — confirm the patch target intercepts the lazy import

---

## Acceptance Criteria

- [ ] `_Pipe()` (nothing passed) → `_get_llm` called with provider `"google"`; `resolved_backend.origin == "package_default"`.
- [ ] `_Pipe(config_backend="anthropic:claude-sonnet-5")` → `_get_llm("anthropic", "claude-sonnet-5")`; origin `"config"` — the omitted `llm_provider` does **not** mask the config.
- [ ] `_Pipe(llm_provider="google", config_backend="anthropic:claude-sonnet-5")` → `_get_llm("google", None)` (provider switch never inherits the other provider's model).
- [ ] `_Pipe(llm="anthropic:claude-sonnet-5")` builds the client from the string (no `AttributeError`).
- [ ] `_Pipe(llm=<instance>)` keeps `pipe.llm is instance`, never calls `_get_llm`, sets `llm_provider` from `client_name`, origin `"llm_instance"`.
- [ ] `config_backend` never appears in the kwargs passed to `_get_llm`; other `**kwargs` still do.
- [ ] `pipe.roi_client` still exists.
- [ ] `open_image(img)` calls `_enhance_image` once; `open_image(img, enhance=False)` does not, and still returns RGB for a non-RGB input.
- [ ] Existing suites unaffected: `pytest packages/ai-parrot-pipelines/tests/test_planogram_types.py -q` and `pytest tests/pipelines/test_product_counter.py -q`
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py -q`
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/abstract.py` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pipeline_base.py -q`

---

## Test Specification

```python
def test_default_backend_is_google(): ...
def test_config_backend_wins_over_omitted_arguments(): ...
def test_explicit_provider_switch_does_not_inherit_model(): ...
def test_llm_string_builds_client(): ...
def test_llm_instance_is_kept_and_provider_read_from_client_name(): ...
def test_config_backend_not_forwarded_but_other_kwargs_are():
    """_Pipe(config_backend="google:x", temperature=0.0) → _get_llm kwargs == {"temperature": 0.0}."""
def test_open_image_enhance_flag():
    """patch.object(_Pipe, "_enhance_image", side_effect=lambda i: i); enhance default → 1 call;
    enhance=False → 0 calls; Image.new("L", (4, 4)) comes back with mode "RGB"."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 "Backend selection", §3 Module 5) and the revision-history note 0.2 (roi_client kept here)
2. **Check dependencies** — TASK-3426 must be merged (`parrot_pipelines/planogram/backend.py` exists)
3. **Verify the Codebase Contract** — re-grep anchors and occurrence counts; confirm `backend.py` exports `UNSET, ResolvedBackend, _Unset, resolve_backend`
4. **Implement** from the blueprint; complete every `# FILL IN:`
5. **Verify** all acceptance criteria, including the two existing suites
6. Commit only the two files listed above; never touch `sdd/`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
