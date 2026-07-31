"""
ModelSwitchingMixin — dual-LLM model switching for AbstractBot.

Adds the ability to configure a **secondary** LLM client next to the bot's
primary one, and use it in one of two modes:

- **fallback**: the primary client serves every call; when it raises, the
  same call is retried once on the secondary client (cross-provider
  failover — complementary to the client-level same-provider
  ``fallback_model`` retries).
- **contrastive**: both clients answer the same prompt concurrently and the
  results are merged into a single :class:`~parrot.models.responses.AIMessage`
  whose ``metadata['model_switching']`` attributes each answer to the model
  that produced it.

The mixin hooks the ``get_client()`` / ``execute_llm_call()`` extension
points on :class:`~parrot.bots.abstract.AbstractBot` — the same cooperative
pattern used by ``IntentRouterMixin`` (``_resolve_output_mode``) and
``SkillRegistryMixin`` (``post_configure``).

Usage::

    from parrot.bots.agent import Agent
    from parrot.bots.mixins import ModelSwitchingMixin, ModelSwitchMode

    class ResearchAgent(ModelSwitchingMixin, Agent):
        pass

    agent = ResearchAgent(
        llm="google:gemini-2.5-flash",
        secondary_llm="anthropic:claude-sonnet-5",
        model_switch_mode=ModelSwitchMode.CONTRASTIVE,
    )

Limitations (v1): only non-streaming calls (``ask``) are switched;
``ask_stream`` always uses the primary client.
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any, Dict, Optional, Union

from ...clients.base import AbstractClient
from ...exceptions import ConfigError
from ...models.basic import CompletionUsage


class ModelSwitchMode(str, Enum):
    """How the secondary LLM client participates in a call."""

    FALLBACK = "fallback"
    CONTRASTIVE = "contrastive"


class ModelSwitchingMixin:
    """Mixin to add dual-LLM model switching to any bot or agent.

    Mix in **before** the bot class so the MRO reaches this class first::

        class MyAgent(ModelSwitchingMixin, Agent):
            ...

    Attributes:
        enable_model_switching: Master switch. When ``False`` the mixin is a
            pure passthrough. Default ``True``.
        model_switch_mode: :class:`ModelSwitchMode` (or its string value)
            selecting fallback or contrastive behavior. Default ``fallback``.
        secondary_llm: Specification of the secondary client, in any format
            :meth:`~parrot.bots.abstract.AbstractBot._resolve_llm_config`
            accepts — ``"provider:model"`` string, ``AbstractClient``
            subclass or instance, or a ``model_config`` dict. Default
            ``None`` (switching disabled until provided).

    The merged response always carries a ``metadata['model_switching']``
    payload attributing which model produced what, e.g. for contrastive::

        {
            "mode": "contrastive",
            "responses": [
                {"role": "primary", "provider": "google", "model": "...",
                 "output": "...", "usage": {...}, "response_time": 1.2},
                {"role": "secondary", ...},
            ],
        }
    """

    # Configuration (overridable as class attrs or constructor kwargs)
    enable_model_switching: bool = True
    model_switch_mode: ModelSwitchMode = ModelSwitchMode.FALLBACK
    secondary_llm: Union[str, dict, AbstractClient, None] = None

    # Event emitted (via EventEmitterMixin) when a fallback switch happens.
    EVENT_MODEL_SWITCHED = "model_switched"

    # Runtime
    _secondary_client: Optional[AbstractClient] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pop mixin kwargs, then continue the cooperative ``__init__`` chain."""
        if "secondary_llm" in kwargs:
            self.secondary_llm = kwargs.pop("secondary_llm")
        if "model_switch_mode" in kwargs:
            self.model_switch_mode = ModelSwitchMode(kwargs.pop("model_switch_mode"))
        if "enable_model_switching" in kwargs:
            self.enable_model_switching = bool(kwargs.pop("enable_model_switching"))
        self._secondary_client = None
        super().__init__(*args, **kwargs)

    # ── Configuration ────────────────────────────────────────────────────

    async def post_configure(self) -> None:
        """Build the secondary client after base configuration completes.

        Chains ``super().post_configure()`` first (documented contract of
        :meth:`AbstractBot.post_configure`), then resolves
        :attr:`secondary_llm` through the existing
        :meth:`~parrot.interfaces.tools.ToolInterface.configure_llm` helper so
        the secondary client gets the same tool sync and conversation memory
        as the primary.

        Raises:
            ConfigError: If switching is enabled with a ``secondary_llm``
                spec that cannot be resolved into a client.
        """
        await super().post_configure()
        if not self.enable_model_switching or self.secondary_llm is None:
            return
        if self._secondary_client is not None:
            return
        try:
            if isinstance(self.secondary_llm, dict):
                self._secondary_client = self.configure_llm(
                    model_config=self.secondary_llm
                )
            else:
                self._secondary_client = self.configure_llm(llm=self.secondary_llm)
        except Exception as exc:
            raise ConfigError(
                f"ModelSwitchingMixin: cannot resolve secondary_llm "
                f"{self.secondary_llm!r}: {exc}"
            ) from exc
        self.logger.info(
            "Model switching enabled (%s): primary=%s secondary=%s",
            ModelSwitchMode(self.model_switch_mode).value,
            self._client_label(getattr(self, "_llm", None)),
            self._client_label(self._secondary_client),
        )

    # ── Policy hooks ─────────────────────────────────────────────────────

    def should_switch_on(self, error: Exception) -> bool:
        """Decide whether an error from the primary triggers the secondary.

        Default: switch on any exception except ``asyncio.CancelledError``.
        Override for finer control (e.g. only capacity errors).

        Args:
            error: The exception raised by the primary client's call.

        Returns:
            ``True`` to retry the call on the secondary client.
        """
        return not isinstance(error, asyncio.CancelledError)

    # ── Core override ────────────────────────────────────────────────────

    async def execute_llm_call(
        self,
        client: AbstractClient,
        method: str = "ask",
        **llm_kwargs: Any,
    ) -> Any:
        """Execute the LLM call with fallback or contrastive switching.

        Passes straight through to the primary when switching is disabled,
        no secondary client is configured, or the call is not an ``ask``.

        Args:
            client: The already-entered primary client.
            method: Client coroutine name (only ``"ask"`` is switched).
            **llm_kwargs: Keyword arguments for the client call.

        Returns:
            The (possibly merged/annotated) ``AIMessage``.
        """
        switching_active = (
            self.enable_model_switching
            and self._secondary_client is not None
            and method == "ask"
        )
        if not switching_active:
            return await super().execute_llm_call(client, method, **llm_kwargs)

        # Normalize: subclasses may declare the mode as a plain string.
        mode = ModelSwitchMode(self.model_switch_mode)
        if mode is ModelSwitchMode.CONTRASTIVE:
            return await self._contrastive_call(client, method, **llm_kwargs)
        return await self._fallback_call(client, method, **llm_kwargs)

    # ── Fallback mode ────────────────────────────────────────────────────

    async def _fallback_call(
        self,
        client: AbstractClient,
        method: str,
        **llm_kwargs: Any,
    ) -> Any:
        """Primary first; on error, retry the same call once on the secondary."""
        try:
            response = await super().execute_llm_call(client, method, **llm_kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as primary_err:
            if not self.should_switch_on(primary_err):
                raise
            primary_info = self._client_info(client)
            self.logger.warning(
                "Primary LLM %s failed (%s: %s) — switching to secondary %s",
                self._client_label(client),
                type(primary_err).__name__,
                primary_err,
                self._client_label(self._secondary_client),
            )
            try:
                async with self._secondary_client as secondary:
                    response = await getattr(secondary, method)(**llm_kwargs)
            except Exception as secondary_err:
                self.logger.error(
                    "Secondary LLM %s also failed (%s: %s); raising primary error",
                    self._client_label(self._secondary_client),
                    type(secondary_err).__name__,
                    secondary_err,
                )
                raise primary_err from secondary_err
            self._annotate(response, {
                "mode": ModelSwitchMode.FALLBACK.value,
                "switched": True,
                "primary": {
                    **primary_info,
                    "error_type": type(primary_err).__name__,
                    "error": str(primary_err),
                },
                "served_by": self._response_info(response),
            })
            self._emit_switch_event(primary_err, response)
            return response

        self._annotate(response, {
            "mode": ModelSwitchMode.FALLBACK.value,
            "switched": False,
            "served_by": self._response_info(response),
        })
        return response

    # ── Contrastive mode ─────────────────────────────────────────────────

    async def _contrastive_call(
        self,
        client: AbstractClient,
        method: str,
        **llm_kwargs: Any,
    ) -> Any:
        """Call primary and secondary concurrently and merge into one message."""
        started = time.perf_counter()
        primary_res, secondary_res = await asyncio.gather(
            super().execute_llm_call(client, method, **llm_kwargs),
            self._call_secondary(method, **llm_kwargs),
            return_exceptions=True,
        )
        if isinstance(primary_res, asyncio.CancelledError):
            raise primary_res
        if isinstance(secondary_res, asyncio.CancelledError):
            raise secondary_res

        primary_failed = isinstance(primary_res, BaseException)
        secondary_failed = isinstance(secondary_res, BaseException)

        if primary_failed and secondary_failed:
            self.logger.error(
                "Contrastive call: both models failed (primary %s: %s / secondary %s: %s)",
                self._client_label(client),
                primary_res,
                self._client_label(self._secondary_client),
                secondary_res,
            )
            raise primary_res

        entries = [
            self._contrastive_entry("primary", client, primary_res),
            self._contrastive_entry("secondary", self._secondary_client, secondary_res),
        ]

        if primary_failed or secondary_failed:
            survivor = secondary_res if primary_failed else primary_res
            self.logger.warning(
                "Contrastive call: %s model failed — returning the surviving answer",
                "primary" if primary_failed else "secondary",
            )
            self._annotate(survivor, {
                "mode": ModelSwitchMode.CONTRASTIVE.value,
                "responses": entries,
            })
            return survivor

        # Both succeeded: primary AIMessage is the carrier so downstream
        # post-processing (sources, memory, formatter) sees a normal message.
        combined = self._combine_outputs(primary_res, secondary_res, **llm_kwargs)
        if combined is not None:
            primary_res.output = combined
            primary_res.response = combined
        self._aggregate_usage(primary_res, secondary_res)
        if primary_res.response_time is not None:
            primary_res.response_time = time.perf_counter() - started
        self._annotate(primary_res, {
            "mode": ModelSwitchMode.CONTRASTIVE.value,
            "responses": entries,
        })
        return primary_res

    async def _call_secondary(self, method: str, **llm_kwargs: Any) -> Any:
        """Run one call on the secondary client, managing its own context."""
        async with self._secondary_client as secondary:
            return await getattr(secondary, method)(**llm_kwargs)

    def _combine_outputs(
        self,
        primary: Any,
        secondary: Any,
        **llm_kwargs: Any,
    ) -> Optional[str]:
        """Build the combined labeled markdown output, or ``None`` to keep primary.

        Structured-output calls and non-text outputs are not merged — the
        primary output stays authoritative and the secondary answer remains
        available in ``metadata['model_switching']``.
        """
        if llm_kwargs.get("structured_output") is not None:
            return None
        primary_text = self._response_text(primary)
        secondary_text = self._response_text(secondary)
        if primary_text is None or secondary_text is None:
            return None
        return (
            f"### {primary.provider}:{primary.model} (primary)\n\n"
            f"{primary_text}\n\n"
            f"### {secondary.provider}:{secondary.model} (secondary)\n\n"
            f"{secondary_text}"
        )

    def _contrastive_entry(
        self,
        role: str,
        client: Optional[AbstractClient],
        result: Any,
    ) -> Dict[str, Any]:
        """Build one attribution entry for the contrastive metadata payload."""
        if isinstance(result, BaseException):
            return {
                "role": role,
                **self._client_info(client),
                "error_type": type(result).__name__,
                "error": str(result),
            }
        usage = getattr(result, "usage", None)
        return {
            "role": role,
            **self._response_info(result),
            "output": self._response_text(result),
            "usage": usage.model_dump() if usage is not None else None,
            "response_time": getattr(result, "response_time", None),
        }

    @staticmethod
    def _aggregate_usage(primary: Any, secondary: Any) -> None:
        """Sum token counts of both calls into the carrier message's usage."""
        p_usage = getattr(primary, "usage", None)
        s_usage = getattr(secondary, "usage", None)
        if not isinstance(p_usage, CompletionUsage) or not isinstance(s_usage, CompletionUsage):
            return
        p_usage.prompt_tokens += s_usage.prompt_tokens
        p_usage.completion_tokens += s_usage.completion_tokens
        p_usage.total_tokens += s_usage.total_tokens

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _response_text(response: Any) -> Optional[str]:
        """Text of a response, or ``None`` when it is not plain text."""
        output = getattr(response, "output", None)
        return output if isinstance(output, str) else None

    @staticmethod
    def _client_info(client: Optional[AbstractClient]) -> Dict[str, Any]:
        """Provider/model attribution for a client instance."""
        if client is None:
            return {"provider": None, "model": None}
        return {
            "provider": getattr(client, "client_name", None) or type(client).__name__,
            "model": getattr(client, "model", None),
        }

    @staticmethod
    def _response_info(response: Any) -> Dict[str, Any]:
        """Provider/model attribution taken from an ``AIMessage``."""
        return {
            "provider": getattr(response, "provider", None),
            "model": getattr(response, "model", None),
        }

    @staticmethod
    def _client_label(client: Optional[AbstractClient]) -> str:
        """Human-readable ``provider:model`` label for logging."""
        if client is None:
            return "<none>"
        provider = getattr(client, "client_name", None) or type(client).__name__
        model = getattr(client, "model", None)
        return f"{provider}:{model}" if model else str(provider)

    @staticmethod
    def _annotate(response: Any, payload: Dict[str, Any]) -> None:
        """Attach the model_switching payload to ``response.metadata``."""
        metadata = getattr(response, "metadata", None)
        if metadata is None:
            try:
                response.metadata = {"model_switching": payload}
            except Exception:
                return
        else:
            metadata["model_switching"] = payload

    def _emit_switch_event(self, error: Exception, response: Any) -> None:
        """Emit the bot-level model_switched event (best-effort)."""
        trigger = getattr(self, "_trigger_event", None)
        if callable(trigger):
            trigger(
                self.EVENT_MODEL_SWITCHED,
                error=str(error),
                error_type=type(error).__name__,
                served_by=self._response_info(response),
            )

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Close the secondary client, then continue the cleanup chain."""
        if self._secondary_client is not None:
            close = getattr(self._secondary_client, "close", None)
            if callable(close):
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    self.logger.error(
                        "Error closing secondary LLM client: %s", exc
                    )
            self._secondary_client = None
        await super().cleanup()
