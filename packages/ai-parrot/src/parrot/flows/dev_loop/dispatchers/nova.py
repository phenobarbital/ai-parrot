"""NovaCodeDispatcher — local coding-agent loop bound to bedrock-mantle.

The Nova dev seat is the only one of the three Nova seats (spec
``novaclient-dev-loop`` §2) that needs a tool loop, and the reason the
transport-split design works at all: AWS serves MiniMax M2.5 (and Kimi
K2.5/GLM-5) over the **OpenAI-compatible ``bedrock-mantle`` endpoint**
(``https://bedrock-mantle.{region}.api.aws/v1``), which is exactly the
shape :class:`~parrot.flows.dev_loop.dispatchers.llm.LLMCodeDispatcher`'s
loop already speaks.

This dispatcher does **NOT** drive the dev seat through :class:`NovaClient`/
Converse — ``BedrockConverseBase`` exposes no OpenAI-shaped
``_chat_completion``, so the base dispatcher's ``_chat_completion`` would
raise ``DispatchExecutionError("... does not expose chat completion")``
against it. Instead, the injected ``client_factory`` builds a plain
:class:`~parrot.clients.gpt.OpenAIClient` pointed at the bedrock-mantle base
URL, reusing the inherited tool loop, Redis event streaming, cwd-safety
guard, and output validation unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from parrot import conf
from parrot.clients.factory import LLMFactory
from parrot.clients.gpt import OpenAIClient
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import NovaCodeDispatchProfile
from parrot.flows.dev_loop.models.nova import effective_max_tokens
from parrot.flows.dev_loop.session_state import SessionHost


class NovaCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to Bedrock via the bedrock-mantle endpoint.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard and output validation, while
    overriding the completion hooks so requests route through an
    OpenAI-compatible client pointed at
    ``https://bedrock-mantle.{region}.api.aws/v1`` instead of the default
    ``LLMFactory``-resolved client (which would resolve ``"nova:"`` to
    :class:`~parrot.clients.nova.client.NovaClient`, a Converse-only client
    with no chat-completion shape).
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=self._create_mantle_client,
        )

    def _create_mantle_client(
        self,
        llm: str,
        *,
        model_args: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """``client_factory`` hook — builds an OpenAI-compatible client bound
        to the bedrock-mantle endpoint instead of routing through
        ``LLMFactory``/``NovaClient``.

        Args:
            llm: The profile's ``llm`` string, e.g.
                ``"nova:minimax.minimax-m2.5"``.
            model_args: Optional dict with ``temperature``/``max_tokens``
                (matches the shape ``LLMCodeDispatcher._create_client``
                passes to the default ``LLMFactory.create`` factory).
            **kwargs: Forwarded to :class:`OpenAIClient`.

        Returns:
            An :class:`OpenAIClient` instance targeting bedrock-mantle.

        Raises:
            DispatchExecutionError: When the mantle base URL or the Bedrock
                API key cannot be resolved — names the missing config key.
        """
        _provider, model = LLMFactory.parse_llm_string(llm)
        init_params: Dict[str, Any] = {}
        if model:
            init_params["model"] = model
        if model_args:
            for key in ("temperature", "max_tokens"):
                value = model_args.get(key)
                if value is not None:
                    init_params[key] = value
        init_params.update(kwargs)
        return OpenAIClient(
            api_key=self._resolve_bedrock_api_key(),
            base_url=self._resolve_mantle_base_url(),
            **init_params,
        )

    @staticmethod
    def _resolve_bedrock_api_key() -> str:
        """Resolve the bedrock-mantle bearer token.

        Reuses ``conf.AWS_NOVA_API_KEY`` — the same Bedrock API key
        ``BedrockConverseBase`` uses for the Converse seats — rather than a
        duplicate secret.
        """
        api_key = conf.AWS_NOVA_API_KEY
        if not api_key:
            raise DispatchExecutionError(
                "AWS_NOVA_API_KEY is required for the nova dev seat "
                "(bedrock-mantle bearer token); set it in the environment "
                "or navconfig settings."
            )
        return api_key

    @staticmethod
    def _resolve_mantle_base_url() -> str:
        """Resolve the bedrock-mantle base URL from config."""
        base_url = conf.DEV_LOOP_NOVA_MANTLE_BASE_URL
        if base_url:
            return base_url
        region = conf.DEV_LOOP_NOVA_MANTLE_REGION
        if not region:
            raise DispatchExecutionError(
                "DEV_LOOP_NOVA_MANTLE_BASE_URL or DEV_LOOP_NOVA_MANTLE_REGION "
                "is required to resolve the bedrock-mantle endpoint for the "
                "nova dev seat."
            )
        return f"https://bedrock-mantle.{region}.api.aws/v1"

    def _completion_args(
        self,
        profile: NovaCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build MiniMax/Kimi/GLM-appropriate completion args.

        Never emits ``extra_body``/``chat_template_kwargs`` — an Nvidia-only
        concept the base class's ``_completion_args`` also emits, but which
        the bedrock-mantle models do not use. Applies the per-model output
        clamp (TASK-2085's :func:`effective_max_tokens`) to the effective
        ``max_tokens``.
        """
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": effective_max_tokens(
                model or profile.model, profile.max_tokens, self.logger
            ),
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        """Route through the client's OpenAI-shaped ``_chat_completion``.

        No request-shape change is needed beyond the base implementation —
        the routing to bedrock-mantle happens at client construction
        (``_create_mantle_client``), not at call time. Overridden (rather
        than left purely inherited) to keep the two-hook override shape
        explicit and documented, mirroring
        ``MoonshotCodeDispatcher``/``ZaiCodeDispatcher``.
        """
        return await super()._chat_completion(
            client=client,
            model=model,
            messages=messages,
            args=args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: NovaCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
    ) -> T:
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
        )
