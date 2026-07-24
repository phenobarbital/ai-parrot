"""InfographicToolkit — Frozen multi-dataset HTML infographic artifacts (FEAT-197).

This toolkit exposes four tools to the LLM:

    infographic_render            — Validate + render + persist.
    infographic_list_templates    — Discover available templates.
    infographic_get_template_contract — Fetch a template's positional contract.
    infographic_validate_blocks   — Dry-run block validation (no persistence).

With ``return_direct=True`` the toolkit bypasses LLM re-summarisation: the
result of ``infographic_render`` is the final agent output, consumed by
``PandasAgent.ask()``'s post-loop branch (TASK-1326).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple, TYPE_CHECKING

import pandas as pd
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from parrot.auth.permission import build_principal_context
from parrot.tools.toolkit import AbstractToolkit
from parrot.template.engine import TemplateEngine
from parrot.models.infographic import (
    InfographicBlock,
    InfographicResponse,
    theme_registry,
    JSBundle,
)
from parrot.models.infographic_templates import (
    BlockSpec,
    InfographicTemplate,
    infographic_registry,
)
from parrot.outputs.formats import get_infographic_html_renderer
from parrot.models.outputs import OutputMode
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.artifact_signing import build_public_html_url
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore, RecipeNotFoundError
from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot.tools.infographic_recipes.freeze import (
    FreezeProvenanceError,
    FreezeValidationError,
    freeze_session_envelope,
)
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

if TYPE_CHECKING:
    from parrot.tools.infographic_sections import SectionDescriptor

#: Recipe tool method names (Module 6, FEAT-324) — excluded from tool
#: generation when no recipe store is configured on this toolkit instance.
_RECIPE_TOOL_NAMES: Tuple[str, ...] = (
    "infographic_save_recipe",
    "infographic_list_recipes",
    "infographic_run_recipe",
    "infographic_get_recipe_contract",
)

#: Per-task holder for the invoker's ``PermissionContext``, set by
#: ``InfographicToolkit._pre_execute`` (mirrors ``DatasetManager``'s own
#: ``_pctx_var`` in ``parrot.auth.context``, which is per-toolkit rather than
#: shared globally — using a dedicated ContextVar here, rather than an
#: instance attribute, ensures concurrent requests on a shared toolkit
#: instance cannot bleed each other's context across an await boundary,
#: exactly like DatasetManager's own doc rationale for the same pattern).
#: Consumed by ``infographic_run_recipe`` so recipe replay honors the SAME
#: PBAC/data-plane guards a live chat call would (spec G8).
_infographic_pctx_var: "contextvars.ContextVar[Any | None]" = contextvars.ContextVar(
    "infographic_toolkit_pctx", default=None
)


# ---------------------------------------------------------------------------
# Threshold for inline HTML (< 50 KB → populate html_inline)
# ---------------------------------------------------------------------------

_INLINE_THRESHOLD: int = 50_000

# Maximum number of DataFrame rows serialised into the LLM enhance context.
# Larger DataFrames are truncated with a warning to avoid excessive token usage.
MAX_ENHANCE_ROWS: int = 50


def _json_safe_default(obj: Any) -> Any:
    """``json.dumps`` ``default`` hook coercing numpy/pandas values (FEAT-326).

    Used by the data-splice render mode. numpy integer/boolean scalars and
    arrays, and objects exposing ``isoformat`` (pandas ``Timestamp``,
    ``datetime``), are coerced to native JSON types. Anything else raises
    ``TypeError`` so ``json.dumps`` fails loudly rather than emitting invalid
    JSON. (numpy floats subclass ``float``, so NaN/Infinity are caught by
    ``allow_nan=False`` before this hook is reached.)

    Args:
        obj: The value ``json`` could not serialise natively.

    Returns:
        A JSON-native representation of ``obj``.

    Raises:
        TypeError: When ``obj`` cannot be safely coerced.
    """
    import numpy as np

    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    isoformat = getattr(obj, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


# ---------------------------------------------------------------------------
# Structured error class
# ---------------------------------------------------------------------------

class InfographicValidationError(Exception):
    """Structured error raised by the validation pipeline.

    All errors carry a stable ``code`` (for client routing) and a ``detail``
    dict (for structured logging and user display).

    Valid codes::

        TEMPLATE_UNKNOWN
        SLOT_MISSING
        SLOT_TYPE_MISMATCH
        SLOT_ITEM_COUNT_INVALID
        EXTRA_BLOCKS
        DATA_VAR_MISSING
        DATA_VAR_EMPTY
        THEME_INVALID
        ENHANCE_OUTPUT_INVALID
        TEMPLATE_ENGINE_UNSET    # render_template: no templates configured
        TEMPLATE_RENDER_ERROR    # render_template: Jinja render failure
    """

    def __init__(self, code: str, detail: Dict[str, Any]) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------

class InfographicRenderResult(BaseModel):
    """Envelope returned by InfographicToolkit.render (return_direct=True).

    Consumed by ``PandasAgent.ask()``'s post-loop branch via isinstance check.
    """

    artifact_id: str
    html_url: str
    html_inline: Optional[str] = None   # None when len(html) >= _INLINE_THRESHOLD
    template_name: str
    theme: Optional[str] = None
    data_variables: List[str] = Field(default_factory=list)
    enhanced: bool = False
    a2ui_envelope: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------

class InfographicToolkit(AbstractToolkit):
    """Toolkit that produces frozen, multi-dataset HTML infographic artifacts.

    Usage::

        toolkit = InfographicToolkit(artifact_store=store)
        tools = toolkit.get_tools()
        # Attach to a PandasAgent before calling ask().
        toolkit._bot = pandas_agent

    Tools exposed (prefixed with ``infographic_``)::

        infographic_render            — typed blocks + pandas (PandasAgent).
        infographic_render_template   — trusted HTML+Jinja template + data (ANY agent).
        infographic_list_templates
        infographic_get_template_contract
        infographic_validate_blocks

    Recipe tools (Module 6, FEAT-324 — spec G2/G6) are exposed ONLY when
    ``recipe_store`` is configured at construction time; otherwise they are
    absent from ``get_tools()`` entirely (see ``exclude_tools``)::

        infographic_save_recipe        — freeze the current session envelope
        infographic_list_recipes       — lightweight recipe summaries
        infographic_run_recipe         — deterministic replay (no LLM)
        infographic_get_recipe_contract — datasets/columns/params a recipe needs
    """

    return_direct: bool = True          # bypass LLM re-summarisation
    tool_prefix: Optional[str] = "infographic"
    prefix_separator: str = "_"
    exclude_tools: Tuple[str, ...] = ()

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        template_dirs: Optional[Any] = None,
        templates: Optional[Dict[str, str]] = None,
        emit_a2ui: bool = False,
        recipe_store: Optional[AbstractRecipeStore] = None,
        recipe_runner: Optional[RecipeRunner] = None,
        dataset_manager: Optional[Any] = None,
        **kwargs,
    ) -> None:
        """Initialise the toolkit.

        Args:
            artifact_store: Initialised ``ArtifactStore`` instance.
            template_dirs: Optional directory (or list of directories) of trusted
                HTML+Jinja templates consumed by ``render_template``. Passed
                straight to :class:`~parrot.template.engine.TemplateEngine`.
            templates: Optional mapping of ``{name: source}`` in-memory HTML+Jinja
                templates for ``render_template`` (registered via the engine's
                ``DictLoader``). Combine with ``template_dirs`` or use alone.
            emit_a2ui: When True, the render tools additionally produce a validated
                A2UI ``CreateSurface`` envelope (FEAT-273 Module 11, D1a lane).
            recipe_store: Optional ``AbstractRecipeStore`` (FEAT-324, Module 4/6).
                When provided, the four recipe tools (``infographic_save_recipe``,
                ``infographic_list_recipes``, ``infographic_run_recipe``,
                ``infographic_get_recipe_contract``) are exposed; otherwise they
                are excluded from ``get_tools()`` entirely.
            recipe_runner: Optional pre-built ``RecipeRunner``. Takes precedence
                over ``dataset_manager`` (below) if both are given.
            dataset_manager: Optional ``DatasetManager`` used to build a
                ``RecipeRunner`` when ``recipe_runner`` is not supplied directly
                (a ``RecipeRunner`` needs both a store and a dataset manager —
                see ``parrot.tools.infographic_recipes.runner.RecipeRunner``).
            **kwargs: Forwarded to ``AbstractToolkit.__init__``.
        """
        super().__init__(**kwargs)
        self._artifact_store = artifact_store
        self._emit_a2ui = emit_a2ui
        self._renderer = get_infographic_html_renderer()()
        self.logger = logging.getLogger(__name__)
        # Ensure the class-level return_direct=True is set as an instance
        # attribute so AbstractToolkit._generate_tool can read it correctly.
        self.return_direct = True  # explicit — do not let kwargs override this
        # Template-driven rendering (usable by ANY agent, not just PandasAgent):
        # a trusted Jinja engine built lazily from developer-supplied templates.
        self._template_engine: Optional[TemplateEngine] = None
        if template_dirs is not None or templates:
            self._template_engine = TemplateEngine(template_dirs=template_dirs)
            if templates:
                self._template_engine.add_templates(templates)

        # Recipe subsystem (FEAT-324, Module 6) — optional; the four recipe
        # tools are excluded from get_tools() entirely when no store is given.
        self._recipe_store = recipe_store
        if recipe_runner is not None:
            self._recipe_runner = recipe_runner
        elif recipe_store is not None and dataset_manager is not None:
            self._recipe_runner = RecipeRunner(
                recipe_store, dataset_manager, artifact_store=artifact_store
            )
        else:
            self._recipe_runner = None
        if self._recipe_store is None:
            self.exclude_tools = (*self.exclude_tools, *_RECIPE_TOOL_NAMES)
        # Per-task token bookkeeping for _infographic_pctx_var (see module
        # docstring comment above the ContextVar definition).
        self._recipe_pctx_tokens: Dict[int, Any] = {}

    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:
        """Capture the invoker's ``PermissionContext`` for recipe-replay tools.

        ``ToolkitTool._execute`` always injects ``_permission_context`` into
        ``kwargs`` (even when ``None``) before calling this hook — see
        ``AbstractToolkit._pre_execute``'s docstring and
        ``parrot.tools.dataset_manager.tool.DatasetManager._pre_execute`` for
        the precedent this mirrors. Stashing it in a ContextVar (rather than
        an instance attribute) keeps concurrent calls on a shared toolkit
        instance from bleeding each other's context (same rationale
        DatasetManager documents for its own ``_pctx_var``).

        Args:
            tool_name: Name of the tool about to execute.
            **kwargs: Tool arguments, including the injected
                ``_permission_context``.
        """
        pctx = kwargs.get("_permission_context")
        token = _infographic_pctx_var.set(pctx)
        task = asyncio.current_task()
        if task is not None:
            self._recipe_pctx_tokens[id(task)] = token

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any:
        """Reset the ``_infographic_pctx_var`` token set by :meth:`_pre_execute`."""
        task = asyncio.current_task()
        if task is not None:
            token = self._recipe_pctx_tokens.pop(id(task), None)
            if token is not None:
                _infographic_pctx_var.reset(token)
        return result

    @staticmethod
    def _current_recipe_pctx(user_id: str) -> Any:
        """Return the invoker's ``PermissionContext`` for recipe replay (spec G8).

        Prefers the REAL ``PermissionContext`` captured by :meth:`_pre_execute`
        (from the toolkit-dispatch-injected ``_permission_context``); falls
        back to a minimal principal-only context built from the resolved
        ``user_id`` when no dispatch-time context is available (e.g. a
        direct method call outside the toolkit dispatch path). NEVER returns
        ``None`` — a falsy ``pctx`` makes ``DatasetManager``'s PBAC guards
        fail OPEN rather than closed.
        """
        pctx = _infographic_pctx_var.get()
        if pctx is not None:
            return pctx
        return build_principal_context(user_id, channel="chat")

    def add_template(self, name: str, source: str) -> None:
        """Register a trusted in-memory HTML+Jinja template for ``render_template``.

        Sync helper (not exposed as an LLM tool). Lets an agent register
        templates after construction. Templates are trusted — never pass
        untrusted/LLM-authored Jinja source here (no sandbox is applied).

        Args:
            name: Template name referenced by ``render_template(template_name=...)``.
            source: HTML+Jinja template source.
        """
        if self._template_engine is None:
            self._template_engine = TemplateEngine()
        self._template_engine.add_templates({name: source})

    def get_tools(self, **kwargs):
        """Return the generated tools, ensuring return_direct is propagated."""
        tools = super().get_tools(**kwargs)
        # AbstractTool's __init__ swallows return_direct into _init_kwargs
        # without setting the instance attribute; patch it explicitly.
        for tool in tools:
            # build_block is non-terminal: the LLM keeps appending blocks and
            # then calls infographic_render. It must NOT short-circuit the loop.
            if getattr(tool, "name", "").endswith("build_block"):
                tool.return_direct = False
                continue
            if not getattr(tool, "return_direct", False):
                tool.return_direct = True
        return tools

    def set_bot(self, bot: Any) -> None:
        """Bind this toolkit to a bot instance for enhance-mode support.

        Binding also teaches the bot how to drive the infographic tools: the
        ``INFOGRAPHIC_SYSTEM_PROMPT_ADDON`` guidance is appended to the bot's
        ``system_prompt_template`` so any agent that registers this toolkit can
        produce infographics ad-hoc — no per-report skill required. Call this
        during the agent's ``configure()`` (before ``super().configure()`` runs
        ``_define_prompt()``) so the guidance lands in the finalised prompt.

        Args:
            bot: Bot instance that must implement
                ``_get_repl_locals() -> Dict[str, Any]`` and optionally
                ``enhance_infographic(...)``.  The bot is stored as
                ``self._bot`` and accessed by ``_maybe_enhance`` and
                ``_get_repl_locals``.
        """
        self._bot = bot
        self._inject_prompt_guidance(bot)

    @staticmethod
    def _inject_prompt_guidance(bot: Any) -> None:
        """Append the infographic usage guide to the bot's system prompt.

        Idempotent: a sentinel header guards against double-injection when a
        toolkit is rebound. No-op when the bot exposes no string
        ``system_prompt_template``.
        """
        tmpl = getattr(bot, "system_prompt_template", None)
        if not isinstance(tmpl, str):
            return
        # Lazy import avoids a tools→bots import cycle at module load.
        from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON  # noqa: PLC0415
        if "## Infographic Generation Mode" in tmpl:
            return  # already injected
        bot.system_prompt_template = f"{tmpl}\n{INFOGRAPHIC_SYSTEM_PROMPT_ADDON}"

    # ------------------------------------------------------------------
    # Public tool methods
    # ------------------------------------------------------------------

    async def render(
        self,
        template_name: str,
        theme: Optional[str],
        mode: Literal["deterministic", "enhance"],
        data_variables: List[str],
        blocks: Optional[List[Dict[str, Any]]] = None,
        blocks_variable: Optional[str] = None,
        enhance_brief: Optional[str] = None,
    ) -> InfographicRenderResult:
        """Validate, render, and persist an infographic artifact.

        This is the **primary** tool.  The LLM calls it as the last tool in
        the turn after computing all required DataFrames.

        The result (``InfographicRenderResult``) is returned *verbatim* to
        the caller — do NOT summarise it.

        Args:
            template_name: Template identifier from ``infographic_list_templates``.
            theme: Theme name (e.g. ``"dark"``, ``"light"``).  Pass ``null``
                to use the template's ``default_theme``.
            mode: ``"deterministic"`` for skeleton-only; ``"enhance"`` for
                optional JS interactivity (requires ``enhance_brief``).
            data_variables: Names of DataFrames in the pandas REPL locals
                that provide the underlying data for this infographic.
            blocks_variable: **Preferred.** Name of a Python variable in the
                pandas REPL that holds the block list (e.g. ``"fp_blocks"``
                built by a skill's ``compute.py``).  The toolkit reads the
                blocks straight from the REPL namespace, so you never have to
                copy a large JSON payload into the tool call.  Takes
                precedence over ``blocks`` when both are given.
            blocks: List of block dicts matching the template's positional
                contract.  Use ``infographic_get_template_contract`` to see
                the expected types and counts.  Prefer ``blocks_variable``
                for anything but a tiny, hand-written block list.
            enhance_brief: Brief description of the desired interactivity
                (required when ``mode == "enhance"``; ignored otherwise).

        Returns:
            ``InfographicRenderResult`` with ``artifact_id``, ``html_url``,
            optional ``html_inline``, and provenance fields.

        Raises:
            InfographicValidationError: When any validation check fails.
                The ``code`` and ``detail`` fields identify the problem.
        """
        # --- Validation pipeline ---
        template = self._validate_template(template_name)
        resolved_blocks = self._resolve_blocks(blocks, blocks_variable)
        coerced_blocks = self._validate_blocks(template, resolved_blocks)
        repl_locals = self._get_repl_locals()
        self._validate_data_variables(data_variables, repl_locals)
        validated_theme = self._validate_theme(theme or template.default_theme)

        # --- Build InfographicResponse ---
        infographic_response = InfographicResponse(
            template=template.name,
            theme=validated_theme,
            blocks=coerced_blocks,
            metadata={"data_variables": data_variables},
        )

        # --- Deterministic skeleton ---
        skeleton = self._renderer.render_to_html(infographic_response, theme=validated_theme)

        # --- Optional enhance pass (TASK-1325 wires this) ---
        # Build data_context, truncating large DataFrames to avoid token bloat.
        data_context: Dict[str, Any] = {}
        for name in data_variables:
            if name in repl_locals and isinstance(repl_locals[name], pd.DataFrame):
                df = repl_locals[name]
                if len(df) > MAX_ENHANCE_ROWS:
                    self.logger.warning(
                        "DataFrame '%s' truncated from %d to %d rows for LLM context",
                        name, len(df), MAX_ENHANCE_ROWS,
                    )
                    df = df.head(MAX_ENHANCE_ROWS)
                data_context[name] = df.to_dict("records")

        html, enhanced = await self._maybe_enhance(
            skeleton=skeleton,
            brief=enhance_brief,
            mode=mode,
            data_context=data_context,
            js_bundles_available=list(template.js_bundles or []),
        )

        # --- Persist ---
        artifact_id, html_url = await self._persist(
            html=html,
            response=infographic_response,
            template=template,
        )

        self.logger.info(
            "Rendered infographic: template=%s theme=%s enhanced=%s size=%d bytes",
            template.name, validated_theme, enhanced, len(html),
        )

        a2ui_envelope = None
        if self._emit_a2ui:
            a2ui_envelope = self._build_a2ui_envelope(
                coerced_blocks, template.name, validated_theme, artifact_id,
            )

        return InfographicRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template.name,
            theme=validated_theme,
            data_variables=data_variables,
            enhanced=enhanced,
            a2ui_envelope=a2ui_envelope,
        )

    async def render_template(
        self,
        template_name: str,
        data: Optional[Dict[str, Any]] = None,
        theme: Optional[str] = None,
        title: Optional[str] = None,
    ) -> InfographicRenderResult:
        """Render a pre-registered HTML+Jinja template into an infographic artifact.

        Use this when you already have the answer *data* (a dict, or the text/JSON
        produced by a previous step) plus a named HTML+Jinja template registered
        on this toolkit. Unlike ``infographic_render`` (typed blocks computed from
        DataFrames in a pandas REPL), this path fills a trusted template directly,
        so it works for **any** agent — no pandas namespace required.

        Call it as the LAST tool in the turn. The result is returned *verbatim* —
        do NOT summarise it or paste the HTML/envelope into your answer.

        Args:
            template_name: Name of a template registered via ``template_dirs``,
                ``templates=`` or ``add_template()``.
            data: Authoritative, JSON-serialisable payload exposed to the template
                as ``data`` (e.g. ``{{ data.title }}``). This is the reliable
                channel — prefer it over the best-effort ``message`` context.
            theme: Optional theme name, exposed as ``theme`` and stored on the
                artifact definition.
            title: Optional artifact title (defaults to ``Infographic — <name>``).

        Returns:
            ``InfographicRenderResult`` with ``artifact_id``, ``html_url`` and
            optional ``html_inline`` (populated only when the HTML is < 50 KB).

        Raises:
            InfographicValidationError: ``TEMPLATE_ENGINE_UNSET`` when no template
                source is configured; ``TEMPLATE_UNKNOWN`` when ``template_name``
                is not found; ``TEMPLATE_RENDER_ERROR`` on any Jinja error (e.g. a
                missing variable under ``StrictUndefined``).
        """
        if self._template_engine is None:
            raise InfographicValidationError(
                "TEMPLATE_ENGINE_UNSET",
                {
                    "detail": (
                        "No HTML+Jinja templates are configured. Pass "
                        "template_dirs= or templates= to InfographicToolkit, or "
                        "call add_template() before rendering."
                    ),
                },
            )

        # Resolve the template first so an unknown name is reported distinctly
        # (``TemplateEngine.render`` wraps a missing template into a generic
        # RuntimeError, collapsing it with genuine render errors).
        try:
            self._template_engine.get_template(template_name)
        except FileNotFoundError as exc:
            raise InfographicValidationError(
                "TEMPLATE_UNKNOWN",
                {"template_name": template_name},
            ) from exc
        except Exception:  # noqa: BLE001 — surfaces below as TEMPLATE_RENDER_ERROR
            pass

        context = self._build_template_context(data, theme, title)
        try:
            html = await self._template_engine.render(template_name, context)
        except (ValueError, RuntimeError) as exc:
            raise InfographicValidationError(
                "TEMPLATE_RENDER_ERROR",
                {"template_name": template_name, "error": str(exc)},
            ) from exc

        artifact_id, html_url = await self._persist_template(
            html=html,
            template_name=template_name,
            theme=theme,
            title=title,
        )

        self.logger.info(
            "Rendered template infographic: template=%s theme=%s size=%d bytes",
            template_name, theme, len(html),
        )

        a2ui_envelope = None
        if self._emit_a2ui:
            sections = [{"heading": title or template_name}]
            if data:
                sections[0]["text"] = str(list(data.keys()))
            a2ui_envelope = self._build_a2ui_envelope(
                [], template_name, theme, artifact_id, title=title,
                extra_sections=sections,
            )

        return InfographicRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template_name,
            theme=theme,
            data_variables=[],
            enhanced=False,
            a2ui_envelope=a2ui_envelope,
        )

    async def render_data_template(
        self,
        template_name: str,
        payload: Dict[str, Any],
        descriptor: Optional["SectionDescriptor"] = None,
        marker_id: str = "report-data",
        title: Optional[str] = None,
    ) -> InfographicRenderResult:
        """Render a self-contained HTML template by *splicing* a JSON payload.

        Unlike ``infographic_render_template`` (Jinja), this **data-splice** mode
        targets a self-contained HTML dashboard whose client-side JS reads its
        data from a ``<script type="application/json" id="...">`` marker tag
        (FEAT-326, generalizing the standalone budget-variance report script).
        The registered template source is loaded **raw** (never Jinja-rendered),
        the ``payload`` is JSON-serialised and injected between the marker's
        open/close tags, and the result is otherwise byte-identical to the
        template. The artifact is persisted exactly like ``render_template``.

        Call it as the LAST tool in the turn. The result is returned *verbatim* —
        do NOT summarise it or paste the HTML/envelope into your answer.

        Args:
            template_name: Name of a template registered via ``template_dirs``,
                ``templates=`` or ``add_template()``.
            payload: JSON-serialisable data injected into the marker script tag.
                numpy/pandas scalars are coerced; ``NaN``/``Infinity`` are
                rejected loudly (they would otherwise produce invalid JSON).
            descriptor: Optional :class:`SectionDescriptor`. When supplied, its
                payload-shape validation gate runs BEFORE any splice/persist, and
                its ``splice_marker_id`` overrides ``marker_id``.
            marker_id: HTML ``id`` of the ``<script type="application/json">``
                marker. Ignored when ``descriptor`` is supplied.
            title: Optional artifact title (defaults to ``Infographic — <name>``).

        Returns:
            ``InfographicRenderResult`` with ``artifact_id``, ``html_url`` and
            optional ``html_inline`` (populated only when the HTML is small).

        Raises:
            InfographicValidationError: ``TEMPLATE_ENGINE_UNSET`` when no template
                source is configured; ``TEMPLATE_UNKNOWN`` when ``template_name``
                is not found; ``SPLICE_MARKER_MISSING`` when the marker (or its
                closing tag) is absent; ``PAYLOAD_NOT_SERIALIZABLE`` when the
                payload contains ``NaN``/``Infinity`` or a non-coercible value;
                ``payload_shape_mismatch`` when a supplied descriptor's gate fails.
        """
        if self._template_engine is None:
            raise InfographicValidationError(
                "TEMPLATE_ENGINE_UNSET",
                {
                    "detail": (
                        "No HTML templates are configured. Pass template_dirs= "
                        "or templates= to InfographicToolkit, or call "
                        "add_template() before rendering."
                    ),
                },
            )

        # Descriptor gate runs FIRST — never splice/persist an invalid payload.
        effective_marker = marker_id
        if descriptor is not None:
            from parrot.tools.infographic_sections import validate_payload_shape

            validate_payload_shape(descriptor, payload)
            effective_marker = descriptor.splice_marker_id

        # Load the RAW template source (data-splice must NOT Jinja-render it).
        try:
            source, _, _ = self._template_engine.env.loader.get_source(
                self._template_engine.env, template_name
            )
        except Exception as exc:  # noqa: BLE001 — TemplateNotFound and friends
            raise InfographicValidationError(
                "TEMPLATE_UNKNOWN",
                {"template_name": template_name},
            ) from exc

        # Serialise safely: coerce numpy/pandas, reject NaN/Infinity loudly.
        try:
            payload_json = json.dumps(
                payload, allow_nan=False, default=_json_safe_default
            )
        except (ValueError, TypeError) as exc:
            raise InfographicValidationError(
                "PAYLOAD_NOT_SERIALIZABLE",
                {"error": str(exc)},
            ) from exc

        # Neutralise HTML-significant characters before embedding the JSON in a
        # <script> tag. ``json.dumps`` does NOT escape ``<``/``>``/``&``, so a
        # payload string containing ``</script>`` would otherwise break out of
        # the marker element and execute following markup in the browser. The
        # ``\uXXXX`` forms are valid JSON and decode back to the original
        # characters client-side (same mitigation as knowledge/graphindex).
        payload_json = (
            payload_json.replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )

        html = self._splice_payload(source, payload_json, effective_marker)

        artifact_id, html_url = await self._persist_template(
            html=html,
            template_name=template_name,
            theme=None,
            title=title,
        )

        self.logger.info(
            "Rendered data-splice infographic: template=%s marker=%s size=%d bytes",
            template_name, effective_marker, len(html),
        )

        return InfographicRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template_name,
            theme=None,
            data_variables=[],
            enhanced=False,
            a2ui_envelope=None,
        )

    @staticmethod
    def _splice_payload(source: str, payload_json: str, marker_id: str) -> str:
        """Inject ``payload_json`` into the ``id="{marker_id}"`` script marker.

        Generalises ``splice_into_template`` from the standalone report script.
        Matches the exact marker string with ``marker_id`` interpolated; output
        is byte-identical to ``source`` except for the swapped payload.

        Args:
            source: Raw template HTML.
            payload_json: Pre-serialised JSON string to inject.
            marker_id: The marker's ``id`` attribute value.

        Returns:
            The spliced HTML.

        Raises:
            InfographicValidationError: ``SPLICE_MARKER_MISSING`` when the marker
                open tag or its closing ``</script>`` is absent.
        """
        start_marker = f'<script type="application/json" id="{marker_id}">'
        end_marker = "</script>"
        start_idx = source.find(start_marker)
        if start_idx == -1:
            raise InfographicValidationError(
                "SPLICE_MARKER_MISSING",
                {
                    "marker_id": marker_id,
                    "expected": start_marker,
                    "detail": (
                        f"No <script type=\"application/json\" id=\"{marker_id}\"> "
                        "marker found in the template."
                    ),
                },
            )
        content_start = start_idx + len(start_marker)
        content_end = source.find(end_marker, content_start)
        if content_end == -1:
            raise InfographicValidationError(
                "SPLICE_MARKER_MISSING",
                {
                    "marker_id": marker_id,
                    "detail": (
                        "No closing </script> tag found after the "
                        f'id="{marker_id}" marker.'
                    ),
                },
            )
        return source[:content_start] + "\n" + payload_json + "\n" + source[content_end:]

    def _build_template_context(
        self,
        data: Optional[Dict[str, Any]],
        theme: Optional[str],
        title: Optional[str],
    ) -> Dict[str, Any]:
        """Assemble the Jinja context for ``render_template``.

        ``data`` is the authoritative payload. ``message`` is a *best-effort*
        snapshot of the bound bot's most recent ``AIMessage`` (may be ``{}`` when
        the current turn is still in flight); templates should prefer ``data``.

        Returns:
            Dict with ``data``, ``message``, ``meta`` (``message.metadata``),
            ``theme``, ``title`` and ``now`` (UTC).
        """
        message = self._snapshot_bot_message()
        meta = message.get("metadata") if isinstance(message, dict) else None
        return {
            "data": data or {},
            "message": message,
            "meta": meta or {},
            "theme": theme,
            "title": title,
            "now": datetime.now(timezone.utc),
        }

    def _build_a2ui_envelope(
        self,
        blocks: List[Dict[str, Any]],
        template_name: str,
        theme: Optional[str],
        artifact_id: str,
        *,
        title: Optional[str] = None,
        extra_sections: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a validated A2UI Infographic envelope from the render data."""
        from parrot.outputs.a2ui.builders import build_infographic

        sections = extra_sections or []
        if not sections:
            for i, block in enumerate(blocks):
                heading = block.get("title") or block.get("type") or f"Block {i + 1}"
                sections.append({"heading": heading})
        if not sections:
            sections = [{"heading": template_name}]

        try:
            envelope = build_infographic(
                title=title or template_name,
                sections=sections,
                theme=theme,
                surface_id=f"infographic-{artifact_id}",
                data_model={"blocks": blocks} if blocks else None,
            )
            return envelope.model_dump(mode="json")
        except Exception:
            self.logger.warning(
                "A2UI envelope build failed for infographic %s; "
                "falling back to HTML-only result.",
                artifact_id,
                exc_info=True,
            )
            return None

    def _snapshot_bot_message(self) -> Dict[str, Any]:
        """Best-effort dict view of the bound bot's last ``AIMessage``.

        Returns ``{}`` when no bot is bound or it exposes no last message. Any
        serialisation failure degrades to a small set of well-known fields, and
        finally to ``{}`` — this context is optional, never authoritative.
        """
        bot = getattr(self, "_bot", None)
        if bot is None:
            return {}
        msg = (
            getattr(bot, "last_response", None)
            or getattr(bot, "_last_message", None)
            or getattr(bot, "last_message", None)
        )
        if msg is None:
            return {}
        for attr in ("model_dump", "dict"):
            dumper = getattr(msg, attr, None)
            if callable(dumper):
                try:
                    return dumper()
                except Exception:  # noqa: BLE001
                    break
        return {
            k: getattr(msg, k, None)
            for k in ("output", "response", "structured_output", "metadata", "sources")
            if hasattr(msg, k)
        }

    async def _persist_template(
        self,
        *,
        html: str,
        template_name: str,
        theme: Optional[str],
        title: Optional[str],
    ) -> Tuple[str, str]:
        """Persist a template-rendered infographic; return ``(artifact_id, html_url)``.

        Mirrors :meth:`_persist` but for the raw-HTML template path: the
        definition carries the rendered ``html`` (served by the public HTML
        route), the ``template`` name and ``theme``, and an empty ``js_bundles``
        list (template output ships no vetted CDN bundles).
        """
        bot = getattr(self, "_bot", None)
        user_id, agent_id, session_id = self._resolve_scope(bot)

        now = datetime.now(timezone.utc)
        artifact_id = f"infographic-{uuid.uuid4().hex[:12]}"

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.INFOGRAPHIC,
            title=title or f"Infographic — {template_name}",
            created_at=now,
            updated_at=now,
            source_turn_id=None,
            created_by=ArtifactCreator.AGENT,
            definition={
                "html": html,
                "template": template_name,
                "theme": theme,
                "js_bundles": [],
            },
        )

        await self._artifact_store.save_artifact(user_id, agent_id, session_id, artifact)

        html_url = build_public_html_url(
            artifact_id,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )

        return artifact_id, html_url

    async def list_templates(self) -> List[Dict[str, str]]:
        """Return the list of available infographic templates.

        Returns:
            List of dicts with ``name`` and ``description`` keys.
        """
        detailed = getattr(infographic_registry, "list_templates_detailed", None)
        if callable(detailed):
            return detailed()
        return [
            {"name": n, "description": infographic_registry.get(n).description}
            for n in infographic_registry.list_templates()
        ]

    async def get_template_contract(self, template_name: str) -> Dict[str, Any]:
        """Return the positional block contract for a template.

        Useful before calling ``infographic_render`` to ensure the blocks you
        build match the template's ``block_specs`` exactly.

        Args:
            template_name: Template identifier.

        Returns:
            Dict with ``name``, ``description``, ``default_theme``,
            ``block_specs`` (list with positional index, type, constraints),
            and ``js_bundles``.

        Raises:
            InfographicValidationError: Code ``TEMPLATE_UNKNOWN`` when the
                template is not found.
        """
        template = self._validate_template(template_name)
        return {
            "name": template.name,
            "description": template.description,
            "default_theme": template.default_theme,
            "block_specs": [
                {
                    "position": idx,
                    "block_type": s.block_type.value,
                    "required": s.required,
                    "description": s.description,
                    "min_items": s.min_items,
                    "max_items": s.max_items,
                    "constraints": s.constraints or {},
                }
                for idx, s in enumerate(template.block_specs)
            ],
            "js_bundles": [
                {"name": b.name, "url": b.url, "scope": b.scope}
                for b in (template.js_bundles or [])
            ],
        }

    async def validate_blocks(
        self,
        template_name: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        blocks_variable: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dry-run block validation without rendering or persisting.

        This tool NEVER raises — it returns a structured result so the LLM
        can branch on success/failure.  Use this before ``infographic_render``
        to avoid hard errors.

        Args:
            template_name: Template identifier.
            blocks_variable: **Preferred.** Name of a Python variable in the
                pandas REPL holding the block list (e.g. ``"fp_blocks"``).
                Validated straight from the REPL namespace — no need to copy
                JSON into the call.  Takes precedence over ``blocks``.
            blocks: Block list to validate.  Prefer ``blocks_variable`` for
                anything but a tiny, hand-written block list.

        Returns:
            ``{"ok": True}`` on success; ``{"ok": False, "code": ...,
            "detail": ...}`` on failure.
        """
        try:
            template = self._validate_template(template_name)
            resolved_blocks = self._resolve_blocks(blocks, blocks_variable)
            self._validate_blocks(template, resolved_blocks)
            return {"ok": True}
        except InfographicValidationError as exc:
            return {"ok": False, "code": exc.code, "detail": exc.detail}

    async def build_block(
        self,
        block_type: str,
        into: str = "infographic_blocks",
        data_variable: Optional[str] = None,
        chart_type: Optional[str] = None,
        label_column: Optional[str] = None,
        value_columns: Optional[List[str]] = None,
        table_columns: Optional[List[str]] = None,
        max_rows: Optional[int] = None,
        title: Optional[str] = None,
        layout: Optional[str] = None,
        block: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build ONE infographic block from REPL data and append it to a list.

        This is the reliable way to assemble chart/table blocks: instead of
        hand-writing large JSON arrays into the tool call (the main failure
        mode), point this tool at a DataFrame already in the pandas namespace.
        It reads the frame, constructs the block, validates it against the
        block schema, and appends it to an accumulator list variable (``into``,
        default ``"infographic_blocks"``) IN CALL ORDER. Build every block in
        the template's positional order, then render with
        ``infographic_render(blocks_variable=into, ...)``.

        Block sources by type:

        - ``"chart"`` — derived from ``data_variable``. ``label_column`` becomes
          the x-axis/category labels; each name in ``value_columns`` becomes one
          series. ``chart_type`` (bar/line/pie/…), ``title`` and ``layout``
          (``"full"``/``"half"``) are optional.
        - ``"table"`` — derived from ``data_variable``. ``table_columns`` selects
          and orders columns (defaults to all); rows come from the frame.
        - any other type (``title``/``hero_card``/``summary``/``callout``/…) —
          carries no DataFrame: pass the literal block dict via ``block``.

        ``max_rows`` caps how many rows are read (chart/table) to keep the
        artifact lean. NumPy/pandas scalars and Timestamps are coerced to native
        JSON types automatically.

        Args:
            block_type: The block ``type`` to build.
            into: Accumulator list variable name in the pandas REPL. Created if
                absent; subsequent calls append in order.
            data_variable: DataFrame name in the REPL (required for chart/table).
            chart_type: Chart kind for ``block_type="chart"``.
            label_column: Column used as chart labels (chart only).
            value_columns: Columns used as chart series — one series each (chart).
            table_columns: Columns to include/order (table only; default all).
            max_rows: Optional cap on rows read from the DataFrame.
            title: Optional block title (chart/table).
            layout: Optional ``"full"``/``"half"`` layout hint (chart).
            block: Literal block dict for non chart/table types (must carry
                ``"type"``).

        Returns:
            ``{"ok": True, "into": <name>, "index": <pos>, "block_type": <type>,
            "n_blocks": <len>}`` on success; ``{"ok": False, "code": ...,
            "detail": ...}`` on a structured failure.
        """
        try:
            repl_locals = self._get_repl_locals()
            if block_type == "chart":
                block_dict = self._build_chart_block(
                    repl_locals, data_variable, chart_type,
                    label_column, value_columns, max_rows, title, layout,
                )
            elif block_type == "table":
                block_dict = self._build_table_block(
                    repl_locals, data_variable, table_columns, max_rows, title,
                )
            else:
                if not isinstance(block, dict):
                    raise InfographicValidationError(
                        "BLOCK_LITERAL_MISSING",
                        {"block_type": block_type,
                         "detail": "Non chart/table blocks require a literal `block` dict."},
                    )
                block_dict = dict(block)
                block_dict.setdefault("type", block_type)

            coerced = self._coerce_single_block(block_dict)
            index, n_blocks = self._append_block(repl_locals, into, coerced)
            return {
                "ok": True,
                "into": into,
                "index": index,
                "block_type": coerced.get("type", block_type),
                "n_blocks": n_blocks,
            }
        except InfographicValidationError as exc:
            return {"ok": False, "code": exc.code, "detail": exc.detail}

    # ------------------------------------------------------------------
    # Recipe tools (FEAT-324, Module 6) — exposed only when recipe_store set
    # ------------------------------------------------------------------

    async def infographic_save_recipe(
        self,
        name: str,
        title: str,
        layout_component: str,
        layout_properties: Dict[str, Any],
        dataset_names: Dict[str, str],
        transform_steps: List[Dict[str, Any]],
        description: Optional[str] = None,
        render_profile: str = "interactive-html",
        theme: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Freeze the current session's infographic construction into a replayable recipe.

        Call this AFTER building an infographic in this session, once you know
        EXACTLY which registered datasets and registered transformer calls
        produced its data. Freezing captures those as recipe steps so the same
        infographic can be regenerated later with fresh data, deterministically,
        with no LLM in the loop (spec G2/G3).

        Every dataset referenced in ``dataset_names`` must be a name registered
        with the DatasetManager, and every step in ``transform_steps`` must name
        a REGISTERED ``@infographic_transformer`` — ad-hoc pandas computation
        done directly in this session cannot be frozen (this is a deliberate
        boundary, not a limitation to work around).

        Args:
            name: Unique recipe name (its storage key).
            title: Human-readable recipe title.
            layout_component: Catalog component name for the layout (e.g.
                ``"Infographic"``, ``"Chart"``).
            layout_properties: Catalog properties for the layout; data-carrying
                properties use ``{"$bind": "/pointer"}`` bindings into the
                dataModel produced by ``transform_steps``.
            dataset_names: Mapping of data-source alias -> registered
                DatasetManager dataset name, e.g. ``{"snapshots": "budget_ledger"}``.
            transform_steps: Ordered list of transform-step dicts, each shaped
                like ``{"transformer": "division_breakdown", "inputs":
                ["snapshots"], "params": {}, "output_key": "division_breakdown"}``.
            description: Optional longer description.
            render_profile: Renderer profile name for replay (default
                ``"interactive-html"``).
            theme: Optional theme name.

        Returns:
            ``{"status": "ok", "recipe": {...summary...}}`` on success, or
            ``{"status": "error", "detail": ...}`` /
            ``{"status": "error", "errors": [...]}`` when the provenance is
            inexpressible or the normalized recipe fails dry-run validation.
        """
        if self._recipe_store is None or self._recipe_runner is None:
            return {
                "status": "error",
                "detail": "Recipe store/runner not configured on this toolkit.",
            }

        from parrot.outputs.a2ui.builders import build_surface  # noqa: PLC0415

        try:
            envelope = build_surface(
                layout_component, layout_properties, surface_id=f"freeze-{name}"
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured tool error
            return {"status": "error", "detail": f"Invalid layout: {exc}"}

        bot = getattr(self, "_bot", None)
        user_id, _agent_id, _session_id = self._resolve_scope(bot)

        try:
            recipe = await freeze_session_envelope(
                envelope,
                dataset_names=dataset_names,
                transform_steps=transform_steps,
                name=name,
                title=title,
                runner=self._recipe_runner,
                description=description,
                owner=user_id,
                render_profile=render_profile,
                theme=theme,
            )
        except FreezeProvenanceError as exc:
            return {"status": "error", "detail": str(exc)}
        except FreezeValidationError as exc:
            return {"status": "error", "errors": [e.model_dump() for e in exc.errors]}

        await self._recipe_store.save(recipe)
        saved = await self._recipe_store.get(recipe.name, owner=user_id)
        return {
            "status": "ok",
            "recipe": {
                "name": saved.name,
                "title": saved.title,
                "description": saved.description,
                "owner": saved.owner,
                "updated_at": saved.updated_at.isoformat(),
            },
        }

    async def infographic_list_recipes(self) -> List[Dict[str, Any]]:
        """List saved recipes available to the current user (lightweight summaries).

        Use this to discover recipe names before calling
        ``infographic_run_recipe`` or ``infographic_get_recipe_contract``.

        Returns:
            List of dicts with ``name``, ``title``, ``description``, ``owner``,
            ``updated_at`` — never full recipe definitions.
        """
        if self._recipe_store is None:
            return []
        bot = getattr(self, "_bot", None)
        user_id, _agent_id, _session_id = self._resolve_scope(bot)
        return await self._recipe_store.list(owner=user_id)

    async def infographic_run_recipe(
        self, name: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Replay a saved recipe deterministically (no LLM) and render a fresh artifact.

        Re-fetches the recipe's datasets, re-runs its registered transform
        chain, and renders a new artifact — same construction instructions,
        fresh data (spec G3).

        Args:
            name: Recipe name to run.
            params: Optional override values for the recipe's declared params
                (e.g. ``{"month": "2026-06"}``); undeclared names are rejected.

        Returns:
            ``{"status": "ok", "artifact_id": ..., "mime_type": ..., "title":
            ..., "filename": ...}`` on success. On failure:
            ``{"status": "error", "error": {...RecipeRunError fields...}}`` —
            a structured diagnostic (recipe/stage/transformer/dataset/
            missing_columns/detail) for you to explain to the user; never a
            raw traceback.
        """
        if self._recipe_runner is None:
            return {
                "status": "error",
                "detail": "Recipe runner not configured on this toolkit.",
            }
        bot = getattr(self, "_bot", None)
        user_id, _agent_id, _session_id = self._resolve_scope(bot)
        pctx = self._current_recipe_pctx(user_id)
        try:
            artifact = await self._recipe_runner.run(
                name, params=params, pctx=pctx, recipe_owner=user_id
            )
        except RecipeRunException as exc:
            return {"status": "error", "error": exc.error.model_dump()}
        return {
            "status": "ok",
            "artifact_id": artifact.artifact_id,
            "mime_type": artifact.mime_type,
            "title": artifact.title,
            "filename": artifact.filename,
        }

    async def infographic_get_recipe_contract(self, name: str) -> Dict[str, Any]:
        """Return the datasets, required columns, and params a recipe needs to replay.

        Use this before running or scheduling a recipe to verify it is still
        replayable (its datasets are registered, its transformers exist).

        Args:
            name: Recipe name.

        Returns:
            ``{"status": "ok", "name": ..., "datasets": [{"alias":...,
            "dataset":...}], "params": [{"name":...,"default":...,
            "description":...}], "transforms": [{"transformer":...,
            "output_key":...,"requires_columns":{...}}]}``, or
            ``{"status": "error", "detail": ...}`` if the recipe or store is
            unavailable.
        """
        if self._recipe_store is None:
            return {"status": "error", "detail": "Recipe store not configured on this toolkit."}
        bot = getattr(self, "_bot", None)
        user_id, _agent_id, _session_id = self._resolve_scope(bot)
        try:
            recipe = await self._recipe_store.get(name, owner=user_id)
        except RecipeNotFoundError as exc:
            return {"status": "error", "detail": str(exc)}

        transforms = []
        for step in recipe.transforms:
            try:
                requires_columns = transformer_registry.manifest(step.transformer).requires_columns
            except KeyError:
                requires_columns = {}
            transforms.append(
                {
                    "transformer": step.transformer,
                    "output_key": step.output_key,
                    "requires_columns": requires_columns,
                }
            )

        return {
            "status": "ok",
            "name": recipe.name,
            "datasets": [
                {"alias": ds.alias, "dataset": ds.dataset} for ds in recipe.data_sources
            ],
            "params": [
                {"name": p.name, "default": p.default, "description": p.description}
                for p in recipe.params
            ],
            "transforms": transforms,
        }

    # ------------------------------------------------------------------
    # Block builders (REPL data → validated block dict)
    # ------------------------------------------------------------------

    def _require_dataframe(
        self, repl_locals: Dict[str, Any], name: Optional[str],
    ) -> pd.DataFrame:
        """Resolve ``name`` to a DataFrame in the REPL or raise structured."""
        if not name:
            raise InfographicValidationError(
                "BLOCK_DATA_VAR_MISSING",
                {"detail": "chart/table blocks require `data_variable`."},
            )
        if name not in repl_locals:
            raise InfographicValidationError(
                "BLOCK_DATA_VAR_MISSING",
                {"name": name, "available": sorted(
                    k for k, v in repl_locals.items() if isinstance(v, pd.DataFrame)
                )},
            )
        df = repl_locals[name]
        if not isinstance(df, pd.DataFrame):
            raise InfographicValidationError(
                "BLOCK_DATA_VAR_INVALID",
                {"name": name, "type": type(df).__name__},
            )
        return df

    @staticmethod
    def _check_columns(df: pd.DataFrame, columns: List[str]) -> None:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise InfographicValidationError(
                "BLOCK_COLUMN_MISSING",
                {"missing": missing, "available": list(df.columns)},
            )

    def _build_chart_block(
        self,
        repl_locals: Dict[str, Any],
        data_variable: Optional[str],
        chart_type: Optional[str],
        label_column: Optional[str],
        value_columns: Optional[List[str]],
        max_rows: Optional[int],
        title: Optional[str],
        layout: Optional[str],
    ) -> Dict[str, Any]:
        if not chart_type:
            raise InfographicValidationError(
                "BLOCK_CHART_INCOMPLETE", {"detail": "`chart_type` is required."},
            )
        if not label_column or not value_columns:
            raise InfographicValidationError(
                "BLOCK_CHART_INCOMPLETE",
                {"detail": "`label_column` and `value_columns` are required."},
            )
        df = self._require_dataframe(repl_locals, data_variable)
        self._check_columns(df, [label_column, *value_columns])
        if max_rows is not None:
            df = df.head(max_rows)
        block: Dict[str, Any] = {
            "type": "chart",
            "chart_type": chart_type,
            "labels": [str(v) for v in df[label_column].tolist()],
            "series": [
                {"name": col, "values": df[col].tolist()}
                for col in value_columns
            ],
        }
        if title:
            block["title"] = title
        if layout:
            block["layout"] = layout
        return block

    def _build_table_block(
        self,
        repl_locals: Dict[str, Any],
        data_variable: Optional[str],
        table_columns: Optional[List[str]],
        max_rows: Optional[int],
        title: Optional[str],
    ) -> Dict[str, Any]:
        df = self._require_dataframe(repl_locals, data_variable)
        columns = table_columns or list(df.columns)
        self._check_columns(df, columns)
        if max_rows is not None:
            df = df.head(max_rows)
        block: Dict[str, Any] = {
            "type": "table",
            "columns": [str(c) for c in columns],
            "rows": df[columns].values.tolist(),
        }
        if title:
            block["title"] = title
        return block

    def _coerce_single_block(self, block_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise + schema-validate one block; return a JSON-native dict."""
        normalized = self._normalize_blocks([block_dict])[0]
        try:
            model = InfographicResponse.model_validate(
                {"blocks": [normalized]}
            ).blocks[0]
        except PydanticValidationError as exc:
            raise InfographicValidationError(
                "BLOCK_SCHEMA_INVALID",
                {"block_type": block_dict.get("type"), "errors": exc.errors()[:5]},
            ) from exc
        return model.model_dump(mode="json")

    def _append_block(
        self, repl_locals: Dict[str, Any], into: str, block_dict: Dict[str, Any],
    ) -> Tuple[int, int]:
        """Append ``block_dict`` to the REPL accumulator list, creating it."""
        acc = repl_locals.get(into)
        if acc is None:
            acc = []
            repl_locals[into] = acc
        elif not isinstance(acc, list):
            raise InfographicValidationError(
                "BLOCK_ACCUMULATOR_INVALID",
                {"name": into, "type": type(acc).__name__},
            )
        acc.append(block_dict)
        return len(acc) - 1, len(acc)

    # ------------------------------------------------------------------
    # Enhance placeholder (TASK-1325 replaces this)
    # ------------------------------------------------------------------

    async def _maybe_enhance(
        self,
        *,
        skeleton: str,
        brief: Optional[str],
        mode: str,
        data_context: Dict[str, Any],
        js_bundles_available: List[JSBundle],
    ) -> Tuple[str, bool]:
        """Run the optional LLM enhance pass (FEAT-197, TASK-1325).

        Returns the enhanced HTML (``enhanced=True``) when the bot has
        ``enhance_infographic`` and the returned HTML passes the SRI whitelist
        check.  Falls back silently to the skeleton (``enhanced=False``) on
        any failure, logging a WARNING-level security event.

        Args:
            skeleton: Deterministic HTML from the render pass.
            brief: User-provided enhancement brief (required for enhance mode).
            mode: ``"deterministic"`` or ``"enhance"``.
            data_context: DataFrames serialised as records dicts.
            js_bundles_available: SRI-whitelist from the template.

        Returns:
            ``(html, enhanced)`` tuple.
        """
        if mode != "enhance":
            return skeleton, False

        # FEAT-273 (Module 11 / G7): the raw-HTML LLM enhance lane is deprecated in
        # favour of deterministic A2UI envelope builders
        # (parrot.outputs.a2ui.builders). Legacy behaviour is preserved.
        import warnings  # noqa: PLC0415

        warnings.warn(
            "InfographicToolkit raw-HTML enhance lane is deprecated (FEAT-273): "
            "emit an A2UI envelope via parrot.outputs.a2ui.builders.build_infographic "
            "with OutputMode.A2UI instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not brief:
            self.logger.warning(
                "enhance requested without a brief — falling back to skeleton."
            )
            return skeleton, False

        bot = getattr(self, "_bot", None)
        if bot is None or not hasattr(bot, "enhance_infographic"):
            self.logger.warning(
                "Bound bot lacks enhance_infographic method — falling back."
            )
            return skeleton, False

        try:
            from parrot.tools._enhance_html_check import validate_enhanced_html

            enhanced_html = await bot.enhance_infographic(
                skeleton=skeleton,
                brief=brief,
                data_context=data_context,
                js_bundles_available=js_bundles_available,
            )
            validate_enhanced_html(enhanced_html, js_bundles_available)
            return enhanced_html, True

        except InfographicValidationError as exc:
            self.logger.warning(
                "Enhanced HTML rejected (%s) — falling back to deterministic skeleton: %s",
                exc.code,
                exc.detail,
            )
            return skeleton, False
        except Exception as exc:
            self.logger.warning(
                "Enhance pass failed (%s) — falling back to deterministic skeleton.",
                exc,
            )
            return skeleton, False

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_template(self, name: str) -> InfographicTemplate:
        """Raise TEMPLATE_UNKNOWN if the template is not registered."""
        try:
            return infographic_registry.get(name)
        except KeyError as exc:
            raise InfographicValidationError(
                "TEMPLATE_UNKNOWN",
                {"template_name": name, "available": infographic_registry.list_templates()},
            ) from exc

    def _validate_blocks(
        self,
        template: InfographicTemplate,
        blocks_raw: List[Dict[str, Any]],
    ) -> List[InfographicBlock]:
        """Validate and coerce blocks against the template's positional contract."""
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
                        {"position": idx, "expected_type": spec.block_type.value},
                    )
                continue  # optional, skip

            block_raw = blocks_raw[idx]
            got_type = block_raw.get("type")
            if got_type != spec.block_type.value:
                raise InfographicValidationError(
                    "SLOT_TYPE_MISMATCH",
                    {
                        "position": idx,
                        "expected_type": spec.block_type.value,
                        "got_type": got_type,
                    },
                )

            # Item-count check (for hero_cards, bullets, etc.)
            self._check_item_count(idx, spec, block_raw)

            # Coerce dict → InfographicBlock via the discriminated union
            block_model = InfographicResponse.model_validate({"blocks": [block_raw]}).blocks[0]
            coerced.append(block_model)

        return coerced

    def _check_item_count(
        self, idx: int, spec: BlockSpec, block_raw: Dict[str, Any],
    ) -> None:
        """Raise SLOT_ITEM_COUNT_INVALID when min/max_items constraints are violated."""
        if spec.min_items is None and spec.max_items is None:
            return

        # Convention: list-like blocks store items under one of these keys.
        # Adjust if block models use different field names.
        for key in ("items", "cards", "rows", "series", "entries", "tabs"):
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

    def _resolve_blocks(
        self,
        blocks: Optional[List[Dict[str, Any]]],
        blocks_variable: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Resolve the block list from an inline payload or a REPL variable.

        When ``blocks_variable`` is given it is looked up in the pandas REPL
        namespace (the same source as ``data_variables``) and takes
        precedence over an inline ``blocks`` payload.  This lets a skill's
        ``compute.py`` leave a ``fp_blocks`` variable in scope and have the
        LLM pass ``blocks_variable="fp_blocks"`` instead of copying a large
        JSON array into the tool call — the copy step is the main failure
        mode for big positional contracts.

        The resolved value is normalised through a NumPy-aware JSON round-trip
        so ``numpy`` scalars (e.g. ``round()`` over a pandas Series) coerce to
        native Python types before Pydantic validation.

        Raises:
            InfographicValidationError: ``BLOCKS_MISSING`` when neither source
                is provided, ``BLOCKS_VAR_MISSING`` when the named variable is
                absent from the REPL, ``BLOCKS_VAR_INVALID`` when it is not a
                list of dicts.
        """
        if blocks_variable:
            repl_locals = self._get_repl_locals()
            if blocks_variable not in repl_locals:
                raise InfographicValidationError(
                    "BLOCKS_VAR_MISSING",
                    {"name": blocks_variable, "available": sorted(repl_locals.keys())},
                )
            resolved = repl_locals[blocks_variable]
            if not isinstance(resolved, list):
                raise InfographicValidationError(
                    "BLOCKS_VAR_INVALID",
                    {"name": blocks_variable, "type": type(resolved).__name__},
                )
            return self._normalize_blocks(resolved)

        if blocks is not None:
            return self._normalize_blocks(blocks)

        raise InfographicValidationError(
            "BLOCKS_MISSING",
            {"detail": "Provide either `blocks` or `blocks_variable`."},
        )

    @staticmethod
    def _normalize_blocks(blocks: List[Any]) -> List[Dict[str, Any]]:
        """Coerce NumPy/pandas scalars inside blocks to native JSON types."""
        def _default(obj: Any) -> Any:
            if hasattr(obj, "item"):  # numpy scalar
                return obj.item()
            if hasattr(obj, "tolist"):  # numpy array / pandas Series
                return obj.tolist()
            if hasattr(obj, "isoformat"):  # datetime / pandas Timestamp
                return obj.isoformat()
            return str(obj)

        return json.loads(json.dumps(blocks, default=_default))

    def _validate_data_variables(
        self, names: List[str], locals_: Dict[str, Any],
    ) -> Dict[str, pd.DataFrame]:
        """Validate that all data_variables are present and non-empty DataFrames."""
        out: Dict[str, pd.DataFrame] = {}
        for name in names:
            if name not in locals_:
                raise InfographicValidationError("DATA_VAR_MISSING", {"name": name})
            df = locals_[name]
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                raise InfographicValidationError(
                    "DATA_VAR_EMPTY", {"name": name, "type": type(df).__name__},
                )
            out[name] = df
        return out

    def _validate_theme(self, name: Optional[str]) -> Optional[str]:
        """Raise THEME_INVALID if the theme name is unknown."""
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

    # ------------------------------------------------------------------
    # Bot binding helpers
    # ------------------------------------------------------------------

    def _get_repl_locals(self) -> Dict[str, Any]:
        """Resolve the pandas REPL locals from the bound bot (PandasAgent).

        The toolkit is attached to a bot via ``toolkit._bot = agent``.
        ``PandasAgent`` exposes ``_get_repl_locals()`` which returns the
        current interpreter namespace including all computed DataFrames.
        """
        bot = getattr(self, "_bot", None)
        if bot is None:
            return {}
        getter = getattr(bot, "_get_repl_locals", None)
        return getter() if callable(getter) else {}

    def _resolve_scope(self, bot: Any) -> Tuple[str, str, str]:
        """Extract (user_id, agent_id, session_id) from the bot context.

        Priority:
            1. ``_current_user_id`` / ``_current_agent_id`` / ``_current_session_id``
               — set by ``PandasAgent.ask()`` before calling the toolkit (TASK-1326).
            2. ``user_id`` / ``agent_id`` / ``session_id`` class attributes.
            3. Fallback sentinels.

        Args:
            bot: The bound bot instance.

        Returns:
            Tuple of ``(user_id, agent_id, session_id)`` strings.
        """
        if bot is None:
            return "_anon", "_anon", "_anon"

        user_id = (
            getattr(bot, "_current_user_id", None)
            or getattr(bot, "user_id", None)
            or "_anon"
        )
        agent_id = (
            getattr(bot, "_current_agent_id", None)
            or getattr(bot, "agent_id", None)
            or "_anon"
        )
        session_id = (
            getattr(bot, "_current_session_id", None)
            or getattr(bot, "session_id", None)
            or "_anon"
        )
        return str(user_id), str(agent_id), str(session_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        html: str,
        response: InfographicResponse,
        template: InfographicTemplate,
    ) -> Tuple[str, str]:
        """Save the artifact and return ``(artifact_id, html_url)``.

        The artifact definition shape is documented here because TASK-1322's
        legacy-fallback path and TASK-1327's e2e tests depend on it::

            {
                "html": "<complete HTML document>",
                "blocks_envelope": response.model_dump(),
                "theme": template_theme,
                "template": template_name,
                "js_bundles": [bundle.model_dump(), ...],
            }
        """
        bot = getattr(self, "_bot", None)
        user_id, agent_id, session_id = self._resolve_scope(bot)

        now = datetime.now(timezone.utc)
        artifact_id = f"infographic-{uuid.uuid4().hex[:12]}"

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.INFOGRAPHIC,
            title=f"Infographic — {template.name}",
            created_at=now,
            updated_at=now,
            source_turn_id=None,
            created_by=ArtifactCreator.AGENT,
            definition={
                "html": html,
                "blocks_envelope": response.model_dump(),
                "theme": response.theme,
                "template": template.name,
                "js_bundles": [b.model_dump() for b in (template.js_bundles or [])],
            },
        )

        await self._artifact_store.save_artifact(user_id, agent_id, session_id, artifact)

        # ``html_url`` must point to *rendered HTML* the frontend can embed in
        # an <iframe>.  ``ArtifactStore.get_public_url`` returns a presigned URL
        # to the raw overflow *JSON* object (and a ``file://`` path on local /
        # non-S3 backends) — neither is servable HTML.  Instead mint a signed
        # URL for the server's public HTML route, which streams
        # ``definition.html`` regardless of storage backend.  The exact persist
        # scope is known here, so we embed it for scope-partitioned stores.
        html_url = build_public_html_url(
            artifact_id,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )

        return artifact_id, html_url
