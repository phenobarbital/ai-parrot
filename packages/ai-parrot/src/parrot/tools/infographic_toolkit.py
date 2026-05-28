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

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandas as pd
from pydantic import BaseModel, Field

from parrot.tools.toolkit import AbstractToolkit
from parrot.models.infographic import (
    InfographicBlock,
    InfographicResponse,
    BlockType,
    theme_registry,
    JSBundle,
)
from parrot.models.infographic_templates import (
    BlockSpec,
    InfographicTemplate,
    infographic_registry,
)
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator


# ---------------------------------------------------------------------------
# Threshold for inline HTML (< 50 KB → populate html_inline)
# ---------------------------------------------------------------------------

_INLINE_THRESHOLD: int = 50_000


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

        infographic_render
        infographic_list_templates
        infographic_get_template_contract
        infographic_validate_blocks
    """

    return_direct: bool = True          # bypass LLM re-summarisation
    tool_prefix: Optional[str] = "infographic"
    prefix_separator: str = "_"
    exclude_tools: tuple[str, ...] = ()

    def __init__(self, *, artifact_store: ArtifactStore, **kwargs) -> None:
        """Initialise the toolkit.

        Args:
            artifact_store: Initialised ``ArtifactStore`` instance.
            **kwargs: Forwarded to ``AbstractToolkit.__init__``.
        """
        super().__init__(**kwargs)
        self._artifact_store = artifact_store
        self._renderer = InfographicHTMLRenderer()
        self.logger = logging.getLogger(__name__)
        # Ensure the class-level return_direct=True is set as an instance
        # attribute so AbstractToolkit._generate_tool can read it correctly.
        self.return_direct = True  # explicit — do not let kwargs override this

    def get_tools(self, **kwargs):
        """Return the generated tools, ensuring return_direct is propagated."""
        tools = super().get_tools(**kwargs)
        # AbstractTool's __init__ swallows return_direct into _init_kwargs
        # without setting the instance attribute; patch it explicitly.
        for tool in tools:
            if not getattr(tool, "return_direct", False):
                tool.return_direct = True
        return tools

    # ------------------------------------------------------------------
    # Public tool methods
    # ------------------------------------------------------------------

    async def render(
        self,
        template_name: str,
        theme: Optional[str],
        mode: Literal["deterministic", "enhance"],
        blocks: List[Dict[str, Any]],
        data_variables: List[str],
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
            blocks: List of block dicts matching the template's positional
                contract.  Use ``infographic_get_template_contract`` to see
                the expected types and counts.
            data_variables: Names of DataFrames in the pandas REPL locals
                that provide the underlying data for this infographic.
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
        coerced_blocks = self._validate_blocks(template, blocks)
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
        html, enhanced = await self._maybe_enhance(
            skeleton=skeleton,
            brief=enhance_brief,
            mode=mode,
            data_context={
                name: repl_locals[name].to_dict("records")
                for name in data_variables
                if name in repl_locals and isinstance(repl_locals[name], pd.DataFrame)
            },
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

        return InfographicRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template.name,
            theme=validated_theme,
            data_variables=data_variables,
            enhanced=enhanced,
        )

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
        blocks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Dry-run block validation without rendering or persisting.

        This tool NEVER raises — it returns a structured result so the LLM
        can branch on success/failure.  Use this before ``infographic_render``
        to avoid hard errors.

        Args:
            template_name: Template identifier.
            blocks: Block list to validate.

        Returns:
            ``{"ok": True}`` on success; ``{"ok": False, "code": ...,
            "detail": ...}`` on failure.
        """
        try:
            template = self._validate_template(template_name)
            self._validate_blocks(template, blocks)
            return {"ok": True}
        except InfographicValidationError as exc:
            return {"ok": False, "code": exc.code, "detail": exc.detail}

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

        # get_public_url may raise ValueError for inline artifacts — catch and
        # return a sentinel so the toolkit can still return a result.
        try:
            html_url = await self._artifact_store.get_public_url(
                user_id, agent_id, session_id, artifact_id, format="html",
            )
        except (ValueError, KeyError):
            # Artifact was stored inline (small definition) or store not S3 —
            # return a relative session-scoped URL as fallback.
            html_url = f"/api/v1/artifacts/{artifact_id}?format=html"

        return artifact_id, html_url
