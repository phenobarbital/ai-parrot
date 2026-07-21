---
type: Wiki Overview
title: 'TASK-1323: `InfographicToolkit` core — envelopes, validation pipeline, render'
id: doc:sdd-tasks-completed-task-1323-infographic-toolkit-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 1 from the spec — the heart of the feature. Implements the
relates_to:
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic_html
  rel: mentions
- concept: mod:parrot.storage.artifacts
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-1323: `InfographicToolkit` core — envelopes, validation pipeline, render

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 1)
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1319, TASK-1321
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Module 1 from the spec — the heart of the feature. Implements the
`InfographicToolkit(AbstractToolkit)` with `return_direct=True` (the
no-summarization lever), the `InfographicRenderResult` envelope consumed
by `PandasAgent.ask` (TASK-1326), the structured
`InfographicValidationError`, and the deterministic guard pipeline:

1. Template existence (`TEMPLATE_UNKNOWN`)
2. Positional block validation (`SLOT_MISSING`, `SLOT_TYPE_MISMATCH`,
   `SLOT_ITEM_COUNT_INVALID`)
3. Extra-blocks check (`EXTRA_BLOCKS`)
4. Data-variable presence + non-emptiness (`DATA_VAR_MISSING`,
   `DATA_VAR_EMPTY`)
5. Theme validity (`THEME_INVALID`)

After validation the toolkit:
- Builds an `InfographicResponse`.
- Renders the deterministic skeleton via
  `InfographicHTMLRenderer.render_to_html(...)`.
- Persists the artifact via `ArtifactStore.save_artifact(...)` with
  `ArtifactType.INFOGRAPHIC` and `definition.html`.
- Calls `ArtifactStore.get_public_url(...)` (from TASK-1321) and returns
  `InfographicRenderResult`.

The toolkit method must be reusable from both the LLM tool-call path and
from a future programmatic caller — keep the validation pipeline as pure
helper functions so it's testable in isolation.

This task **does not implement** the enhance pass (`mode="enhance"`) —
that's TASK-1325. The toolkit accepts the `mode` parameter and routes
`mode="enhance"` through a no-op placeholder hook
(`self._maybe_enhance(...)`) that the TASK-1325 implementer fills in.

---

## Scope

- Create `parrot/tools/infographic_toolkit.py` with:
  - `InfographicRenderResult` Pydantic v2 model.
  - `InfographicValidationError` exception class with structured `code`
    and `detail` attributes.
  - `InfographicToolkit(AbstractToolkit)` class:
    - `return_direct: bool = True`
    - `tool_prefix: Optional[str] = "infographic"`
    - `prefix_separator: str = "_"`
    - `__init__(self, *, artifact_store: ArtifactStore, **kwargs)`
    - `async def render(template_name, theme, mode, blocks, data_variables,
       enhance_brief=None) -> InfographicRenderResult` — exposes as tool
      `infographic_render`.
    - `async def _maybe_enhance(skeleton, brief, data_context) -> Tuple[str, bool]`
      — placeholder returning `(skeleton, False)`; TASK-1325 implements it.
- Validation pipeline as private helpers:
  - `_validate_template(name) -> InfographicTemplate`
  - `_validate_blocks(template, blocks_raw) -> List[InfographicBlock]`
  - `_validate_data_variables(names, repl_locals) -> Dict[str, pd.DataFrame]`
  - `_validate_theme(name) -> Optional[str]`
- Inline-vs-URL output rule (spec §3 Module 4 + §5):
  - When `len(html) < 50_000`: populate `html_inline` AND `html_url`.
  - When `len(html) >= 50_000`: `html_inline=None`, only `html_url`.
- Persistence: build `Artifact` with
  `type=ArtifactType.INFOGRAPHIC`, `creator=ArtifactCreator.AGENT`,
  `definition={"html": <html>, "blocks_envelope": <response.model_dump()>,
  "theme": theme, "template": template_name, "js_bundles":
  <template.js_bundles or []>}`. Document this shape in the module
  docstring — TASK-1322's legacy-fallback path depends on it.
- Logging: INFO on success, INFO on validation failure (rate-able), no
  WARNING for deterministic-mode failures (those are user errors).

**NOT in scope**:
- The three auxiliary tools (`list_templates`, `get_template_contract`,
  `validate_blocks`) — TASK-1324.
- `_maybe_enhance` body + HTML SRI validation — TASK-1325.
- `PandasAgent.ask` post-loop integration — TASK-1326.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | CREATE | Toolkit, envelopes, validation pipeline, render. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py` | CREATE | Validation + render + persistence unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:191 (AbstractToolkit), :32 (ToolkitTool)
# return_direct propagation: line 513.

from parrot.models.infographic import (
    InfographicBlock, InfographicResponse, BlockType, ChartType,
    theme_registry, JSBundle,    # JSBundle added by TASK-1319
)
# verified: packages/ai-parrot/src/parrot/models/infographic.py:634 (InfographicBlock),
# :657 (InfographicResponse), :45 (BlockType), :64 (ChartType), :863 (theme_registry)

from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)
# verified: :21, :47, :471

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
# verified: packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:582
# Sync helper:  html = renderer.render_to_html(response, theme=...)

from parrot.storage.artifacts import ArtifactStore
# verified: packages/ai-parrot/src/parrot/storage/artifacts.py:22

from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
# verified (in use): packages/ai-parrot/src/parrot/handlers/infographic.py:201
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                              # line 191
    return_direct: bool = False                          # line 220 — KEY LEVER
    exclude_tools: tuple[str, ...] = ()                  # line 228
    tool_prefix: Optional[str] = None                    # line 242
    prefix_separator: str = "_"                          # line 244

    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...
    def get_tools(self, ...) -> List[AbstractTool]: ...
    def _generate_tools(self) -> None: ...

class ToolkitTool(AbstractTool):                         # line 32
    # __init__ at line 508 propagates `return_direct=self.return_direct`
    # at line 513. No manual propagation needed in our subclass.
```

```python
# packages/ai-parrot/src/parrot/models/infographic_templates.py
class BlockSpec(BaseModel):                              # line 21
    block_type: BlockType
    required: bool = True
    description: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    constraints: Optional[Dict[str, str]] = Field(default_factory=dict)

class InfographicTemplate(BaseModel):                    # line 47
    name: str
    description: str
    block_specs: List[BlockSpec]
    default_theme: Optional[str] = None
    js_bundles: Optional[List[JSBundle]] = None          # added by TASK-1319

class InfographicTemplateRegistry:                       # line 398
    def get(self, name: str) -> InfographicTemplate: ... # raises KeyError on miss
```

```python
# parrot/models/infographic.py
# InfographicBlock is a Union of 15 block models (line 634).
# Each block has a `type: Literal["..."]` discriminator matching BlockType.value.

class InfographicResponse(BaseModel):                    # line 657
    template: Optional[str]
    theme: Optional[str]
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

```python
# parrot/outputs/formats/infographic_html.py
class InfographicHTMLRenderer(BaseRenderer):             # line 582
    def render_to_html(                                  # line 647 (sync)
        self,
        response,        # InfographicResponse OR raw dict / json
        theme: Optional[str] = None,
        **kwargs,
    ) -> str: ...
```

### Does NOT Exist
- ~~`InfographicToolkit`, `InfographicRenderResult`,
  `InfographicValidationError`~~ — created by this task.
- ~~`BlockSpec.slot_id`~~ — does NOT exist; identification is positional.
- ~~`BlockSpec.position`~~ — does NOT exist; the position is the index in
  `block_specs`.
- ~~`InfographicTemplate.validate(blocks)`~~ — there is no method by that
  name. Build the pipeline yourself.
- ~~`pandas.DataFrame.empty_or_none()`~~ — use `df is None or df.empty`.

---

## Implementation Notes

### Skeleton

```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Tuple
import logging

import pandas as pd
from pydantic import BaseModel, Field

from parrot.tools.toolkit import AbstractToolkit
from parrot.models.infographic import (
    InfographicBlock, InfographicResponse, BlockType, theme_registry,
)
from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator


_INLINE_THRESHOLD = 50_000


class InfographicValidationError(Exception):
    """Structured error from the validation pipeline.

    Stable error codes for client routing:
      TEMPLATE_UNKNOWN, SLOT_MISSING, SLOT_TYPE_MISMATCH,
      SLOT_ITEM_COUNT_INVALID, EXTRA_BLOCKS, DATA_VAR_MISSING,
      DATA_VAR_EMPTY, THEME_INVALID, ENHANCE_OUTPUT_INVALID.
    """
    def __init__(self, code: str, detail: Dict[str, Any]) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class InfographicRenderResult(BaseModel):
    artifact_id: str
    html_url: str
    html_inline: Optional[str] = None
    template_name: str
    theme: Optional[str] = None
    data_variables: List[str] = Field(default_factory=list)
    enhanced: bool = False


class InfographicToolkit(AbstractToolkit):
    return_direct: bool = True
    tool_prefix: Optional[str] = "infographic"
    prefix_separator: str = "_"
    exclude_tools: tuple[str, ...] = ()

    def __init__(self, *, artifact_store: ArtifactStore, **kwargs) -> None:
        super().__init__(**kwargs)
        self._artifact_store = artifact_store
        self._renderer = InfographicHTMLRenderer()
        self.logger = logging.getLogger(__name__)

    async def render(
        self,
        template_name: str,
        theme: Optional[str],
        mode: Literal["deterministic", "enhance"],
        blocks: List[Dict[str, Any]],
        data_variables: List[str],
        enhance_brief: Optional[str] = None,
    ) -> InfographicRenderResult:
        template = self._validate_template(template_name)
        coerced_blocks = self._validate_blocks(template, blocks)
        repl_locals = self._get_repl_locals()
        dataframes = self._validate_data_variables(data_variables, repl_locals)
        validated_theme = self._validate_theme(theme or template.default_theme)

        response = InfographicResponse(
            template=template.name,
            theme=validated_theme,
            blocks=coerced_blocks,
            metadata={"data_variables": data_variables},
        )
        skeleton = self._renderer.render_to_html(response, theme=validated_theme)

        html, enhanced = await self._maybe_enhance(
            skeleton=skeleton,
            brief=enhance_brief,
            mode=mode,
            data_context={name: df.to_dict("records") for name, df in dataframes.items()},
            js_bundles_available=list(template.js_bundles or []),
        )

        artifact_id, html_url = await self._persist(
            html=html, response=response, template=template,
        )
        return InfographicRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template.name,
            theme=validated_theme,
            data_variables=data_variables,
            enhanced=enhanced,
        )

    async def _maybe_enhance(
        self, *, skeleton: str, brief: Optional[str], mode: str,
        data_context: Dict[str, Any], js_bundles_available: List[Any],
    ) -> Tuple[str, bool]:
        """Placeholder. TASK-1325 implements the enhance pass.

        Until then, return the deterministic skeleton unchanged.
        """
        if mode == "enhance":
            self.logger.info(
                "Enhance requested but not yet wired (TASK-1325). "
                "Returning deterministic skeleton.")
        return skeleton, False

    def _validate_template(self, name: str) -> InfographicTemplate:
        try:
            return infographic_registry.get(name)
        except KeyError as exc:
            raise InfographicValidationError(
                "TEMPLATE_UNKNOWN",
                {"template_name": name,
                 "available": infographic_registry.list_templates()},
            ) from exc

    def _validate_blocks(
        self, template: InfographicTemplate, blocks_raw: List[Dict[str, Any]],
    ) -> List[InfographicBlock]:
        specs = template.block_specs
        if len(blocks_raw) > len(specs):
            raise InfographicValidationError(
                "EXTRA_BLOCKS",
                {"expected": len(specs), "got": len(blocks_raw)},
            )
        coerced: List[InfographicBlock] = []
        for idx, spec in enumerate(specs):
            if idx >= len(blocks_raw):
                if spec.required:
                    raise InfographicValidationError(
                        "SLOT_MISSING",
                        {"position": idx,
                         "expected_type": spec.block_type.value},
                    )
                continue
            block_raw = blocks_raw[idx]
            block_type = block_raw.get("type")
            if block_type != spec.block_type.value:
                raise InfographicValidationError(
                    "SLOT_TYPE_MISMATCH",
                    {"position": idx,
                     "expected_type": spec.block_type.value,
                     "got_type": block_type},
                )
            # Count check for list-like blocks (hero_cards, bullets, etc.)
            self._check_item_count(idx, spec, block_raw)
            # Coerce dict -> InfographicBlock via the discriminated union
            block_model = InfographicResponse.model_validate(
                {"blocks": [block_raw]}).blocks[0]
            coerced.append(block_model)
        return coerced

    def _check_item_count(self, idx: int, spec: BlockSpec, block_raw: Dict[str, Any]) -> None:
        if spec.min_items is None and spec.max_items is None:
            return
        # Convention: list blocks expose their items under one of these keys.
        candidates = ("items", "cards", "rows", "series")
        for key in candidates:
            items = block_raw.get(key)
            if isinstance(items, list):
                n = len(items)
                if spec.min_items is not None and n < spec.min_items:
                    raise InfographicValidationError(
                        "SLOT_ITEM_COUNT_INVALID",
                        {"position": idx, "min_items": spec.min_items, "got": n},
                    )
                if spec.max_items is not None and n > spec.max_items:
                    raise InfographicValidationError(
                        "SLOT_ITEM_COUNT_INVALID",
                        {"position": idx, "max_items": spec.max_items, "got": n},
                    )
                return  # only check the first list-like key found

    def _validate_data_variables(
        self, names: List[str], locals_: Dict[str, Any],
    ) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for name in names:
            if name not in locals_:
                raise InfographicValidationError(
                    "DATA_VAR_MISSING", {"name": name})
            df = locals_[name]
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                raise InfographicValidationError(
                    "DATA_VAR_EMPTY",
                    {"name": name, "type": type(df).__name__},
                )
            out[name] = df
        return out

    def _validate_theme(self, name: Optional[str]) -> Optional[str]:
        if name is None:
            return None
        try:
            theme_registry.get(name)
        except KeyError as exc:
            raise InfographicValidationError(
                "THEME_INVALID",
                {"theme_name": name, "available": theme_registry.list_themes()},
            ) from exc
        return name

    def _get_repl_locals(self) -> Dict[str, Any]:
        """Resolve the pandas REPL locals from the bound bot.

        Toolkit instances are attached to a bot; the bot exposes
        `_get_repl_locals()` on PandasAgent. Look up via `self._bot`
        or the standard toolkit-bot binding pattern (mirror what other
        toolkits do — search for `_get_repl_locals` in tools/*).
        """
        bot = getattr(self, "_bot", None)
        if bot is None:
            return {}
        getter = getattr(bot, "_get_repl_locals", None)
        return getter() if callable(getter) else {}

    async def _persist(
        self, *, html: str, response: InfographicResponse,
        template: InfographicTemplate,
    ) -> Tuple[str, str]:
        artifact = Artifact(
            type=ArtifactType.INFOGRAPHIC,
            creator=ArtifactCreator.AGENT,
            definition={
                "html": html,
                "blocks_envelope": response.model_dump(),
                "theme": response.theme,
                "template": template.name,
                "js_bundles": [b.model_dump() for b in (template.js_bundles or [])],
            },
            # other Artifact fields as required by the storage model — read
            # parrot/storage/models.py to fill these in.
        )
        # Note: ArtifactStore.save_artifact signature expects user/agent/session
        # IDs. Toolkit must be supplied those at instantiation OR receive them
        # via the bot binding. Mirror DatasetManager etc.
        bot = getattr(self, "_bot", None)
        user_id, agent_id, session_id = self._resolve_scope(bot)
        await self._artifact_store.save_artifact(
            user_id, agent_id, session_id, artifact)
        html_url = await self._artifact_store.get_public_url(
            user_id, agent_id, session_id, artifact.id, format="html",
        )
        return artifact.id, html_url

    def _resolve_scope(self, bot: Any) -> Tuple[str, str, str]:
        """Pull (user_id, agent_id, session_id) from the bot context.

        See how other toolkits (e.g. DatasetManager) source these values.
        Raise InfographicValidationError if any is missing.
        """
        ...  # implement against the existing bot binding pattern
```

### Key Constraints
- All public methods MUST be async.
- Use `pydantic.BaseModel` v2 — no v1 syntax (`@validator` etc.).
- Catch `KeyError` from registries and re-raise as
  `InfographicValidationError` with stable codes.
- `return_direct=True` means the toolkit IS the final say — every
  validation path must produce a comprehensible error envelope for the
  user.
- Log with `self.logger`, never `print`.
- The `_check_item_count` heuristic looks at `items`, `cards`, `rows`,
  `series` — verify against the actual block models in
  `parrot/models/infographic.py` (HeroCardBlock, BulletListBlock,
  ChartBlock, TableBlock). Adjust the candidate list if a block uses a
  different field name.

---

## Acceptance Criteria

- [ ] `InfographicToolkit.return_direct is True` and a generated
      `ToolkitTool` exposes `tool.return_direct is True`.
- [ ] `render(template_name="does-not-exist", ...)` raises
      `InfographicValidationError(code="TEMPLATE_UNKNOWN")`.
- [ ] Missing required block → `SLOT_MISSING`.
- [ ] Wrong block `type` at a position → `SLOT_TYPE_MISMATCH`.
- [ ] `min_items` / `max_items` violation → `SLOT_ITEM_COUNT_INVALID`.
- [ ] `blocks` longer than `block_specs` → `EXTRA_BLOCKS`.
- [ ] Missing data variable → `DATA_VAR_MISSING`.
- [ ] Empty DataFrame → `DATA_VAR_EMPTY`.
- [ ] Unknown theme → `THEME_INVALID`.
- [ ] Successful render returns `InfographicRenderResult` with
      `enhanced=False`.
- [ ] When `len(html) >= 50_000`, `html_inline is None`; when
      `len(html) < 50_000`, `html_inline` carries the HTML.
- [ ] `ArtifactStore.save_artifact` invoked exactly once per render with
      `ArtifactType.INFOGRAPHIC` and `definition.html` populated.
- [ ] `ArtifactStore.get_public_url` invoked exactly once per render.
- [ ] `pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py -v` passes (~12 tests minimum).
- [ ] `mypy --strict packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` clean.
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py
import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicRenderResult, InfographicValidationError,
)
from parrot.models.infographic import BlockType
from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)


@pytest.fixture
def fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


@pytest.fixture
def hero_cards_template():
    t = InfographicTemplate(
        name="four_cards", description="four hero cards",
        block_specs=[BlockSpec(block_type=BlockType.HERO_CARD,
                               min_items=4, max_items=4)],
    )
    infographic_registry.register(t)
    yield t
    # Cleanup — depends on registry's API; if there's no unregister,
    # leave it (test isolation guaranteed by unique name).


@pytest.fixture
def toolkit(fake_artifact_store):
    tk = InfographicToolkit(artifact_store=fake_artifact_store)
    tk._bot = MagicMock()
    tk._bot._get_repl_locals = MagicMock(return_value={})
    tk._bot.user_id = "u"; tk._bot.agent_id = "agt"; tk._bot.session_id = "sess"
    return tk


class TestReturnDirect:
    def test_class_attr(self):
        assert InfographicToolkit.return_direct is True

    def test_tool_propagates(self, toolkit):
        tools = toolkit.get_tools()
        assert any(getattr(t, "return_direct", False) for t in tools)


class TestValidation:
    async def test_template_unknown(self, toolkit):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name="nope", theme=None, mode="deterministic",
                blocks=[], data_variables=[],
            )
        assert ei.value.code == "TEMPLATE_UNKNOWN"

    async def test_slot_missing(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name, theme=None,
                mode="deterministic", blocks=[], data_variables=[],
            )
        assert ei.value.code == "SLOT_MISSING"

    async def test_slot_type_mismatch(self, toolkit, hero_cards_template):
        with pytest.raises(InfographicValidationError) as ei:
            await toolkit.render(
                template_name=hero_cards_template.name, theme=None,
                mode="deterministic",
                blocks=[{"type": "title", "text": "wrong"}],
                data_variables=[],
            )
        assert ei.value.code == "SLOT_TYPE_MISMATCH"

    async def test_slot_item_count_invalid(self, toolkit, hero_cards_template):

…(truncated)…
