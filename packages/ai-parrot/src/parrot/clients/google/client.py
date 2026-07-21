from __future__ import annotations
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from collections import defaultdict
import copy
import difflib
import re
import asyncio
import inspect
import logging
import time
from pathlib import Path
import io
import uuid
from PIL import Image
from navconfig import config

# Lazy SDK guard: importing this module must not fail when google-genai is
# absent. Names resolve to ``None`` and ``_require_google_sdk()`` raises an
# actionable error the first time the client is instantiated.
try:
    from google import genai
    from google.genai.types import (
        GenerateContentConfig,
        HttpOptions,
        Part,
        ModelContent,
        UserContent,
        ThinkingConfig,
    )
    from google.oauth2 import service_account
    from google.genai import types

    _GOOGLE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when extra is missing
    genai = None  # type: ignore[assignment]
    GenerateContentConfig = None  # type: ignore[assignment]
    HttpOptions = None  # type: ignore[assignment]
    Part = None  # type: ignore[assignment]
    ModelContent = None  # type: ignore[assignment]
    UserContent = None  # type: ignore[assignment]
    ThinkingConfig = None  # type: ignore[assignment]
    service_account = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _GOOGLE_SDK_AVAILABLE = False


def _require_google_sdk() -> None:
    """Raise an actionable ImportError when google-genai is not installed."""
    if not _GOOGLE_SDK_AVAILABLE:
        raise ImportError(
            "GoogleGenAIClient requires the 'google-genai' SDK. " "Install with: pip install ai-parrot[google]"
        )


import pandas as pd
from ..base import AbstractClient, ToolDefinition, StreamingRetryConfig
from ...models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat,
    CompletionUsage,
    ObjectDetectionResult,
)
from ...models.responses import InvokeResult
from ...exceptions import InvokeError
from ...models.google import (
    GoogleModel,
    ALL_VOICE_PROFILES,
    VoiceRegistry,
)
from ...tools.abstract import AbstractTool, ToolResult
from ...core.exceptions import HumanInteractionInterrupt
from ...auth.credentials import CredentialRequired  # FEAT-264 — per-user cred gate
from ...security.redaction import OutputScrubber, ScrubPolicy  # FEAT-252 (TASK-1613)
from .analysis import GoogleAnalysis
from .generation import GoogleGeneration

logging.getLogger(name="PIL.TiffImagePlugin").setLevel(logging.ERROR)  # Suppress TiffImagePlugin warnings
logging.getLogger(name="google_genai").setLevel(logging.WARNING)  # Suppress GenAI warnings


# Sentinel returned by ``_create_simple_summary`` when the LLM consumed
# its full tool-calling budget without producing any synthesised text.
# Callers (e.g. ``PandasAgent``) can detect this exact string to surface
# a graceful "agent ran out of attempts" message instead of treating the
# tool-call trace as a real answer.
LLM_NO_FINAL_ANSWER = (
    "The model exhausted its tool-calling budget without producing a "
    "final answer. Please rephrase your question or try again."
)


class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.

    Only Gemini-2.5-pro works well with multi-turn function calling.
    Supports both API Key (Gemini Developer API) and Service Account (Vertex AI).

    **Combined tools + structured output**: for models whose identifier starts with a prefix
    in ``_default_combined_call_prefixes`` (default: ``gemini-3.1-pro``, ``gemini-3.5-flash``,
    ``gemini-3.1-flash-lite``), ``ask()`` and ``ask_stream()`` send ``tools`` and
    ``response_schema`` in a single ``GenerateContentConfig`` (no reformat round-trip).
    For all other models (e.g. ``gemini-2.5-pro``), the legacy two-phase flow is preserved.
    Override the whitelist per-instance via ``GoogleGenAIClient(combined_call_prefixes=...)``.
    """

    client_type: str = "google"
    client_name: str = "google"
    _default_model: str = GoogleModel.GEMINI_FLASH_LATEST.value
    _fallback_model: str = "gemini-3.1-flash-lite-preview"
    _model_garden: bool = False
    _lightweight_model: str = "gemini-3.1-flash-lite-preview"
    # Default prefixes for which tools + response_schema may be sent in a
    # single GenerateContentConfig (FEAT-193). Override per-subclass by
    # setting this attribute, or per-instance via the constructor kwarg
    # ``combined_call_prefixes``. Gemini 3.x models listed here have been
    # validated by upstream evaluation to accept both simultaneously.
    _default_combined_call_prefixes: tuple[str, ...] = (
        "gemini-3.1-pro",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    )
    _sensitive_tool_result_names: frozenset[str] = frozenset({"python_repl", "python_repl_pandas"})
    # Default model used to reformat tool-using responses into structured
    # output for models that cannot combine tools + response_schema in one
    # call (e.g., gemini-2.5-pro). Override per-instance via the
    # ``reformat_model`` constructor kwarg. DO NOT downgrade the default to
    # a smaller model (e.g. flash-lite): small models hallucinate rows when
    # extracting tabular data from a shape-annotated preview, corrupting
    # ``data``. Whitelisted Gemini 3.x models (configured via
    # ``combined_call_prefixes``) bypass this reformat step — see
    # ``_supports_combined_tools_and_schema``.
    _default_reformat_model: str = GoogleModel.GEMINI_3_FLASH_PREVIEW.value
    # FEAT-181: Gemini requires ≥4096 tokens for CachedContent resources
    _min_cache_tokens: int = 4096
    # Default TTL for CachedContent resources (5 minutes)
    _cache_ttl: str = "300s"

    def __init__(
        self,
        vertexai: bool = False,
        model_garden: bool = False,
        reformat_model: Optional[Union[str, GoogleModel]] = None,
        combined_call_prefixes: Optional[tuple[str, ...]] = None,
        **kwargs,
    ):
        _require_google_sdk()
        self.model_garden = model_garden
        self.vertexai: bool = True if model_garden else vertexai
        self.vertex_location = kwargs.get("location", config.get("VERTEX_REGION"))
        self.vertex_project = kwargs.get("project", config.get("VERTEX_PROJECT_ID"))
        self._credentials_file = kwargs.get(
            "credentials_file", config.get("VERTEX_CREDENTIALS_FILE") or config.get("GENAI_APPLICATION_CREDENTIALS")
        )
        if isinstance(self._credentials_file, str):
            self._credentials_file = Path(self._credentials_file).expanduser()

        self.api_key = kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))

        # Suppress httpcore logs as requested
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
        logging.getLogger("httpcore.http11").setLevel(logging.WARNING)

        super().__init__(**kwargs)
        self.max_tokens = kwargs.get("max_tokens", None)
        # Resolve reformat_model: explicit kwarg > class default. Accepts
        # both ``GoogleModel`` enum members and raw strings.
        self._reformat_model: str = self._as_model_str(reformat_model) or self._default_reformat_model
        # Resolve combined_call_prefixes: explicit kwarg > class default.
        # Coerce to tuple so callers can pass any sequence (list, tuple, generator).
        self._combined_call_prefixes: tuple[str, ...] = (
            tuple(combined_call_prefixes)
            if combined_call_prefixes is not None
            else self._default_combined_call_prefixes
        )
        #  Create a single instance of the Voice registry
        self.voice_db = VoiceRegistry(profiles=ALL_VOICE_PROFILES)
        # FEAT-252 (TASK-1613): single chokepoint scrubber for all response text.
        # Redaction is OPT-IN: default False; the owning bot (or a direct
        # ``enable_redaction=True`` kwarg) flags clients that must scrub.
        self.enable_redaction: bool = bool(kwargs.get("enable_redaction", False))
        self._scrubber: OutputScrubber = OutputScrubber(ScrubPolicy())
        # Echo-suppression threshold (fraction of tool-result chars that must appear
        # in candidate_text before it's classified as a tool echo). Conservative
        # default; expose as a config attribute for tuning (Open Q O2).
        self._echo_threshold: float = 0.85

    @staticmethod
    def _is_gemini3_model(model: str) -> bool:
        """Check if a model belongs to the Gemini 3.x family.

        Gemini 3.x models on Vertex AI require location='global'
        and preview variants need api_version='v1beta1'.
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return model.startswith("gemini-3")

    @staticmethod
    def _is_preview_model(model: str) -> bool:
        """Check if a model is a preview variant."""
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return "preview" in model

    # Maps the native computer-use predefined function names (returned by the
    # model) to the prefixed tool names registered by ComputerInteractionToolkit
    # (tool_prefix="computer"). The model never emits the "computer_" prefix, so
    # the dispatcher translates the call before resolving it in the ToolManager.
    _COMPUTER_USE_PREDEFINED_MAP = {
        "open_web_browser": "computer_open_browser",
        "wait_5_seconds": "computer_wait",
        "go_back": "computer_go_back",
        "go_forward": "computer_go_forward",
        "search": "computer_search",
        "navigate": "computer_navigate",
        "click_at": "computer_click_at",
        "hover_at": "computer_hover_at",
        "type_text_at": "computer_type_text_at",
        "key_combination": "computer_key_combination",
        "scroll_document": "computer_scroll_document",
        "scroll_at": "computer_scroll_at",
        "drag_and_drop": "computer_drag_and_drop",
    }

    @staticmethod
    def _requires_thinking(model: str) -> bool:
        """Check if a model only works in thinking mode (budget > 0).

        Gemini 2.5 Pro, Gemini 3.x Pro, and computer-use models are
        thinking-only and reject budget=0.
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return (
            model.startswith("gemini-2.5-pro")
            or model.startswith("gemini-3.1-pro")
            or model.startswith("gemini-3-pro")
            or GoogleGenAIClient._is_computer_use_model(model)
        )

    @staticmethod
    def _is_computer_use_model(model: str) -> bool:
        """Check if a model is a Gemini computer-use model.

        Computer-use models require the ``types.ComputerUse`` tool type in
        the GenerateContentConfig and return predefined function calls
        (click_at, type_text_at, etc.) rather than custom FunctionDeclarations.

        Args:
            model: Model identifier — accepts plain string, GoogleModel enum,
                or None (returns False for falsy inputs).

        Returns:
            True if the model is a computer-use model.
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model:
            return False
        return model.startswith("gemini-2.5-computer-use") or model.startswith("gemini-3-flash-preview")

    @staticmethod
    def _supports_combined_tools_and_schema(
        model: "str | GoogleModel | None",
        prefixes: "tuple[str, ...]",
    ) -> bool:
        """Whether ``model`` may receive tools + response_schema in a single call.

        Returns True when the normalised model identifier starts with any
        prefix in ``prefixes``. Pattern matches ``_is_gemini3_model`` and
        ``_requires_thinking`` for consistency.

        Args:
            model: Model identifier — accepts plain string, GoogleModel enum,
                or None (returns False for falsy inputs).
            prefixes: Tuple of model-name prefixes to match against. Pass an
                empty tuple to disable combined mode entirely (documented
                kill switch for ``combined_call_prefixes=()``).

        Returns:
            True iff ``model`` starts with any prefix in ``prefixes``.
        """
        model = GoogleGenAIClient._as_model_str(model)
        if not model or not prefixes:
            return False
        return any(model.startswith(p) for p in prefixes)

    @staticmethod
    def _as_model_str(model) -> str:
        """Normalize a model identifier to a plain string.

        Accepts ``GoogleModel`` enum instances (any variant imported under the
        class name — handles duplicate imports from stale build dirs), plain
        strings, and ``None``. Returns the ``.value`` for enums and ``""`` for
        falsy inputs so callers can safely chain ``.startswith`` etc.
        """
        if not model:
            return ""
        value = getattr(model, "value", model)
        return value if isinstance(value, str) else str(value)

    def _model_class_key(self, model: str) -> str:
        """Return a key representing the client configuration a model needs.

        Different model families may require different Vertex AI endpoints
        (location, API version). This key is used to invalidate the cached
        client when switching between incompatible model families.
        """
        if self._is_gemini3_model(model):
            suffix = "preview" if self._is_preview_model(model) else "stable"
            return f"gemini3_{suffix}"
        return "default"

    def _filter_get_client_hints(self, **hints: Any) -> dict:
        """Forward ``model`` hint to ``get_client()`` when present.

        Returns:
            A dict containing only ``model`` if it was supplied, otherwise
            an empty dict (matching ``get_client``'s optional ``model`` kwarg).
        """
        return {"model": hints["model"]} if "model" in hints else {}

    # ── FEAT-181: Gemini Prompt Caching ──────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using a conservative 4-chars-per-token heuristic.

        Args:
            text: Text to estimate token count for.

        Returns:
            Estimated number of tokens.
        """
        return len(text) // 4

    def _apply_cache_hints(self, payload: dict, segments: list) -> tuple:
        """Gemini cache translator — FEAT-181.

        Gemini requires explicit ``CachedContent`` resource creation when
        the cacheable token count meets or exceeds ``_min_cache_tokens``
        (default 4096).  Because resource creation is async, this method
        performs the threshold check synchronously and returns the cacheable
        segments as a local value so callers can pass them to
        ``_maybe_apply_gemini_cache()`` without concurrency hazards.

        CONCURRENCY NOTE: This method no longer uses ``self._pending_cache_segments``
        (which was a shared mutable instance attribute susceptible to race conditions
        when multiple coroutines share the same client instance). The segments are
        returned as the second element of a tuple and passed explicitly through the
        call chain.

        When the threshold is NOT met (or segments is empty), this method is
        a true no-op — the payload is returned unchanged and ``None`` is returned
        as the segments value.

        Args:
            payload: The request payload dict being assembled.
            segments: List of ``CacheableSegment`` produced by
                ``PromptBuilder.build_segments()``.  May be empty.

        Returns:
            Tuple of ``(payload, pending_segments)`` where ``pending_segments`` is
            the list of cacheable segments to pass to ``_maybe_apply_gemini_cache()``,
            or ``None`` when caching should be skipped.
        """
        if not segments:
            return payload, None

        # Only consider cacheable segments for the token estimate
        cacheable_text = "\n\n".join(s.text for s in segments if s.cacheable)
        est_tokens = self._estimate_tokens(cacheable_text)

        if est_tokens < self._min_cache_tokens:
            self.logger.debug(
                "Gemini prompt caching skipped: estimated %d tokens < threshold %d",
                est_tokens,
                self._min_cache_tokens,
            )
            return payload, None

        self.logger.debug(
            "Gemini prompt caching: %d cacheable tokens queued for CachedContent",
            est_tokens,
        )
        return payload, segments

    async def _maybe_apply_gemini_cache(
        self,
        client: Any,
        model: str,
        payload: dict,
        segments: list,
    ) -> dict:
        """Create a Gemini ``CachedContent`` resource and inject ``cached_content``.

        Called from ``generate_content`` call sites when segments is not None/empty.
        On any error the method logs at WARNING level and returns the payload unchanged
        (fail-open).

        CONCURRENCY NOTE: ``segments`` is now passed explicitly as a parameter instead
        of being read from ``self._pending_cache_segments``, eliminating the concurrency
        hazard when two coroutines share the same client instance.

        Args:
            client: The active ``genai.Client`` instance.
            model: Model name string (e.g. ``"gemini-2.5-flash"``).
            payload: The ``generate_content`` payload dict to update.
            segments: The cacheable segments returned by ``_apply_cache_hints()``.

        Returns:
            The (potentially updated) payload dict.
        """
        if not segments:
            return payload

        try:
            from google.genai import types as genai_types

            cacheable_text = "\n\n".join(s.text for s in segments if s.cacheable)
            cached = await client.aio.caches.create(
                model=model,
                config=genai_types.CreateCachedContentConfig(
                    system_instruction=cacheable_text,
                    ttl=self._cache_ttl,
                    display_name="parrot-prompt-cache",
                ),
            )
            payload["cached_content"] = cached.name
            self.logger.debug("Gemini CachedContent created: %s (model=%s)", cached.name, model)
        except Exception as exc:
            self.logger.warning(
                "Gemini CachedContent creation failed (proceeding without cache): %s",
                exc,
            )

        return payload

    # ── End FEAT-181 ──────────────────────────────────────────────────────────

    def _client_invalid_for_current(self, client: Any, **hints: Any) -> bool:
        """Return ``True`` when the cached client was built for a different model class.

        Compares the ``model_class`` key stored in the current loop's
        ``_LoopClientEntry.metadata`` with the model class implied by the
        incoming ``model`` hint.  Returns ``True`` (force rebuild) when the
        classes differ, and ``False`` (reuse) when they match or when no
        metadata is available yet.

        Args:
            client: The currently cached SDK client (unused directly; the
                metadata lives in the entry, not the client object).
            **hints: Hints from ``_ensure_client()``.  ``model`` is the
                key used to derive the desired model class.

        Returns:
            ``True`` if the client should be rebuilt; ``False`` otherwise.
        """
        model = hints.get("model") or self.model or self._default_model
        if isinstance(model, GoogleModel):
            model = model.value
        desired = self._model_class_key(model)
        loop = self._get_current_loop()
        if loop is None:
            return False
        # Note: the base class only invokes this hook when an entry already
        # exists for the current loop, so entry is guaranteed non-None here.
        entry = self._clients_by_loop.get(id(loop))
        if entry is None:
            return False  # no entry yet — base will build one; hook is moot
        cached = entry.metadata.get("model_class")
        return cached is not None and cached != desired

    async def _ensure_client(self, model: str = None, **hints: Any) -> genai.Client:  # type: ignore[override]
        """Return the loop-local GenAI client, rebuilding when the model class changes.

        Thin wrapper around the base ``_ensure_client`` that:
        - Folds the positional-style ``model`` kwarg into ``hints`` so existing
          call sites (``await self._ensure_client(model=...)``) keep working.
        - Stamps ``entry.metadata["model_class"]`` after each build/reuse so
          ``_client_invalid_for_current`` can compare on the next call.

        Args:
            model: Model name hint (forwarded to ``get_client`` via
                ``_filter_get_client_hints``).
            **hints: Additional hints (currently unused by this subclass).

        Returns:
            The loop-local ``genai.Client`` instance.
        """
        if model is not None:
            hints["model"] = model
        client = await super()._ensure_client(**hints)
        # Stamp the model-class on the entry ONLY when a model hint was
        # explicitly supplied.  Stamping with the instance default on hint-free
        # calls (e.g. deep_research / resume) would overwrite a Gemini-3.x
        # model_class with the default "default" key, causing a spurious
        # rebuild on the very next call that does pass a model hint.
        if "model" in hints:
            loop = asyncio.get_running_loop()
            entry = self._clients_by_loop.get(id(loop))
            if entry is not None:
                resolved = hints["model"]
                if isinstance(resolved, GoogleModel):
                    resolved = resolved.value
                entry.metadata["model_class"] = self._model_class_key(resolved)
        return client

    async def get_client(self, model: str = None, **kwargs) -> genai.Client:
        """Construct and return a fresh Google GenAI client for the current loop.

        Called by the base ``_ensure_client`` on a cache miss (or when
        ``_client_invalid_for_current`` signals staleness).  This method must
        NOT cache anything — the per-loop cache in ``AbstractClient`` handles
        that.

        Args:
            model: Model name to configure the client for. Gemini 3.x models
                   require location='global' on Vertex AI, and preview variants
                   additionally need api_version='v1beta1'.
            **kwargs: Extra keyword arguments forwarded to ``genai.Client``.

        Returns:
            A freshly constructed ``genai.Client`` instance.

        Raises:
            Exception: Re-raised from the Vertex AI client constructor on failure.
        """
        resolved_model = model or self.model or self._default_model
        # Normalize GoogleModel enum → string so downstream helpers
        # (_is_gemini3_model, _is_preview_model, …) that call .startswith()
        # on the value don't blow up with "'GoogleModel' object has no
        # attribute 'startswith'".
        if isinstance(resolved_model, GoogleModel):
            resolved_model = resolved_model.value

        if self.vertexai:
            location = self.vertex_location

            # Gemini 3.x family requires location='global' on Vertex AI
            if self._is_gemini3_model(resolved_model):
                location = "global"

            self.logger.info(f"Initializing Vertex AI for project {self.vertex_project} in {location}")
            try:
                if self._credentials_file and self._credentials_file.exists():
                    credentials = service_account.Credentials.from_service_account_file(
                        str(self._credentials_file),
                        scopes=["https://www.googleapis.com/auth/cloud-platform"],
                    )
                else:
                    credentials = None  # Use default credentials

                client_kwargs = {
                    "vertexai": True,
                    "project": self.vertex_project,
                    "location": location,
                    "credentials": credentials,
                }

                # Preview models require v1beta1 API version
                if self._is_preview_model(resolved_model):
                    client_kwargs["http_options"] = HttpOptions(api_version="v1beta1")

                client_kwargs.update(kwargs)
                return genai.Client(**client_kwargs)
            except Exception as exc:
                self.logger.error(f"Failed to initialize Vertex AI client: {exc}")
                raise
        return genai.Client(api_key=self.api_key, **kwargs)

    async def close(self) -> None:
        """Close all per-loop SDK clients.

        Delegates to the base class ``close_all()`` which safely handles dead
        or foreign loops without awaiting their coroutines.
        """
        await super().close_all()

    def _is_capacity_error(self, error: Exception) -> bool:
        """Return True when error indicates temporary model overload/high demand.

        Overrides base class with Google-specific detection markers.
        """
        error_text = str(error).lower()
        capacity_markers = (
            "503",
            "unavailable",
            "high demand",
            "model is overloaded",
            "experiencing high demand",
            "please try again later",
            "429",
            "rate limit",
            "rate_limit",
            "overloaded",
            "too many requests",
            "resource_exhausted",
        )
        return any(marker in error_text for marker in capacity_markers)

    def _retry_delay_from_error(self, retry_count: int, error: Union[Exception, str]) -> int:
        """Compute retry delay using exponential backoff and retryDelay hints."""
        error_text = str(error)
        delay = min(2 ** max(retry_count, 1), 60)
        try:
            match = re.search(r"retryDelay.*?(\d+)s", error_text, re.IGNORECASE)
            if match:
                hinted_delay = int(match.group(1)) + 1
                delay = max(delay, hinted_delay)
        except Exception:
            pass
        return delay

    def _should_use_fallback(self, model: str, error: Exception) -> bool:
        """Determine if fallback model should be used for Google models.

        Extends base class check with Google-specific constraint: only
        Gemini models can fallback to the Gemini fallback model.
        """
        if not model or not model.lower().startswith("gemini"):
            return False
        return super()._should_use_fallback(model, error)

    # Gemini function-name contract: start with a letter or underscore, then
    # only [a-zA-Z0-9_.:-], max length 128. Names that violate this trigger a
    # 400 INVALID_ARGUMENT that fails the *entire* request, so we normalise
    # every declaration name and keep a reverse map for the call round-trip.
    _INVALID_FUNCTION_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_.:-]")
    _VALID_FUNCTION_NAME_START = re.compile(r"[a-zA-Z_]")

    @classmethod
    def _sanitize_function_name(cls, name: str) -> str:
        """Coerce an arbitrary tool name into a Gemini-valid function name.

        Args:
            name: The raw tool name (``tool.name``).

        Returns:
            A name matching ``[a-zA-Z_][a-zA-Z0-9_.:-]{0,127}``. Names that are
            already valid are returned unchanged.
        """
        sanitized = cls._INVALID_FUNCTION_NAME_CHARS.sub("_", name or "")
        if not sanitized or not cls._VALID_FUNCTION_NAME_START.match(sanitized):
            sanitized = f"_{sanitized}"
        return sanitized[:128]

    def _register_sanitized_name(self, original: str) -> str:
        """Return a unique Gemini-valid alias for ``original`` and remember it.

        Populates ``self._sanitized_name_map`` (sanitized → original) so that
        ``_execute_tool`` can translate the model's call back to the real tool.
        If two distinct originals collapse to the same sanitized string, a
        numeric suffix disambiguates them.
        """
        name_map = self.__dict__.setdefault("_sanitized_name_map", {})
        safe = self._sanitize_function_name(original)
        if safe == original:
            # Still record identity so lookups are uniform and O(1).
            name_map[safe] = original
            return safe
        candidate = safe
        suffix = 1
        # Avoid clobbering a different original that already claimed this alias.
        while candidate in name_map and name_map[candidate] != original:
            tail = f"_{suffix}"
            candidate = f"{safe[:128 - len(tail)]}{tail}"
            suffix += 1
        name_map[candidate] = original
        return candidate

    def _fix_tool_schema(self, schema: dict):
        """Recursively converts schema type values to uppercase for GenAI compatibility."""
        if isinstance(schema, dict):
            for key, value in schema.items():
                if key == "type" and isinstance(value, str):
                    schema[key] = value.upper()
                else:
                    self._fix_tool_schema(value)
        elif isinstance(schema, list):
            for item in schema:
                self._fix_tool_schema(item)
        return schema

    def _analyze_prompt_for_tools(self, prompt: str) -> List[str]:
        """
        Analyze the prompt to determine which tools might be needed.
        This is a placeholder for more complex logic that could analyze the prompt.
        """
        prompt_lower = prompt.lower()
        # Keywords that suggest need for built-in tools
        search_keywords = ["search", "find", "google", "web", "internet", "latest", "news", "weather"]
        has_search_intent = any(keyword in prompt_lower for keyword in search_keywords)
        if has_search_intent:
            return "builtin_tools"
        else:
            # Mixed intent - prefer custom functions if available, otherwise builtin
            return "custom_functions"

    def _resolve_schema_refs(self, schema: dict, defs: dict = None) -> dict:
        """
        Recursively resolves $ref in JSON schema by inlining definitions.
        This is crucial for Pydantic v2 schemas used with Gemini.
        """
        if defs is None:
            defs = schema.get("$defs", schema.get("definitions", {}))

        if not isinstance(schema, dict):
            return schema

        # Handle $ref
        if "$ref" in schema:
            ref_path = schema["$ref"]
            # Extract definition name (e.g., "#/$defs/MyModel" -> "MyModel")
            def_name = ref_path.split("/")[-1]
            if def_name in defs:
                # Get the definition
                resolved = self._resolve_schema_refs(defs[def_name], defs)
                # Merge with any other properties in the current schema (rare but possible)
                merged = {k: v for k, v in schema.items() if k != "$ref"}
                merged.update(resolved)
                return merged

        # Process children
        new_schema = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                new_schema[key] = {k: self._resolve_schema_refs(v, defs) for k, v in value.items()}
            elif key == "items" and isinstance(value, dict):
                new_schema[key] = self._resolve_schema_refs(value, defs)
            elif key in ("anyOf", "allOf", "oneOf") and isinstance(value, list):
                new_schema[key] = [self._resolve_schema_refs(item, defs) for item in value]
            else:
                new_schema[key] = value

        return new_schema

    def clean_google_schema(self, schema: dict) -> dict:
        """
        Clean a Pydantic-generated schema for Google Function Calling compatibility.
        NOW INCLUDES: Reference resolution.
        """
        if not isinstance(schema, dict):
            return schema

        # 1. Resolve References FIRST
        # Pydantic v2 uses $defs, v1 uses definitions
        if "$defs" in schema or "definitions" in schema:
            schema = self._resolve_schema_refs(schema)

        cleaned = {}

        # Fields that Google Function Calling supports
        supported_fields = {"type", "description", "enum", "default", "properties", "required", "items"}

        # Copy supported fields
        for key, value in schema.items():
            if key in supported_fields:
                if key == "properties":
                    cleaned[key] = {k: self.clean_google_schema(v) for k, v in value.items()}
                elif key == "items":
                    cleaned[key] = self.clean_google_schema(value)
                else:
                    cleaned[key] = value

        # ... [Rest of your existing type conversion logic stays the same] ...
        if "type" in cleaned:
            if cleaned["type"] == "integer":
                cleaned["type"] = "number"  # Google prefers 'number' over 'integer'
            elif cleaned["type"] == "object" and "properties" not in cleaned:
                # Ensure objects have properties field, even if empty, to prevent confusion
                cleaned["properties"] = {}
            elif isinstance(cleaned["type"], list):
                non_null_types = [t for t in cleaned["type"] if t != "null"]
                cleaned["type"] = non_null_types[0] if non_null_types else "string"

        # Handle anyOf (union types) - Simplified for Gemini
        if "anyOf" in schema:
            # Pick the first non-null type, effectively flattening the union
            found_valid_option = False
            for option in schema["anyOf"]:
                if not isinstance(option, dict):
                    continue
                option_type = option.get("type")
                if option_type and option_type != "null":
                    cleaned["type"] = option_type
                    if option_type == "array" and "items" in option:
                        cleaned["items"] = self.clean_google_schema(option["items"])
                    if option_type == "object" and "properties" in option:
                        cleaned["properties"] = {
                            k: self.clean_google_schema(v) for k, v in option["properties"].items()
                        }
                        if "required" in option:
                            cleaned["required"] = option["required"]
                    found_valid_option = True
                    break

            if not found_valid_option:
                # If no valid option found (e.g. only nulls?), default to string
                cleaned["type"] = "string"

            # IMPORTANT: Remove anyOf after processing to avoid confusion
            cleaned.pop("anyOf", None)

        # Ensure type is present
        if "type" not in cleaned:
            # Heuristic: if properties exist, it's an object
            if "properties" in cleaned:
                cleaned["type"] = "object"
            elif "items" in cleaned:
                cleaned["type"] = "array"
            else:
                cleaned["type"] = "string"

        # Ensure object-like schemas always advertise an object type
        if "properties" in cleaned and cleaned.get("type") != "object":
            cleaned["type"] = "object"

        # Ensure objects always have a properties key (Gemini requires it).
        # This handles cases where `type: object` was set via anyOf processing
        # AFTER the earlier type-check block ran, so properties: {} was never added.
        if cleaned.get("type") == "object" and "properties" not in cleaned:
            cleaned["properties"] = {}

        # Gemini requires every array schema to carry an `items` schema and does
        # NOT understand `prefixItems` (the draft-2020-12 keyword Pydantic v2
        # emits for fixed-length tuples, e.g. `Tuple[float, float]`). Since
        # `prefixItems` is stripped below as unsupported, an array would be left
        # with no item schema at all — Google then rejects the whole request
        # with "...properties[<field>].items: missing field". Backfill `items`
        # from the first `prefixItems` entry (tuples are homogeneous in practice,
        # e.g. coordinate pairs), or fall back to a permissive string item.
        if cleaned.get("type") == "array" and "items" not in cleaned:
            prefix_items = schema.get("prefixItems")
            if isinstance(prefix_items, list) and prefix_items:
                cleaned["items"] = self.clean_google_schema(prefix_items[0])
            else:
                cleaned["items"] = {"type": "string"}

        # Vertex AI requires function parameters to be of type OBJECT.
        # Keep empty-property objects as OBJECT (don't coerce to string).

        # Remove problematic fields
        problematic_fields = {
            "prefixItems",
            "additionalItems",
            "minItems",
            "maxItems",
            "minLength",
            "maxLength",
            "pattern",
            "format",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "allOf",
            "anyOf",
            "oneOf",
            "not",
            "const",
            "examples",
            "$defs",
            "definitions",
            "$ref",
            "title",
            "additionalProperties",
        }

        for field in problematic_fields:
            cleaned.pop(field, None)

        return cleaned

    def _recursive_json_repair(self, data: Any) -> Any:
        """
        Traverses a dictionary/list and attempts to parse string values
        that look like JSON objects/lists.
        """
        if isinstance(data, dict):
            return {k: self._recursive_json_repair(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._recursive_json_repair(item) for item in data]
        elif isinstance(data, str):
            data = data.strip()
            # fast check if it looks like json
            if (data.startswith("{") and data.endswith("}")) or (data.startswith("[") and data.endswith("]")):
                try:
                    import json

                    parsed = json.loads(data)
                    # Recurse into the parsed object in case it has nested strings
                    return self._recursive_json_repair(parsed)
                except (json.JSONDecodeError, TypeError):
                    return data
        return data

    def _coerce_json_keys_to_str(self, data: Any) -> Any:
        """Recursively coerce mapping keys to strings for JSON compatibility."""
        if isinstance(data, dict):
            return {str(k): self._coerce_json_keys_to_str(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._coerce_json_keys_to_str(item) for item in data]
        if isinstance(data, tuple):
            return [self._coerce_json_keys_to_str(item) for item in data]
        if isinstance(data, set):
            return [self._coerce_json_keys_to_str(item) for item in data]
        return data

    def _apply_structured_output_schema(
        self, generation_config: Dict[str, Any], output_config: Optional[StructuredOutputConfig]
    ) -> Optional[Dict[str, Any]]:
        """Apply a cleaned structured output schema to the generationho config."""
        if not output_config or output_config.format != OutputFormat.JSON:
            return None

        try:
            raw_schema = output_config.get_schema()
            cleaned_schema = self.clean_google_schema(raw_schema)
            fixed_schema = self._fix_tool_schema(cleaned_schema)
        except Exception as exc:
            self.logger.error(f"Failed to generate structured output schema for Gemini: {exc}")
            return None

        generation_config["response_mime_type"] = "application/json"
        generation_config["response_schema"] = fixed_schema
        return fixed_schema

    async def _reformat_to_structured(
        self,
        text: str,
        output_config: Union[type, Any],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Reformat a free-text model response into structured output via a second LLM call.

        This is the legacy two-phase helper used by non-whitelisted models and as a
        recovery path when combined-mode parsing fails. It calls ``self._reformat_model``
        (a fast model without tools) and asks it to convert ``text`` into the JSON schema
        described by ``output_config``.

        Args:
            text: The free-text model response to reformat.
            output_config: A ``StructuredOutputConfig``, a Pydantic model class, or any
                object supported by ``_apply_structured_output_schema``.
            temperature: Override for the reformat call temperature.
            max_tokens: Override for the reformat call max_output_tokens.

        Returns:
            The parsed structured output (Pydantic model, dict, etc.) on success,
            or ``text`` unchanged if reformatting or parsing fails.
        """
        _max = max_tokens if max_tokens is not None else self.max_tokens
        structured_config: Dict[str, Any] = {
            "temperature": temperature if temperature is not None else self.temperature,
            "response_mime_type": "application/json",
        }
        if _max:
            structured_config["max_output_tokens"] = _max

        # Set the schema based on the type of output_config
        schema_config = (
            output_config
            if isinstance(output_config, StructuredOutputConfig)
            else self._get_structured_config(output_config)
        )
        if schema_config:
            self._apply_structured_output_schema(structured_config, schema_config)

        # CRITICAL: disable thinking for the reformat call.
        # Gemini 3 Flash defaults to thinking ON, which turns a
        # trivial string→JSON conversion into a multi-minute
        # reasoning exercise (observed: 10s–4min latency for
        # ~600 chars of input). Reformat is pure mechanical
        # schema-filling — we already pass `response_schema`
        # via `_apply_structured_output_schema`, so the model
        # has no structural decisions to make.
        # `_requires_thinking` is False for flash-preview, so
        # budget=0 is accepted. Do NOT remove this.
        reformat_model = self._reformat_model
        if not self._requires_thinking(reformat_model):
            structured_config["thinking_config"] = ThinkingConfig(thinking_budget=0)

        # Create a new client call without tools for structured output
        format_prompt = (
            "Convert the following response into the requested JSON structure.\n\n"
            "RULES (STRICT — violating these produces corrupted data):\n"
            "1. The `explanation` field MUST contain the COMPLETE original text "
            "verbatim — do NOT summarize, truncate, rewrite, or omit any part of it.\n"
            "2. NEVER invent, fabricate, extend, complete, infer, or 'fill in' any "
            "row, column, or value that is not literally present in the text below. "
            "If the text shows only N rows of a table, the `data` field must contain "
            "AT MOST those N rows — even if the text mentions that more rows exist "
            "(e.g. 'Shape: (21, 4)'). Do not guess the missing rows.\n"
            "3. If the text references a pandas variable holding the full result "
            "(e.g. `data_variable = 'foo'` or 'the full breakdown is in `foo`'), "
            "set `data_variable` to that exact variable name and leave `data` as "
            "null or an empty table. The caller will inject the full DataFrame "
            "from memory — you must not try to reconstruct it from the text.\n"
            "4. Only populate `data` from a markdown table when ALL of its rows are "
            "literally present in the text. When in doubt, prefer `data_variable` "
            "over `data`.\n\n"
            f"Return only the JSON object:\n\n{text}"
        )
        self.logger.debug(
            "Reformatting response as structured output using %s " "(thinking=%s, input_chars=%d)...",
            reformat_model,
            structured_config.get("thinking_config") and "off" or "default",
            len(format_prompt),
        )
        _reformat_start = time.perf_counter()
        structured_response = await self.client.aio.models.generate_content(
            model=reformat_model,
            contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
            config=GenerateContentConfig(**structured_config),
        )
        _reformat_elapsed = time.perf_counter() - _reformat_start
        self.logger.info(
            "Structured output reformatting complete in %.2fs",
            _reformat_elapsed,
        )

        # Extract and parse the structured text
        structured_text = self._safe_extract_text(structured_response)
        if not structured_text:
            self.logger.warning("No structured text received, falling back to original response")
            return text

        if isinstance(output_config, StructuredOutputConfig):
            return await self._parse_structured_output(structured_text, output_config)
        elif isinstance(output_config, type):
            if hasattr(output_config, "model_validate_json"):
                return output_config.model_validate_json(structured_text)
            elif hasattr(output_config, "model_validate"):
                parsed_json = self._json.loads(structured_text)
                return output_config.model_validate(parsed_json)
        return self._json.loads(structured_text)

    def _build_tools(self, tool_type: str, filter_names: Optional[List[str]] = None) -> Optional[List[types.Tool]]:
        """Build tools based on the specified type.

        Supports three tool types:
        - ``"custom_functions"`` — FunctionDeclaration tools from the ToolManager.
        - ``"builtin_tools"`` — Google Search builtin tool.
        - ``"computer_use"`` — ComputerUse tool for vision-based browser automation.
          Requires ``self._computer_use_config`` to be set (a
          :class:`~parrot_tools.computer.models.ComputerUseConfig` instance).

        Args:
            tool_type: One of ``"custom_functions"``, ``"builtin_tools"``,
                or ``"computer_use"``.
            filter_names: Optional list of tool names to include (custom_functions only).

        Returns:
            List of ``types.Tool`` instances, or None if tool_type is unrecognised.
        """
        if tool_type == "computer_use":
            # ComputerUse tool type for vision-based browser automation.
            # Requires self._computer_use_config (set by ComputerAgent or caller).
            config = getattr(self, "_computer_use_config", None)
            excluded = []
            if config is not None:
                excluded = getattr(config, "excluded_actions", [])
            try:
                computer_tool = types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                        excluded_predefined_functions=excluded,
                    )
                )
            except Exception as exc:
                self.logger.error("_build_tools(computer_use): failed to build ComputerUse tool: %s", exc)
                return None

            built = [computer_tool]
            # Append any *genuinely custom* function declarations (e.g.
            # computer_screenshot, computer_run_loop, scraping tools) so they
            # are still callable. The 13 predefined-equivalent toolkit tools
            # (computer_click_at, …) are dropped — the model invokes those via
            # the native ComputerUse tool instead, and sending duplicates only
            # confuses tool selection.
            predefined = set(self._COMPUTER_USE_PREDEFINED_MAP.values())
            try:
                custom = self._build_tools("custom_functions", filter_names=filter_names) or []
            except Exception as exc:
                # No ToolManager (e.g. bare client) or build failure — the
                # ComputerUse tool alone is still a valid request.
                self.logger.debug("_build_tools(computer_use): no custom functions appended: %s", exc)
                custom = []
            for tool in custom:
                decls = getattr(tool, "function_declarations", None) or []
                kept = [fd for fd in decls if fd.name not in predefined]
                if kept:
                    built.append(types.Tool(function_declarations=kept))
            return built

        if tool_type == "custom_functions":
            # migrate to use abstractool + tool definition:
            # Group function declarations by their category.
            #
            # Tools come from two sources for this build:
            #   1. ``self._request_tools`` — request-scoped tools passed via
            #      ``ask(tools=[...])``. Not registered in the ToolManager;
            #      live only for the duration of this call. Win on collisions.
            #   2. ``self.tool_manager.all_tools()`` — persistent tools.
            declarations_by_category = defaultdict(list)
            request_tools = getattr(self, "_request_tools", None) or {}
            seen_names: set = set()
            tool_sources = []
            tool_sources.extend(request_tools.values())
            tool_sources.extend(self.tool_manager.all_tools())
            for tool in tool_sources:
                tool_name = tool.name
                if tool_name in seen_names:
                    continue
                seen_names.add(tool_name)
                if filter_names is not None and tool_name not in filter_names:
                    continue

                tool_name = tool.name
                category = getattr(tool, "category", "tools")
                if isinstance(tool, AbstractTool):
                    full_schema = tool.get_schema()
                    tool_description = full_schema.get("description", tool.description)
                    # Extract ONLY the parameters part
                    schema = full_schema.get("parameters", {}).copy()
                    # Clean the schema for Google compatibility
                    schema = self.clean_google_schema(schema)
                elif isinstance(tool, ToolDefinition):
                    tool_description = tool.description
                    schema = self.clean_google_schema(tool.input_schema.copy())
                else:
                    # Fallback for other tool types
                    tool_description = getattr(tool, "description", f"Tool: {tool_name}")
                    schema = getattr(tool, "input_schema", {})
                    schema = self.clean_google_schema(schema)

                # Ensure we have a valid parameters schema
                if not schema:
                    schema = {"type": "object", "properties": {}, "required": []}
                try:
                    fixed_schema = self._fix_tool_schema(schema)
                    # Diagnostic: log the exact schema for tools known to cause issues
                    if tool_name in ("nav_execute_sql", "nav_create_program"):
                        import json as _json

                        try:
                            self.logger.debug(
                                "SCHEMA DECL [%s]: %s",
                                tool_name,
                                _json.dumps(fixed_schema, default=str)[:800],
                            )
                        except Exception:
                            pass
                    # Gemini rejects non-identifier function names with a 400
                    # that fails the whole request. Alias to a valid name and
                    # keep the reverse map so tool calls resolve back correctly.
                    safe_name = self._register_sanitized_name(tool_name)
                    if safe_name != tool_name:
                        self.logger.debug(
                            "Sanitized tool name for Gemini: %r -> %r",
                            tool_name,
                            safe_name,
                        )
                    declaration = types.FunctionDeclaration(
                        name=safe_name, description=tool_description, parameters=fixed_schema
                    )
                    declarations_by_category[category].append(declaration)
                except Exception as e:
                    self.logger.error(f"Error creating function declaration for {tool_name}: {e}")
                    # Skip this tool if it can't be created
                    continue

            tool_list = []
            for category, declarations in declarations_by_category.items():
                if declarations:
                    tool_list.append(types.Tool(function_declarations=declarations))
            return tool_list
        elif tool_type == "builtin_tools":
            return [
                types.Tool(google_search=types.GoogleSearch()),
            ]

        return None

    # Maximum characters per tool result sent back to the model.
    # ~200K chars ≈ 50K tokens; keeps aggregate well under the 1M limit.
    MAX_TOOL_RESULT_CHARS: int = 200_000

    def _truncate_large_result(self, data: Any, max_chars: int) -> Any:
        """Truncate a Python object so its JSON stays under *max_chars*.

        Strategy keeps the JSON structurally valid:
        * list  → binary-search for the max item count that fits.
        * dict  → find the largest list-valued key and trim that list.
        * other → fall back to a string slice (already the old behaviour).
        """

        def _fits(obj) -> tuple[bool, str]:
            """Return (fits?, serialized) for *obj*."""
            s = self._json.dumps(obj)
            return len(s) <= max_chars, s

        # --- list --------------------------------------------------------
        if isinstance(data, list):
            total = len(data)
            lo, hi, best = 0, total, 0
            while lo <= hi:
                mid = (lo + hi) // 2
                ok, _ = _fits(data[:mid])
                if ok:
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            # Guarantee at least 1 item so the model gets *something*
            best = max(best, 1)
            truncated = data[:best]
            if best < total:
                meta = {
                    "_truncated": True,
                    "_total_items": total,
                    "_kept_items": best,
                }
                truncated.append(meta)
            return truncated

        # --- dict with a dominant list value -----------------------------
        if isinstance(data, dict):
            # Find the key whose value is the largest list
            largest_key, largest_size = None, 0
            for k, v in data.items():
                if isinstance(v, list) and len(self._json.dumps(v)) > largest_size:
                    largest_key = k
                    largest_size = len(self._json.dumps(v))

            if largest_key is not None:
                # Budget = max_chars minus everything-except-the-list
                shell = {k: v for k, v in data.items() if k != largest_key}
                shell_size = len(self._json.dumps(shell))
                list_budget = max(max_chars - shell_size - 100, 1024)
                trimmed_list = self._truncate_large_result(data[largest_key], list_budget)
                result = dict(data)
                result[largest_key] = trimmed_list
                return result

        # --- fallback: stringify and slice -------------------------------
        s = self._json.dumps(data) if not isinstance(data, str) else data
        if len(s) > max_chars:
            return s[:max_chars] + "\n...[TRUNCATED]"
        return data

    def _extract_screenshot_bytes(self, result: Any) -> Optional[bytes]:
        """Extract raw PNG screenshot bytes from a computer-use tool result.

        Computer-use tools (e.g. ``click_at``, ``navigate``) return a dict
        that may contain a ``"screenshot_bytes"`` key with PNG bytes. This
        helper pulls those bytes out so the caller can wrap them in a
        ``FunctionResponseBlob`` instead of sending them as a JSON string.

        Also handles :class:`~parrot.tools.abstract.ToolResult` wrappers.

        Args:
            result: Raw tool result (dict, ToolResult, or any other type).

        Returns:
            PNG bytes if found, otherwise ``None``.
        """
        # Unwrap ToolResult
        if isinstance(result, ToolResult):
            result = result.result

        if not isinstance(result, dict):
            return None

        screenshot = result.get("screenshot_bytes")
        if isinstance(screenshot, (bytes, bytearray)):
            return bytes(screenshot)
        return None

    def _build_computer_use_function_response_part(
        self,
        tool_id: str,
        tool_name: str,
        result: Any,
    ) -> "Part":
        """Build a ``Part`` with ``FunctionResponse`` for a computer-use tool.

        When the tool result contains screenshot bytes, wraps them in a
        ``FunctionResponseBlob`` (``inline_data``) so Gemini can process
        the screenshot visually. Non-screenshot fields are sent as the
        ``response`` dict.

        Args:
            tool_id: The function call ID to correlate request and response.
            tool_name: Name of the computer-use tool that produced the result.
            result: Raw tool result (usually a dict from the backend).

        Returns:
            A ``Part`` with a populated ``function_response``.
        """
        screenshot_bytes = self._extract_screenshot_bytes(result)

        # Unwrap ToolResult for metadata access
        raw = result.result if isinstance(result, ToolResult) else result

        # Build the text response dict (URL, status, etc.) without the raw
        # screenshot bytes (which go into the blob instead).
        if isinstance(raw, dict):
            text_fields = {k: v for k, v in raw.items() if k != "screenshot_bytes"}
        else:
            text_fields = {"result": str(raw) if raw is not None else "ok"}

        if screenshot_bytes is not None:
            # Send screenshot as a FunctionResponseBlob so Gemini can see it.
            blob = types.FunctionResponseBlob(
                mime_type="image/png",
                data=screenshot_bytes,
            )
            return Part(
                function_response=types.FunctionResponse(
                    id=tool_id,
                    name=tool_name,
                    response=text_fields if text_fields else {"ok": True},
                    parts=[types.FunctionResponsePart(inline_data=blob)],
                )
            )
        else:
            # No screenshot — fall back to the standard JSON response.
            response_content = self._process_tool_result_for_api(result)
            return Part(
                function_response=types.FunctionResponse(
                    id=tool_id,
                    name=tool_name,
                    response=response_content,
                )
            )

    def _process_tool_result_for_api(self, result) -> dict:
        """Process tool result for Google Function Calling API compatibility.

        Serializes various Python objects into a JSON-compatible dict
        for the Google GenAI API. Results exceeding MAX_TOOL_RESULT_CHARS
        are truncated to prevent context-window overflow.
        """
        # 1. Handle exceptions and special wrapper types first
        if isinstance(result, Exception):
            return {"result": f"Tool execution failed: {str(result)}", "error": True}

        # Handle ToolResult wrapper
        if isinstance(result, ToolResult):
            content = result.result
            if result.metadata and "stdout" in result.metadata:
                # Prioritize stdout if exists
                content = result.metadata["stdout"]
            result = content  # The actual result to process is the content

        # Handle string results early (no conversion needed)
        if isinstance(result, str):
            result = self._scrubber.scrub(result, tool_name="tool_result")  # FEAT-252
            if not result.strip():
                return {"result": "Code executed successfully (no output)"}
            if len(result) > self.MAX_TOOL_RESULT_CHARS:
                result = result[: self.MAX_TOOL_RESULT_CHARS] + "\n...[TRUNCATED]"
            return {"result": result}

        # Convert complex types to basic Python types
        clean_result = result

        if isinstance(result, pd.DataFrame):
            # For large DataFrames, limit rows to prevent context overflow
            if len(result) > 500:
                self.logger.warning(f"DataFrame has {len(result)} rows, truncating to 500 " f"for API response")
                result = result.head(500)
            # Convert DataFrame to records and ensure all keys are strings
            records = result.to_dict(orient="records")
            clean_result = [{str(k): v for k, v in record.items()} for record in records]
        elif isinstance(result, list):
            # Handle lists (including lists of Pydantic models)
            clean_result = []
            for item in result:
                if hasattr(item, "model_dump"):  # Pydantic v2
                    clean_result.append(item.model_dump())
                elif hasattr(item, "dict"):  # Pydantic v1
                    clean_result.append(item.dict())
                else:
                    clean_result.append(item)
        elif hasattr(result, "model_dump"):  # Pydantic v2 single model
            clean_result = result.model_dump()
        elif hasattr(result, "dict"):  # Pydantic v1 single model
            clean_result = result.dict()

        clean_result = self._coerce_json_keys_to_str(clean_result)
        clean_result = self._scrubber.scrub(clean_result, tool_name="tool_result")  # FEAT-252

        # 4. Attempt to serialize the processed result
        try:
            serialized = self._json.dumps(clean_result)
            # --- truncation gate ---
            if len(serialized) > self.MAX_TOOL_RESULT_CHARS:
                self.logger.warning(
                    f"Tool result too large ({len(serialized)} chars), " f"truncating to {self.MAX_TOOL_RESULT_CHARS}"
                )
                truncated = self._truncate_large_result(clean_result, self.MAX_TOOL_RESULT_CHARS)
                return {"result": truncated}
            json_compatible_result = self._json.loads(serialized)
        except Exception as e:
            # This is the fallback for non-serializable objects (like PriceOutput)
            self.logger.warning(
                f"Could not serialize result of type {type(clean_result)} to JSON: {e}. "
                "Falling back to string representation."
            )
            fallback = self._scrubber.scrub(str(clean_result), tool_name="tool_result")  # FEAT-252
            if len(fallback) > self.MAX_TOOL_RESULT_CHARS:
                fallback = fallback[: self.MAX_TOOL_RESULT_CHARS] + "\n...[TRUNCATED]"
            json_compatible_result = fallback

        # Wrap for Google Function Calling format
        if isinstance(json_compatible_result, dict) and "result" in json_compatible_result:
            return json_compatible_result
        else:
            return {"result": json_compatible_result}

    def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str:
        """Create a short, human-readable summary of a tool result.

        Empty / None / `[]` / `{}` results are surfaced as the explicit
        sentinel ``"returned no data"`` instead of the literal string
        ``"None"``. Without this, Gemini-2.5-pro tends to treat a bare
        ``None`` as ambiguous and reply with imperative-to-self meta
        text ("If you have sufficient information, provide a final
        answer…") rather than reporting the empty result.
        """

        try:
            if result is None:
                return "returned no data"
            if isinstance(result, Exception):
                summary = f"Error: {result}"
            elif isinstance(result, pd.DataFrame):
                if result.empty:
                    return "returned no data (empty DataFrame)"
                preview = result.head(5)
                summary = preview.to_string(index=True)
            elif hasattr(result, "model_dump"):
                summary = self._json.dumps(self._coerce_json_keys_to_str(result.model_dump()))
            elif isinstance(result, (dict, list)):
                if not result:
                    return "returned no data (empty result)"
                summary = self._json.dumps(self._coerce_json_keys_to_str(result))
            else:
                summary = str(result)
        except Exception as exc:  # pylint: disable=broad-except
            summary = f"Unable to summarize result: {exc}"

        summary = self._scrubber.scrub(summary.strip() or "returned no data", tool_name="tool_summary")  # FEAT-252
        if len(summary) > max_length:
            summary = summary[:max_length].rstrip() + "…"
        return summary

    def _create_tool_summary_part(
        self, function_calls, tool_results, original_prompt: Optional[str] = None
    ) -> Optional[Part]:
        """Disabled. Returns ``None`` so the next-turn payload only carries
        the canonical ``function_response`` parts.

        Why: gemini-2.5-pro intermittently treats any extra text part appended
        after the tool responses as a section-header cue and echoes a chunk
        of it verbatim at the start of the visible answer. Both flavours
        observed:

        - ``Original Request: <prompt>`` → prompt-echo at the start of the
          response.
        - ``Tool execution summaries:\\n- <tool>: <truncated JSON>`` → a
          slice of the JSON tool dump prefixed to the response.

        The ``function_response`` parts already carry the tool output in the
        format Gemini consumes natively (see SDK
        ``tests/afc/test_generate_content_stream_afc_thoughts.py``), so the
        textual summary is redundant.

        Both call sites guard against ``None`` (``if summary_part :=`` and
        ``if summary_part:``), so no other code needs to change.
        """
        return None

    def _has_registered_tool(self, tool_name: str) -> bool:
        """Return True if ``tool_name`` is registered in the ToolManager."""
        tm = getattr(self, "tool_manager", None)
        if tm is None:
            return False
        try:
            return tm.get_tool(tool_name) is not None
        except Exception:
            return False

    @staticmethod
    def _adapt_computer_use_args(native_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt native computer-use call args to the toolkit method signature.

        Most predefined actions map 1:1 (coordinates are already 0-1000
        normalized, which the toolkit expects). Two need fixups:

        - ``wait_5_seconds`` takes no args natively → drop them (the toolkit's
          ``computer_wait`` defaults to ``seconds=5``).
        - ``key_combination`` may arrive as a list (``["control", "c"]``) or a
          ``"+"``-joined string; the toolkit expects a comma-separated string.
        """
        if native_name == "wait_5_seconds":
            return {}
        if native_name == "key_combination":
            keys = args.get("keys")
            if isinstance(keys, (list, tuple)):
                args["keys"] = ",".join(str(k) for k in keys)
            elif isinstance(keys, str) and "+" in keys:
                args["keys"] = ",".join(k.strip() for k in keys.split("+"))
        return args

    async def _execute_computer_use_call(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Execute a single computer-use function call, handling safety.

        The model embeds an optional ``safety_decision`` object inside the
        call args (``{"explanation": ..., "decision": "require_confirmation"}``).
        That key is NOT a tool parameter, so it is always stripped before
        dispatch. When the decision requires confirmation, a configured
        ``_computer_use_safety_handler`` is consulted (e.g. ComputerAgent's
        HITL handler); on approval the action runs and the result is tagged
        with ``safety_acknowledgement="true"`` so the API call is accepted, on
        rejection the action is skipped and a refusal is returned.
        """
        args = dict(args or {})
        safety = args.pop("safety_decision", None)
        acknowledged = False
        if isinstance(safety, dict) and safety.get("decision") == "require_confirmation":
            approved = await self._confirm_computer_use_safety(tool_name, safety, args)
            if not approved:
                self.logger.warning("Computer-use action %r rejected by safety confirmation.", tool_name)
                return {
                    "error": "rejected_by_user",
                    "message": "The user did not approve this action.",
                    "safety_acknowledgement": "false",
                }
            acknowledged = True

        result = await self._execute_tool(tool_name, args)

        if acknowledged and isinstance(result, dict):
            result["safety_acknowledgement"] = "true"
        return result

    async def _confirm_computer_use_safety(self, tool_name: str, safety: Dict[str, Any], args: Dict[str, Any]) -> bool:
        """Ask the configured handler whether a flagged action may proceed.

        Returns True (proceed) when no handler is configured — preserving the
        previous auto-acknowledge behaviour — and otherwise defers to
        ``self._computer_use_safety_handler`` (sync or async).
        """
        handler = getattr(self, "_computer_use_safety_handler", None)
        decision = {
            "tool": tool_name,
            "arguments": args,
            "explanation": safety.get("explanation", ""),
            "decision": safety.get("decision"),
        }
        if handler is None:
            self.logger.warning(
                "Computer-use safety_decision auto-acknowledged (no handler set): %s",
                decision,
            )
            return True
        try:
            res = handler(decision)
            if inspect.isawaitable(res):
                res = await res
            return bool(res)
        except Exception as exc:
            self.logger.error("Computer-use safety handler raised (denying action): %s", exc)
            return False

    async def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        tool_context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Resolve and execute a tool.

        Request-scoped tools (passed via ``ask(tools=[...])`` and held in
        ``self._request_tools`` for the duration of one call) are checked
        first and executed directly via ``AbstractTool.execute()`` — they
        are not registered in the ToolManager. If the name is not found
        in the overlay, fall through to the base implementation which
        dispatches via ``self.tool_manager``.
        """
        # Translate any Gemini-sanitized alias back to the real tool name so
        # request-scoped and ToolManager lookups (keyed by the original name)
        # succeed. Identity entries make this a no-op for already-valid names.
        name_map = getattr(self, "_sanitized_name_map", None)
        if name_map:
            tool_name = name_map.get(tool_name, tool_name)

        # Translate native computer-use predefined function calls (click_at,
        # type_text_at, …) to the prefixed ComputerInteractionToolkit tools
        # (computer_click_at, …) that are actually registered. Only applied
        # when the mapped tool exists, so non-computer agents are unaffected.
        mapped = self._COMPUTER_USE_PREDEFINED_MAP.get(tool_name)
        if mapped is not None and self._has_registered_tool(mapped):
            parameters = self._adapt_computer_use_args(tool_name, dict(parameters or {}))
            tool_name = mapped

        request_tools = getattr(self, "_request_tools", None) or {}
        if tool_name in request_tools:
            tool = request_tools[tool_name]
            ctx = tool_context or getattr(self, "_tool_context", None)
            if ctx:
                # Filter ctx keys to those the tool actually declares —
                # request-scoped tools that don't accept ``user_id`` /
                # ``session_id`` would otherwise raise ``TypeError``.
                accepted = self._tool_param_names(tool_name)
                if accepted is None:
                    filtered_ctx = ctx
                else:
                    filtered_ctx = {k: v for k, v in ctx.items() if k in accepted}
                merged = {**filtered_ctx, **parameters}
            else:
                merged = dict(parameters)
            perm_ctx = getattr(self, "_permission_context", None)
            if perm_ctx is not None:
                merged["_permission_context"] = perm_ctx
            try:
                result = await tool.execute(**merged)
                if isinstance(result, ToolResult):
                    if result.status == "error":
                        raise ValueError(result.error)
                    return result.result
                return result
            except Exception as exc:
                self.logger.error(
                    "Error executing request-scoped tool %s: %s",
                    tool_name,
                    exc,
                )
                raise
        return await super()._execute_tool(tool_name, parameters, tool_context)

    async def _handle_multiturn_function_calls(
        self,
        chat,
        initial_response,
        all_tool_calls: List[ToolCall],
        original_prompt: Optional[str] = None,
        model: str = None,
        max_iterations: int = 15,
        config: GenerateContentConfig = None,
        max_retries: int = 3,
        lazy_loading: bool = False,
        active_tool_names: Optional[set] = None,
        session_id: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        stop_tools: Optional[set] = None,
    ) -> Any:
        """
        Simple multi-turn function calling - just keep going until no more function calls.

        Args:
            stop_tools: Tool names that signal the loop should end. When a
                stop tool executes successfully its result is still sent back
                to the model, but further tool-calling is disabled so the
                model must produce a final text answer on the next turn.
        """
        current_response = initial_response
        current_config = config
        iteration = 0

        if active_tool_names is None:
            active_tool_names = set()

        model = model or self.model
        self.logger.info("Starting simple multi-turn function calling loop")

        while iteration < max_iterations:
            iteration += 1

            # Get function calls (including converted from tool_code)
            function_calls = self._get_function_calls_from_response(current_response)
            if not function_calls:
                # Check if we have any text content in the response
                final_text = self._safe_extract_text(current_response)
                self.logger.notice(f"🎯 Final Response from Gemini: {final_text[:200]}...")
                if not final_text and all_tool_calls:
                    # Detect MALFORMED_FUNCTION_CALL — happens when the model tries to
                    # call a tool whose name or schema doesn't match the declared tools
                    # (e.g. a skill body that references a tool with the wrong name).
                    finish_reason_str = ""
                    try:
                        if hasattr(current_response, "candidates") and current_response.candidates:
                            fr = getattr(current_response.candidates[0], "finish_reason", None)
                            finish_reason_str = str(fr) if fr else ""
                    except Exception:
                        pass

                    if "MALFORMED_FUNCTION_CALL" in finish_reason_str:
                        skill_calls = [tc for tc in all_tool_calls if tc.name == "load_skill"]
                        if skill_calls:
                            skill_name = (
                                skill_calls[0].arguments.get("name", "unknown")
                                if isinstance(skill_calls[0].arguments, dict)
                                else "unknown"
                            )
                            self.logger.error(
                                "Skill '%s' loaded but subsequent tool call was malformed "
                                "(tool name in skill content does not match any declared tool). "
                                "Returning error to user.",
                                skill_name,
                            )
                        else:
                            self.logger.error(
                                "MALFORMED_FUNCTION_CALL after tools %s — "
                                "model tried to call a tool not in the declared schema.",
                                [tc.name for tc in all_tool_calls],
                            )
                    else:
                        self.logger.warning(
                            "Final response is empty after tool execution. "
                            "Skipping forced synthesis to avoid unnecessary delays."
                        )
                    # try:
                    #     synthesis_prompt = """
                    # Please now generate the complete response based on all the information gathered from the tools.
                    # Provide a comprehensive answer to the original request.
                    # Synthesize the data and provide insights, analysis, and conclusions as appropriate.
                    #     """
                    #     current_response = await chat.send_message(
                    #         synthesis_prompt,
                    #         config=current_config
                    #     )
                    #     # Check if this worked
                    #     synthesis_text = self._safe_extract_text(current_response)
                    #     if synthesis_text:
                    #         self.logger.info("Successfully generated synthesis response")
                    #     else:
                    #         self.logger.warning("Synthesis attempt also returned empty response")
                    # except Exception as e:
                    #     self.logger.error(f"Synthesis attempt failed: {e}")

                self.logger.info(f"No function calls found - completed after {iteration-1} iterations")
                break

            self.logger.info(f"Iteration {iteration}: Processing {len(function_calls)} function calls")

            # Execute function calls
            tool_call_objects = []
            for fc in function_calls:
                tc = ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=fc.name,
                    arguments=dict(fc.args) if hasattr(fc.args, "items") else fc.args,
                )
                tool_call_objects.append(tc)

            if messages is not None:
                messages.append(
                    {
                        "role": "model",
                        "function_calls": [
                            {"name": fc.name, "arguments": dict(fc.args) if hasattr(fc.args, "items") else fc.args}
                            for fc in function_calls
                        ],
                    }
                )

            # Execute tools
            start_time = time.time()
            if self._is_computer_use_model(model):
                # Computer-use calls carry an optional ``safety_decision`` in
                # their args. Each is handled sequentially (a confirmation may
                # block on human input) — see _execute_computer_use_call.
                tool_results = []
                for fc in function_calls:
                    try:
                        tool_results.append(
                            await self._execute_computer_use_call(
                                fc.name,
                                dict(fc.args) if hasattr(fc.args, "items") else (fc.args or {}),
                            )
                        )
                    except Exception as exc:  # mirror gather(return_exceptions=True)
                        tool_results.append(exc)
            else:
                tool_execution_tasks = [
                    self._execute_tool(fc.name, dict(fc.args) if hasattr(fc.args, "items") else fc.args)
                    for fc in function_calls
                ]
                tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)
            execution_time = time.time() - start_time

            # Lazy Loading Check
            if lazy_loading:
                found_new = False
                for fc, result in zip(function_calls, tool_results):
                    if fc.name == "search_tools" and isinstance(result, str):
                        new_tools = self._check_new_tools(fc.name, result)
                        for nt in new_tools:
                            if nt not in active_tool_names:
                                active_tool_names.add(nt)
                                found_new = True

                if found_new:
                    # Rebuild tools with expanded set
                    new_tools_list = self._build_tools("custom_functions", filter_names=list(active_tool_names))
                    current_config.tools = new_tools_list
                    self.logger.info(f"Updated tools for next turn. Count: {len(active_tool_names)}")

            # Update tool call objects
            for tc, result in zip(tool_call_objects, tool_results):
                tc.execution_time = execution_time / len(tool_call_objects)
                if isinstance(result, HumanInteractionInterrupt):
                    result.session_id = session_id
                    result.messages = messages.copy() if messages else []
                    result.tool_call_id = tc.id
                    result.agent_name = getattr(self, "name", "Google_Agent")
                    raise result
                elif isinstance(result, CredentialRequired):
                    # FEAT-264: a per-user credential is missing. Propagate
                    # (like HumanInteractionInterrupt) so the surface bridge
                    # (e.g. MSAgentSDK) can emit a sign-in / capture card
                    # instead of feeding the error back to the model.
                    raise result
                elif isinstance(result, Exception):
                    tc.error = str(result)
                    self.logger.error(f"Tool {tc.name} failed: {result}")
                else:
                    tc.result = self._scrubber.scrub(result, tool_name=tc.name)  # FEAT-252
                    # self.logger.info(f"Tool {tc.name} result: {result}")

            all_tool_calls.extend(tool_call_objects)

            # After the first tool round, relax function-calling to AUTO so the
            # model can synthesize a final text answer. ANY was only used on
            # the initial turn to guarantee the model started calling tools.
            fcc = getattr(getattr(current_config, "tool_config", None), "function_calling_config", None)
            if fcc is not None and getattr(fcc, "mode", None) == types.FunctionCallingConfigMode.ANY:
                fcc.mode = types.FunctionCallingConfigMode.AUTO

            # Stop-tool check: if a stop tool executed successfully, disable
            # further tool-calling so the model produces a final text answer
            # on the next turn (its result is still sent back for synthesis).
            stop_tool_fired = False
            if stop_tools:
                for tc in tool_call_objects:
                    if tc.name in stop_tools and tc.error is None:
                        stop_tool_fired = True
                        self.logger.info(
                            "Stop tool '%s' fired — disabling further tool calls.",
                            tc.name,
                        )
                        break
                if stop_tool_fired:
                    fcc = getattr(
                        getattr(current_config, "tool_config", None),
                        "function_calling_config",
                        None,
                    )
                    if fcc is not None:
                        fcc.mode = types.FunctionCallingConfigMode.NONE
                    else:
                        current_config.tools = None

            is_computer_use = self._is_computer_use_model(model)
            function_response_parts = []
            for fc, result in zip(function_calls, tool_results):
                tool_id = fc.id or f"call_{uuid.uuid4().hex[:8]}"
                self.logger.notice(f"🔍 Tool: {fc.name}")
                self.logger.notice(f"📤 Raw Result Type: {type(result)}")

                try:
                    # Debug log first 20 chars of result
                    result_preview = self._scrubber.scrub(str(result), tool_name=fc.name)[:20]  # FEAT-252
                    self.logger.notice(f"Tool {fc.name} output preview: {result_preview}...")

                    if is_computer_use:
                        # Computer-use tools may return screenshot bytes that
                        # must be wrapped in FunctionResponseBlob so Gemini
                        # can process the screenshot visually.
                        part = self._build_computer_use_function_response_part(tool_id, fc.name, result)
                    else:
                        response_content = self._process_tool_result_for_api(result)
                        part = Part(
                            function_response=types.FunctionResponse(
                                id=tool_id,
                                name=fc.name,
                                response=response_content,
                            )
                        )

                    function_response_parts.append(part)

                except Exception as e:
                    self.logger.error(f"Error processing result for tool {fc.name}: {e}")
                    function_response_parts.append(
                        Part(
                            function_response=types.FunctionResponse(
                                id=tool_id, name=fc.name, response={"result": f"Tool error: {str(e)}", "error": True}
                            )
                        )
                    )

            summary_part = self._create_tool_summary_part(function_calls, tool_results, original_prompt)
            # Combine the tool results with the textual summary prompt
            next_prompt_parts = function_response_parts.copy()
            if summary_part:
                next_prompt_parts.append(summary_part)

            # Send responses back
            retry_count = 0
            try:
                self.logger.debug(f"Sending {len(next_prompt_parts)} responses back to model")
                while retry_count < max_retries:
                    try:
                        current_response = await chat.send_message(next_prompt_parts, config=current_config)
                        finish_reason = getattr(current_response.candidates[0], "finish_reason", None)
                        if finish_reason:
                            if finish_reason.name == "MAX_TOKENS" and current_config.max_output_tokens < 8192:
                                self.logger.warning("Hit MAX_TOKENS limit. Retrying with increased token limit.")
                                retry_count += 1
                                current_config.max_output_tokens = 8192
                                continue
                            elif finish_reason.name == "MALFORMED_FUNCTION_CALL":
                                # Diagnose: try to extract which tool was attempted
                                try:
                                    cand = current_response.candidates[0]
                                    n_cands = len(current_response.candidates)
                                    content = getattr(cand, "content", None)
                                    self.logger.error(
                                        "MALFORMED details: candidates=%d, content=%s",
                                        n_cands,
                                        type(content).__name__ if content else "None",
                                    )
                                    if content and hasattr(content, "parts"):
                                        for p in content.parts or []:
                                            if hasattr(p, "function_call") and p.function_call:
                                                fc = p.function_call
                                                self.logger.error(
                                                    "MALFORMED call: tool=%s args=%s",
                                                    getattr(fc, "name", "?"),
                                                    dict(fc.args) if hasattr(fc.args, "items") else str(fc.args),
                                                )
                                            elif hasattr(p, "text") and p.text:
                                                self.logger.error("MALFORMED part text: %s", str(p.text)[:200])
                                    # Also log what we sent (function responses)
                                    for part in next_prompt_parts:
                                        try:
                                            fr = getattr(part, "function_response", None)
                                            if fr:
                                                self.logger.error(
                                                    "MALFORMED context — sent FunctionResponse: name=%s response_keys=%s",
                                                    getattr(fr, "name", "?"),
                                                    list((getattr(fr, "response", None) or {}).keys()),
                                                )
                                        except Exception:
                                            pass
                                except Exception as _diag_exc:
                                    self.logger.error("MALFORMED diagnostic failed: %s", _diag_exc)
                                self.logger.warning("Malformed function call detected. Retrying...")
                                retry_count += 1
                                await asyncio.sleep(2**retry_count)
                                continue
                        break
                    except Exception as e:
                        error_str = str(e)
                        retry_count += 1
                        delay = self._retry_delay_from_error(retry_count, e)
                        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                            self.logger.warning(
                                "Rate limited (429). Waiting %ss before retry %d/%d",
                                delay,
                                retry_count,
                                max_retries,
                            )
                        elif self._is_capacity_error(e):
                            self.logger.warning(
                                "Google model under high demand (503/UNAVAILABLE). " "Waiting %ss before retry %d/%d.",
                                delay,
                                retry_count,
                                max_retries,
                            )
                        else:
                            self.logger.error(f"Error sending message: {e}")
                        if retry_count >= max_retries:
                            self.logger.error("Max retries reached, aborting")
                            raise e
                        await asyncio.sleep(delay)

                # Check for UNEXPECTED_TOOL_CALL error
                if (
                    hasattr(current_response, "candidates")
                    and current_response.candidates
                    and hasattr(current_response.candidates[0], "finish_reason")
                ):

                    finish_reason = current_response.candidates[0].finish_reason

                    if str(finish_reason) == "FinishReason.UNEXPECTED_TOOL_CALL":
                        self.logger.warning("Received UNEXPECTED_TOOL_CALL")

                # Debug what we got back — lightweight check that avoids
                # alarming warnings from _safe_extract_text on function-call responses.
                try:
                    next_fc = self._get_function_calls_from_response(current_response)
                    if next_fc:
                        names = [fc.name for fc in next_fc]
                        self.logger.debug(f"Model requested {len(next_fc)} more tool call(s): {names}")
                    else:
                        preview_text = self._safe_extract_text(current_response)
                        preview = preview_text[:100] if preview_text else "(empty)"
                        self.logger.debug(f"Response preview: {preview}")
                except Exception as e:
                    self.logger.debug(f"Could not preview response: {e}")

            except Exception as e:
                self.logger.error(f"Failed to send responses back: {e}")
                break

        # If the loop exited because it hit the iteration cap while the model
        # was STILL requesting tools, force one final synthesis turn with
        # tool-calling disabled. Otherwise we return a function-call-only
        # response with no text, and the caller is left to reformat raw tool
        # output into the answer (producing garbage such as a column dump).
        if iteration >= max_iterations and self._get_function_calls_from_response(current_response):
            self.logger.warning(
                "Reached max_iterations (%d) with the model still requesting "
                "tools — forcing a final tool-free synthesis turn.",
                max_iterations,
            )
            try:
                # Forbid further tool calls so the model must produce text.
                fcc = getattr(
                    getattr(current_config, "tool_config", None),
                    "function_calling_config",
                    None,
                )
                if fcc is not None:
                    fcc.mode = types.FunctionCallingConfigMode.NONE
                else:
                    current_config.tools = None
                synthesis_prompt = (
                    "You have reached the maximum number of tool calls allowed "
                    "for this turn. Do NOT request any more tools. Using ONLY "
                    "the information already gathered from the tool outputs "
                    "above, write your final answer to the user's original "
                    "question now. If what you gathered is not enough to fully "
                    "answer, say so explicitly and summarize what you did find."
                )
                current_response = await chat.send_message(synthesis_prompt, config=current_config)
            except Exception as e:
                self.logger.error("Forced synthesis turn failed: %s", e)

        self.logger.info(f"Completed with {len(all_tool_calls)} total tool calls")
        return current_response

    def _parse_tool_code_blocks(self, text: str) -> List:
        """Convert tool_code blocks to function call objects."""
        function_calls = []

        if "```tool_code" not in text:
            return function_calls

        # Simple regex to extract tool calls
        pattern = r"```tool_code\s*\n\s*print\(default_api\.(\w+)\((.*?)\)\)\s*\n\s*```"
        matches = re.findall(pattern, text, re.DOTALL)

        for tool_name, args_str in matches:
            self.logger.debug(f"Converting tool_code to function call: {tool_name}")
            try:
                # Parse arguments like: a = 9310, b = 3, operation = "divide"
                args = {}
                for arg_part in args_str.split(","):
                    if "=" in arg_part:
                        key, value = arg_part.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip("\"'")  # Remove quotes

                        # Try to convert to number
                        try:
                            if "." in value:
                                args[key] = float(value)
                            else:
                                args[key] = int(value)
                        except ValueError:
                            args[key] = value  # Keep as string
                # extract tool from Tool Manager
                tool = self.tool_manager.get_tool(tool_name)
                if tool:
                    # Create function call
                    fc = types.FunctionCall(id=f"call_{uuid.uuid4().hex[:8]}", name=tool_name, args=args)
                    function_calls.append(fc)
                    self.logger.info(f"Created function call: {tool_name}({args})")

            except Exception as e:
                self.logger.error(f"Failed to parse tool_code: {e}")

        return function_calls

    def _format_function_call_args(self, fc, max_chars: int = 300) -> str:
        """Render FunctionCall.args as a compact, truncated string for logs.

        The SDK's ``types.py:8051`` warning hides the actual function_call
        payload, so we render it ourselves at DEBUG. Truncation keeps log
        lines bounded when tools pass large argument blobs.
        """
        args = getattr(fc, "args", None) or {}
        try:
            rendered = self._json.dumps(args, default=str, ensure_ascii=False)
        except Exception:
            rendered = repr(args)
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars] + f"... (+{len(rendered) - max_chars} chars)"
        return rendered

    def _log_non_text_parts(self, response, where: str = "response") -> None:
        """Log the non-text parts (function_call, code_execution_*) at DEBUG.

        Mirrors the SDK warning at ``google.genai.types:8051`` but surfaces
        the actual payload — name + truncated args for function calls — so
        we can debug what the model emitted alongside or instead of text.
        """
        try:
            candidates = getattr(response, "candidates", None) or []
            if not candidates:
                return
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) or []
            if not parts:
                return
            for idx, part in enumerate(parts):
                fc = getattr(part, "function_call", None)
                if fc:
                    self.logger.debug(
                        "Non-text part [%s #%d]: function_call %s(%s) id=%s",
                        where,
                        idx,
                        fc.name,
                        self._format_function_call_args(fc),
                        getattr(fc, "id", None),
                    )
                    continue
                if getattr(part, "code_execution_result", None):
                    res = part.code_execution_result
                    self.logger.debug(
                        "Non-text part [%s #%d]: code_execution_result outcome=%s",
                        where,
                        idx,
                        getattr(res, "outcome", None),
                    )
                    continue
                if getattr(part, "executable_code", None):
                    ec = part.executable_code
                    code = getattr(ec, "code", "") or ""
                    self.logger.debug(
                        "Non-text part [%s #%d]: executable_code lang=%s code_chars=%d",
                        where,
                        idx,
                        getattr(ec, "language", None),
                        len(code),
                    )
        except Exception as exc:
            self.logger.debug(f"_log_non_text_parts failed: {exc}")

    def _get_function_calls_from_response(self, response) -> List:
        """Get function calls from response - handles both proper calls and tool_code blocks."""
        function_calls = []

        try:
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:

                for part in response.candidates[0].content.parts:
                    # Check for proper function calls first
                    if hasattr(part, "function_call") and part.function_call:
                        function_calls.append(part.function_call)
                        self.logger.debug(
                            "Found proper function call: %s(%s)",
                            part.function_call.name,
                            self._format_function_call_args(part.function_call),
                        )

                    # Skip reasoning/thought parts. Match the SDK contract
                    # exactly (``google.genai`` v1.75 ``GenerateContentResponse._get_text``,
                    # ``types.py:7993``): ``part.thought is True`` is the only
                    # canonical thought marker. ``thought_signature`` is opaque
                    # cross-turn metadata that legitimately appears on real
                    # answer parts (see SDK test ``test_thought_signature_no_warning_in_text``)
                    # and MUST NOT be used as a filter.
                    elif part.thought is True:
                        self.logger.debug("Skipping reasoning/thought part during function extraction")

                    # Check for tool_code in text parts
                    elif hasattr(part, "text") and part.text and "```tool_code" in part.text:
                        self.logger.info("Found tool_code block - converting to function call")
                        code_function_calls = self._parse_tool_code_blocks(part.text)
                        function_calls.extend(code_function_calls)
            else:
                self.logger.warning("Response has no candidates or content parts")

        except Exception as e:
            self.logger.error(f"Error getting function calls: {e}")

        # FEAT-252 (TASK-1613): gate default_api / non-existent tool attempts
        # Any function call named "default_api" is a hallucinated discovery attempt
        # by the model. Drop it and log a typed warning.
        gated_calls = []
        for fc in function_calls:
            fc_name = getattr(fc, "name", "") or ""
            if fc_name == "default_api":
                self.logger.warning(
                    "_get_function_calls_from_response: gated default_api call "
                    "(model attempted to discover/import non-existent tool)"
                )
                # Replace with typed sentinel rather than silently dropping
                # so the loop can surface it to the caller
                continue  # drop — _resolve_final_response handles the gap
            gated_calls.append(fc)

        self.logger.info(f"Total function calls found: {len(gated_calls)}")
        return gated_calls

    def _safe_extract_text(self, response, is_stream_chunk: bool = False) -> str:
        """
        Enhanced text extraction that handles reasoning models and mixed content warnings.

        This method tries multiple approaches to extract text from Google GenAI responses,
        handling special cases like thought_signature parts from reasoning models.
        """

        # Pre-check for function calls and thoughts to avoid library warnings when accessing .text
        # and to prevent reasoning parts from leaking into the final output.
        has_function_call = False
        has_thought = False
        has_content_parts = False
        try:
            if (
                hasattr(response, "candidates")
                and response.candidates
                and len(response.candidates) > 0
                and hasattr(response.candidates[0], "content")
                and response.candidates[0].content
                and hasattr(response.candidates[0].content, "parts")
                and response.candidates[0].content.parts
            ):
                has_content_parts = True
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        has_function_call = True
                    # Match SDK filter exactly (``types.py:7993``):
                    # only ``part.thought is True`` marks a thought.
                    if part.thought is True:
                        has_thought = True
        except Exception:
            pass

        # Method 1: Try response.text first (fastest path)
        # Skip if content parts are available: SDK-flattened response.text may
        # include planning text that should not be shown to callers.
        if not has_content_parts and not has_function_call and not has_thought:
            try:
                if hasattr(response, "text") and response.text:
                    if text := response.text.strip():
                        self.logger.debug(f"Extracted text via response.text: '{text[:100]}...'")
                        return text
            except Exception as e:
                # This is expected with reasoning models that have mixed content
                self.logger.debug(f"response.text failed (normal for reasoning models): {e}")

        # Method 2: Manual extraction from parts (more robust)
        try:
            if (
                hasattr(response, "candidates")
                and response.candidates
                and len(response.candidates) > 0
                and hasattr(response.candidates[0], "content")
                and response.candidates[0].content
                and hasattr(response.candidates[0].content, "parts")
                and response.candidates[0].content.parts
            ):

                text_parts = []
                thought_parts_found = 0

                # Extract text from each part, handling special cases.
                # Skip reasoning/thought parts using the SDK's canonical
                # predicate only (``part.thought is True``, see
                # ``google.genai`` v1.75 ``types.py:7993``).
                # ``thought_signature`` is opaque cross-turn metadata that
                # legitimately appears on real answer parts (SDK test
                # ``test_thought_signature_no_warning_in_text``); using it as
                # a filter silently drops valid output.
                for part in response.candidates[0].content.parts:
                    if part.thought is True:
                        thought_parts_found += 1
                        self.logger.debug("Skipping reasoning/thought part")
                        continue

                    # Check for regular text content
                    if hasattr(part, "text") and part.text:
                        if clean_text := part.text.strip():
                            text_parts.append(clean_text)
                            self.logger.debug(f"Found text part: '{clean_text[:50]}...'")

                    # Check for code execution result (contains output from executed code)
                    elif hasattr(part, "code_execution_result") and part.code_execution_result:
                        result = part.code_execution_result
                        outcome = getattr(result, "outcome", None)
                        output = getattr(result, "output", None)
                        self.logger.debug(f"Found code_execution_result: outcome={outcome}")
                        if output and isinstance(output, str) and output.strip():
                            text_parts.append(output.strip())
                            self.logger.debug(f"Extracted code execution output: '{output[:50]}...'")

                    # Check for executable code (the code that was executed)
                    elif hasattr(part, "executable_code") and part.executable_code:
                        exec_code = part.executable_code
                        code_text = getattr(exec_code, "code", None)
                        language = getattr(exec_code, "language", "PYTHON")
                        self.logger.debug(
                            f"Found executable_code part: language={language}, code_len={len(code_text) if code_text else 0}"
                        )
                        # We don't add executable_code to text output by default,
                        # but log it for debugging purposes

                # Log reasoning model detection
                if thought_parts_found > 0:
                    self.logger.debug(f"Detected reasoning model with {thought_parts_found} thought parts")

                # Combine text parts
                if text_parts:
                    if combined_text := "".join(text_parts).strip():
                        self.logger.debug(f"Successfully extracted text from {len(text_parts)} parts")
                        return combined_text
                else:
                    self.logger.debug("No text parts found in response parts")

        except Exception as e:
            self.logger.error(f"Manual text extraction failed: {e}")

        # Method 3: Deep inspection for debugging (fallback)
        try:
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0] if len(response.candidates) > 0 else None
                if candidate:
                    if hasattr(candidate, "finish_reason"):
                        finish_reason = str(candidate.finish_reason)
                        self.logger.debug(f"Response finish reason: {finish_reason}")
                        if "MAX_TOKENS" in finish_reason:
                            self.logger.warning("Response truncated due to token limit")
                        elif "SAFETY" in finish_reason:
                            self.logger.warning("Response blocked by safety filters")
                        elif "STOP" in finish_reason:
                            self.logger.debug("Response completed normally but no text found")

                    if hasattr(candidate, "content") and candidate.content:
                        if hasattr(candidate.content, "parts"):
                            parts_count = len(candidate.content.parts) if candidate.content.parts else 0
                            self.logger.debug(f"Response has {parts_count} parts but no extractable text")
                            if candidate.content.parts:
                                part_types = []
                                for part in candidate.content.parts:
                                    part_attrs = [
                                        attr
                                        for attr in dir(part)
                                        if not attr.startswith("_") and hasattr(part, attr) and getattr(part, attr)
                                    ]
                                    part_types.append(part_attrs)
                                self.logger.debug(f"Part attribute types found: {part_types}")

        except Exception as e:
            self.logger.error(f"Deep inspection failed: {e}")

        # Method 4: Final fallback - return empty string with clear logging.
        # A function-call-only turn legitimately has no text (the model is
        # invoking a tool, not answering), so log it at debug to avoid alarming
        # WARNING noise on every tool-calling step.
        if has_function_call:
            self.logger.debug("No text in response (function-call-only turn — expected)")
        elif is_stream_chunk:
            self.logger.debug("No text in stream chunk")
        else:
            self.logger.warning("Could not extract any text from response using any method")
        return ""

    # ==========================================================================
    # FEAT-252 (TASK-1613) — _resolve_final_response chokepoint
    # ==========================================================================

    _NO_ANSWER_SENTINEL: str = (
        "[No answer produced: the model consumed its tool budget without "
        "synthesising a final response.]"
    )
    _TOOL_NOT_AVAILABLE_SENTINEL: str = (
        "[Tool not available: the requested tool does not exist in the current "
        "session. Please use only the registered tools listed in the system prompt.]"
    )

    def _is_no_answer(self, text: str) -> bool:
        """Return True when *text* is the typed no-answer sentinel."""
        return text == self._NO_ANSWER_SENTINEL

    def _no_answer_sentinel(self) -> str:
        """Return the typed no-answer sentinel string."""
        return self._NO_ANSWER_SENTINEL

    def _frame_code_output(self, text: str) -> str:
        """Wrap raw code-exec stdout in a safe framing block.

        Args:
            text: Raw code execution output string.

        Returns:
            Framed output string.
        """
        return f"[Code execution output]\n{text}\n[End code execution output]"

    def _classify_provenance(
        self,
        candidate_text: str,
        all_tool_calls: Optional[List],
        code_exec_output: Optional[str],
    ) -> str:
        """Classify the provenance of a response candidate.

        Args:
            candidate_text: The text candidate from the model.
            all_tool_calls: All tool calls made during this turn.
            code_exec_output: Raw code execution stdout, if any.

        Returns:
            One of ``"synthesis"`` | ``"tool_echo"`` | ``"code_exec_stdout"``.
        """
        if not candidate_text:
            return "synthesis"  # will be caught as empty-after-tools below

        # Code-exec stdout: if the candidate is substantially the same as the
        # raw code execution output, classify it for safe framing.
        if code_exec_output and candidate_text.strip() == code_exec_output.strip():
            return "code_exec_stdout"

        # Tool echo: check if the candidate text is a near-verbatim copy of
        # any recent tool result.
        if all_tool_calls:
            for tc in all_tool_calls:
                result_str = str(getattr(tc, "result", "") or "")
                if not result_str:
                    continue
                # Normalised similarity check using SequenceMatcher (case-insensitive)
                norm_candidate = candidate_text.strip().lower()
                norm_result = result_str.strip().lower()
                if not norm_result:
                    continue
                ratio = difflib.SequenceMatcher(
                    None, norm_result, norm_candidate
                ).ratio()
                if ratio >= self._echo_threshold and len(norm_candidate) < len(norm_result) * 1.5:
                    self.logger.warning(
                        "_resolve_final_response: tool_echo detected "
                        "(tool=%s overlap=%.2f threshold=%.2f)",
                        getattr(tc, "name", "?"),
                        ratio,
                        self._echo_threshold,
                    )
                    return "tool_echo"

        return "synthesis"

    def _resolve_final_response(
        self,
        candidate_text: str,
        all_tool_calls: Optional[List],
        code_exec_output: Optional[str],
    ) -> str:
        """Single deterministic chokepoint for all terminal Gemini responses.

        Steps:
        1. Classify provenance: synthesis | tool_echo | code_exec_stdout.
        2. If tool_echo → return typed no-answer sentinel (suppress verbatim echo).
        3. If code_exec_stdout → frame output safely.
        4. If empty-after-tools → return typed no-answer sentinel.
        5. Run ``OutputScrubber.scrub`` **last**, always.

        Args:
            candidate_text: The text extracted from the Gemini response.
            all_tool_calls: All tool calls made during this turn (used for echo detection).
            code_exec_output: Raw code execution stdout, if any.

        Returns:
            Scrubbed, safe response text.
        """
        provenance = self._classify_provenance(candidate_text, all_tool_calls, code_exec_output)

        if provenance == "tool_echo":
            # Never ship verbatim tool-result echo back to the user
            result = self._no_answer_sentinel()
        elif provenance == "code_exec_stdout":
            # Frame code output safely before scrubbing
            result = self._frame_code_output(candidate_text)
        else:
            result = candidate_text

        # Empty-after-tools: model produced no synthesis
        if not result and all_tool_calls:
            result = self._no_answer_sentinel()

        # Scrub last — single egress gate. Redaction is opt-in per agent:
        # the owning bot stamps ``enable_redaction`` when it is flagged.
        if getattr(self, "enable_redaction", False):
            return self._scrubber.scrub(result, tool_name="gemini_client")
        return result

    def _build_closed_tool_manifest(self, tool_names: Optional[List[str]] = None) -> str:
        """Build the closed tool manifest instruction for the system prompt.

        Args:
            tool_names: List of registered tool names for the current call.

        Returns:
            Manifest instruction string to append to the system prompt.
        """
        if tool_names:
            tool_list = ", ".join(f"``{n}``" for n in sorted(tool_names))
            return (
                f"\n\n[SECURITY: Closed Tool Manifest]\n"
                f"The ONLY tools available in this session are: {tool_list}. "
                "There is no ``default_api`` tool. "
                "Do NOT write tool_code blocks that call ``default_api`` or any other unlisted tool. "
                "Do NOT attempt to import or discover additional tools at runtime."
            )
        return (
            "\n\n[SECURITY: Closed Tool Manifest]\n"
            "Do NOT write tool_code blocks that call ``default_api`` or any unlisted tool. "
            "Do NOT attempt to import or discover additional tools at runtime."
        )

    def _extract_code_execution_content(
        self, response, output_directory: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Extract code execution content from response including code, results, and images.

        This method handles responses from Google's code execution feature which can
        include executed Python code, execution results, and generated images (e.g., matplotlib charts).

        Args:
            response: The Google GenAI response object
            output_directory: Optional directory to save extracted images

        Returns:
            Dict containing:
                - 'code': List of executed code strings
                - 'output': Combined text output from code execution
                - 'images': List of PIL Image objects or saved file paths
                - 'has_content': Boolean indicating if any content was extracted
        """
        result = {"code": [], "output": [], "images": [], "has_content": False}

        try:
            if not (
                hasattr(response, "candidates")
                and response.candidates
                and len(response.candidates) > 0
                and hasattr(response.candidates[0], "content")
                and response.candidates[0].content
                and hasattr(response.candidates[0].content, "parts")
                and response.candidates[0].content.parts
            ):
                return result

            for part in response.candidates[0].content.parts:
                # Extract executable code
                if hasattr(part, "executable_code") and part.executable_code:
                    exec_code = part.executable_code
                    code_text = getattr(exec_code, "code", None)
                    if code_text:
                        result["code"].append(code_text)
                        result["has_content"] = True
                        self.logger.debug(f"Extracted executable code: {len(code_text)} chars")

                # Extract code execution result
                elif hasattr(part, "code_execution_result") and part.code_execution_result:
                    exec_result = part.code_execution_result
                    outcome = getattr(exec_result, "outcome", None)
                    output_text = getattr(exec_result, "output", None)

                    self.logger.debug(f"Code execution result: outcome={outcome}")

                    if output_text and isinstance(output_text, str) and output_text.strip():
                        result["output"].append(output_text.strip())
                        result["has_content"] = True

                # Extract images from inline_data (matplotlib charts, generated images)
                elif hasattr(part, "inline_data") and part.inline_data:
                    try:
                        inline_data = part.inline_data
                        mime_type = getattr(inline_data, "mime_type", "")

                        # Check if it's an image
                        if mime_type and mime_type.startswith("image/"):
                            image_data = getattr(inline_data, "data", None)
                            if image_data:
                                # Convert to PIL Image
                                image = Image.open(io.BytesIO(image_data))
                                self.logger.debug(f"Extracted image from inline_data: {mime_type}, size={image.size}")

                                # Save to file if output_directory is provided
                                if output_directory:
                                    output_dir = Path(output_directory)
                                    output_dir.mkdir(parents=True, exist_ok=True)
                                    # Generate unique filename
                                    ext = mime_type.split("/")[-1] if "/" in mime_type else "png"
                                    filename = f"chart_{uuid.uuid4().hex[:8]}.{ext}"
                                    file_path = output_dir / filename
                                    image.save(file_path)
                                    result["images"].append(file_path)
                                    self.logger.debug(f"Saved image to: {file_path}")
                                else:
                                    result["images"].append(image)

                                result["has_content"] = True
                    except Exception as e:
                        self.logger.warning(f"Failed to extract image from inline_data: {e}")

                # Try as_image() method for parts that support it
                elif hasattr(part, "as_image") and callable(getattr(part, "as_image")):
                    try:
                        # Check if this part can be converted to an image
                        # The as_image() method is available on parts with image content
                        image = part.as_image()
                        if image:
                            self.logger.debug(
                                f"Extracted image via as_image(): size={image.size if hasattr(image, 'size') else 'unknown'}"
                            )

                            if output_directory:
                                output_dir = Path(output_directory)
                                output_dir.mkdir(parents=True, exist_ok=True)
                                filename = f"chart_{uuid.uuid4().hex[:8]}.png"
                                file_path = output_dir / filename
                                image.save(file_path)
                                result["images"].append(file_path)
                                self.logger.debug(f"Saved image to: {file_path}")
                            else:
                                result["images"].append(image)

                            result["has_content"] = True
                    except Exception as e:
                        # as_image() may fail if the part doesn't actually contain image data
                        self.logger.debug(f"as_image() not applicable for this part: {e}")

            # Log summary
            if result["has_content"]:
                self.logger.info(
                    f"Extracted code execution content: "
                    f"{len(result['code'])} code blocks, "
                    f"{len(result['output'])} outputs, "
                    f"{len(result['images'])} images"
                )

        except Exception as e:
            self.logger.error(f"Error extracting code execution content: {e}")

        return result

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        use_thinking: Optional[bool] = None,
        stateless: bool = False,
        deep_research: bool = False,
        file_search_store_names: Optional[List[str]] = None,
        lazy_loading: bool = False,
        max_iterations: int = 15,
        stop_tools: Optional[set] = None,
        **kwargs,
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.

        Args:
            prompt (str): The input prompt for the model.
            model (Union[str, GoogleModel]): The model to use. If None, uses the client's configured model
                or defaults to GEMINI_2_5_FLASH.
            max_tokens (int): Maximum number of tokens in the response.
            temperature (float): Sampling temperature for response generation.
            files (Optional[List[Union[str, Path]]]): Optional files to include in the request.
            system_prompt (Optional[str]): Optional system prompt to guide the model.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output configuration.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id: Optional session identifier for tracking.
            force_tool_usage (Optional[str]): Force usage of specific tools, if needed.
                ("custom_functions", "builtin_tools", or None)
            stateless (bool): If True, don't use conversation memory (stateless mode).
            deep_research (bool): If True, use Google's deep research agent.
            file_search_store_names (Optional[List[str]]): Names of file search stores for deep research.
            max_iterations (int): Maximum number of tool-calling rounds (default 15).
            stop_tools: Tool names that signal the loop should end. When a
                stop tool executes successfully, further tool-calling is
                disabled and the model must produce a final text answer.
        """
        max_retries = kwargs.pop("max_retries", 2)
        retry_on_fail = kwargs.pop("retry_on_fail", True)

        if not retry_on_fail:
            max_retries = 1

        # Route to deep research if requested
        if deep_research:
            self.logger.info("Using Google Deep Research mode via interactions.create()")
            return await self._deep_research_ask(
                prompt=prompt,
                file_search_store_names=file_search_store_names,
                user_id=user_id,
                session_id=session_id,
                files=files,
            )

        # If use_tools is None, use the instance default
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        if not model:
            model = self.model or GoogleModel.GEMINI_2_5_FLASH.value

        # Handle case where model is passed as a tuple or list
        if isinstance(model, (list, tuple)):
            model = model[0]

        # Normalize enum → string regardless of which GoogleModel path the
        # caller came from (covers stale build-dir duplicates that make
        # `isinstance` return False for the "right" enum class).
        model = self._as_model_str(model) or model

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        ask_started = time.perf_counter()

        # FEAT-176: lifecycle event — BeforeClientCallEvent
        _lc_tc_google = self._emit_before_call(
            client_name="google",
            model=str(model) if model else "",
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(_use_tools),
            parent_trace=None,
        )

        # Store runtime context so _execute_tool can inject it into tools
        self._tool_context = {
            k: v
            for k, v in {
                "user_id": user_id,
                "session_id": session_id,
            }.items()
            if v is not None
        }

        # Per-call overlay of request-scoped tools. Tools passed via
        # ``tools=[...]`` are NOT registered into the persistent ToolManager —
        # they are combined with manager tools only when building this call's
        # function declarations and when looking up a tool to execute.
        # Indexed by tool name; request-scoped tools win on collisions.
        self._request_tools = {getattr(t, "name", None): t for t in (tools or []) if getattr(t, "name", None)}

        # Prepare conversation context using unified memory system
        conversation_history = None
        messages = []

        # Use the abstract method to prepare conversation context
        if stateless:
            # For stateless mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            # Use the unified conversation context preparation from AbstractClient
            phase_started = time.perf_counter()
            messages, conversation_history, system_prompt = await self._prepare_conversation_context(
                prompt, files, user_id, session_id, system_prompt, stateless=stateless
            )
            self.logger.debug(
                "Google ask timing: prepare_conversation_context_ms=%.1f messages=%d history=%s",
                (time.perf_counter() - phase_started) * 1000,
                len(messages),
                bool(conversation_history),
            )

        # Prepare conversation history for Google GenAI format
        history = []
        # Construct history directly from the 'messages' array, which should be in the correct format
        if messages:
            for msg in messages[:-1]:  # Exclude the current user message (last in list)
                role = msg["role"].lower()
                # Assuming content is already in the format [{"type": "text", "text": "..."}]
                # or other GenAI Part types if files were involved.
                # Here, we only expect text content for history, as images/files are for the current turn.
                if role == "user":
                    # Content can be a list of dicts (for text/parts) or a single string.
                    # Standardize to list of Parts.
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                        # Add other part types if necessary for history (e.g., function responses)
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ["assistant", "model"]:
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    if parts:
                        history.append(ModelContent(parts=parts))

        default_tokens = max_tokens or self.max_tokens
        generation_config = {"temperature": temperature or self.temperature}
        if default_tokens:
            generation_config["max_output_tokens"] = default_tokens
        base_temperature = generation_config["temperature"]

        # Prepare structured output configuration
        output_config = self._get_structured_config(structured_output)

        # Tool selection
        # Always expose every registered custom tool when tools are enabled —
        # the LLM decides which (if any) to call. `tool_type="builtin_tools"`
        # is still honored for Google-native tools like search/code exec.
        requested_tools = tools

        kw_tool_type = kwargs.pop("tool_type", None)

        if kw_tool_type == "builtin_tools":
            tool_type = kw_tool_type
            _use_tools = True
        elif _use_tools and self._is_computer_use_model(model):
            # Computer-use models REQUIRE types.Tool(computer_use=...) in the
            # request — sending only function_declarations yields a 400
            # INVALID_ARGUMENT ("This model requires the use of the Computer
            # Use tool."). The "computer_use" build path emits that tool and
            # appends any genuinely-custom (non-predefined) function tools.
            tool_type = "computer_use"
        elif _use_tools:
            tool_type = kw_tool_type or "custom_functions"
        else:
            tool_type = kw_tool_type

        if _use_tools:
            # Reduce temperature to avoid hallucinations; thinking-only models
            # on Vertex AI reject temperature < 0.7.
            generation_config["temperature"] = 0.7 if self._requires_thinking(model) else 0

        phase_started = time.perf_counter()
        tools = self._build_tools(tool_type) if tool_type else []
        self.logger.debug(
            "Google ask timing: build_tools_ms=%.1f toolboxes=%d tool_type=%s",
            (time.perf_counter() - phase_started) * 1000,
            len(tools),
            tool_type,
        )

        # Debug: List tool names
        tool_names = []
        if tools:
            for tool in tools:
                if getattr(tool, "function_declarations", None):
                    tool_names.extend([fd.name for fd in tool.function_declarations])
            self.logger.debug(f"TOOLS ({len(tool_names)}): {tool_names}")
            self.logger.debug(f'request_form in tools: {"request_form" in tool_names}')

        if _use_tools and tool_type == "custom_functions" and not tools:
            self.logger.info("Tool usage requested but no tools are registered - disabling tools for this request.")
            _use_tools = False
            tool_type = None
            tools = []
            generation_config["temperature"] = base_temperature

        use_tools = _use_tools

        # LAZY LOADING LOGIC
        active_tool_names = set()
        if use_tools and lazy_loading:
            # Override initial tool selection to just search_tools
            active_tool_names.add("search_tools")
            tools = self._build_tools("custom_functions", filter_names=["search_tools"])
            # Add system prompt instruction
            search_prompt = (
                "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            )
            system_prompt = f"{system_prompt}\n\n{search_prompt}" if system_prompt else search_prompt
            # Update final_config later with this new system prompt if needed,
            # but system_prompt is passed to GenerateContentConfig below.

        self.logger.debug(
            f"Using model: {model}, max_tokens: {default_tokens}, temperature: {temperature}, "
            f"structured_output: {structured_output}, "
            f"use_tools: {_use_tools}, tool_type: {tool_type}, toolbox: {len(tools)}, "
        )

        use_structured_output = bool(output_config)
        # FEAT-193: whitelisted Gemini 3.x models can receive tools + response_schema
        # in a single GenerateContentConfig (combined mode).  Non-whitelisted models
        # (e.g. gemini-2.5-pro) keep the legacy two-phase reformat flow.
        combined_mode = (
            _use_tools
            and use_structured_output
            and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)
        )

        if _use_tools and use_structured_output and not combined_mode:
            # Two-phase path: tools first, then reformat via _reformat_model.
            self.logger.info(
                "Google Gemini doesn't support tools + structured output simultaneously. "
                "Using tools first, then applying structured output to the final result."
            )
            structured_output_for_later = output_config
            # Don't set structured output in initial config
            output_config = None
        elif combined_mode:
            # Combined path: apply schema to the same chat call as tools.
            structured_output_for_later = None
            self._apply_structured_output_schema(generation_config, output_config)
            if model.startswith("gemini-3.1-flash-lite"):
                self.logger.debug(
                    "Combined tools+schema mode on %s: upstream evaluation flagged "
                    "AFC instability — monitor latency.",
                    model,
                )
        else:
            structured_output_for_later = None
            # Set structured output in generation config if no tools conflict
            if output_config:
                self._apply_structured_output_schema(generation_config, output_config)

        # Track tool calls for the response
        all_tool_calls = []

        phase_started = time.perf_counter()
        await self._ensure_client(model=model)
        self.logger.debug(
            "Google ask timing: ensure_client_ms=%.1f model=%s",
            (time.perf_counter() - phase_started) * 1000,
            model,
        )
        # configure thinking config for gemini:
        thinking_config = None
        _requires_thinking = self._requires_thinking(model)
        if use_thinking:
            thinking_config = ThinkingConfig(
                max_thinking_steps=1,
                max_thinking_tokens=100,
                max_thinking_time=10,
            )
        elif self._is_computer_use_model(model):
            # Computer-use models reason over screenshots and require thoughts
            # enabled (see Gemini computer-use docs / reference implementation).
            thinking_config = ThinkingConfig(include_thoughts=True)
        elif _requires_thinking:
            # Pro models (2.5-pro, 3-pro, 3.1-pro) are thinking-only — budget=0 is invalid.
            thinking_config = ThinkingConfig(thinking_budget=8192, include_thoughts=False)
        elif "flash" in model.lower():
            # Flash puede deshabilitarse con budget=0
            thinking_config = ThinkingConfig(thinking_budget=0, include_thoughts=False)
        elif use_tools:
            # Gemini 2.5 Pro + thinking + tool schemas → MALFORMED_FUNCTION_CALL.
            # Disable thinking when tools are active to ensure reliable function calls.
            thinking_config = ThinkingConfig(thinking_budget=0, include_thoughts=False)
        else:
            thinking_config = ThinkingConfig(thinking_budget=8192, include_thoughts=False)
        # Use AUTO: let Gemini decide whether a tool call is needed.
        # Previous default was ANY (forced tool use on the first turn),
        # which caused two problems: (a) on generic questions Gemini would
        # pick an arbitrary tool and (b) when the conversation history
        # contained a recent function_call (e.g. ask_human), Gemini would
        # re-emit it with the previous arguments because it had to call
        # *something*. If the concern is that AUTO is "too hands-off" with
        # 30+ tools, address it via system prompt / tool descriptions, not
        # by forcing calls. Callers can still opt in to ANY by passing
        # ``force_tool_call=True`` via generation_config.
        tool_config = None
        if tools and tool_type == "custom_functions":
            force_tool_call = (
                bool(generation_config.pop("force_tool_call", False)) if isinstance(generation_config, dict) else False
            )
            mode = (
                types.FunctionCallingConfigMode.ANY
                if force_tool_call and bool((prompt or "").strip())
                else types.FunctionCallingConfigMode.AUTO
            )
            tool_config = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=mode))

        # Computer-use requests send a native ComputerUse tool alongside any
        # genuinely-custom FunctionDeclaration tools (computer_screenshot,
        # computer_run_loop, scraping helpers). The google-genai SDK cannot run
        # Automatic Function Calling over raw function declarations, so it logs a
        # noisy "Tools at indices [...] are not compatible with AFC. AFC is
        # disabled." warning on every turn. We never want AFC here — the
        # ComputerUse loop drives function_call/function_response manually — so
        # we declare that intent explicitly. Setting ``disable=True`` makes the
        # SDK short-circuit (should_disable_afc) *before* the incompatible-tools
        # check, silencing the warning. Leave ``maximum_remote_calls`` unset to
        # avoid the SDK's secondary "disable + positive max_remote_calls" warning.
        afc_config = None
        if tool_type == "computer_use":
            afc_config = types.AutomaticFunctionCallingConfig(disable=True)

        # FEAT-181: resolve List[CacheableSegment] → string before passing to
        # GenerateContentConfig, which does not accept segment lists.
        # Also handle prompt caching: if segments were provided, attempt to create
        # a CachedContent resource (fail-open on error).
        _pending_cache_segs = None
        if isinstance(system_prompt, list):
            # This is a List[CacheableSegment] from PromptBuilder.build_segments()
            _payload_tmp, _pending_cache_segs = self._apply_cache_hints({}, system_prompt)
            system_prompt = self._resolve_system_prompt(system_prompt)

        # FEAT-252 (TASK-1613): append closed tool manifest to system prompt so the
        # model knows exactly which tools are available and cannot hallucinate default_api.
        if _use_tools and tools:
            _tool_names = [getattr(t, "name", None) or getattr(t, "__name__", str(t)) for t in tools]
            _manifest = self._build_closed_tool_manifest(_tool_names)
            system_prompt = f"{system_prompt}\n\n{_manifest}" if system_prompt else _manifest

        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
            tools=tools,
            tool_config=tool_config,
            thinking_config=thinking_config,
            automatic_function_calling=afc_config,
            **generation_config,
        )
        # FEAT-181: if we have pending cache segments, attempt to create
        # a Gemini CachedContent resource (fail-open on any error).
        if _pending_cache_segs:
            _cache_payload = {}
            _cache_payload = await self._maybe_apply_gemini_cache(
                self.client, model, _cache_payload, _pending_cache_segs
            )
            if _cache_payload.get("cached_content"):
                try:
                    final_config.cached_content = _cache_payload["cached_content"]
                except (AttributeError, TypeError):
                    self.logger.debug(
                        "GenerateContentConfig does not support cached_content assignment; " "continuing without cache."
                    )

        # Single execution path for both stateless and stateful modes.
        # ``stateless`` only controls whether conversation history is loaded
        # earlier (see _prepare_conversation_context above) — it does NOT
        # change how tool-calling iterates or how the request is dispatched.
        # In stateless mode ``history`` is empty; in stateful mode it carries
        # the prior turns. Everything else is identical.
        current_model = model
        chat = self.client.aio.chats.create(model=current_model, history=history)
        retry_count = 0
        while retry_count < max_retries:
            try:
                phase_started = time.perf_counter()
                self.logger.info(
                    "Google ask timing: chat.send_message start model=%s prompt_chars=%d system_prompt_chars=%d tools=%d thinking=%s stateless=%s history=%d",
                    current_model,
                    len(prompt or ""),
                    len(system_prompt or ""),
                    len(tool_names),
                    bool(thinking_config),
                    stateless,
                    len(history),
                )
                response = await chat.send_message(message=prompt, config=final_config)
                self.logger.info(
                    "Google ask timing: chat.send_message_ms=%.1f model=%s attempt=%d",
                    (time.perf_counter() - phase_started) * 1000,
                    current_model,
                    retry_count + 1,
                )
                finish_reason = getattr(response.candidates[0], "finish_reason", None)
                if finish_reason:
                    if finish_reason.name == "MAX_TOKENS" and generation_config["max_output_tokens"] <= 1024:
                        retry_count += 1
                        self.logger.warning(
                            f"Hit MAX_TOKENS limit on initial response. Retrying {retry_count}/{max_retries} with increased token limit."
                        )
                        final_config.max_output_tokens = 8192
                        continue
                    elif finish_reason.name == "MALFORMED_FUNCTION_CALL":
                        retry_count += 1
                        if retry_count >= max_retries:
                            self.logger.error(
                                "Malformed function call detected. " "Exhausted %d retries — raising.",
                                max_retries,
                            )
                            raise RuntimeError(
                                f"Gemini returned MALFORMED_FUNCTION_CALL after "
                                f"{max_retries} retries. The tool schema may be "
                                "too complex or the model failed to produce a valid call."
                            )
                        self.logger.warning(
                            "Malformed function call detected. Retrying %d/%d...",
                            retry_count,
                            max_retries,
                        )
                        await asyncio.sleep(2**retry_count)
                        continue
                break
            except Exception as e:
                # Handle specific network client error (socket/aiohttp issue)
                if "'NoneType' object has no attribute 'getaddrinfo'" in str(e):
                    retry_count += 1
                    self.logger.warning(f"Encountered network client error: {e}. Resetting client and retrying.")
                    # Reset the current-loop client only; sibling loops are unaffected.
                    await self._close_current_loop_entry()
                    await self._ensure_client(model=current_model)
                    # Recreate the chat session
                    chat = self.client.aio.chats.create(model=current_model, history=history)
                    delay = self._retry_delay_from_error(retry_count, e)
                    if retry_count >= max_retries:
                        raise
                    await asyncio.sleep(delay)
                    continue

                retry_count += 1
                if self._should_use_fallback(current_model, e):
                    self.logger.warning(
                        "Google model '%s' capacity error: %s. " "Retrying once with fallback: '%s'.",
                        current_model,
                        e,
                        self._fallback_model,
                    )
                    current_model = self._fallback_model
                    chat = self.client.aio.chats.create(model=current_model, history=history)

                delay = self._retry_delay_from_error(retry_count, e)
                self.logger.warning(
                    "Error during initial chat.send_message (attempt %d/%d): %s. " "Retrying in %ss.",
                    retry_count,
                    max_retries,
                    e,
                    delay,
                )
                if retry_count >= max_retries:
                    raise
                await asyncio.sleep(delay)

        has_function_calls = False
        if response and getattr(response, "candidates", None):
            candidate = response.candidates[0] if response.candidates else None
            content = getattr(candidate, "content", None) if candidate else None
            parts = getattr(content, "parts", None) if content else None
            if parts:
                has_function_calls = any(hasattr(p, "function_call") and p.function_call for p in parts)

        self.logger.debug(f"Initial response has function calls: {has_function_calls}")
        if has_function_calls:
            self._log_non_text_parts(response, where="initial response")

        # Multi-turn function calling loop
        phase_started = time.perf_counter()
        final_response = await self._handle_multiturn_function_calls(
            chat,
            response,
            all_tool_calls,
            original_prompt=original_prompt,
            model=current_model,
            max_iterations=max_iterations,
            config=final_config,
            max_retries=max_retries,
            lazy_loading=lazy_loading,
            active_tool_names=active_tool_names,
            session_id=session_id,
            messages=messages,
            stop_tools=stop_tools,
        )
        self.logger.debug(
            "Google ask timing: function_loop_ms=%.1f tool_calls=%d",
            (time.perf_counter() - phase_started) * 1000,
            len(all_tool_calls),
        )
        model = current_model

        # Extract assistant response text for conversation memory
        phase_started = time.perf_counter()
        assistant_response_text = self._safe_extract_text(final_response)

        # Extract code execution content (code, results, images) from the response
        code_execution_content = self._extract_code_execution_content(final_response)

        # If code execution produced output but we don't have text, use the code execution output
        if not assistant_response_text and code_execution_content["output"]:
            assistant_response_text = "\n".join(code_execution_content["output"])
            self.logger.info(f"Using code execution output as response text: {len(assistant_response_text)} chars")

        # If we still don't have text but have tool calls, generate a summary
        if not assistant_response_text and all_tool_calls:
            assistant_response_text = self._create_simple_summary(all_tool_calls)
        self.logger.debug(
            "Google ask timing: response_text_extract_ms=%.1f text_chars=%d",
            (time.perf_counter() - phase_started) * 1000,
            len(assistant_response_text or ""),
        )

        # Handle structured output
        final_output = None
        if structured_output_for_later and use_tools and assistant_response_text:
            try:
                # Create a new generation config for structured output only
                _max = max_tokens or self.max_tokens
                structured_config = {
                    "temperature": temperature or self.temperature,
                    "response_mime_type": "application/json",
                }
                if _max:
                    structured_config["max_output_tokens"] = _max

                # OPTIMIZATION: Try to parse immediately to avoid 2nd LLM call
                # If the model already returned valid valid JSON, we can skip the slow reformatting call
                try:
                    self.logger.debug("Attempting fast-path check for structured output...")

                    # Check if text looks like JSON before trying to parse (avoids warnings)
                    text_to_check = assistant_response_text.strip()
                    is_json_candidate = (
                        text_to_check.startswith("{") or text_to_check.startswith("[") or "```json" in text_to_check
                    )

                    if is_json_candidate:
                        # We accept the result if it is NOT just the original string (which implies parsing failure return)
                        fast_parsed = await self._parse_structured_output(
                            assistant_response_text, structured_output_for_later
                        )

                        # _parse_structured_output returns the (possibly stripped) response
                        # text as a string when parsing fails.  A successfully parsed
                        # structured output is NEVER a plain str, so checking isinstance
                        # is more reliable than text comparison (whitespace can differ).
                        if not isinstance(fast_parsed, str):
                            self.logger.info("Fast-path structured parsing successful. Skipping reformatting step.")
                            final_output = fast_parsed
                    else:
                        self.logger.debug("Response does not look like JSON, skipping fast-path parsing.")
                except Exception as e:
                    self.logger.debug(f"Fast-path parsing failed: {e}")

                if final_output is None:
                    # Set the schema based on the type of structured output
                    schema_config = (
                        structured_output_for_later
                        if isinstance(structured_output_for_later, StructuredOutputConfig)
                        else self._get_structured_config(structured_output_for_later)
                    )
                    if schema_config:
                        self._apply_structured_output_schema(structured_config, schema_config)
                    # Use a fast model for the reformatting call — this is
                    # just JSON conversion, not reasoning. The default is
                    # ``_default_reformat_model`` (GEMINI_3_FLASH_PREVIEW);
                    # override per-instance via the ``reformat_model``
                    # constructor kwarg. DO NOT downgrade to flash-lite:
                    # small models hallucinate rows when extracting tabular
                    # data from a shape-annotated preview.
                    reformat_model = self._reformat_model
                    # CRITICAL: disable thinking for the reformat call.
                    # Gemini 3 Flash defaults to thinking ON, which turns a
                    # trivial string→JSON conversion into a multi-minute
                    # reasoning exercise (observed: 10s–4min latency for
                    # ~600 chars of input). Reformat is pure mechanical
                    # schema-filling — we already pass `response_schema`
                    # via `_apply_structured_output_schema`, so the model
                    # has no structural decisions to make.
                    # `_requires_thinking` is False for flash-preview, so
                    # budget=0 is accepted. Do NOT remove this.
                    if not self._requires_thinking(reformat_model):
                        structured_config["thinking_config"] = ThinkingConfig(thinking_budget=0)
                    # Create a new client call without tools for structured output
                    format_prompt = (
                        "Convert the following response into the requested JSON structure.\n\n"
                        "RULES (STRICT — violating these produces corrupted data):\n"
                        "1. The `explanation` field MUST contain the COMPLETE original text "
                        "verbatim — do NOT summarize, truncate, rewrite, or omit any part of it.\n"
                        "2. NEVER invent, fabricate, extend, complete, infer, or 'fill in' any "
                        "row, column, or value that is not literally present in the text below. "
                        "If the text shows only N rows of a table, the `data` field must contain "
                        "AT MOST those N rows — even if the text mentions that more rows exist "
                        "(e.g. 'Shape: (21, 4)'). Do not guess the missing rows.\n"
                        "3. If the text references a pandas variable holding the full result "
                        "(e.g. `data_variable = 'foo'` or 'the full breakdown is in `foo`'), "
                        "set `data_variable` to that exact variable name and leave `data` as "
                        "null or an empty table. The caller will inject the full DataFrame "
                        "from memory — you must not try to reconstruct it from the text.\n"
                        "4. Only populate `data` from a markdown table when ALL of its rows are "
                        "literally present in the text. When in doubt, prefer `data_variable` "
                        "over `data`.\n\n"
                        f"Return only the JSON object:\n\n{assistant_response_text}"
                    )
                    self.logger.debug(
                        "Reformatting response as structured output using %s " "(thinking=%s, input_chars=%d)...",
                        reformat_model,
                        structured_config.get("thinking_config") and "off" or "default",
                        len(format_prompt),
                    )
                    _reformat_start = time.perf_counter()
                    structured_response = await self.client.aio.models.generate_content(
                        model=reformat_model,
                        contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
                        config=GenerateContentConfig(**structured_config),
                    )
                    _reformat_elapsed = time.perf_counter() - _reformat_start
                    self.logger.info(
                        "Structured output reformatting complete in %.2fs",
                        _reformat_elapsed,
                    )
                    # Extract structured text
                    if structured_text := self._safe_extract_text(structured_response):
                        # Parse the structured output
                        if isinstance(structured_output_for_later, StructuredOutputConfig):
                            final_output = await self._parse_structured_output(
                                structured_text, structured_output_for_later
                            )
                        elif isinstance(structured_output_for_later, type):
                            if hasattr(structured_output_for_later, "model_validate_json"):
                                final_output = structured_output_for_later.model_validate_json(structured_text)
                            elif hasattr(structured_output_for_later, "model_validate"):
                                parsed_json = self._json.loads(structured_text)
                                final_output = structured_output_for_later.model_validate(parsed_json)
                        else:
                            final_output = self._json.loads(structured_text)
                    else:
                        self.logger.warning("No structured text received, falling back to original response")
                        final_output = assistant_response_text
            except Exception as e:
                self.logger.error(f"Error parsing structured output: {e}")
                # Fallback to original text if structured output fails
                final_output = assistant_response_text
        elif combined_mode and assistant_response_text and output_config:
            # FEAT-193: combined mode — the model was already sent tools + response_schema
            # in the same call, so we only need to parse the response (no second LLM call).
            try:
                parsed = await self._parse_structured_output(assistant_response_text, output_config)
                if isinstance(parsed, str):
                    # _parse_structured_output returns the input string on parse failure.
                    # Recovery: fall back to the legacy reformat call.
                    self.logger.warning(
                        "Combined-mode parse returned raw string for %s — falling back to reformat call.",
                        model,
                    )
                    final_output = await self._reformat_to_structured(
                        assistant_response_text,
                        output_config,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                else:
                    final_output = parsed
            except Exception as e:
                self.logger.warning(
                    "Combined-mode parse raised %s — falling back to reformat call.",
                    type(e).__name__,
                )
                try:
                    final_output = await self._reformat_to_structured(
                        assistant_response_text,
                        output_config,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as reformat_err:
                    self.logger.error("Recovery reformat also failed: %s", reformat_err)
                    final_output = assistant_response_text
        elif output_config and not use_tools:
            try:
                final_output = await self._parse_structured_output(assistant_response_text, output_config)
            except Exception:
                final_output = assistant_response_text
        else:
            final_output = assistant_response_text

        # Update conversation memory with the final response
        final_assistant_message = {
            "role": "model",
            "content": [
                {
                    "type": "text",
                    "text": str(final_output) if final_output != assistant_response_text else assistant_response_text,
                }
            ],
        }

        # Update conversation memory with unified system
        if not stateless and conversation_history:
            phase_started = time.perf_counter()
            tools_used = [tc.name for tc in all_tool_calls]
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [final_assistant_message],
                system_prompt,
                turn_id,
                original_prompt,
                assistant_response_text,
                tools_used,
            )
            self.logger.debug(
                "Google ask timing: update_conversation_memory_ms=%.1f",
                (time.perf_counter() - phase_started) * 1000,
            )
        # Prepare code execution content for AIMessage
        extracted_images = code_execution_content.get("images", []) if code_execution_content else []
        extracted_code = (
            "\n\n".join(code_execution_content["code"])
            if code_execution_content and code_execution_content.get("code")
            else None
        )

        # FEAT-252 (TASK-1613): route through single chokepoint before factory
        code_exec_raw = (
            "\n".join(code_execution_content["output"])
            if code_execution_content and code_execution_content.get("output")
            else None
        )
        assistant_response_text = self._resolve_final_response(
            assistant_response_text or "", all_tool_calls, code_exec_raw
        )

        # Create AIMessage using factory
        phase_started = time.perf_counter()
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls,
            conversation_history=conversation_history,
            text_response=assistant_response_text,
            files=extracted_images,
            images=extracted_images,
            code=extracted_code,
        )
        self.logger.debug(
            "Google ask timing: ai_message_factory_ms=%.1f total_ms=%.1f",
            (time.perf_counter() - phase_started) * 1000,
            (time.perf_counter() - ask_started) * 1000,
        )

        # Override provider to distinguish from Vertex AI
        ai_message.provider = "google_genai"

        # Drop the per-call request-tools overlay so its bound state does
        # not leak into subsequent calls.
        self._request_tools = {}

        # FEAT-176: lifecycle event — AfterClientCallEvent
        _lc_google_usage = getattr(ai_message, "usage", None)
        await self._emit_after_call(
            _lc_tc_google,
            client_name="google",
            model=str(model) if model else "",
            duration_ms=(time.perf_counter() - ask_started) * 1000,
            input_tokens=getattr(_lc_google_usage, "prompt_tokens", None) if _lc_google_usage else None,
            output_tokens=getattr(_lc_google_usage, "completion_tokens", None) if _lc_google_usage else None,
            finish_reason=None,
        )
        return ai_message

    def _create_simple_summary(self, all_tool_calls: List[ToolCall]) -> str:
        """Create a simple summary from tool calls."""
        if not all_tool_calls:
            return "Task completed."

        if len(all_tool_calls) == 1:
            tc = all_tool_calls[0]
            if isinstance(tc.result, Exception):
                return f"Tool {tc.name} failed with error: {tc.result}"
            elif isinstance(tc.result, pd.DataFrame):
                if not tc.result.empty:
                    return f"Tool {tc.name} returned a DataFrame with {len(tc.result)} rows."
                else:
                    return f"Tool {tc.name} returned an empty DataFrame."
            elif tc.name in self._sensitive_tool_result_names and isinstance(tc.result, str):
                return f"Tool {tc.name} completed; output withheld for safety."
            elif tc.name in self._sensitive_tool_result_names and isinstance(tc.result, dict):
                return f"Tool {tc.name} completed; output withheld for safety."
            elif tc.result and isinstance(tc.result, dict) and "expression" in tc.result:
                return self._scrubber.scrub(str(tc.result["expression"]), tool_name=tc.name)  # FEAT-252
            elif tc.result and isinstance(tc.result, dict) and "result" in tc.result:
                return f"Result: {self._scrubber.scrub(str(tc.result['result']), tool_name=tc.name)}"  # FEAT-252
        if len(all_tool_calls) >= 1:
            # Multiple calls - show the final result
            final_tc = all_tool_calls[-1]
            if isinstance(final_tc.result, pd.DataFrame):
                if not final_tc.result.empty:
                    return f"Data: {final_tc.result.to_string()}"
                else:
                    return f"Final tool {final_tc.name} returned an empty DataFrame."
            if final_tc.name in self._sensitive_tool_result_names and isinstance(final_tc.result, (str, dict)):
                return f"Final tool {final_tc.name} completed; output withheld for safety."
            if final_tc.result and isinstance(final_tc.result, dict):
                if "result" in final_tc.result:
                    return f"Final result: {self._scrubber.scrub(str(final_tc.result['result']), tool_name=final_tc.name)}"  # FEAT-252
                elif "expression" in final_tc.result:
                    return self._scrubber.scrub(str(final_tc.result["expression"]), tool_name=final_tc.name)  # FEAT-252
            # Plain strings from intermediate tools (e.g. load_skill body) must not
            # be surfaced as the final answer — fall through to the sentinel below.

        # Detect skill-loading failure: load_skill was called (returned content)
        # but the model could not call the next tool (MALFORMED_FUNCTION_CALL).
        skill_tc = next(
            (tc for tc in all_tool_calls if tc.name == "load_skill"),
            None,
        )
        if skill_tc is not None and isinstance(skill_tc.result, str):
            skill_name = (
                skill_tc.arguments.get("name", "unknown") if isinstance(skill_tc.arguments, dict) else "unknown"
            )
            self.logger.error(
                "Skill '%s' loaded but subsequent tool call was malformed — "
                "the skill may reference a tool not declared in the current toolset.",
                skill_name,
            )
            return (
                f"Error: skill `{skill_name}` was loaded but could not execute the next step. "
                "The skill may reference a tool that is not available in the current configuration. "
                "Please check the skill definition and try again."
            )

        # Last resort: the LLM exhausted its tool-calling budget without
        # synthesizing a final answer. Surface a clear failure message
        # instead of a debug-style trace of tool names — the caller can
        # detect this via the LLM_NO_FINAL_ANSWER sentinel below.
        tool_names = [tc.name for tc in all_tool_calls]
        self.logger.error(
            "LLM exhausted tool-calling loop without producing a final " "answer. Tools invoked (%d): %s",
            len(all_tool_calls),
            ", ".join(tool_names),
        )
        return LLM_NO_FINAL_ANSWER

    def _build_function_declarations(self) -> List[types.FunctionDeclaration]:
        """Build function declarations for Google GenAI tools."""
        function_declarations = []

        for tool in self.tool_manager.all_tools():
            tool_name = tool.name

            if isinstance(tool, AbstractTool):
                full_schema = tool.get_tool_schema()
                tool_description = full_schema.get("description", tool.description)
                schema = full_schema.get("parameters", {}).copy()
                schema = self.clean_google_schema(schema)
            elif isinstance(tool, ToolDefinition):
                tool_description = tool.description
                schema = self.clean_google_schema(tool.input_schema.copy())
            else:
                tool_description = getattr(tool, "description", f"Tool: {tool_name}")
                schema = getattr(tool, "input_schema", {})
                schema = self.clean_google_schema(schema)

            if not schema:
                schema = {"type": "object", "properties": {}, "required": []}

            try:
                safe_name = self._register_sanitized_name(tool_name)
                declaration = types.FunctionDeclaration(
                    name=safe_name, description=tool_description, parameters=self._fix_tool_schema(schema)
                )
                function_declarations.append(declaration)
            except Exception as e:
                self.logger.error(f"Error creating {tool_name}: {e}")
                continue

        return function_declarations

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",  # "retry", "notify", "ignore"
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        use_thinking: Optional[bool] = None,
        stateless: bool = False,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        max_iterations: int = 15,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """
        Stream Google Generative AI's response using AsyncIterator with support for Tool Calling.

        Args:
            on_max_tokens: How to handle MAX_TOKENS finish reason:
                - "retry": Automatically retry with increased token limit
                - "notify": Yield a notification message and continue
                - "ignore": Silently continue (original behavior)
            deep_research: If True, use Google's deep research agent (stream mode)
            agent_config: Optional configuration for deep research (e.g., thinking_summaries)
        """
        model = (model.value if isinstance(model, GoogleModel) else model) or (
            self.model or GoogleModel.GEMINI_2_5_FLASH.value
        )

        # Handle case where model is passed as a tuple or list
        if isinstance(model, (list, tuple)):
            model = model[0]

        turn_id = str(uuid.uuid4())

        # FEAT-176: lifecycle event — BeforeClientCallEvent for stream
        from parrot.core.events.lifecycle.events import ClientStreamChunkEvent as _GoogleStreamChunkEvent

        _lc_tc_googles = self._emit_before_call(
            client_name="google",
            model=str(model) if model else "",
            temperature=temperature if temperature is not None else self.temperature,
            system_prompt=system_prompt,
            has_tools=bool(use_tools if use_tools is not None else self.enable_tools),
            parent_trace=None,
        )
        _lc_t0_googles = time.perf_counter()
        _lc_has_chunk_subs_google = self.events.has_subscribers(_GoogleStreamChunkEvent)
        _lc_chunk_idx_google = 0

        # Store runtime context so _execute_tool can inject it into tools
        self._tool_context = {
            k: v
            for k, v in {
                "user_id": user_id,
                "session_id": session_id,
            }.items()
            if v is not None
        }

        if deep_research:
            yield "⏳ **Running Deep Research...**\n"
            yield "_Gathering information and exploring sources..._\n\n"
            try:
                ai_message = await self._deep_research_ask(
                    prompt=prompt, model=model, agent_config=agent_config, user_id=user_id, session_id=session_id
                )
                yield ai_message.text_response
                yield ai_message
            except Exception as e:
                self.logger.error(f"Deep Research failed: {e}")
                import traceback

                traceback.print_exc()
                yield f"\n\n❌ **Deep Research failed: {str(e)}**\n"
            return

        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        # Use the unified conversation context preparation
        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude current user message
                role = msg["role"].lower()
                if role == "user":
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ["assistant", "model"]:
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    if parts:
                        history.append(ModelContent(parts=parts))

        _use_tools = use_tools if use_tools is not None else getattr(self, "enable_tools", False)

        # Per-call overlay
        self._request_tools = {getattr(t, "name", None): t for t in (tools or []) if getattr(t, "name", None)}

        try:
            if _use_tools:
                temperature = 0.0 if temperature is None else temperature
                tool_type = "custom_functions"
            elif _use_tools is None:
                tool_type = self._analyze_prompt_for_tools(prompt)
            else:
                tool_type = "builtin_tools" if _use_tools else None

            active_tool_names = set()
            if tool_type and _use_tools and lazy_loading:
                active_tool_names.add("search_tools")
                gemini_tools = self._build_tools("custom_functions", filter_names=["search_tools"])
                search_prompt = (
                    "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
                )
                system_prompt = f"{system_prompt}\n\n{search_prompt}" if system_prompt else search_prompt
            else:
                gemini_tools = self._build_tools(tool_type) if tool_type else []

            if _use_tools and tool_type == "custom_functions" and not gemini_tools:
                gemini_tools = None

            # configure thinking config
            thinking_config = None
            _requires_thinking = self._requires_thinking(model)
            if use_thinking:
                thinking_config = ThinkingConfig(
                    max_thinking_steps=1,
                    max_thinking_tokens=100,
                    max_thinking_time=10,
                )
            elif _requires_thinking:
                thinking_config = ThinkingConfig(thinking_budget=8192, include_thoughts=False)
            elif "flash" in model.lower():
                thinking_config = ThinkingConfig(thinking_budget=0, include_thoughts=False)
            elif _use_tools:
                thinking_config = ThinkingConfig(thinking_budget=0, include_thoughts=False)
            else:
                thinking_config = ThinkingConfig(thinking_budget=8192, include_thoughts=False)

            current_max_tokens = max_tokens or getattr(self, "max_tokens", 8192)
            retry_count = 0
            iteration = 0
            current_message_content = prompt
            keep_looping = True

            # FEAT-181: resolve List[CacheableSegment] → string before passing to
            # GenerateContentConfig, which does not accept segment lists.
            if isinstance(system_prompt, list):
                system_prompt = self._resolve_system_prompt(system_prompt)

            generation_config_args = {
                "temperature": temperature or getattr(self, "temperature", 0.0),
                "max_output_tokens": current_max_tokens,
            }
            if thinking_config:
                generation_config_args["thinking_config"] = thinking_config
            if system_prompt:
                generation_config_args["system_instruction"] = system_prompt
            if gemini_tools:
                generation_config_args["tools"] = gemini_tools

            # FEAT-193: whitelisted models can receive tools + response_schema together.
            combined_mode = bool(
                structured_output
                and _use_tools
                and self._supports_combined_tools_and_schema(model, self._combined_call_prefixes)
            )

            # Handle structured output mapping
            schema_config = None
            applies_schema = bool(structured_output) and (not _use_tools or combined_mode)
            if applies_schema:
                schema_config = (
                    structured_output
                    if isinstance(structured_output, StructuredOutputConfig)
                    else self._get_structured_config(structured_output)
                )
                if schema_config:
                    self._apply_structured_output_schema(generation_config_args, schema_config)
                    if combined_mode and model.startswith("gemini-3.1-flash-lite"):
                        self.logger.debug(
                            "Combined tools+schema mode on %s: upstream evaluation flagged "
                            "AFC instability — monitor latency.",
                            model,
                        )

            chat = self.client.aio.chats.create(
                model=model, history=history, config=GenerateContentConfig(**generation_config_args)
            )

            all_assistant_text = []
            all_tool_calls_history = []

            while keep_looping and retry_count <= retry_config.max_retries and iteration < max_iterations:
                keep_looping = False
                iteration += 1

                try:
                    chat._config.max_output_tokens = current_max_tokens
                    assistant_content_chunk = ""
                    max_tokens_reached = False
                    collected_function_calls = []

                    async for chunk in await chat.send_message_stream(current_message_content):
                        if hasattr(chunk, "candidates") and chunk.candidates:
                            candidate = chunk.candidates[0]
                            if (
                                hasattr(candidate, "finish_reason")
                                and str(candidate.finish_reason) == "FinishReason.MAX_TOKENS"
                            ):
                                max_tokens_reached = True
                                if on_max_tokens == "notify":
                                    yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens).**\n"
                                elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                                    break

                        if hasattr(chunk, "candidates") and chunk.candidates:
                            for candidate in chunk.candidates:
                                if hasattr(candidate, "content") and candidate.content and candidate.content.parts:
                                    for part in candidate.content.parts:
                                        if hasattr(part, "function_call") and part.function_call:
                                            collected_function_calls.append(part.function_call)

                        chunk_text = self._safe_extract_text(chunk, is_stream_chunk=True)
                        if chunk_text:
                            assistant_content_chunk += chunk_text
                            all_assistant_text.append(chunk_text)
                            # FEAT-176: per-chunk event
                            if _lc_has_chunk_subs_google:
                                await self.events.emit(
                                    _GoogleStreamChunkEvent(
                                        trace_context=_lc_tc_googles,
                                        client_name="google",
                                        model=str(model) if model else "",
                                        chunk_index=_lc_chunk_idx_google,
                                        chunk_size_bytes=len(chunk_text.encode("utf-8")),
                                        source_type="client",
                                        source_name="google",
                                    )
                                )
                                _lc_chunk_idx_google += 1
                            yield chunk_text

                    if max_tokens_reached and on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                        if retry_count < retry_config.max_retries:
                            new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)
                            yield f"\n\n🔄 **Retrying with increased limit ({new_max_tokens})...**\n\n"
                            current_max_tokens = new_max_tokens
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            keep_looping = True
                            continue
                        else:
                            yield "\n\n❌ **Maximum retries reached.**\n"

                    if collected_function_calls:
                        self.logger.info(f"Streaming detected {len(collected_function_calls)} tool calls.")

                        tool_call_objects = []
                        for fc in collected_function_calls:
                            tc = ToolCall(
                                id=f"call_{uuid.uuid4().hex[:8]}",
                                name=fc.name,
                                arguments=dict(fc.args) if hasattr(fc.args, "items") else fc.args,
                            )
                            tool_call_objects.append(tc)

                        start_time = time.time()
                        tool_execution_tasks = [
                            self._execute_tool(fc.name, dict(fc.args) if hasattr(fc.args, "items") else fc.args)
                            for fc in collected_function_calls
                        ]
                        tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)
                        execution_time = time.time() - start_time

                        if lazy_loading:
                            found_new = False
                            for fc, result in zip(collected_function_calls, tool_results):
                                if fc.name == "search_tools" and isinstance(result, str):
                                    new_tools = self._check_new_tools(fc.name, result)
                                    for nt in new_tools:
                                        if nt not in active_tool_names:
                                            active_tool_names.add(nt)
                                            found_new = True

                            if found_new:
                                new_tools_list = self._build_tools(
                                    "custom_functions", filter_names=list(active_tool_names)
                                )
                                chat._config.tools = new_tools_list
                                self.logger.info(f"Updated tools for next turn. Count: {len(active_tool_names)}")

                        for tc, fc, result in zip(tool_call_objects, collected_function_calls, tool_results):
                            tc.execution_time = execution_time / len(tool_call_objects) if tool_call_objects else 0
                            if isinstance(result, HumanInteractionInterrupt):
                                result.session_id = session_id
                                result.messages = messages.copy() if messages else []
                                result.tool_call_id = getattr(fc, "id", "")
                                result.agent_name = getattr(self, "name", "Google_Agent")
                                raise result
                            elif isinstance(result, CredentialRequired):
                                # FEAT-264: per-user credential missing —
                                # propagate so the surface bridge can emit a
                                # sign-in / capture card (see non-streaming path).
                                raise result
                            elif isinstance(result, Exception):
                                tc.error = str(result)
                                self.logger.error(f"Tool {tc.name} failed: {result}")
                            else:
                                tc.result = self._scrubber.scrub(result, tool_name=tc.name)  # FEAT-252

                        all_tool_calls_history.extend(tool_call_objects)

                        function_response_parts = []
                        for fc, result in zip(collected_function_calls, tool_results):
                            response_content = self._process_tool_result_for_api(result)
                            function_response_parts.append(
                                Part(function_response=types.FunctionResponse(name=fc.name, response=response_content))
                            )

                        current_message_content = function_response_parts
                        keep_looping = True

                except Exception as e:
                    if "'NoneType' object has no attribute 'getaddrinfo'" in str(e):
                        if retry_count < retry_config.max_retries:
                            self.logger.warning(f"Encountered network client error during stream: {e}. Resetting...")
                            await self._close_current_loop_entry()
                            await self._ensure_client(model=model)

                            chat = self.client.aio.chats.create(
                                model=model, history=history, config=GenerateContentConfig(**generation_config_args)
                            )
                            retry_count += 1
                            await self._wait_with_backoff(retry_count, retry_config)
                            keep_looping = True
                            continue

                    if retry_count < retry_config.max_retries:
                        error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                        yield error_msg
                        retry_count += 1
                        await self._wait_with_backoff(retry_count, retry_config)
                        keep_looping = True
                        continue
                    else:
                        yield f"\n\n❌ **Streaming failed: {str(e)}**\n"
                        break

            final_text = "".join(all_assistant_text)

            if not final_text and all_tool_calls_history:
                final_text = self._create_simple_summary(all_tool_calls_history)
                yield final_text

            final_output = None
            if structured_output and final_text:
                if combined_mode:
                    # FEAT-193: combined mode — schema was sent with tools in a single call.
                    # No second generate_content call needed; just parse the streamed text.
                    # Use schema_config (a StructuredOutputConfig) rather than raw structured_output
                    # so that _parse_structured_output can access .output_type correctly.
                    _so_config = schema_config or (
                        structured_output
                        if isinstance(structured_output, StructuredOutputConfig)
                        else self._get_structured_config(structured_output)
                    )
                    try:
                        parsed = await self._parse_structured_output(final_text, _so_config)
                        if isinstance(parsed, str):
                            # Recovery: malformed JSON despite response_schema — fall back to reformat.
                            self.logger.warning(
                                "Combined-mode stream parse returned raw string for %s — falling back to reformat call.",
                                model,
                            )
                            final_output = await self._reformat_to_structured(
                                final_text,
                                _so_config,
                                temperature=temperature,
                                max_tokens=current_max_tokens,
                            )
                        else:
                            final_output = parsed
                    except Exception as e:
                        self.logger.warning(
                            "Combined-mode stream parse raised %s — falling back to reformat call.",
                            type(e).__name__,
                        )
                        try:
                            final_output = await self._reformat_to_structured(
                                final_text,
                                _so_config,
                                temperature=temperature,
                                max_tokens=current_max_tokens,
                            )
                        except Exception as reformat_err:
                            self.logger.error("Recovery reformat also failed: %s", reformat_err)
                elif _use_tools:
                    # EXISTING two-phase path — unchanged.
                    try:
                        is_json_candidate = (
                            final_text.strip().startswith("{")
                            or final_text.strip().startswith("[")
                            or "```json" in final_text.strip()
                        )
                        if is_json_candidate:
                            fast_parsed = await self._parse_structured_output(final_text, structured_output)
                            if not isinstance(fast_parsed, str):
                                final_output = fast_parsed

                        if final_output is None:
                            struct_cfg = {"response_mime_type": "application/json"}
                            if schema_config := (
                                structured_output
                                if isinstance(structured_output, StructuredOutputConfig)
                                else self._get_structured_config(structured_output)
                            ):
                                self._apply_structured_output_schema(struct_cfg, schema_config)

                            reformat_model = self._reformat_model
                            if not self._requires_thinking(reformat_model):
                                struct_cfg["thinking_config"] = ThinkingConfig(thinking_budget=0)

                            format_prompt = (
                                "Convert the following response into the requested JSON structure.\n\n"
                                "RULES (STRICT — violating these produces corrupted data):\n"
                                "1. The `explanation` field MUST contain the COMPLETE original text "
                                "verbatim — do NOT summarize, truncate, rewrite, or omit any part of it.\n"
                                "2. NEVER invent, fabricate, extend, complete, infer, or 'fill in' any "
                                "row, column, or value that is not literally present in the text below. "
                                "If the text shows only N rows of a table, the `data` field must contain "
                                "AT MOST those N rows — even if the text mentions that more rows exist "
                                "(e.g. 'Shape: (21, 4)'). Do not guess the missing rows.\n"
                                "3. If the text references a pandas variable holding the full result "
                                "(e.g. `data_variable = 'foo'` or 'the full breakdown is in `foo`'), "
                                "set `data_variable` to that exact variable name and leave `data` as "
                                "null or an empty table. The caller will inject the full DataFrame "
                                "from memory — you must not try to reconstruct it from the text.\n"
                                "4. Only populate `data` from a markdown table when ALL of its rows are "
                                "literally present in the text. When in doubt, prefer `data_variable` "
                                "over `data`.\n\n"
                                f"Return only the JSON object:\n\n{final_text}"
                            )
                            structured_response = await self.client.aio.models.generate_content(
                                model=reformat_model,
                                contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
                                config=GenerateContentConfig(**struct_cfg),
                            )
                            if structured_text := self._safe_extract_text(structured_response):
                                if isinstance(structured_output, StructuredOutputConfig):
                                    final_output = await self._parse_structured_output(
                                        structured_text, structured_output
                                    )
                                elif isinstance(structured_output, type):
                                    if hasattr(structured_output, "model_validate_json"):
                                        final_output = structured_output.model_validate_json(structured_text)
                                    elif hasattr(structured_output, "model_validate"):
                                        parsed_json = self._json.loads(structured_text)
                                        final_output = structured_output.model_validate(parsed_json)
                                else:
                                    final_output = self._json.loads(structured_text)
                    except Exception as e:
                        self.logger.error(f"Streaming structured output reformat failed: {e}")
                else:
                    try:
                        final_output = await self._parse_structured_output(final_text, structured_output)
                    except Exception:
                        pass

            if final_text and not stateless:
                final_assistant_message = {
                    "role": "model",
                    "content": [{"type": "text", "text": str(final_output) if final_output else final_text}],
                }
                tools_used = [tc.name for tc in all_tool_calls_history]
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_history,
                    messages + [final_assistant_message],
                    system_prompt,
                    turn_id,
                    prompt,
                    final_text,
                    tools_used,
                )

            # FEAT-252 (TASK-1613): chokepoint — stream assembles text per-chunk;
            # run _resolve_final_response on the final assembled text only (Risk R3)
            final_text = self._resolve_final_response(
                final_text or "", all_tool_calls_history, None
            )

            ai_message = AIMessageFactory.from_gemini(
                response=None,
                input_text=prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                structured_output=final_output if final_output is not None else final_text,
                tool_calls=all_tool_calls_history,
                conversation_history=conversation_history,
                text_response=final_text,
                files=[],
                images=[],
                code=None,
            )
            ai_message.provider = "google_genai"
            # FEAT-176: lifecycle event — AfterClientCallEvent (stream)
            _lc_google_s_usage = getattr(ai_message, "usage", None)
            await self._emit_after_call(
                _lc_tc_googles,
                client_name="google",
                model=str(model) if model else "",
                duration_ms=(time.perf_counter() - _lc_t0_googles) * 1000,
                input_tokens=getattr(_lc_google_s_usage, "prompt_tokens", None) if _lc_google_s_usage else None,
                output_tokens=getattr(_lc_google_s_usage, "completion_tokens", None) if _lc_google_s_usage else None,
                finish_reason=None,
            )
            yield ai_message

        finally:
            self._request_tools = {}

    async def batch_ask(self, requests: List[Dict[str, Any]]) -> List[AIMessage]:
        """Process multiple requests in batch. Delegates to ask_batch for efficiency."""
        return await self.ask_batch(requests, use_flex=True)

    async def _build_batch_request_payload(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a standard ask() call parameters dict into a Gemini Batch API request dict."""
        prompt = req.get("prompt", "")
        model = req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value
        model = self._as_model_str(model) or model

        # Determine tools
        use_tools = req.get("use_tools") if req.get("use_tools") is not None else self.enable_tools
        tools = req.get("tools")
        kw_tool_type = req.get("tool_type", None)

        if kw_tool_type == "builtin_tools":
            tool_type = kw_tool_type
            use_tools = True
        elif use_tools:
            tool_type = kw_tool_type or "custom_functions"
        else:
            tool_type = kw_tool_type

        built_tools = []
        if use_tools:
            built_tools = self._build_tools(tool_type) if tool_type else []

        # System prompt
        system_prompt = req.get("system_prompt")

        # Generation config
        generation_config = {
            "temperature": req.get("temperature") if req.get("temperature") is not None else self.temperature
        }
        max_tokens = req.get("max_tokens") or self.max_tokens
        if max_tokens:
            generation_config["max_output_tokens"] = max_tokens

        # Structured output
        structured_output = req.get("structured_output")
        if structured_output:
            output_config = self._get_structured_config(structured_output)
            if output_config:
                self._apply_structured_output_schema(generation_config, output_config)

        # Upload files if any
        contents = []
        files = req.get("files")
        if files:
            for file_path in files:
                path = Path(file_path).resolve()
                self.logger.info(f"Uploading {path.name} to Gemini File API for batch request...")
                file_obj = await self.client.aio.files.upload(file=path)

                # Wait for file to process if it's a video/etc.
                processing_start = time.monotonic()
                while file_obj.state == "PROCESSING":
                    if time.monotonic() - processing_start > 300:
                        raise TimeoutError(f"File processing timed out for {path.name}")
                    await asyncio.sleep(5)
                    file_obj = await self.client.aio.files.get(name=file_obj.name)

                contents.append({"parts": [{"file_data": {"file_uri": file_obj.uri, "mime_type": file_obj.mime_type}}]})

        # Add the main prompt content
        contents.append({"parts": [{"text": prompt}]})

        request_payload = {"contents": contents}
        if system_prompt:
            request_payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        generation_config = {k: v for k, v in generation_config.items() if v is not None}
        if generation_config:
            request_payload["generation_config"] = generation_config

        if built_tools:
            serialized_tools = []
            for t in built_tools:
                if hasattr(t, "model_dump"):
                    serialized_tools.append(t.model_dump(mode="json", exclude_none=True))
                else:
                    serialized_tools.append(t)
            request_payload["tools"] = serialized_tools

        return request_payload

    async def ask_batch(
        self,
        requests: List[Dict[str, Any]],
        use_flex: bool = False,
        wait_for_completion: bool = True,
        poll_interval: int = 30,
        webhook_uri: Optional[str] = None,
        display_name: Optional[str] = None,
        **kwargs,
    ) -> Union[Any, List[AIMessage]]:
        """
        Execute a list of requests using Gemini Batch Mode or Flex Inference.

        Args:
            requests (List[Dict[str, Any]]): List of request parameters matching ask() arguments.
            use_flex (bool): If True, execute requests synchronously using Flex Inference tier (latency target 1-15 min).
                             If False, execute asynchronously using Gemini's Batch API (turnaround up to 24 hours).
            wait_for_completion (bool): If True, wait/poll until job finishes and return parsed AIMessage objects.
                                       Only applicable when use_flex=False.
            poll_interval (int): How often (in seconds) to poll for job completion.
            webhook_uri (Optional[str]): Optional webhook URL to receive state notifications when job completes.
            display_name (Optional[str]): Human-readable display name for the batch job.
            **kwargs: Extra arguments forwarded to batch creation or client initialization.
        """
        import tempfile
        from datamodel.parsers.json import json_encoder
        from google.genai import types

        if not requests:
            return []

        # Ensure we have a valid client
        await self._ensure_client()

        if use_flex:
            self.logger.info(f"Processing {len(requests)} batch requests using Flex Inference tier...")
            tasks = []
            for req in requests:
                req_copy = req.copy()
                req_copy["service_tier"] = "flex"
                # Pass down standard defaults
                for k, v in kwargs.items():
                    req_copy.setdefault(k, v)
                tasks.append(self.ask(**req_copy))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            processed_results = []
            for r in results:
                if isinstance(r, Exception):
                    self.logger.error(f"Batch flex request failed: {r}")
                    processed_results.append(r)
                else:
                    processed_results.append(r)
            return processed_results

        # Standard asynchronous Batch API
        self.logger.info(f"Preparing {len(requests)} requests for Gemini asynchronous Batch API...")

        # Determine the model. Batch jobs require all requests to run on the same model.
        first_req = requests[0]
        batch_model = first_req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value
        batch_model = self._as_model_str(batch_model) or batch_model

        # Build requests payloads
        payload_tasks = [self._build_batch_request_payload(req) for req in requests]
        payloads = await asyncio.gather(*payload_tasks)

        # Write .jsonl input file
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w+", delete=False, encoding="utf-8") as temp_file:
            temp_path = Path(temp_file.name)
            try:
                for i, payload in enumerate(payloads):
                    line = {"key": f"req_{i}", "request": payload}
                    temp_file.write(json_encoder(line) + "\n")
                temp_file.flush()
                temp_file.close()

                self.logger.info("Uploading input JSONL file to Gemini files service...")
                uploaded_file = await self.client.aio.files.upload(
                    file=temp_path, config={"mime_type": "application/jsonl"}
                )
                self.logger.info(f"Uploaded input file: {uploaded_file.name}")
            finally:
                if temp_path.exists():
                    temp_path.unlink()

        # Create config
        config_args = {"display_name": display_name or f"batch_job_{int(time.time())}"}
        if webhook_uri:
            config_args["webhook_config"] = types.WebhookConfig(uris=[webhook_uri])

        create_config = types.CreateBatchJobConfig(**config_args)

        self.logger.info(f"Creating Gemini Batch Job with model: {batch_model}...")
        batch_job = await self.client.aio.batches.create(
            model=batch_model, src=types.BatchJobSource(file_name=uploaded_file.name), config=create_config
        )
        self.logger.info(f"Batch Job created successfully. Name: {batch_job.name}, State: {batch_job.state}")

        if not wait_for_completion:
            return batch_job

        # Poll for completion
        self.logger.info(f"Polling Gemini Batch Job state every {poll_interval}s until completion...")
        while batch_job.state not in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"):
            await asyncio.sleep(poll_interval)
            batch_job = await self.client.aio.batches.get(name=batch_job.name)
            self.logger.debug(f"Batch Job state: {batch_job.state}")

        if batch_job.state == "JOB_STATE_SUCCEEDED":
            self.logger.info("Batch Job succeeded! Downloading and parsing results...")
            results = await self.download_and_parse_batch_results(batch_job, requests)

            try:
                await self.persist_batch_results(results, batch_id=batch_job.name)
            except Exception as e:
                self.logger.error(f"Failed to automatically persist batch results: {e}")

            # Clean up uploaded input file
            try:
                await self.client.aio.files.delete(name=uploaded_file.name)
            except Exception as e:
                self.logger.warning(f"Failed to delete uploaded input file {uploaded_file.name}: {e}")

            return results
        else:
            error_msg = f"Gemini Batch Job finished with terminal state: {batch_job.state}."
            if getattr(batch_job, "error", None):
                error_msg += f" Error: {batch_job.error}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    async def get_batch_job(self, job_name: str) -> Any:
        """Retrieve status of an active or completed Batch Job."""
        await self._ensure_client()
        return await self.client.aio.batches.get(name=job_name)

    async def cancel_batch_job(self, job_name: str) -> Any:
        """Cancel an active Batch Job."""
        await self._ensure_client()
        return await self.client.aio.batches.cancel(name=job_name)

    async def list_batch_jobs(self) -> List[Any]:
        """List active or past Batch Jobs."""
        await self._ensure_client()
        jobs = []
        async for job in self.client.aio.batches.list():
            jobs.append(job)
        return jobs

    async def persist_batch_results(
        self, results: List[AIMessage], batch_id: str, save_dir: Optional[Union[str, Path]] = None
    ) -> Path:
        """
        Serialize and persist batch results (AIMessage objects, images, videos, and structured data)
        to a local directory to prevent content loss.

        Args:
            results: List of AIMessage objects from a batch execution.
            batch_id: A unique identifier for the batch (e.g. job name, timestamp).
            save_dir: Destination directory. Defaults to BASE_DIR / "batch_results".

        Returns:
            The Path where the batch results were saved.
        """
        import shutil
        from navconfig import BASE_DIR
        from datamodel.parsers.json import json_encoder

        # 1. Resolve and create base save directory
        if save_dir is None:
            save_dir = BASE_DIR.joinpath("batch_results")
        else:
            save_dir = Path(save_dir)

        # Clean batch_id for filename/folder safety
        clean_batch_id = str(batch_id).replace("/", "_").replace("\\", "_").replace(":", "_")
        job_dir = save_dir.joinpath(clean_batch_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Persisting {len(results)} batch results to: {job_dir}")

        for i, msg in enumerate(results):
            if isinstance(msg, Exception):
                # Write exception details to a file
                err_file = job_dir.joinpath(f"result_{i}_error.txt")
                err_file.write_text(str(msg), encoding="utf-8")
                continue

            # Copy media files to the job directory and update their paths in serialized dict
            msg_dict = msg.model_dump(mode="json")

            # Helper to copy list of files
            def copy_files(file_paths, key_name):
                new_paths = []
                if file_paths:
                    media_dir = job_dir.joinpath(key_name)
                    media_dir.mkdir(parents=True, exist_ok=True)
                    for path_str in file_paths:
                        src_path = Path(path_str)
                        if src_path.exists() and src_path.is_file():
                            timestamp = int(time.time() * 1000)
                            unique_name = f"{src_path.stem}_{timestamp}{src_path.suffix}"
                            dest_path = media_dir.joinpath(unique_name)
                            shutil.copy2(src_path, dest_path)
                            new_paths.append(str(dest_path))
                        else:
                            new_paths.append(path_str)
                return new_paths

            # Copy images, files, media, documents if present
            if msg.images:
                msg_dict["images"] = copy_files([str(p) for p in msg.images], "images")
            if msg.files:
                msg_dict["files"] = copy_files([str(p) for p in msg.files], "files")
            if msg.media:
                msg_dict["media"] = copy_files([str(p) for p in msg.media], "media")
            if msg.documents:
                msg_dict["documents"] = copy_files([str(p) for p in msg.documents], "documents")

            # Write serialized AIMessage JSON
            json_file = job_dir.joinpath(f"result_{i}_message.json")
            with open(json_file, "w", encoding="utf-8") as f:
                f.write(json_encoder(msg_dict))

            # Write structured output separately for convenience
            if msg.structured_output is not None:
                struct_file = job_dir.joinpath(f"result_{i}_structured.json")
                with open(struct_file, "w", encoding="utf-8") as f:
                    if hasattr(msg.structured_output, "model_dump"):
                        f.write(json_encoder(msg.structured_output.model_dump(mode="json")))
                    elif isinstance(msg.structured_output, (dict, list)):
                        f.write(json_encoder(msg.structured_output))
                    else:
                        f.write(str(msg.structured_output))

            # Write plain response text separately
            if msg.response:
                text_file = job_dir.joinpath(f"result_{i}_response.txt")
                text_file.write_text(msg.response, encoding="utf-8")

        self.logger.info("Persisted batch results successfully.")
        return job_dir

    def _validate_genai_response(self, resp_dict: Dict[str, Any]) -> Any:
        """Validate a raw batch ``response`` dict into a GenerateContentResponse.

        The batch API may emit usage-metadata fields (e.g. ``serviceTier``)
        that a given ``google-genai`` SDK version does not yet model. Those
        models are configured with ``extra='forbid'``, so a strict
        ``model_validate`` raises ``ValidationError`` on the unknown key and
        the whole batch is lost. This validator strips any ``extra_forbidden``
        keys reported by Pydantic and retries, so we degrade gracefully across
        SDK versions instead of failing.

        Args:
            resp_dict: Raw ``response`` mapping from a batch JSONL line.

        Returns:
            A parsed ``types.GenerateContentResponse`` instance.
        """
        from google.genai import types
        from pydantic import ValidationError

        # Validate against a mutable copy so we never mutate the caller's dict.
        payload = copy.deepcopy(resp_dict)
        max_attempts = 8
        for _ in range(max_attempts):
            try:
                return types.GenerateContentResponse.model_validate(payload)
            except ValidationError as exc:
                removed = False
                for err in exc.errors():
                    if err.get("type") != "extra_forbidden":
                        continue
                    # loc is the path to the offending key inside payload.
                    if self._drop_nested_key(payload, err.get("loc", ())):
                        removed = True
                if not removed:
                    raise
                self.logger.warning(
                    "Stripped %d unknown field(s) from batch GenerateContentResponse "
                    "before validation (SDK schema mismatch).",
                    len([e for e in exc.errors() if e.get("type") == "extra_forbidden"]),
                )
        # Final attempt; let it raise if it still fails.
        return types.GenerateContentResponse.model_validate(payload)

    @staticmethod
    def _drop_nested_key(payload: Any, loc: tuple) -> bool:
        """Remove the value at ``loc`` (a Pydantic error location path).

        Walks ``payload`` (nested dicts/lists) following ``loc`` and deletes the
        final key. Returns True if a key was removed.
        """
        if not loc:
            return False
        node = payload
        for part in loc[:-1]:
            if isinstance(node, dict):
                node = node.get(part)
            elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
                node = node[part]
            else:
                return False
            if node is None:
                return False
        last = loc[-1]
        if isinstance(node, dict) and last in node:
            del node[last]
            return True
        return False

    async def download_and_parse_batch_results(
        self, job: Any, original_requests: List[Dict[str, Any]]
    ) -> List[AIMessage]:
        """Download output file from completed Batch Job and parse to List[AIMessage]."""
        from datamodel.parsers.json import json_decoder

        if not getattr(job, "dest", None) or not getattr(job.dest, "file_name", None):
            raise ValueError(f"Job does not have a destination output file: {job}")

        output_file_name = job.dest.file_name
        self.logger.info(f"Downloading batch job results from: {output_file_name}")

        results_bytes = await self.client.aio.files.download(file=output_file_name)
        results_text = results_bytes.decode("utf-8")

        # Parse output JSONL
        output_map = {}
        for line in results_text.splitlines():
            if not line.strip():
                continue
            line_dict = json_decoder(line)
            key = line_dict.get("key")
            if not key:
                continue

            if "response" in line_dict:
                resp_dict = line_dict["response"]
                response_obj = self._validate_genai_response(resp_dict)
                output_map[key] = response_obj
            elif "error" in line_dict:
                output_map[key] = line_dict["error"]

        # Map back to original requests in original order
        results = []
        for i, req in enumerate(original_requests):
            key = f"req_{i}"
            prompt = req.get("prompt", "")
            model = req.get("model") or self.model or GoogleModel.GEMINI_2_5_FLASH.value
            model = self._as_model_str(model) or model

            if key not in output_map:
                err_msg = AIMessage(
                    input=prompt,
                    output=f"Error: Missing response for {key} in batch output",
                    response=f"Error: Missing response for {key} in batch output",
                    model=str(model),
                    provider="google_genai",
                    usage=CompletionUsage(total_time=0),
                )
                results.append(err_msg)
                continue

            item = output_map[key]
            if isinstance(item, dict):  # Error dictionary
                err_msg = AIMessage(
                    input=prompt,
                    output=f"Error {item.get('code', 'unknown')}: {item.get('message', 'unknown')}",
                    response=f"Error {item.get('code', 'unknown')}: {item.get('message', 'unknown')}",
                    model=str(model),
                    provider="google_genai",
                    usage=CompletionUsage(total_time=0),
                )
                results.append(err_msg)
            else:  # types.GenerateContentResponse object
                structured_output = req.get("structured_output")
                final_output = None
                text_response = self._safe_extract_text(item)

                if structured_output and text_response:
                    try:
                        output_config = self._get_structured_config(structured_output)
                        if isinstance(output_config, StructuredOutputConfig):
                            final_output = await self._parse_structured_output(text_response, output_config)
                        elif isinstance(structured_output, type):
                            if hasattr(structured_output, "model_validate_json"):
                                final_output = structured_output.model_validate_json(text_response)
                            elif hasattr(structured_output, "model_validate"):
                                parsed_json = json_decoder(text_response)
                                final_output = structured_output.model_validate(parsed_json)
                        else:
                            final_output = json_decoder(text_response)
                    except Exception as e:
                        self.logger.error(f"Error parsing structured output for batch response: {e}")

                # Check for any tool calls in response
                all_tool_calls = []
                if item.candidates and item.candidates[0].content and item.candidates[0].content.parts:
                    for part in item.candidates[0].content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            tc = ToolCall(
                                id=f"call_{uuid.uuid4().hex[:8]}",
                                name=part.function_call.name,
                                arguments=dict(part.function_call.args),
                            )
                            all_tool_calls.append(tc)

                # FEAT-252 (TASK-1613): chokepoint for batch responses
                _batch_text = self._safe_extract_text(item)
                _batch_scrubbed = self._resolve_final_response(
                    _batch_text or "", all_tool_calls, None
                )

                ai_message = AIMessageFactory.from_gemini(
                    response=item,
                    input_text=prompt,
                    model=model,
                    structured_output=final_output,
                    tool_calls=all_tool_calls,
                    text_response=_batch_scrubbed,
                )
                results.append(ai_message)

        # Delete the destination file to keep files list tidy
        try:
            await self.client.aio.files.delete(name=output_file_name)
        except Exception as e:
            self.logger.warning(f"Failed to delete results output file {output_file_name}: {e}")

        return results

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes],
        reference_images: Optional[Union[List[Path], List[bytes]]] = None,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        no_memory: bool = False,
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI using a stateful chat session.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        if not model:
            model = self.model or GoogleModel.GEMINI_2_5_FLASH.value
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        if no_memory:
            # For no_memory mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_session = None
        else:
            messages, conversation_session, _ = await self._prepare_conversation_context(
                prompt, None, user_id, session_id, None
            )

        # Prepare conversation history for Google GenAI format
        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude the current user message (last in list)
                role = msg["role"].lower()
                if role == "user":
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ["assistant", "model"]:
                    parts = []
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    if parts:
                        history.append(ModelContent(parts=parts))

        # --- Multi-Modal Content Preparation ---
        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(f"Image file not found: {image}")
            # Load the primary image
            primary_image = Image.open(image)
        elif isinstance(image, bytes):
            primary_image = Image.open(io.BytesIO(image))
        elif isinstance(image, Image.Image):
            primary_image = image
        else:
            raise ValueError("Image must be a Path, bytes, or PIL.Image object.")

        # The content for the API call is a list containing images and the final prompt
        contents = [primary_image]
        if reference_images:
            for ref_path in reference_images:
                self.logger.debug(f"Loading reference image from: {ref_path}")
                if isinstance(ref_path, Path):
                    if not ref_path.exists():
                        raise FileNotFoundError(f"Reference image file not found: {ref_path}")
                    contents.append(Image.open(ref_path))
                elif isinstance(ref_path, bytes):
                    contents.append(Image.open(io.BytesIO(ref_path)))
                elif isinstance(ref_path, Image.Image):
                    # is already a PIL.Image Object
                    contents.append(ref_path)
                else:
                    raise ValueError("Reference Image must be a Path, bytes, or PIL.Image object.")

        contents.append(prompt)  # The text prompt always comes last
        _max = max_tokens or self.max_tokens
        generation_config = {
            "temperature": temperature or self.temperature,
        }
        if _max:
            generation_config["max_output_tokens"] = _max
        output_config = self._get_structured_config(structured_output)
        structured_output_config = output_config
        # Vision models generally don't support tools, so we focus on structured output
        if structured_output_config:
            self.logger.debug("Structured output requested for vision task.")
            self._apply_structured_output_schema(generation_config, structured_output_config)
        elif count_objects:
            # Default to JSON for structured output if not specified
            structured_output_config = StructuredOutputConfig(output_type=ObjectDetectionResult)
            self._apply_structured_output_schema(generation_config, structured_output_config)

        # Create the stateful chat session
        chat = self.client.aio.chats.create(model=model, history=history)
        # Disable thinking for image tasks (reduces latency).
        # Pro models (2.5-pro, 3-pro, 3.1-pro) are thinking-only and reject budget=0.
        _thinking_budget = 8192 if self._requires_thinking(model) else 0
        final_config = GenerateContentConfig(
            **generation_config, thinking_config=ThinkingConfig(thinking_budget=_thinking_budget)
        )

        # Make the primary multi-modal call with retry for transient 503 errors
        self.logger.debug(f"Sending {len(contents)} parts to the model.")
        _max_retries = 3
        _retry_delay = 1.0
        for _attempt in range(_max_retries):
            try:
                response = await chat.send_message(message=contents, config=final_config)
                break
            except Exception as _e:
                _err_str = str(_e).lower()
                if _attempt < _max_retries - 1 and any(kw in _err_str for kw in ("503", "unavailable", "overloaded")):
                    self.logger.warning(
                        f"ask_to_image: transient error on attempt {_attempt + 1}/{_max_retries}: {_e}. "
                        f"Retrying in {_retry_delay:.1f}s..."
                    )
                    await asyncio.sleep(_retry_delay)
                    _retry_delay *= 2
                    chat = self.client.aio.chats.create(model=model, history=history)
                else:
                    raise

        # --- Response Handling ---
        final_output = None
        if structured_output_config:
            try:
                final_output = await self._parse_structured_output(response.text, structured_output_config)
            except Exception as e:
                self.logger.error(f"Failed to parse structured output from vision model: {e}")
                final_output = response.text
        elif "```json" in response.text:
            # Attempt to extract JSON from markdown code block
            try:
                final_output = self._parse_json_from_text(response.text)
            except Exception as e:
                self.logger.error(f"Failed to parse JSON from markdown in vision model response: {e}")
                final_output = response.text
        else:
            final_output = response.text

        final_assistant_message = {"role": "model", "content": [{"type": "text", "text": final_output}]}
        if no_memory is False:
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages
                + [
                    {"role": "user", "content": [{"type": "text", "text": f"[Image Analysis]: {prompt}"}]},
                    final_assistant_message,
                ],
                None,
                turn_id,
                original_prompt,
                response.text,
                [],
            )
        # FEAT-252 (TASK-1613): chokepoint for vision ask
        _vision_text = self._resolve_final_response(
            getattr(response, "text", "") or "", [], None
        )

        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=[],
            text_response=_vision_text,
        )
        ai_message.provider = "google_genai"
        return ai_message

    async def _deep_research_ask(
        self,
        prompt: str,
        file_search_store_names: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[str]] = None,
    ) -> AIMessage:
        """
        Perform deep research using Google's interactions.create() API.
        """
        model = "deep-research-pro-preview-12-2025"

        agent_config = {"type": "deep-research", "thinking_summaries": "auto"}

        tools = []
        if file_search_store_names:
            tools.append({"type": "file_search", "file_search_store_names": file_search_store_names})

        try:
            self.logger.info(f"Starting Deep Research Interaction: {prompt}")

            # Check if interactions API is supported
            if not hasattr(self.client, "interactions"):
                raise NotImplementedError(
                    "The installed google-genai SDK does not support 'interactions' API. "
                    "Deep Research feature is unavailable."
                )

            # Create interaction stream
            stream = self.client.interactions.create(
                input=prompt, agent=model, background=True, stream=True, tools=tools, agent_config=agent_config
            )

            interaction_id = None
            last_event_id = None
            full_text = ""
            thought_process = []

            # Iterate through the stream (synchronous iterator in current SDK)
            # We wrap it in to_thread if it blocks, but let's assume standard iteration for now
            # loops over the stream
            for chunk in stream:
                if hasattr(chunk, "event_type"):
                    if chunk.event_type == "interaction.start":
                        interaction_id = chunk.interaction.id
                        self.logger.info(f"Interaction started: {interaction_id}")

                    if chunk.event_id:
                        last_event_id = chunk.event_id

                    if chunk.event_type == "content.delta":
                        if chunk.delta.type == "text":
                            self.logger.debug("deep_research chunk: %s", chunk.delta.text)
                            full_text += chunk.delta.text
                        elif chunk.delta.type == "thought_summary":
                            thought = chunk.delta.content.text
                            self.logger.debug("deep_research thought: %s", thought)
                            thought_process.append(thought)

                    elif chunk.event_type == "interaction.complete":
                        self.logger.info("Research Complete")

            # Construct response
            response = AIMessage(
                input=prompt,
                output=full_text,
                response=full_text,
                is_structured=False,
                model=model,
                provider="google",
                usage=CompletionUsage(total_tokens=0, prompt_tokens=0, completion_tokens=0),
                finish_reason="stop",
            )

            # Attach metadata
            response.user_id = user_id
            response.session_id = session_id
            if thought_process:
                response.prediction = "\n".join(thought_process)

            return response

        except Exception as e:
            self.logger.error(f"Deep Research failed: {e}")
            raise

    async def deep_research(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[Union[str, Path]]] = None,
    ) -> AIMessage:
        """
        Execute a Deep Research task, optionally uploading files first.

        Args:
            query: The research query
            user_id: Optional user ID
            session_id: Optional session ID
            files: List of file paths to upload and include in research

        Returns:
            AIMessage containing the research results
        """
        file_search_store_names = []

        await self._ensure_client()

        # Handle file uploads if provided
        if files:
            try:
                self.logger.info(f"Uploading {len(files)} files for deep research...")
                uploaded_files = []
                for file_path in files:
                    file_path = Path(file_path).expanduser().resolve()
                    if not file_path.exists():
                        self.logger.warning(f"File not found: {file_path}")
                        continue

                    uploaded_file = self.client.files.upload(file=file_path)
                    uploaded_files.append(uploaded_file)
                    self.logger.info(f"Uploaded {file_path.name} as {uploaded_file.name}")

                # Wait for files to be processed
                self.logger.info("Waiting for files to process...")
                active_files = []
                for f in uploaded_files:
                    while f.state.name == "PROCESSING":
                        time.sleep(1)
                        f = self.client.files.get(name=f.name)

                    if f.state.name == "ACTIVE":
                        active_files.append(f)
                    else:
                        self.logger.error(f"File {f.name} failed processing with state: {f.state.name}")

                if active_files:
                    # Create a temporary store or just use the files directly if supported
                    # The SDK example uses 'file_search_store_names' which implies we need a store
                    # For now, let's assume we pass a store name if we had one, or maybe just the file names
                    # The example code showed: "file_search_store_names": ['fileSearchStores/my-store-name']
                    # We might need to creates a store. But for this preview, let's see if we can just skip store
                    # creation if not strictly required or if we can infer it.
                    pass

            except Exception as e:
                self.logger.error(f"Error handling files for deep research: {e}")
                # Proceed without files if upload fails? Or raise?
                # Raising seems safer for "deep research on files"
                raise

        return await self._deep_research_ask(
            prompt=query, user_id=user_id, session_id=session_id, file_search_store_names=file_search_store_names
        )

    async def question(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        use_internal_tools: bool = False,  # New parameter to control internal tools
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI in a stateless manner,
        without conversation history and with optional internal tools.

        Args:
            prompt (str): The input prompt for the model.
            model (Union[str, GoogleModel]): The model to use, defaults to GEMINI_2_5_FLASH.
            max_tokens (int): Maximum number of tokens in the response.
            temperature (float): Sampling temperature for response generation.
            files (Optional[List[Union[str, Path]]]): Optional files to include in the request.
            system_prompt (Optional[str]): Optional system prompt to guide the model.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output configuration.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
            use_internal_tools (bool): If True, Gemini's built-in tools (e.g., Google Search)
                will be made available to the model. Defaults to False.
        """
        # Store runtime context so _execute_tool can inject it into tools
        self._tool_context = {
            k: v
            for k, v in {
                "user_id": user_id,
                "session_id": session_id,
            }.items()
            if v is not None
        }

        self.logger.info(f"Initiating RAG pipeline for prompt: '{prompt[:50]}...'")

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        output_config = self._get_structured_config(structured_output)

        _max = max_tokens or self.max_tokens
        generation_config = {
            "temperature": temperature or self.temperature,
        }
        if _max:
            generation_config["max_output_tokens"] = _max

        if output_config:
            self._apply_structured_output_schema(generation_config, output_config)

        tools = None
        if use_internal_tools:
            tools = self._build_tools("builtin_tools")  # Only built-in tools
            self.logger.debug("Enabled internal tool usage.")

        # Build contents for the stateless call
        contents = []
        if files:
            for file_path in files:
                # In a real scenario, you'd handle file uploads to Gemini properly
                # This is a placeholder for file content
                contents.append(
                    {
                        "part": {
                            "inline_data": {
                                "mime_type": "application/octet-stream",
                                "data": "BASE64_ENCODED_FILE_CONTENT",
                            }
                        }
                    }
                )

        # Add the user prompt as the first part
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        all_tool_calls = []  # To capture any tool calls made by internal tools

        final_config = GenerateContentConfig(system_instruction=system_prompt, tools=tools, **generation_config)

        response = await self.client.aio.models.generate_content(model=model, contents=contents, config=final_config)

        # Handle potential internal tool calls if they are part of the direct generate_content response
        # Gemini can sometimes decide to use internal tools even without explicit function calling setup
        # if the tools are broadly enabled (e.g., through a general 'tool' parameter).
        # This part assumes Gemini's 'generate_content' directly returns tool calls if it uses them.
        if use_internal_tools and response.candidates and response.candidates[0].content.parts:
            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, "function_call") and part.function_call
            ]
            if function_calls:
                tool_call_objects = []
                for fc in function_calls:
                    tc = ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=fc.name, arguments=dict(fc.args))
                    tool_call_objects.append(tc)

                start_time = time.time()
                tool_execution_tasks = [self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls]
                tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)
                execution_time = time.time() - start_time

                for tc, result in zip(tool_call_objects, tool_results):
                    tc.execution_time = execution_time / len(tool_call_objects)
                    if isinstance(result, Exception):
                        tc.error = str(result)
                    else:
                        tc.result = self._scrubber.scrub(result, tool_name=tc.name)  # FEAT-252

                all_tool_calls.extend(tool_call_objects)
                pass  # We're not doing a multi-turn here for stateless

        final_output = None
        _extracted_text = self._safe_extract_text(response)
        if output_config:
            try:
                final_output = await self._parse_structured_output(_extracted_text, output_config)
            except Exception:
                final_output = _extracted_text

        # FEAT-252 (TASK-1613): route through the single egress chokepoint
        _stateless_text = self._resolve_final_response(
            self._safe_extract_text(response) or "", all_tool_calls, None
        )

        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != _extracted_text else None,
            tool_calls=all_tool_calls,
            text_response=_stateless_text,
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:
        """Resume a suspended model execution.

        Args:
            session_id: The session ID
            user_input: The user's input to inject as tool result
            state: The suspended state containing messages and tool_call_id

        Returns:
            AIMessage: The response from the LLM
        """
        await self._ensure_client()

        # Store runtime context so _execute_tool can inject it into tools
        self._tool_context = {"session_id": session_id}

        messages = state["messages"]
        tool_call_id = state["tool_call_id"]
        model_str = state.get("agent_name", self.model or getattr(self, "default_model", self._default_model))

        # We need to rebuild the Google GenAI history format from `messages` array
        history = []
        if messages:
            # We skip the very last message if it's the model's tool calls that we're responding to,
            # or rather we map everything to UserContent/ModelContent.
            for msg in messages:
                role = msg.get("role", "user").lower()

                if role == "user":
                    parts = []
                    # We might have various content types here
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                        elif isinstance(part_content, dict) and part_content.get("type") == "image_url":
                            # Basic string fallback for images in history if needed, though usually omitted
                            pass
                    if parts:
                        history.append(UserContent(parts=parts))

                elif role in ["assistant", "model"]:
                    parts = []
                    # Handle text output
                    for part_content in msg.get("content", []):
                        if isinstance(part_content, dict) and part_content.get("type") == "text":
                            parts.append(Part(text=part_content.get("text", "")))
                    # Handle function calls
                    for fc_data in msg.get("function_calls", []):
                        # Convert back to types.FunctionCall
                        fc = types.FunctionCall(name=fc_data["name"], args=fc_data["arguments"])
                        parts.append(Part(function_call=fc))
                    if parts:
                        history.append(ModelContent(parts=parts))

        # 1. Initialize the Chat Session with rebuilt history
        chat = self.client.aio.chats.create(model=model_str, history=history)

        # 2. Inject the human user's input as the Tool Response
        response_part = Part(
            function_response=types.FunctionResponse(
                id=tool_call_id,
                name="handoff_to_human",  # Based on parrot's HandoffTool.name
                response={"result": user_input},
            )
        )

        generation_config = {"temperature": getattr(self, "temperature", 0.0)}
        final_config = GenerateContentConfig(**generation_config)

        # 3. Send the response back to the model
        retry_count = 0
        max_retries = 3
        while retry_count < max_retries:
            try:
                response = await chat.send_message([response_part], config=final_config)
                break
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    raise
                await asyncio.sleep(self._retry_delay_from_error(retry_count, e))

        # 4. We are now back in the loop, we could have MORE tool calls
        final_response = await self._handle_multiturn_function_calls(
            chat=chat,
            initial_response=response,
            all_tool_calls=[],  # We can pass empty, or load previous if we decided to persist them
            model=model_str,
            config=final_config,
            max_retries=max_retries,
            session_id=session_id,
            messages=messages,
        )

        assistant_response_text = self._safe_extract_text(final_response)

        # Extract code execution content
        code_execution_content = self._extract_code_execution_content(final_response)
        code_exec_raw = "\n".join(code_execution_content["output"]) if code_execution_content["output"] else None
        if not assistant_response_text and code_exec_raw:
            assistant_response_text = code_exec_raw

        # FEAT-252 (TASK-1613): route through the single egress chokepoint
        assistant_response_text = self._resolve_final_response(
            assistant_response_text or "", [], code_exec_raw
        )

        ai_message = AIMessageFactory.from_gemini(
            response=final_response,
            input_text="resume",  # Original prompt is lost in resume statelessness, we use this as placeholder
            model=model_str,
            session_id=session_id,
            turn_id=str(uuid.uuid4()),
            tool_calls=[],  # Update if we want to bubble up tool calls here
            text_response=assistant_response_text,
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Lightweight stateless invocation for GoogleGenAIClient.

        Uses ``generation_config`` with ``response_mime_type="application/json"``
        and ``response_schema`` for structured output.  When ``use_tools=True``
        and ``output_type`` are both set, a two-call strategy is used:

        1. First call: tools enabled, no structured output — gets tool results.
        2. Second call: raw result as input, structured output — parses into schema.

        Args:
            prompt: User prompt.
            output_type: Pydantic model or dataclass to parse the response into.
            structured_output: Full :class:`StructuredOutputConfig`; takes
                precedence over ``output_type``.
            model: Model override. Defaults to ``_lightweight_model``.
            system_prompt: System prompt override.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            use_tools: Whether to inject registered tools.
            tools: Additional tool definitions.

        Returns:
            :class:`InvokeResult` with parsed output.

        Raises:
            :class:`InvokeError`: On provider errors.
        """
        try:
            resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
            config = self._build_invoke_structured_config(output_type, structured_output)
            resolved_model = self._resolve_invoke_model(model)

            if not self.client:
                raise RuntimeError("GoogleGenAIClient not initialised. Use async context manager.")

            needs_two_call = use_tools and config is not None

            if needs_two_call:
                # --- First call: tools, no structured output ---
                tool_defs = self._prepare_tools()
                first_config = GenerateContentConfig(
                    system_instruction=resolved_prompt,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    tools=tool_defs or None,
                )
                first_response = await self.client.aio.models.generate_content(
                    model=resolved_model,
                    contents=[{"role": "user", "parts": [{"text": prompt}]}],
                    config=first_config,
                )
                # Extract raw text from first response safely
                first_text = self._safe_extract_text(first_response)

                # --- Second call: structured output, no tools ---
                second_prompt = (
                    f"Based on this information:\n{first_text}\n\n"
                    f"Original request: {prompt}\n\nProvide structured output."
                )
                second_config = GenerateContentConfig(
                    system_instruction=resolved_prompt,
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=config.get_schema(),
                )
                second_response = await self.client.aio.models.generate_content(
                    model=resolved_model,
                    contents=[{"role": "user", "parts": [{"text": second_prompt}]}],
                    config=second_config,
                )
                # Extract raw text from second response safely
                raw_text = self._safe_extract_text(second_response)

                final_response = second_response

            else:
                # --- Single call ---
                gen_config_kwargs: Dict[str, Any] = {
                    "system_instruction": resolved_prompt,
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                }
                if config:
                    gen_config_kwargs["response_mime_type"] = "application/json"
                    gen_config_kwargs["response_schema"] = config.get_schema()
                if use_tools:
                    sdk_tools = self._prepare_tools()
                    if sdk_tools:
                        gen_config_kwargs["tools"] = sdk_tools

                gen_config = GenerateContentConfig(**gen_config_kwargs)
                final_response = await self.client.aio.models.generate_content(
                    model=resolved_model,
                    contents=[{"role": "user", "parts": [{"text": prompt}]}],
                    config=gen_config,
                )
                # Extract raw text from final response safely
                raw_text = self._safe_extract_text(final_response)

            # Parse output
            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            # Extract usage
            usage_dict: Dict[str, Any] = {}
            if hasattr(final_response, "usage_metadata") and final_response.usage_metadata:
                um = final_response.usage_metadata
                usage_dict = {
                    "prompt_token_count": getattr(um, "prompt_token_count", 0),
                    "candidates_token_count": getattr(um, "candidates_token_count", 0),
                    "total_token_count": getattr(um, "total_token_count", 0),
                }
            usage = CompletionUsage.from_gemini(usage_dict)

            return self._build_invoke_result(output, output_type, resolved_model, usage, final_response)
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)
