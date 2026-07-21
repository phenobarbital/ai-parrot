"""InteractiveToolkit — free-form, self-contained interactive HTML artifacts.

The "vibe-coding" counterpart to :class:`~parrot.tools.infographic_toolkit.InfographicToolkit`.
Where infographics constrain the LLM to typed JSON blocks rendered
deterministically, this toolkit hands the LLM a **scaffold** (a self-contained
HTML skeleton with named slots) plus a **catalog** of vetted JS libraries, and
lets it author the HTML/JS directly during an *enhance* pass. The result is the
same artifact plumbing infographics use: persisted via :class:`ArtifactStore`,
served by the public signed-URL HTML route, and locked down by the JSBundle
SRI allow-list + CSP.

Tools exposed (prefixed with ``interactive_``)::

    interactive_render            — Build skeleton + enhance + validate + persist.
    interactive_list_templates    — Discover scaffold templates.
    interactive_list_libraries    — Discover available JS libraries.
    interactive_get_scaffold      — Inspect one template's skeleton + libraries.

With ``return_direct=True`` the ``interactive_render`` result is the final agent
output (consumed by the agent post-loop), exactly like ``infographic_render``.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from parrot.tools.toolkit import AbstractToolkit
from parrot.models.infographic import JSBundle
from parrot.models.interactive import (
    InteractiveRenderResult,
    LibraryEntry,
    ScaffoldTemplate,
)
from parrot.tools.interactive.catalog_registry import (
    HEAD_MARKER,
    InteractiveCatalogRegistry,
    build_head,
    get_interactive_catalog,
)
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.artifact_signing import build_public_html_url
from parrot.storage.models import Artifact, ArtifactCreator, ArtifactType


_INLINE_THRESHOLD: int = 50_000

_SLOT_RE = re.compile(r"<!--\s*SLOT:[A-Za-z0-9_]+\s*-->")


class InteractiveValidationError(Exception):
    """Structured error raised by the interactive render pipeline.

    Carries a stable ``code`` (for client routing) and a ``detail`` dict.

    Valid codes::

        TEMPLATE_UNKNOWN
        LIBRARY_UNKNOWN
        LIBRARY_NOT_ALLOWED
        ENHANCE_BRIEF_MISSING
        ENHANCE_OUTPUT_INVALID
    """

    def __init__(self, code: str, detail: Dict[str, Any]) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class InteractiveToolkit(AbstractToolkit):
    """Toolkit producing self-contained interactive HTML artifacts.

    Usage::

        toolkit = InteractiveToolkit(artifact_store=store)
        tools = toolkit.get_tools()
        toolkit.set_bot(agent)   # enables enhance mode + prompt guidance
    """

    return_direct: bool = True
    tool_prefix: Optional[str] = "interactive"
    prefix_separator: str = "_"
    exclude_tools: Tuple[str, ...] = ()

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        catalog: Optional[InteractiveCatalogRegistry] = None,
        emit_a2ui: bool = False,
        **kwargs,
    ) -> None:
        """Initialise the toolkit.

        Args:
            artifact_store: Initialised ``ArtifactStore`` instance.
            catalog: Optional catalog override; defaults to the bundled singleton.
            emit_a2ui: When True, the render tool additionally produces a validated
                A2UI ``CreateSurface`` envelope (FEAT-273 Module 11, D1a lane).
            **kwargs: Forwarded to ``AbstractToolkit.__init__``.
        """
        super().__init__(**kwargs)
        self._artifact_store = artifact_store
        self._catalog = catalog or get_interactive_catalog()
        self._emit_a2ui = emit_a2ui
        self.logger = logging.getLogger(__name__)
        self.return_direct = True

    def get_tools(self, **kwargs):
        """Return generated tools; only ``interactive_render`` is terminal."""
        tools = super().get_tools(**kwargs)
        for tool in tools:
            tool.return_direct = getattr(tool, "name", "").endswith("render")
        return tools

    def set_bot(self, bot: Any) -> None:
        """Bind a bot for enhance-mode support and inject prompt guidance.

        Appends both the usage guide and the static catalog index to the bot's
        ``system_prompt_template`` so any agent that registers this toolkit knows
        which scaffolds and libraries exist (the two-tier skills pattern). Call
        during the agent's ``configure()`` before ``_define_prompt()`` runs.
        """
        self._bot = bot
        self._inject_prompt_guidance(bot)

    def _inject_prompt_guidance(self, bot: Any) -> None:
        """Append the interactive usage guide + catalog index to the bot prompt.

        Idempotent: a sentinel header guards against double-injection. No-op when
        the bot exposes no string ``system_prompt_template``.
        """
        tmpl = getattr(bot, "system_prompt_template", None)
        if not isinstance(tmpl, str):
            return
        from parrot.bots.prompts import INTERACTIVE_SYSTEM_PROMPT_ADDON  # noqa: PLC0415
        if "## Interactive HTML Generation Mode" in tmpl:
            return
        catalog_index = self._catalog.render_prompt_index()
        bot.system_prompt_template = (
            f"{tmpl}\n{INTERACTIVE_SYSTEM_PROMPT_ADDON}\n\n{catalog_index}"
        )

    # ------------------------------------------------------------------
    # Public tool methods
    # ------------------------------------------------------------------

    async def list_templates(self) -> List[Dict[str, Any]]:
        """Return available scaffold templates with their slots and libraries.

        Returns:
            List of dicts with ``name``, ``description``, ``default_theme``,
            ``allowed_bundles`` and ``slots``.
        """
        await self._catalog.ensure_loaded_async()
        return [
            {
                "name": t.name,
                "description": t.description,
                "default_theme": t.default_theme,
                "allowed_bundles": t.allowed_bundles,
                "slots": t.slots,
            }
            for t in self._catalog.list_templates()
        ]

    async def list_libraries(self) -> List[Dict[str, Any]]:
        """Return available JS libraries the LLM may use in artifacts.

        Returns:
            List of dicts with ``name``, ``description``, ``category`` and
            ``scope`` (``"cdn"`` or ``"inline"``).
        """
        await self._catalog.ensure_loaded_async()
        return [
            {
                "name": lib.name,
                "description": lib.description,
                "category": lib.category,
                "scope": lib.bundle.scope,
            }
            for lib in self._catalog.list_libraries()
        ]

    async def get_scaffold(self, template_name: str) -> Dict[str, Any]:
        """Return one template's raw skeleton plus its allowed library details.

        Use this before ``interactive_render`` to see the slot markers you must
        fill and the usage snippets for the libraries you may reference.

        Args:
            template_name: Template identifier from ``interactive_list_templates``.

        Returns:
            Dict with ``name``, ``description``, ``slots``, ``html_skeleton``
            (raw, with ``<!--HEAD-->`` and ``<!-- SLOT:* -->`` markers), and
            ``allowed_libraries`` (each with ``usage`` and ``types``).

        Raises:
            InteractiveValidationError: ``TEMPLATE_UNKNOWN`` if not found.
        """
        await self._catalog.ensure_loaded_async()
        template = self._resolve_template(template_name)
        libs = []
        for n in template.allowed_bundles:
            try:
                libs.append(self._catalog.get_library(n))
            except KeyError:
                raise InteractiveValidationError(
                    "LIBRARY_UNKNOWN",
                    {"library": n, "template": template_name},
                )
        return {
            "name": template.name,
            "description": template.description,
            "default_theme": template.default_theme,
            "slots": template.slots,
            "html_skeleton": template.html_skeleton,
            "allowed_libraries": [
                {
                    "name": lib.name,
                    "description": lib.description,
                    "category": lib.category,
                    "scope": lib.bundle.scope,
                    "usage": lib.usage_snippet,
                    "types": lib.ts_types,
                }
                for lib in libs
            ],
        }

    async def render(
        self,
        template_name: str,
        brief: str,
        libraries: Optional[List[str]] = None,
        mode: Literal["deterministic", "enhance"] = "enhance",
        theme: Optional[str] = None,
        title: Optional[str] = None,
        data_context: Optional[Dict[str, Any]] = None,
    ) -> InteractiveRenderResult:
        """Build, (optionally) enhance, validate, and persist an interactive artifact.

        This is the **primary** tool. Call it as the last tool in the turn.
        The result is returned verbatim — do NOT summarise it.

        Args:
            template_name: Scaffold identifier from ``interactive_list_templates``.
            brief: Natural-language description of the page to build (what each
                slot should contain, the data to visualise, desired interactivity).
            libraries: Library names to use; each MUST be in the template's
                ``allowed_bundles``. Defaults to all of the template's libraries.
            mode: ``"enhance"`` (LLM authors the content) or ``"deterministic"``
                (return the empty skeleton — used as the safe fallback).
            theme: Theme name (``"light"``/``"dark"``); defaults to the template's.
            title: Optional document title (used for the artifact title).
            data_context: Optional JSON-serialisable data passed to the LLM as the
                source of truth for any figures it renders.

        Returns:
            ``InteractiveRenderResult`` with ``artifact_id``, ``html_url``,
            optional ``html_inline`` and provenance fields.

        Raises:
            InteractiveValidationError: On unknown/disallowed template or library,
                or a missing enhance brief.
        """
        await self._catalog.ensure_loaded_async()
        template = self._resolve_template(template_name)
        entries, bundles = self._resolve_libraries(template, libraries)
        resolved_theme = theme or template.default_theme

        head = build_head(bundles, theme=resolved_theme)
        skeleton_with_slots = template.html_skeleton.replace(HEAD_MARKER, head)
        deterministic = _SLOT_RE.sub("", skeleton_with_slots)

        html, enhanced = await self._maybe_enhance(
            skeleton=skeleton_with_slots,
            deterministic=deterministic,
            brief=brief,
            mode=mode,
            data_context=data_context or {},
            bundles=bundles,
            library_guide=self._library_guide(entries),
        )

        artifact_id, html_url = await self._persist(
            html=html,
            template=template,
            theme=resolved_theme,
            libraries=[e.name for e in entries],
            bundles=bundles,
            title=title,
        )

        self.logger.info(
            "Rendered interactive artifact: template=%s theme=%s enhanced=%s size=%d bytes",
            template.name, resolved_theme, enhanced, len(html),
        )

        a2ui_envelope = None
        if self._emit_a2ui:
            a2ui_envelope = self._build_a2ui_envelope(
                template_name=template.name,
                artifact_id=artifact_id,
                title=title,
                brief=brief,
            )

        return InteractiveRenderResult(
            artifact_id=artifact_id,
            html_url=html_url,
            html_inline=html if len(html) < _INLINE_THRESHOLD else None,
            template_name=template.name,
            theme=resolved_theme,
            libraries_used=[e.name for e in entries],
            enhanced=enhanced,
            a2ui_envelope=a2ui_envelope,
        )

    def _build_a2ui_envelope(
        self,
        template_name: str,
        artifact_id: str,
        *,
        title: Optional[str] = None,
        brief: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build a validated A2UI Card envelope from the interactive render."""
        from parrot.outputs.a2ui.builders import build_card

        try:
            envelope = build_card(
                title=title or template_name,
                body=brief,
                surface_id=f"interactive-{artifact_id}",
            )
            return envelope.model_dump(mode="json")
        except Exception:
            self.logger.warning(
                "A2UI envelope build failed for interactive artifact %s; "
                "falling back to HTML-only result.",
                artifact_id,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_template(self, name: str) -> ScaffoldTemplate:
        try:
            return self._catalog.get_template(name)
        except KeyError as exc:
            raise InteractiveValidationError(
                "TEMPLATE_UNKNOWN",
                {"template_name": name,
                 "available": [t.name for t in self._catalog.list_templates()]},
            ) from exc

    def _resolve_libraries(
        self, template: ScaffoldTemplate, libraries: Optional[List[str]],
    ) -> Tuple[List[LibraryEntry], List[JSBundle]]:
        """Resolve requested library names to entries + their bundles.

        Defaults to the template's full allow-list. Rejects any library the
        template does not permit (``LIBRARY_NOT_ALLOWED``) or that is absent from
        the catalog (``LIBRARY_UNKNOWN``).
        """
        names = libraries if libraries is not None else list(template.allowed_bundles)
        entries: List[LibraryEntry] = []
        bundles: List[JSBundle] = []
        for name in names:
            if name not in template.allowed_bundles:
                raise InteractiveValidationError(
                    "LIBRARY_NOT_ALLOWED",
                    {"library": name, "template": template.name,
                     "allowed": template.allowed_bundles},
                )
            try:
                entry = self._catalog.get_library(name)
            except KeyError as exc:
                raise InteractiveValidationError(
                    "LIBRARY_UNKNOWN", {"library": name},
                ) from exc
            entries.append(entry)
            bundles.extend(entry.bundles())
        return entries, bundles

    @staticmethod
    def _library_guide(entries: List[LibraryEntry]) -> str:
        """Build a compact usage guide (snippets + types) for the chosen libraries."""
        if not entries:
            return "(no libraries selected)"
        blocks: List[str] = []
        for e in entries:
            block = [f"### {e.name} ({e.category})", e.description]
            if e.usage_snippet:
                block.append("Usage:\n" + e.usage_snippet)
            if e.ts_types:
                block.append("Types:\n" + e.ts_types)
            blocks.append("\n".join(block))
        return "\n\n".join(blocks)

    async def _maybe_enhance(
        self,
        *,
        skeleton: str,
        deterministic: str,
        brief: str,
        mode: str,
        data_context: Dict[str, Any],
        bundles: List[JSBundle],
        library_guide: str,
    ) -> Tuple[str, bool]:
        """Run the optional LLM enhance pass.

        Returns the enhanced HTML (``enhanced=True``) when a bound bot exposes
        ``enhance_interactive`` and the output passes the SRI allow-list check.
        Falls back to the deterministic (empty-slot) skeleton on any failure,
        logging a WARNING-level security event.
        """
        if mode != "enhance":
            return deterministic, False

        # FEAT-273 (Module 11 / G7): the LLM raw-HTML authoring lane
        # (INTERACTIVE_SYSTEM_PROMPT_ADDON / INTERACTIVE_ENHANCE_PROMPT) is the
        # arbitrary-HTML channel A2UI replaces. Deprecated; legacy behaviour preserved.
        import warnings  # noqa: PLC0415

        warnings.warn(
            "InteractiveToolkit raw-HTML enhance lane is deprecated (FEAT-273): emit an "
            "A2UI envelope via parrot.outputs.a2ui.builders with OutputMode.A2UI instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not brief:
            raise InteractiveValidationError(
                "ENHANCE_BRIEF_MISSING",
                {"detail": "enhance mode requires a non-empty `brief`."},
            )

        bot = getattr(self, "_bot", None)
        if bot is None or not hasattr(bot, "enhance_interactive"):
            self.logger.warning(
                "Bound bot lacks enhance_interactive — falling back to skeleton."
            )
            return deterministic, False

        try:
            from parrot.tools._enhance_html_check import validate_enhanced_html

            enhanced_html = await bot.enhance_interactive(
                skeleton=skeleton,
                brief=brief,
                data_context=data_context,
                js_bundles_available=bundles,
                library_guide=library_guide,
            )
            validate_enhanced_html(
                enhanced_html, bundles, error_cls=InteractiveValidationError,
            )
            return enhanced_html, True
        except InteractiveValidationError as exc:
            self.logger.warning(
                "Enhanced HTML rejected (%s) — falling back to skeleton: %s",
                exc.code, exc.detail,
            )
            return deterministic, False
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Enhance pass failed (%s) — falling back to skeleton.", exc,
            )
            return deterministic, False

    def _resolve_scope(self, bot: Any) -> Tuple[str, str, str]:
        """Extract ``(user_id, agent_id, session_id)`` from the bound bot."""
        if bot is None:
            return "_anon", "_anon", "_anon"
        user_id = (
            getattr(bot, "_current_user_id", None)
            or getattr(bot, "user_id", None) or "_anon"
        )
        agent_id = (
            getattr(bot, "_current_agent_id", None)
            or getattr(bot, "agent_id", None) or "_anon"
        )
        session_id = (
            getattr(bot, "_current_session_id", None)
            or getattr(bot, "session_id", None) or "_anon"
        )
        return str(user_id), str(agent_id), str(session_id)

    async def _persist(
        self,
        *,
        html: str,
        template: ScaffoldTemplate,
        theme: Optional[str],
        libraries: List[str],
        bundles: List[JSBundle],
        title: Optional[str],
    ) -> Tuple[str, str]:
        """Save the artifact and return ``(artifact_id, html_url)``.

        The definition shape mirrors the infographic contract so the public
        HTML route (``_extract_html_from_artifact`` → ``definition.html``) and
        the CSP builder (``definition.js_bundles``) work unchanged::

            {"html", "js_bundles", "template", "libraries", "theme"}
        """
        bot = getattr(self, "_bot", None)
        user_id, agent_id, session_id = self._resolve_scope(bot)

        now = datetime.now(timezone.utc)
        artifact_id = f"interactive-{uuid.uuid4().hex[:12]}"

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.INTERACTIVE,
            title=title or f"Interactive — {template.name}",
            created_at=now,
            updated_at=now,
            source_turn_id=None,
            created_by=ArtifactCreator.AGENT,
            definition={
                "html": html,
                "js_bundles": [b.model_dump() for b in bundles],
                "template": template.name,
                "libraries": libraries,
                "theme": theme,
            },
        )

        await self._artifact_store.save_artifact(user_id, agent_id, session_id, artifact)

        html_url = build_public_html_url(
            artifact_id, user_id=user_id, agent_id=agent_id, session_id=session_id,
        )
        return artifact_id, html_url
