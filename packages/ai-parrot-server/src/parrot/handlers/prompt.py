"""HTTP handler for runtime system-prompt fine-tuning — ``/api/v1/agents/prompt``.

Lets an authenticated user load the *current* prompt definition of a live
agent, edit every layer of its ``PromptBuilder`` (semantic fields **and** raw
layer templates), request LLM-assisted suggestions driven by a meta-prompting
framework document, test the edits against an ephemeral clone, and finally
save them onto the live in-memory instance.

The changes are **in-memory only** — they live on the ``BotManager``'s bot
instance for the process lifetime and are lost on restart. This is a
fine-tuning / playground surface, not a persistence layer.

Workflow (mirrors the phases requested in FEAT prompt-tuner):
    1. The user picks an agent (``{agent_name}`` in the URL).
    2. ``GET`` resolves the live instance from the ``BotManager``.
    3. ``GET`` returns every part that constitutes the agent's prompt
       (semantic fields + layer templates + the fully-rendered prompt).
    4. ``PATCH`` records edits in a per-user **session draft** (the in-memory
       working copy) without touching the live bot.
    5. ``POST .../suggest`` asks a lightweight LLM (Claude Haiku by default)
       — primed with the meta-prompting doc — to propose concrete edits.
    6. ``POST .../test`` builds an ephemeral clone with the draft applied and
       runs a query against it.
    7. ``POST .../save`` applies the draft to the live instance.

Routes:
    GET    /api/v1/agents/prompt/{agent_name}          — load current definition + draft
    PATCH  /api/v1/agents/prompt/{agent_name}          — merge edits into the draft
    POST   /api/v1/agents/prompt/{agent_name}/suggest  — LLM meta-prompting suggestions
    POST   /api/v1/agents/prompt/{agent_name}/test     — test the draft on a clone
    POST   /api/v1/agents/prompt/{agent_name}/save     — apply the draft to the live bot
    DELETE /api/v1/agents/prompt/{agent_name}          — discard the draft + test clone
"""
from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from aiohttp import web
from navconfig.logging import logging
from navigator_session import get_session
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session

from parrot.bots.dynamic_values import dynamic_values
from parrot.bots.prompts.layers import (
    PromptLayer,
    IDENTITY_LAYER,
    PRE_INSTRUCTIONS_LAYER,
    SECURITY_LAYER,
    KNOWLEDGE_LAYER,
    USER_SESSION_LAYER,
    TOOLS_LAYER,
    OUTPUT_LAYER,
    BEHAVIOR_LAYER,
)
from parrot.bots.prompts.domain_layers import _DOMAIN_LAYERS, KNOWLEDGE_SCOPE_LAYER
from parrot.clients.factory import LLMFactory

if TYPE_CHECKING:
    from ..manager import BotManager
    from parrot.bots.abstract import AbstractBot
    from parrot.bots.prompts.builder import PromptBuilder


# Session key prefix for the per-agent working draft.
DRAFT_PREFIX = "_prompt_draft_"

# Semantic personality fields that map onto CONFIGURE-phase layers.
SEMANTIC_FIELDS = ("role", "goal", "backstory", "rationale", "capabilities")

# Default lightweight LLM for the suggestion endpoint (env-overridable).
DEFAULT_TUNER_LLM = "claude:claude-haiku-4-5-20251001"

# Pristine (un-baked) layer templates keyed by layer name. Used to regenerate
# a layer's literal text when the user edits a semantic field, because the live
# builder's CONFIGURE layers are already baked (their $placeholders resolved).
_PRISTINE_LAYERS: Dict[str, PromptLayer] = {
    layer.name: layer
    for layer in (
        IDENTITY_LAYER,
        PRE_INSTRUCTIONS_LAYER,
        SECURITY_LAYER,
        KNOWLEDGE_LAYER,
        USER_SESSION_LAYER,
        TOOLS_LAYER,
        OUTPUT_LAYER,
        BEHAVIOR_LAYER,
    )
}
_PRISTINE_LAYERS.update(_DOMAIN_LAYERS)

# Which layer each semantic field feeds, and the $placeholder it fills.
# Editing any field in ``fields`` regenerates ``layer`` from its pristine
# template — but only if that layer actually exists in the bot's builder.
_FIELD_LAYERS: Dict[str, Dict[str, Any]] = {
    "identity": {
        "template": IDENTITY_LAYER.template,
        "fields": ("name", "role", "goal", "backstory"),
    },
    "behavior": {
        "template": BEHAVIOR_LAYER.template,
        "fields": ("rationale",),
    },
    "knowledge_scope": {
        "template": KNOWLEDGE_SCOPE_LAYER.template,
        "fields": ("capabilities",),
    },
    "pre_instructions": {
        "template": PRE_INSTRUCTIONS_LAYER.template,
        "fields": ("pre_instructions",),
    },
}


@is_authenticated()
@user_session()
class PromptTunerHandler(BaseView):
    """Runtime system-prompt fine-tuning console.

    Delegates instance lookup/cloning to ``BotManager`` (``app['bot_manager']``)
    and keeps per-user edits in the session so concurrent editors never collide.
    """

    _logger_name: str = "Parrot.PromptTunerHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # ------------------------------------------------------------------ #
    # Accessors                                                           #
    # ------------------------------------------------------------------ #
    @property
    def manager(self) -> Optional["BotManager"]:
        """Return the BotManager attached to the app, if any."""
        return self.request.app.get("bot_manager")

    def _agent_name(self) -> Optional[str]:
        """Extract ``agent_name`` from the URL path."""
        return self.request.match_info.get("agent_name") or None

    async def _get_session(self) -> Any:
        """Return the current aiohttp/navigator session."""
        with contextlib.suppress(AttributeError):
            return self.request.session or await get_session(self.request)
        return await get_session(self.request)

    # ------------------------------------------------------------------ #
    # Meta-prompting document (loaded lazily, cached on the app)          #
    # ------------------------------------------------------------------ #
    def _meta_doc(self) -> str:
        """Load the meta-prompting framework doc (system prompt for suggest).

        Cached on the app under ``_prompt_tuner_meta_doc``. The path is
        overridable via the ``PROMPT_TUNER_META_DOC`` env var.
        """
        cached = self.request.app.get("_prompt_tuner_meta_doc")
        if cached is not None:
            return cached
        path = os.getenv("PROMPT_TUNER_META_DOC") or str(
            Path(__file__).parent / "prompts" / "meta_prompting.md"
        )
        try:
            doc = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Could not load meta-prompting doc at %s: %s", path, exc)
            doc = (
                "You are a prompt-engineering assistant. Improve the agent's "
                "system prompt layers. Preserve $placeholder variables and the "
                "security guardrails. Return concrete, minimal edits."
            )
        self.request.app["_prompt_tuner_meta_doc"] = doc
        return doc

    # ------------------------------------------------------------------ #
    # Draft helpers                                                       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _draft_key(agent_name: str) -> str:
        return f"{DRAFT_PREFIX}{agent_name}"

    async def _load_draft(self, agent_name: str) -> Dict[str, Any]:
        """Return the session draft for ``agent_name`` (fresh if absent)."""
        session = await self._get_session()
        draft = session.get(self._draft_key(agent_name)) if session else None
        if not draft:
            draft = {"fields": {}, "layers": {}, "test_bot_name": None}
        # Defensive: guarantee the expected shape.
        draft.setdefault("fields", {})
        draft.setdefault("layers", {})
        draft.setdefault("test_bot_name", None)
        return draft

    async def _store_draft(self, agent_name: str, draft: Dict[str, Any]) -> None:
        session = await self._get_session()
        if session is not None:
            session[self._draft_key(agent_name)] = draft

    # ------------------------------------------------------------------ #
    # Prompt rendering / override machinery                               #
    # ------------------------------------------------------------------ #
    async def _dynamic_context(self) -> Dict[str, str]:
        """Resolve all registered dynamic values (e.g. ``$current_date``)."""
        ctx: Dict[str, str] = {}
        for name in dynamic_values.get_all_names():
            try:
                ctx[name] = await dynamic_values.get_value(name, {})
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("dynamic value '%s' failed: %s", name, exc)
                ctx[name] = ""
        return ctx

    @staticmethod
    def _current_fields(bot: "AbstractBot") -> Dict[str, Any]:
        """Read the agent's current semantic fields off the instance."""
        return {
            "name": getattr(bot, "name", ""),
            "role": getattr(bot, "role", "") or "",
            "goal": getattr(bot, "goal", "") or "",
            "backstory": getattr(bot, "backstory", "") or "",
            "rationale": getattr(bot, "rationale", "") or "",
            "capabilities": getattr(bot, "capabilities", "") or "",
            "pre_instructions": list(getattr(bot, "pre_instructions", []) or []),
        }

    def _effective_overrides(
        self,
        bot: "AbstractBot",
        draft: Dict[str, Any],
        dynamic_context: Dict[str, str],
    ) -> Dict[str, str]:
        """Compute the literal per-layer template overrides for a draft.

        Raw layer overrides (``draft['layers']``) win outright. For edited
        semantic fields, the feeding layer is regenerated from its pristine
        template with the merged field values substituted in (dynamic vars
        pre-resolved), but only when that layer is present in ``bot``'s builder
        and not already raw-overridden.
        """
        builder = bot.prompt_builder
        overrides: Dict[str, str] = dict(draft.get("layers", {}))
        if builder is None:
            return overrides

        edited = draft.get("fields", {})
        if not edited:
            return overrides

        present = set(builder.layer_names)
        merged = self._current_fields(bot)
        merged.update({k: v for k, v in edited.items() if k in merged})

        def _resolve(text: Any) -> str:
            text = "" if text is None else str(text)
            return Template(text).safe_substitute(dynamic_context) if text else text

        for layer_name, spec in _FIELD_LAYERS.items():
            if layer_name not in present or layer_name in overrides:
                continue
            if not any(f in edited for f in spec["fields"]):
                continue
            subs: Dict[str, str] = {}
            for field in spec["fields"]:
                if field == "pre_instructions":
                    items = merged.get("pre_instructions", []) or []
                    subs["pre_instructions_content"] = "\n".join(
                        f"- {item}" for item in items
                    )
                else:
                    subs[field] = _resolve(merged.get(field, ""))
            overrides[layer_name] = Template(spec["template"]).safe_substitute(**subs)
        return overrides

    @staticmethod
    def _apply_overrides(builder: "PromptBuilder", overrides: Dict[str, str]) -> List[str]:
        """Replace each named layer's template with a literal override.

        Returns the list of layer names that were not found (skipped).
        """
        skipped: List[str] = []
        for name, template in overrides.items():
            existing = builder.get(name)
            if existing is None:
                skipped.append(name)
                continue
            builder.replace(
                name,
                PromptLayer(
                    name=existing.name,
                    priority=existing.priority,
                    template=template,
                    phase=existing.phase,
                    condition=existing.condition,
                    required_vars=existing.required_vars,
                ),
            )
        return skipped

    async def _render_preview(self, bot: "AbstractBot", draft: Dict[str, Any]) -> str:
        """Render the draft-applied prompt without mutating the live bot."""
        builder = bot.prompt_builder
        if builder is None:
            # Legacy bot: single system_prompt string.
            return draft.get("fields", {}).get(
                "system_prompt", getattr(bot, "system_prompt", "") or ""
            )
        dynamic_context = await self._dynamic_context()
        overrides = self._effective_overrides(bot, draft, dynamic_context)
        preview = builder.clone()
        self._apply_overrides(preview, overrides)
        # Blank REQUEST-phase variables so the skeleton renders cleanly.
        request_ctx = {
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
            "output_instructions": "",
        }
        return preview.build(request_ctx)

    def _layers_payload(self, bot: "AbstractBot") -> List[Dict[str, Any]]:
        """Serialise the bot's current (baked) layers for the UI."""
        builder = bot.prompt_builder
        if builder is None:
            return []
        field_driven = set(_FIELD_LAYERS.keys())
        layers: List[Dict[str, Any]] = []
        sorted_layers = sorted(builder._layers.values(), key=lambda lyr: lyr.priority)
        for layer in sorted_layers:
            phase = getattr(layer.phase, "value", layer.phase)
            layers.append({
                "name": layer.name,
                "priority": int(layer.priority),
                "phase": str(phase),
                "template": layer.template,
                "field_driven": layer.name in field_driven,
            })
        return layers

    async def _apply_draft_to(self, bot: "AbstractBot", draft: Dict[str, Any]) -> List[str]:
        """Mutate ``bot`` (live or clone) with the draft. Returns skipped layers."""
        edited = draft.get("fields", {})
        for field in SEMANTIC_FIELDS:
            if field in edited:
                setattr(bot, field, edited[field])
        if "pre_instructions" in edited:
            value = edited["pre_instructions"]
            bot.pre_instructions = list(value) if isinstance(value, (list, tuple)) else [value]
        if bot.prompt_builder is None:
            if "system_prompt" in edited:
                bot.system_prompt = edited["system_prompt"]
            return []
        dynamic_context = await self._dynamic_context()
        overrides = self._effective_overrides(bot, draft, dynamic_context)
        return self._apply_overrides(bot.prompt_builder, overrides)

    # ------------------------------------------------------------------ #
    # GET — load current definition (phases 1-3)                          #
    # ------------------------------------------------------------------ #
    async def get(self) -> web.Response:
        """Return the agent's current prompt parts, rendered prompt, and draft."""
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(response={"message": "agent_name is required in URL"}, status=400)
        manager = self.manager
        if not manager:
            return self.error(response={"message": "BotManager is not installed."}, status=500)

        try:
            bot = await manager.get_bot(agent_name, request=self.request)
        except Exception as exc:
            return self._not_found_or_denied(agent_name, exc)
        if not bot:
            return self.error(response={"message": f"Agent '{agent_name}' not found"}, status=404)

        draft = await self._load_draft(agent_name)
        rendered = await self._render_preview(bot, draft)
        return self.json_response({
            "agent": agent_name,
            "has_prompt_builder": bot.prompt_builder is not None,
            "fields": self._current_fields(bot),
            "layers": self._layers_payload(bot),
            "rendered_prompt": rendered,
            "draft": draft,
            "note": (
                "Edits are in-memory only and lost on restart. Semantic fields "
                "(role/goal/backstory/rationale/capabilities) regenerate their "
                "feeding layer; everything else is editable via raw layer "
                "templates (keep $placeholders intact)."
            ),
        })

    # ------------------------------------------------------------------ #
    # PATCH — record edits into the draft (phase 4)                       #
    # ------------------------------------------------------------------ #
    async def patch(self) -> web.Response:
        """Merge ``{fields:{...}, layers:{...}}`` into the session draft."""
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(response={"message": "agent_name is required in URL"}, status=400)
        manager = self.manager
        if not manager:
            return self.error(response={"message": "BotManager is not installed."}, status=500)
        try:
            data = await self.request.json()
        except Exception:
            return self.error(response={"message": "Invalid JSON body"}, status=400)

        try:
            bot = await manager.get_bot(agent_name, request=self.request)
        except Exception as exc:
            return self._not_found_or_denied(agent_name, exc)
        if not bot:
            return self.error(response={"message": f"Agent '{agent_name}' not found"}, status=404)

        draft = await self._load_draft(agent_name)
        incoming_fields = data.get("fields") or {}
        incoming_layers = data.get("layers") or {}
        if not isinstance(incoming_fields, dict) or not isinstance(incoming_layers, dict):
            return self.error(
                response={"message": "'fields' and 'layers' must be objects"}, status=400
            )
        draft["fields"].update(incoming_fields)
        draft["layers"].update(incoming_layers)
        await self._store_draft(agent_name, draft)

        rendered = await self._render_preview(bot, draft)
        return self.json_response({
            "agent": agent_name,
            "draft": draft,
            "rendered_prompt": rendered,
        })

    # ------------------------------------------------------------------ #
    # POST — suggest / test / save (phases 5-7)                           #
    # ------------------------------------------------------------------ #
    async def post(self) -> web.Response:
        """Dispatch on the trailing path segment: suggest | test | save."""
        action = self.request.match_info.get("action")
        # When routed via the bare {agent_name} path, infer from URL tail.
        if action is None:
            tail = self.request.path.rstrip("/").rsplit("/", 1)[-1]
            action = tail if tail in {"suggest", "test", "save"} else "save"
        if action == "suggest":
            return await self._suggest()
        if action == "test":
            return await self._test()
        if action == "save":
            return await self._save()
        return self.error(response={"message": f"Unknown action '{action}'"}, status=400)

    async def _suggest(self) -> web.Response:
        """Ask the lightweight LLM for meta-prompting-driven edit suggestions."""
        agent_name = self._agent_name()
        manager = self.manager
        if not agent_name or not manager:
            return self.error(response={"message": "agent_name and BotManager required"}, status=400)
        try:
            data = await self.request.json()
        except Exception:
            data = {}
        instruction = data.get("instruction") or data.get("goal") or (
            "Improve clarity, specificity and consistency of this agent's prompt."
        )
        try:
            bot = await manager.get_bot(agent_name, request=self.request)
        except Exception as exc:
            return self._not_found_or_denied(agent_name, exc)
        if not bot:
            return self.error(response={"message": f"Agent '{agent_name}' not found"}, status=404)

        draft = await self._load_draft(agent_name)
        rendered = await self._render_preview(bot, draft)
        user_message = (
            f"# Tuning goal\n{instruction}\n\n"
            f"# Current semantic fields\n{self._current_fields(bot)}\n\n"
            f"# Pending draft edits\n{draft}\n\n"
            f"# Current rendered system prompt\n{rendered}\n\n"
            "Propose concrete edits per the output format."
        )
        llm = os.getenv("PROMPT_TUNER_LLM", DEFAULT_TUNER_LLM)
        try:
            client = LLMFactory.create(
                llm=llm,
                model_args={"temperature": 0.3, "max_tokens": 2000},
            )
            async with client:
                response = await client.ask(prompt=user_message, system_prompt=self._meta_doc())
        except Exception as exc:
            self.logger.exception("Suggestion LLM call failed")
            return self.error(response={"message": f"Suggestion failed: {exc}"}, status=502)

        content = getattr(response, "content", None)
        return self.json_response({
            "agent": agent_name,
            "instruction": instruction,
            "model": llm,
            "suggestions": str(content) if content is not None else str(response),
        })

    async def _test(self) -> web.Response:
        """Build an ephemeral clone with the draft applied and run a query."""
        agent_name = self._agent_name()
        manager = self.manager
        if not agent_name or not manager:
            return self.error(response={"message": "agent_name and BotManager required"}, status=400)
        try:
            data = await self.request.json()
        except Exception:
            return self.error(response={"message": "Invalid JSON body"}, status=400)
        query = data.get("query")
        if not query:
            return self.error(response={"message": "'query' field is required"}, status=400)

        draft = await self._load_draft(agent_name)
        session_id = uuid.uuid4().hex[:12]
        try:
            clone = await manager.get_bot(
                agent_name, new=True, session_id=session_id, request=self.request
            )
        except Exception as exc:
            return self._not_found_or_denied(agent_name, exc)
        if not clone:
            return self.error(response={"message": f"Agent '{agent_name}' not found"}, status=404)

        await self._apply_draft_to(clone, draft)
        draft["test_bot_name"] = clone.name
        await self._store_draft(agent_name, draft)

        user_session = await self._get_session()
        try:
            # AbstractBot.session reads request.session for context binding.
            setattr(self.request, "session", user_session)
            async with clone.session(request=self.request, app=self.request.app) as bot:
                response = await bot.ask(question=query)
        except Exception as exc:
            self.logger.exception("Test query failed for '%s'", agent_name)
            return self.error(response={"message": f"Test query failed: {exc}"}, status=500)

        content = getattr(response, "content", None)
        rendered = await self._render_preview(clone, draft)
        return self.json_response({
            "agent": agent_name,
            "clone": clone.name,
            "query": query,
            "response": str(content) if content is not None else str(response),
            "rendered_prompt": rendered,
        })

    async def _save(self) -> web.Response:
        """Apply the draft to the live in-memory instance (no persistence)."""
        agent_name = self._agent_name()
        manager = self.manager
        if not agent_name or not manager:
            return self.error(response={"message": "agent_name and BotManager required"}, status=400)

        draft = await self._load_draft(agent_name)
        if not draft.get("fields") and not draft.get("layers"):
            return self.error(response={"message": "Draft is empty — nothing to save"}, status=400)

        try:
            bot = await manager.get_bot(agent_name, request=self.request)
        except Exception as exc:
            return self._not_found_or_denied(agent_name, exc)
        if not bot:
            return self.error(response={"message": f"Agent '{agent_name}' not found"}, status=404)

        skipped = await self._apply_draft_to(bot, draft)
        rendered = await self._render_preview(bot, {"fields": {}, "layers": {}})

        # Clear the draft + discard any test clone now that changes are live.
        await self._discard(agent_name, draft)
        return self.json_response({
            "agent": agent_name,
            "saved": True,
            "skipped_layers": skipped,
            "rendered_prompt": rendered,
            "note": "Applied in-memory only; resets on server restart.",
        })

    # ------------------------------------------------------------------ #
    # DELETE — discard draft + test clone                                 #
    # ------------------------------------------------------------------ #
    async def delete(self) -> web.Response:
        """Discard the session draft and any ephemeral test clone."""
        agent_name = self._agent_name()
        if not agent_name:
            return self.error(response={"message": "agent_name is required in URL"}, status=400)
        draft = await self._load_draft(agent_name)
        await self._discard(agent_name, draft)
        return self.json_response({"agent": agent_name, "discarded": True})

    async def _discard(self, agent_name: str, draft: Dict[str, Any]) -> None:
        """Remove the draft from the session and any test clone from the manager."""
        test_bot = draft.get("test_bot_name")
        if test_bot and self.manager:
            with contextlib.suppress(KeyError):
                self.manager.remove_bot(test_bot)
        session = await self._get_session()
        if session is not None:
            with contextlib.suppress(KeyError, AttributeError):
                del session[self._draft_key(agent_name)]

    # ------------------------------------------------------------------ #
    # Error helpers                                                       #
    # ------------------------------------------------------------------ #
    def _not_found_or_denied(self, agent_name: str, exc: Exception) -> web.Response:
        """Map a get_bot failure onto a 403/404/500 response."""
        name = type(exc).__name__
        if name == "AgentAccessDenied":
            return self.error(response={"message": str(exc)}, status=403)
        if isinstance(exc, (LookupError, KeyError)):
            return self.error(
                response={"message": f"Agent '{agent_name}' not found"}, status=404
            )
        self.logger.exception("Error resolving agent '%s'", agent_name)
        return self.error(response={"message": f"Error resolving agent: {exc}"}, status=500)
