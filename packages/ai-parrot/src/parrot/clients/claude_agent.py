"""ClaudeAgentClient — dispatch tasks to Claude Code agents via the agent SDK.

This module exposes :class:`ClaudeAgentClient`, an
:class:`AbstractClient` subclass that drives Anthropic's
``claude-agent-sdk`` (which itself wraps the bundled ``claude`` CLI) so
ai-parrot Agents can delegate file-aware, bash-capable, tool-using work
to a Claude Code sub-agent.

Highlights:

* The ``claude_agent_sdk`` import is **strictly lazy** — performed inside
  every method that needs it. ``import parrot.clients.claude_agent`` is
  therefore safe even when the optional ``ai-parrot[claude-agent]`` extra
  is not installed; the failure surfaces only when the user actually
  calls a method (with a clear ``ImportError``).

* ``ask`` runs a one-shot ``query()``, collects the entire SDK message
  stream, and renders an :class:`AIMessage` via
  :py:meth:`AIMessageFactory.from_claude_agent`.

* ``ask_stream`` yields :class:`TextBlock` text incrementally as each
  ``AssistantMessage`` arrives.

* ``invoke`` produces a stateless structured-output extraction by
  embedding the JSON schema of ``output_type`` directly in the prompt and
  parsing the assistant's text response. The agent SDK has no native
  ``response_format`` parameter equivalent to OpenAI's, so we follow the
  ``AnthropicClient.invoke`` schema-in-prompt pattern.

* ``resume`` continues a conversation by passing
  ``ClaudeAgentOptions.resume = session_id`` to ``query()``.

* Methods that the upstream SDK does not support (``batch_ask``,
  ``ask_to_image``, the analytic helpers) raise ``NotImplementedError``
  with a redirect message pointing at :class:`AnthropicClient`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import is_dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from ..exceptions import InvokeError
from ..models import AIMessage, AIMessageFactory
from ..models.responses import InvokeResult
from .base import AbstractClient


logging.getLogger("claude_agent_sdk").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Public option surface — pydantic mirror of ``ClaudeAgentOptions``
# ---------------------------------------------------------------------------


class ClaudeAgentRunOptions(BaseModel):
    """Run-time options forwarded to ``claude_agent_sdk.ClaudeAgentOptions``.

    The agent SDK exposes a fairly large dataclass (``ClaudeAgentOptions``)
    with about 30 fields. We surface only the subset that is meaningful for
    typical ai-parrot agent dispatch scenarios — file/bash agents, tool
    whitelisting, working-directory pinning, model selection. Unknown
    options can still be passed by callers via the ``extra_options`` mapping.

    Attributes:
        allowed_tools: Whitelist of CC tools (``Read``, ``Write``, ``Bash``,
            ``Edit``, …). When set, every tool not in this list is forbidden.
        disallowed_tools: Tools that must never be used during this run.
        permission_mode: One of ``default`` / ``acceptEdits`` / ``plan`` /
            ``bypassPermissions`` (see the SDK for the exhaustive list). The
            spec recommends ``"default"`` as the safest library default.
        cwd: Working directory the agent should operate from.
        cli_path: Override the bundled ``claude`` CLI binary location.
        system_prompt: Override the agent's system prompt.
        max_turns: Hard cap on agent reasoning turns.
        max_budget_usd: Hard cap on total spend for the run.
        model: Model id passed to the SDK (e.g. ``claude-sonnet-4-6``).
        fallback_model: Model id used if the primary model is unavailable.
        add_dirs: Extra directories the agent is permitted to access.
        env: Extra environment variables for the spawned CLI.
        extra_options: Escape hatch — keys forwarded to ``ClaudeAgentOptions``
            verbatim. Use sparingly; prefer adding fields here.
    """

    allowed_tools: Optional[List[str]] = Field(
        default=None,
        description="Whitelist of Claude Code tools (Read, Write, Bash, Edit, …).",
    )
    disallowed_tools: Optional[List[str]] = Field(
        default=None,
        description="Tools that must never be used during this run.",
    )
    permission_mode: Optional[str] = Field(
        default=None,
        description="default / acceptEdits / plan / bypassPermissions / dontAsk / auto.",
    )
    cwd: Optional[str] = Field(
        default=None,
        description="Working directory the agent should operate from.",
    )
    cli_path: Optional[str] = Field(
        default=None,
        description="Override the bundled `claude` CLI binary location.",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Override the agent's system prompt.",
    )
    max_turns: Optional[int] = Field(
        default=None,
        description="Hard cap on agent reasoning turns.",
    )
    max_budget_usd: Optional[float] = Field(
        default=None,
        description="Hard cap on total spend for the run.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model id (e.g. claude-sonnet-4-6).",
    )
    fallback_model: Optional[str] = Field(
        default=None,
        description="Model id used if the primary model is unavailable.",
    )
    add_dirs: Optional[List[str]] = Field(
        default=None,
        description="Extra directories the agent is permitted to access.",
    )
    env: Optional[Dict[str, str]] = Field(
        default=None,
        description="Extra environment variables for the spawned CLI.",
    )
    extra_options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Escape hatch — forwarded to ClaudeAgentOptions verbatim.",
    )


# ---------------------------------------------------------------------------
# ClaudeAgentClient
# ---------------------------------------------------------------------------


_INSTALL_HINT = (
    "claude_agent_sdk is not installed. "
    "Install with: pip install ai-parrot[claude-agent]"
)


def _import_sdk():
    """Lazy-import the ``claude_agent_sdk`` symbols we use.

    Returns:
        A tuple ``(query, ClaudeSDKClient, ClaudeAgentOptions)``.

    Raises:
        ImportError: With a clear pip install hint when the optional
            ``[claude-agent]`` extra is not installed.
    """
    try:  # pragma: no cover - import side effect varies by env
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, query
    except ImportError as exc:  # pragma: no cover
        raise ImportError(_INSTALL_HINT) from exc
    return query, ClaudeSDKClient, ClaudeAgentOptions


class ClaudeAgentClient(AbstractClient):
    """Dispatch tasks to a Claude Code agent via ``claude-agent-sdk``.

    This client wraps the bundled ``claude`` CLI as a subprocess and is
    intended for ai-parrot Agents that need to delegate file-aware,
    bash-capable, tool-using work to a Claude Code sub-agent.

    Authentication is delegated to the CLI: it picks up ``ANTHROPIC_API_KEY``
    from the environment when set, otherwise it relies on whatever auth
    flow the user has previously completed via ``claude auth``.

    Methods that have no SDK equivalent (``batch_ask``, ``ask_to_image``,
    the analytic helpers) raise ``NotImplementedError`` with a redirect to
    :class:`AnthropicClient`.
    """

    client_type: str = "claude_agent"
    client_name: str = "claude-agent"
    use_session: bool = False
    _default_model: str = "claude-sonnet-4-6"
    _lightweight_model: str = "claude-haiku-4-5-20251001"

    def __init__(
        self,
        cli_path: Optional[str] = None,
        cwd: Optional[str] = None,
        permission_mode: Optional[str] = None,
        run_options: Optional[ClaudeAgentRunOptions] = None,
        **kwargs: Any,
    ) -> None:
        """Initialise a ``ClaudeAgentClient``.

        Args:
            cli_path: Optional override for the bundled ``claude`` CLI binary.
            cwd: Optional default working directory for every run.
            permission_mode: Optional default permission mode (``"default"``,
                ``"acceptEdits"``, ``"plan"``, ``"bypassPermissions"``).
            run_options: Optional default :class:`ClaudeAgentRunOptions`
                applied to every call. Per-call overrides are still honoured.
            **kwargs: Forwarded to :class:`AbstractClient`.
        """
        # No HTTP headers needed — the transport is a subprocess CLI.
        self.base_headers: Dict[str, str] = {}
        self.cli_path = cli_path
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.default_run_options: ClaudeAgentRunOptions = (
            run_options or ClaudeAgentRunOptions()
        )
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_options(
        self,
        *,
        run_options: Optional[ClaudeAgentRunOptions] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        resume_id: Optional[str] = None,
        permission_mode: Optional[str] = None,
    ) -> Any:
        """Translate ai-parrot options into a ``ClaudeAgentOptions`` instance.

        Per-call ``run_options`` override the instance defaults, which in
        turn override the class-level fallbacks (e.g. ``self.cli_path``).
        """
        _, _, ClaudeAgentOptions = _import_sdk()

        merged = self.default_run_options.model_copy(deep=True)
        if run_options is not None:
            for key, value in run_options.model_dump(exclude_none=True).items():
                if key == "extra_options":
                    if value:
                        merged.extra_options = {**merged.extra_options, **value}
                else:
                    setattr(merged, key, value)

        kwargs: Dict[str, Any] = {}
        # Map merged ClaudeAgentRunOptions onto ClaudeAgentOptions kwargs.
        if merged.allowed_tools is not None:
            kwargs["allowed_tools"] = merged.allowed_tools
        if merged.disallowed_tools is not None:
            kwargs["disallowed_tools"] = merged.disallowed_tools
        effective_permission_mode = (
            permission_mode
            or merged.permission_mode
            or self.permission_mode
        )
        if effective_permission_mode is not None:
            kwargs["permission_mode"] = effective_permission_mode
        effective_cwd = merged.cwd or self.cwd
        if effective_cwd is not None:
            kwargs["cwd"] = effective_cwd
        effective_cli_path = merged.cli_path or self.cli_path
        if effective_cli_path is not None:
            kwargs["cli_path"] = effective_cli_path
        effective_system_prompt = system_prompt or merged.system_prompt
        if effective_system_prompt is not None:
            kwargs["system_prompt"] = effective_system_prompt
        if merged.max_turns is not None:
            kwargs["max_turns"] = merged.max_turns
        if merged.max_budget_usd is not None:
            kwargs["max_budget_usd"] = merged.max_budget_usd
        effective_model = model or merged.model
        if effective_model is not None:
            kwargs["model"] = effective_model
        if merged.fallback_model is not None:
            kwargs["fallback_model"] = merged.fallback_model
        if merged.add_dirs:
            kwargs["add_dirs"] = list(merged.add_dirs)
        if merged.env:
            kwargs["env"] = dict(merged.env)
        if session_id is not None:
            kwargs["session_id"] = session_id
        if resume_id is not None:
            kwargs["resume"] = resume_id
        # Forward arbitrary extras last so they win.
        for key, value in (merged.extra_options or {}).items():
            kwargs[key] = value

        return ClaudeAgentOptions(**kwargs)

    async def _collect_messages(
        self,
        prompt: str,
        *,
        options: Any,
    ) -> List[Any]:
        """Run ``query()`` to completion and return every yielded message."""
        query, _, _ = _import_sdk()
        messages: List[Any] = []
        async for msg in query(prompt=prompt, options=options):
            messages.append(msg)
        return messages

    @staticmethod
    def _resolve_model(model: Optional[Union[str, Any]], fallback: str) -> str:
        """Coerce a model argument (Enum / str / None) into a model id."""
        if model is None:
            return fallback
        # Support enum-like inputs (parrot.models.claude.ClaudeModel).
        return getattr(model, "value", model)

    # ------------------------------------------------------------------
    # AbstractClient surface
    # ------------------------------------------------------------------

    async def get_client(self) -> Any:
        """Return a fresh ``ClaudeSDKClient`` instance.

        ``ClaudeSDKClient`` is a stateful object (it can ``connect()`` to
        the CLI subprocess and exchange messages over its lifetime). One
        instance per event loop is built and cached by the inherited
        ``_ensure_client()`` machinery.

        Raises:
            ImportError: When ``claude_agent_sdk`` is not installed.
        """
        _, ClaudeSDKClient, _ = _import_sdk()
        options = self._build_options()
        return ClaudeSDKClient(options=options)

    async def ask(
        self,
        prompt: str,
        model: Optional[Union[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Any = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        deep_research: bool = False,
        background: bool = False,
        lazy_loading: bool = False,
        *,
        run_options: Optional[ClaudeAgentRunOptions] = None,
    ) -> AIMessage:
        """Dispatch ``prompt`` to a Claude Code agent and return an AIMessage.

        The full SDK message stream is collected first, then converted via
        :py:meth:`AIMessageFactory.from_claude_agent`. ``max_tokens`` and
        ``temperature`` are accepted for ``AbstractClient`` compatibility but
        are not propagated to the agent SDK (which has no equivalent on the
        ``ClaudeAgentOptions`` surface).

        Args:
            prompt: User prompt to send to the agent.
            model: Optional model override.
            run_options: Optional :class:`ClaudeAgentRunOptions` for this call.
            session_id: Optional session id to attach to the run.
            structured_output: Optional pre-parsed structured payload to
                replace the assistant text in the returned ``AIMessage``.
            (other args): Accepted for ``AbstractClient`` compatibility.

        Returns:
            A populated :class:`AIMessage` with ``provider="claude-agent"``.

        Raises:
            ImportError: When ``claude_agent_sdk`` is not installed.
        """
        del max_tokens, temperature, files, tools, use_tools  # not used by SDK
        del deep_research, background, lazy_loading
        resolved_model = self._resolve_model(model, self._default_model)
        turn_id = str(uuid.uuid4())

        self.logger.debug(
            "ClaudeAgentClient.ask model=%s session_id=%s prompt-length=%d",
            resolved_model,
            session_id,
            len(prompt or ""),
        )

        options = self._build_options(
            run_options=run_options,
            model=resolved_model,
            system_prompt=system_prompt,
            session_id=session_id,
        )

        messages = await self._collect_messages(prompt, options=options)

        return AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text=prompt,
            model=resolved_model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output,
        )

    async def ask_stream(  # type: ignore[override]
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        files: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        *,
        run_options: Optional[ClaudeAgentRunOptions] = None,
    ) -> AsyncIterator[str]:
        """Yield the agent's text output incrementally as ``TextBlock``s arrive.

        The agent SDK does not expose a token-by-token streaming primitive
        equivalent to Anthropic's ``messages.stream``; instead we yield each
        ``TextBlock.text`` payload as soon as the corresponding
        ``AssistantMessage`` is received.

        Tool-use blocks are not yielded (they have no user-facing text); the
        full tool-call list is recoverable via ``ask`` if needed.

        Args:
            prompt: User prompt to send to the agent.
            model: Optional model override.
            run_options: Optional :class:`ClaudeAgentRunOptions` for this call.

        Yields:
            ``str`` chunks corresponding to consecutive ``TextBlock``s.

        Raises:
            ImportError: When ``claude_agent_sdk`` is not installed.
        """
        del max_tokens, temperature, files, user_id, tools, deep_research
        del agent_config, lazy_loading
        query, _, _ = _import_sdk()

        resolved_model = self._resolve_model(model, self._default_model)
        options = self._build_options(
            run_options=run_options,
            model=resolved_model,
            system_prompt=system_prompt,
            session_id=session_id,
        )

        try:
            from claude_agent_sdk.types import AssistantMessage, TextBlock
        except ImportError as exc:  # pragma: no cover
            raise ImportError(_INSTALL_HINT) from exc

        async for msg in query(prompt=prompt, options=options):
            # Duck-typed defensive checks in case the SDK introduces new
            # subclasses or aliases.
            if isinstance(msg, AssistantMessage) or type(msg).__name__ == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    if (
                        isinstance(block, TextBlock)
                        or type(block).__name__ == "TextBlock"
                    ):
                        text = getattr(block, "text", "") or ""
                        if text:
                            yield text

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> AIMessage:
        """Continue a previous Claude Code agent session.

        Wraps ``query()`` with ``ClaudeAgentOptions.resume = session_id`` so
        the agent picks up where it left off.

        Args:
            session_id: The session id returned by a previous ``ask`` /
                ``ask_stream`` run (typically read from
                ``AIMessage.session_id``).
            user_input: The new user message to inject into the resumed run.
            state: Optional caller-managed state. Currently unused — accepted
                for ``AbstractClient`` compatibility.

        Returns:
            A populated :class:`AIMessage` with ``provider="claude-agent"``.
        """
        del state  # accepted for AbstractClient parity
        turn_id = str(uuid.uuid4())
        options = self._build_options(resume_id=session_id, session_id=session_id)
        messages = await self._collect_messages(user_input, options=options)
        return AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text=user_input,
            model=self._default_model,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Any = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
        run_options: Optional[ClaudeAgentRunOptions] = None,
    ) -> InvokeResult:
        """Stateless structured-output extraction.

        The agent SDK has no native structured-output primitive analogous to
        OpenAI's ``response_format``. We follow the
        :py:meth:`AnthropicClient.invoke` pattern: embed the JSON schema of
        ``output_type`` directly in the prompt, parse the assistant's text
        response, and return an :class:`InvokeResult`.

        ``invoke`` runs with ``permission_mode="plan"`` by default (no file
        writes), in line with the spec's "decide during implementation"
        guidance — extraction tasks should not mutate the filesystem.
        Callers can override via ``run_options.permission_mode``.

        Args:
            prompt: The user prompt.
            output_type: Pydantic model class or dataclass to parse into.
            structured_output: Pre-parsed payload, takes precedence.
            model: Override model. Falls back to ``_lightweight_model``.
            system_prompt: Override the agent's system prompt.
            max_tokens: Accepted for parity; not propagated.
            temperature: Accepted for parity; not propagated.
            use_tools: Accepted for parity; ignored.
            tools: Accepted for parity; ignored.
            run_options: Optional :class:`ClaudeAgentRunOptions` for this call.

        Returns:
            An :class:`InvokeResult` with ``output``, ``output_type``, ``model``,
            ``usage`` and ``raw_response``.

        Raises:
            InvokeError: If the agent fails or its output cannot be parsed
                into ``output_type``.
        """
        del max_tokens, temperature, use_tools, tools  # parity-only
        resolved_model = self._resolve_model(
            model, self._lightweight_model or self._default_model
        )

        # Effective options: default to permission_mode="plan" so invoke()
        # can never mutate the filesystem unless the caller explicitly opts in.
        effective_run_options = (
            run_options.model_copy(deep=True)
            if run_options is not None
            else ClaudeAgentRunOptions()
        )
        if effective_run_options.permission_mode is None:
            effective_run_options.permission_mode = "plan"

        # Build a schema-in-prompt extension when output_type is provided.
        schema_clause = ""
        if structured_output is None and output_type is not None:
            schema_clause = self._render_schema_clause(output_type)

        full_prompt = (
            f"{prompt}\n\n{schema_clause}".strip()
            if schema_clause
            else prompt
        )

        try:
            options = self._build_options(
                run_options=effective_run_options,
                model=resolved_model,
                system_prompt=system_prompt,
            )
            messages = await self._collect_messages(full_prompt, options=options)
        except ImportError:
            raise
        except Exception as exc:  # pragma: no cover - provider-side
            raise InvokeError(
                f"ClaudeAgentClient.invoke failed: {exc}", original=exc
            ) from exc

        ai_message = AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text=full_prompt,
            model=resolved_model,
        )

        # Parse the assistant text into ``output_type`` when asked.
        parsed: Any = structured_output if structured_output is not None else ai_message.response
        if structured_output is None and output_type is not None and ai_message.response:
            parsed = self._parse_structured_output(ai_message.response, output_type)

        return InvokeResult(
            output=parsed,
            output_type=output_type,
            model=resolved_model,
            usage=ai_message.usage,
            raw_response=ai_message.raw_response,
        )

    async def batch_ask(self, requests: List[Any], **kwargs: Any) -> List[Any]:
        """Always raises — the agent SDK has no batch primitive.

        Use :class:`AnthropicClient` for the Messages Batches API.
        """
        del requests, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not support batch processing. "
            "Use AnthropicClient for the Anthropic Messages Batches API."
        )

    # ------------------------------------------------------------------
    # Methods with no SDK equivalent — explicit failure mode
    # ------------------------------------------------------------------

    async def ask_to_image(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not support vision / image inputs. "
            "Use AnthropicClient.ask_to_image instead."
        )

    async def summarize_text(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not implement summarize_text. "
            "Use AnthropicClient.summarize_text instead."
        )

    async def translate_text(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not implement translate_text. "
            "Use AnthropicClient.translate_text instead."
        )

    async def analyze_sentiment(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not implement analyze_sentiment. "
            "Use AnthropicClient.analyze_sentiment instead."
        )

    async def analyze_product_review(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not implement analyze_product_review. "
            "Use AnthropicClient.analyze_product_review instead."
        )

    async def extract_key_points(self, *args: Any, **kwargs: Any) -> AIMessage:
        del args, kwargs
        raise NotImplementedError(
            "ClaudeAgentClient does not implement extract_key_points. "
            "Use AnthropicClient.extract_key_points instead."
        )

    # ------------------------------------------------------------------
    # Internals — schema rendering & response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _render_schema_clause(output_type: type) -> str:
        """Build a short instruction describing the JSON schema to emit."""
        schema: Optional[Dict[str, Any]] = None
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            try:
                schema = output_type.model_json_schema()
            except Exception:  # pragma: no cover - very defensive
                schema = None
        elif is_dataclass(output_type):
            # Best-effort schema for dataclasses: list of field names.
            schema = {
                "type": "object",
                "properties": {
                    f.name: {"type": "string"}
                    for f in output_type.__dataclass_fields__.values()  # type: ignore[attr-defined]
                },
            }
        if schema is None:
            return (
                "Respond with a single JSON object that captures the answer. "
                "Do not include any prose before or after the JSON."
            )
        schema_text = json.dumps(schema, indent=2, default=str)
        return (
            "Respond with a single JSON object that conforms to the following "
            f"JSON schema and nothing else (no prose, no code fences):\n\n{schema_text}"
        )

    @staticmethod
    def _parse_structured_output(text: str, output_type: type) -> Any:
        """Parse the agent's text output into ``output_type``.

        Tries ``output_type.model_validate_json`` (Pydantic v2) first, then
        falls back to ``json.loads`` + dataclass / type construction.

        Raises:
            InvokeError: If the response is not valid JSON or cannot be
                coerced into ``output_type``.
        """
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # Try to recover JSON from a fenced block before giving up.
            stripped = text.strip()
            if "```" in stripped:
                inside = stripped.split("```", 2)
                if len(inside) >= 2:
                    body = inside[1]
                    if body.lower().startswith("json\n"):
                        body = body[5:]
                    try:
                        payload = json.loads(body)
                    except json.JSONDecodeError:
                        raise InvokeError(
                            "ClaudeAgentClient.invoke: response is not valid JSON.",
                            original=exc,
                        ) from exc
                else:
                    raise InvokeError(
                        "ClaudeAgentClient.invoke: response is not valid JSON.",
                        original=exc,
                    ) from exc
            else:
                raise InvokeError(
                    "ClaudeAgentClient.invoke: response is not valid JSON.",
                    original=exc,
                ) from exc

        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            try:
                return output_type.model_validate(payload)
            except Exception as exc:
                raise InvokeError(
                    f"ClaudeAgentClient.invoke: payload does not match {output_type.__name__}.",
                    original=exc,
                ) from exc
        if is_dataclass(output_type):
            try:
                return output_type(**payload)  # type: ignore[misc]
            except Exception as exc:
                raise InvokeError(
                    f"ClaudeAgentClient.invoke: payload does not match {output_type.__name__}.",
                    original=exc,
                ) from exc
        return payload
