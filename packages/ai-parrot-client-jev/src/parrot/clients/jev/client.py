"""TypeSafe AI System One client (Jev) for AI-Parrot.

Jev is a *System One* model: it does not generate text. A request carries
**state** (a string or JSON document) plus a map of typed **questions**
(:class:`~parrot.clients.jev.models.Noul`, :class:`~parrot.clients.jev.models.Choice`,
:class:`~parrot.clients.jev.models.Score`); the model answers every question
in one parallel pass and returns structured answers with calibrated
probabilities. There is no streaming, no tool calling and no free text.

This client maps that contract onto :class:`~parrot.clients.base.AbstractClient`:

- :meth:`JevClient.system_one` is the raw API call
  (``POST {base_url}/v1/systemone``) and returns a
  :class:`~parrot.clients.jev.models.SystemOneResponse`.
- :meth:`JevClient.ask` treats the prompt (plus optional ``system_prompt`` and
  rendered ``history``) as the state; the questions come from the
  ``questions=`` kwarg, a Pydantic ``structured_output`` type, or the
  ``questions=`` configured at construction. It returns an ``AIMessage``
  whose ``output`` / ``structured_output`` is the typed result.
- :meth:`JevClient.invoke` derives the questions from ``output_type`` (see
  :mod:`parrot.clients.jev.schema`) and validates the answers back into it.
- :meth:`JevClient.ask_stream` is a pseudo-stream (one text chunk, then the
  final ``AIMessage``) so streaming consumers keep working.

No vendor SDK is used: the official ``typesafe-sdk`` is built on ``httpx2``,
which the codebase conventions forbid, so the wire protocol (Bearer auth,
JSON body ``{"state", "model", "questions"}``, ``retry-after`` handling and
the status → error mapping) is implemented here over ``aiohttp`` with
``tenacity`` retries.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from enum import Enum
from importlib.metadata import PackageNotFoundError, version as _dist_version
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Sequence, Tuple, Type, Union

import aiohttp
from navconfig import config
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from parrot.clients.base import AbstractClient, MessageResponse
from parrot.memory.render import HistoryMessage
from parrot.models import AIMessage, CompletionUsage, StructuredOutputConfig
from parrot.models.responses import InvokeResult
from parrot.observability.context import current_session_id, current_user_id

from .exceptions import (
    REQUEST_ID_HEADER,
    JevAPIError,
    JevConfigurationError,
    JevConnectionError,
    JevError,
    api_error,
)
from .models import (
    JSONContent,
    JevModel,
    ListModelsResponse,
    ModelMetadata,
    QuestionInput,
    SystemOneResponse,
    normalize_questions,
)
from .schema import answers_to_type, questions_from_type

#: Default API origin; override with ``base_url=`` or ``TYPESAFE_BASE_URL``.
DEFAULT_BASE_URL = "https://api.typesafe.ai"
SYSTEM_ONE_PATH = "/v1/systemone"
MODELS_PATH = "/v1/models"
#: Default per-request timeout in seconds (the vendor SDK default).
DEFAULT_TIMEOUT = 10.0
#: HTTP statuses that are retried (the vendor SDK default policy).
RETRYABLE_STATUSES = frozenset({408, 429, *range(500, 600)})
#: Longest wait honoured from a ``retry-after`` header, in seconds.
MAX_RETRY_AFTER = 30.0

QuestionsInput = Mapping[str, QuestionInput]


def _package_version() -> str:
    """Version of this satellite, for the ``User-Agent`` header."""
    try:
        return _dist_version("ai-parrot-client-jev")
    except PackageNotFoundError:  # running from a source checkout
        return "0.0.0"


def _json_default(value: Any) -> Any:
    """``json.dumps`` fallback for Pydantic models, enums, paths and sets."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _decode_body(raw: bytes) -> Any:
    """Decode a response body as JSON, falling back to text; ``None`` when empty."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")


class JevClient(AbstractClient):
    """Client for TypeSafe AI's System One API (the Jev model).

    Args:
        api_key: TypeSafe API key. Falls back to the ``TYPESAFE_API_KEY``
            environment variable (resolved via ``navconfig.config``). Checked
            lazily, on the first request.
        base_url: API origin. Falls back to ``TYPESAFE_BASE_URL``, then
            :data:`DEFAULT_BASE_URL`.
        model: Model name or alias (see :class:`JevModel`). Falls back to
            ``TYPESAFE_DEFAULT_MODEL``, then ``jev-latest``. Versioned IDs such
            as ``jev-1.13.0`` are accepted even when ``list_models()`` only
            lists the aliases.
        timeout: Per-request timeout in seconds (default 10).
        max_retries: Retries after the initial attempt on 408/429/5xx and
            connection errors (default 2; ``0`` disables retries).
        questions: Default question map used by :meth:`ask` when a call
            supplies neither ``questions=`` nor a structured output type.
        noul_threshold: Probability at or above which a noul answer becomes
            ``True`` when validated into a ``bool`` field (default 0.5).
        **kwargs: Forwarded to :class:`~parrot.clients.base.AbstractClient`.

    Example::

        client = JevClient()
        response = await client.system_one(
            state={"document": "I was charged twice. Please fix this ASAP."},
            questions={
                "category": Choice(
                    instructions="What is this ticket about?",
                    criteria={"billing": None, "technical": None, "other": None},
                ),
            },
        )
        response.choices["category"].choice  # "billing"
    """

    client_type: str = "jev"
    client_name: str = "jev"
    #: Provider label stamped on every ``AIMessage`` / ``InvokeResult``.
    provider_name: str = "typesafe"

    # FEAT-523 folder-convention attributes (read by LLMFactory).
    provider_keys: tuple[str, ...] = ("jev", "typesafe")
    models: type[Enum] = JevModel
    _default_model: str = JevModel.JEV_LATEST.value
    # System One emits no generated tokens: there is no output budget to cap.
    _default_max_tokens: Optional[int] = None
    _invoke_max_tokens: Optional[int] = None
    _lightweight_model: Optional[str] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Union[str, JevModel, None] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        questions: Optional[QuestionsInput] = None,
        noul_threshold: float = 0.5,
        **kwargs: Any,
    ) -> None:
        resolved_key = api_key or config.get("TYPESAFE_API_KEY") or None
        resolved_url = (base_url or config.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        if isinstance(model, Enum):
            model = model.value
        resolved_model = (
            model or kwargs.pop("model", None) or config.get("TYPESAFE_DEFAULT_MODEL") or self._default_model
        )
        kwargs["model"] = resolved_model
        super().__init__(api_key=resolved_key, **kwargs)
        # Re-set after super().__init__ because AbstractClient may overwrite
        # self.api_key during its own initialisation (same guard as the other
        # satellites, e.g. MoonshotClient).
        self.api_key: Optional[str] = resolved_key
        self.base_url: str = resolved_url
        self.timeout: float = float(timeout)
        self.max_retries: int = max(0, int(max_retries))
        self.default_questions: Optional[Dict[str, QuestionInput]] = dict(questions) if questions else None
        self.noul_threshold: float = float(noul_threshold)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def _session_headers(self) -> Dict[str, str]:
        """Static headers sent on every request."""
        headers = {
            "Accept": "application/json",
            "User-Agent": f"ai-parrot-client-jev/{_package_version()}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_client(self) -> aiohttp.ClientSession:
        """Build the per-event-loop ``aiohttp`` session.

        Cached by :meth:`~parrot.clients.base.AbstractClient._ensure_client`
        and closed by :meth:`~parrot.clients.base.AbstractClient.close`.

        Returns:
            A configured :class:`aiohttp.ClientSession`.
        """
        return aiohttp.ClientSession(
            headers=self._session_headers(),
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            raise_for_status=False,
        )

    # ------------------------------------------------------------------ #
    # Transport                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_retryable(error: BaseException) -> bool:
        """Retry connection failures/timeouts and 408/429/5xx responses."""
        if isinstance(error, JevConnectionError):
            return True
        return isinstance(error, JevAPIError) and error.status in RETRYABLE_STATUSES

    @staticmethod
    def _retry_wait(retry_state: RetryCallState) -> float:
        """Honour ``retry-after`` when present, else jittered exponential backoff (0.5s → 5s)."""
        error = retry_state.outcome.exception() if retry_state.outcome is not None else None
        if isinstance(error, JevAPIError) and error.retry_after is not None:
            return min(error.retry_after, MAX_RETRY_AFTER)
        exponential = min(5.0, 0.5 * (2 ** (retry_state.attempt_number - 1)))
        return round(exponential * (1 - random.random() * 0.25), 3)  # noqa: S311 - jitter, not crypto

    async def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Tuple[Any, Optional[str]]:
        """Send one API request with retries and map failures to exceptions.

        Args:
            method: HTTP method.
            path: Path under :attr:`base_url`.
            body: JSON body, or ``None`` for body-less requests.
            timeout: Per-call override of the session timeout, in seconds.

        Returns:
            ``(decoded_body, request_id)``.

        Raises:
            JevConfigurationError: No API key is configured.
            JevConnectionError: The request produced no HTTP response.
            JevAPIError: The API answered with a non-2xx status (subclass
                chosen by status code).
        """
        if not self.api_key:
            raise JevConfigurationError(
                "No TypeSafe API key was provided. Pass api_key= or set the TYPESAFE_API_KEY environment variable."
            )
        session = await self._ensure_client()
        url = f"{self.base_url}{path}"
        payload: Optional[bytes] = None
        headers: Dict[str, str] = {}
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, default=_json_default).encode("utf-8")
            headers["Content-Type"] = "application/json"
        client_timeout = aiohttp.ClientTimeout(total=timeout) if timeout is not None else None

        async def attempt() -> Tuple[Any, Optional[str]]:
            try:
                async with session.request(method, url, data=payload, headers=headers, timeout=client_timeout) as resp:
                    raw = await resp.read()
                    request_id = resp.headers.get(REQUEST_ID_HEADER)
                    data = _decode_body(raw)
                    self.logger.debug("%s %s <- %s (request %s)", method, url, resp.status, request_id or "-")
                    if resp.status >= 400:
                        raise api_error(resp.status, data, resp.headers)
                    return data, request_id
            except asyncio.TimeoutError as exc:
                raise JevConnectionError(f"Request to {url} timed out after {timeout or self.timeout}s") from exc
            except aiohttp.ClientError as exc:
                raise JevConnectionError(f"Connection error calling {url}: {exc}") from exc

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.max_retries + 1),
            wait=self._retry_wait,
            retry=retry_if_exception(self._is_retryable),
            reraise=True,
        )
        return await retrying(attempt)

    # ------------------------------------------------------------------ #
    # Request shaping                                                     #
    # ------------------------------------------------------------------ #

    def _resolve_model(self, model: Union[str, Enum, None] = None) -> str:
        """Explicit model > configured ``self.model`` > class default."""
        if isinstance(model, Enum):
            model = model.value
        return model or self.model or self._default_model

    @staticmethod
    def _coerce_state(state: Any) -> JSONContent:
        """Normalise ``state`` to text / JSON object / JSON array.

        Args:
            state: A string, dict, list, or Pydantic model.

        Returns:
            The JSON-ready state.

        Raises:
            JevConfigurationError: For any other type.
        """
        if isinstance(state, BaseModel):
            return state.model_dump(mode="json")
        if isinstance(state, (str, dict, list)):
            return state
        if isinstance(state, Mapping):
            return dict(state)
        if isinstance(state, (tuple, set, frozenset)):
            return list(state)
        raise JevConfigurationError(
            f"state must be text, a JSON object/array or a Pydantic model, got {type(state).__name__}"
        )

    def _format_history(self, history: Sequence[HistoryMessage]) -> List[Dict[str, Any]]:
        """Render history as plain ``{"role", "content"}`` entries for the state document."""
        return [{"role": message.role, "content": message.content} for message in history]

    def _build_state(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[HistoryMessage]] = None,
    ) -> JSONContent:
        """Compose the state document for a chat-style call.

        A bare prompt is sent as text. When a system prompt or history is
        present the state becomes a JSON object with named fields
        (``context`` / ``conversation`` / ``input``) so the questions can
        reference them.

        Args:
            prompt: The current user input.
            system_prompt: Optional background instructions.
            history: Already-rendered conversation history.

        Returns:
            The state to send.
        """
        if not system_prompt and not history:
            return prompt
        state: Dict[str, Any] = {}
        if system_prompt:
            state["context"] = system_prompt
        if history:
            state["conversation"] = self._format_history(history)
        state["input"] = prompt
        return state

    @staticmethod
    def _output_type_of(structured_output: Union[type, StructuredOutputConfig, None]) -> Optional[Type[BaseModel]]:
        """Extract the target type from a ``structured_output`` argument."""
        if structured_output is None:
            return None
        if isinstance(structured_output, StructuredOutputConfig):
            return structured_output.output_type
        return structured_output

    def _resolve_questions(
        self,
        questions: Optional[QuestionsInput],
        output_type: Optional[Type[BaseModel]],
    ) -> Dict[str, QuestionInput]:
        """Pick the question map: explicit > derived from ``output_type`` > constructor default.

        Raises:
            JevConfigurationError: When no source yields any question.
        """
        if questions:
            return dict(questions)
        if output_type is not None:
            return dict(questions_from_type(output_type))
        if self.default_questions:
            return dict(self.default_questions)
        raise JevConfigurationError(
            "Jev answers typed questions only: pass questions=..., a Pydantic structured_output/output_type, "
            "or configure JevClient(questions=...)"
        )

    @staticmethod
    def _usage_from(response: SystemOneResponse) -> CompletionUsage:
        """Map API token accounting onto :class:`CompletionUsage`."""
        prompt_tokens = response.usage.input_tokens or 0
        completion_tokens = response.usage.output_tokens or 0
        return CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    async def system_one(
        self,
        state: Any,
        questions: QuestionsInput,
        *,
        model: Union[str, JevModel, None] = None,
        extra_body: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> SystemOneResponse:
        """Ask Jev a set of typed questions about ``state`` (``POST /v1/systemone``).

        Jev accepts text only: a string, a JSON object, or an array of text
        values (pre-process images, audio or binaries into text first). The
        documented budget is 64k tokens for ``state`` plus all questions, and
        32k for ``state`` plus the single longest question.

        Args:
            state: Text, a JSON object/array, or a Pydantic model describing
                the situation the questions are about.
            questions: Questions keyed by the id their answers are returned under.
            model: Model route; defaults to the configured model.
            extra_body: Extra top-level fields merged into the request body.
            timeout: Per-call timeout override, in seconds.

        Returns:
            The parsed :class:`SystemOneResponse`.

        Raises:
            JevConfigurationError: Empty/invalid questions, bad state, no API key.
            JevAPIError: Non-2xx response (see subclasses).
            JevConnectionError: No HTTP response could be obtained.
            JevError: The 2xx body did not match the response schema.
        """
        body: Dict[str, Any] = {
            "state": self._coerce_state(state),
            "model": self._resolve_model(model),
            "questions": normalize_questions(questions),
        }
        if extra_body:
            body.update(extra_body)
        data, request_id = await self._request("POST", SYSTEM_ONE_PATH, body, timeout=timeout)
        if not isinstance(data, dict):
            raise JevError(f"Unexpected System One response body: {data!r}")
        try:
            response = SystemOneResponse.model_validate(data)
        except ValidationError as exc:
            raise JevError(f"Invalid System One response: {exc}") from exc
        response.request_id = request_id
        return response

    async def list_models(self, *, timeout: Optional[float] = None) -> List[ModelMetadata]:
        """List the models available to the account (``GET /v1/models``).

        The API currently lists the aliases (``jev-latest``, ``jev-preview``);
        versioned IDs such as ``jev-1.13.0`` are accepted by the ``model``
        field whether or not they appear here.

        Args:
            timeout: Per-call timeout override, in seconds.

        Returns:
            One :class:`ModelMetadata` per model or alias.
        """
        data, _ = await self._request("GET", MODELS_PATH, timeout=timeout)
        try:
            return ListModelsResponse.model_validate(data).models
        except ValidationError as exc:
            raise JevError(f"Invalid models response: {exc}") from exc

    async def ask(
        self,
        prompt: str,
        model: Union[str, JevModel, None] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[HistoryMessage]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        questions: Optional[QuestionsInput] = None,
        state: Any = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Evaluate typed questions against the prompt and return an ``AIMessage``.

        The prompt is the state (see :meth:`_build_state`) unless ``state=`` is
        given explicitly. ``max_tokens``, ``temperature``, ``files``, ``tools``
        and ``use_tools`` exist for interface parity only — System One has no
        sampling, no generated tokens, no attachments and no tool loop.

        Args:
            prompt: The user input; becomes the state (or ``state["input"]``).
            model: Model route override.
            max_tokens: Ignored (no generated output).
            temperature: Ignored (no sampling).
            files: Ignored, with a warning.
            system_prompt: Background instructions, sent as ``state["context"]``.
            history: Rendered conversation history, sent as ``state["conversation"]``.
            structured_output: A Pydantic model class (or
                :class:`StructuredOutputConfig`) whose fields define the
                questions; the answers are validated back into it.
            tools: Ignored, with a warning.
            use_tools: Ignored, with a warning.
            questions: Explicit question map; takes precedence over
                ``structured_output`` and the constructor default.
            state: Explicit state, replacing the prompt-derived one.
            **kwargs: Accepted for interface parity and ignored.

        Returns:
            An :class:`AIMessage` with ``output`` / ``structured_output`` set to
            the validated ``structured_output`` instance (when given) or the
            :class:`SystemOneResponse`, ``data`` set to the plain answer values,
            ``response`` set to their JSON rendering, and per-answer detail
            (probabilities, confidence) under ``metadata["answers"]``.
        """
        if files:
            self.logger.warning("JevClient ignores file attachments: System One takes text/JSON state only")
        if tools or use_tools:
            self.logger.warning("JevClient ignores tools: System One has no tool-calling loop")
        resolved_model = self._resolve_model(model)
        output_type = self._output_type_of(structured_output)
        resolved_questions = self._resolve_questions(questions, output_type)
        request_state = (
            self._coerce_state(state) if state is not None else self._build_state(prompt, system_prompt, history)
        )

        tc = self._emit_before_call(
            client_name=self.client_name,
            model=resolved_model,
            temperature=None,
            system_prompt=system_prompt,
            has_tools=False,
        )
        started = time.perf_counter()
        try:
            response = await self.system_one(request_state, resolved_questions, model=resolved_model)
        except Exception as exc:
            await self._emit_failed_call_safe(tc, self.client_name, resolved_model, started, exc)
            raise
        elapsed = time.perf_counter() - started
        usage = self._usage_from(response)
        await self._emit_after_call(
            tc,
            client_name=self.client_name,
            model=response.model,
            duration_ms=elapsed * 1000,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            finish_reason="completed",
        )
        return self._build_message(
            prompt=prompt,
            response=response,
            output_type=output_type,
            questions=resolved_questions,
            usage=usage,
            elapsed=elapsed,
            history_used=bool(history),
        )

    def _build_message(
        self,
        *,
        prompt: str,
        response: SystemOneResponse,
        output_type: Optional[Type[BaseModel]],
        questions: Mapping[str, QuestionInput],
        usage: CompletionUsage,
        elapsed: float,
        history_used: bool,
    ) -> AIMessage:
        """Wrap a :class:`SystemOneResponse` into the framework's ``AIMessage``."""
        typed = answers_to_type(response, output_type, noul_threshold=self.noul_threshold) if output_type else None
        output: Any = typed if typed is not None else response
        values = response.values()
        return AIMessage(
            input=prompt,
            output=output,
            response=json.dumps(values, ensure_ascii=False, default=_json_default),
            data=values,
            model=response.model,
            provider=self.provider_name,
            usage=usage,
            stop_reason="completed",
            finish_reason="completed",
            raw_response=response.model_dump(mode="json"),
            structured_output=output,
            is_structured=True,
            user_id=current_user_id.get(),
            session_id=current_session_id.get(),
            turn_id=str(uuid.uuid4()),
            response_time=elapsed,
            used_conversation_history=history_used,
            metadata={
                "request_id": response.request_id,
                "answers": {name: answer.model_dump(mode="json") for name, answer in response.answers.items()},
                "questions": normalize_questions(questions),
            },
        )

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, JevModel, None] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[HistoryMessage]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Pseudo-stream: one text chunk (the JSON answer values) then the final ``AIMessage``.

        System One answers in a single pass, so there is nothing to stream
        incrementally; this keeps streaming consumers working unchanged.

        Args:
            prompt: See :meth:`ask`.
            model: See :meth:`ask`.
            max_tokens: Ignored.
            temperature: Ignored.
            files: Ignored, with a warning.
            system_prompt: See :meth:`ask`.
            history: See :meth:`ask`.
            tools: Ignored, with a warning.
            deep_research: Ignored.
            agent_config: Ignored.
            lazy_loading: Ignored.
            **kwargs: ``questions=``, ``state=`` and ``structured_output=`` are
                forwarded to :meth:`ask`.

        Yields:
            The JSON-rendered answer values, then the ``AIMessage``.
        """
        message = await self.ask(
            prompt,
            model=model,
            files=files,
            system_prompt=system_prompt,
            history=history,
            tools=tools,
            **kwargs,
        )
        yield message.response or ""
        yield message

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
        questions: Optional[QuestionsInput] = None,
        state: Any = None,
    ) -> InvokeResult:
        """Stateless typed evaluation of ``prompt``.

        With ``output_type`` (a Pydantic model) the questions are derived from
        its fields and the answers validated back into an instance — the
        provider-native structured output of System One. Without one,
        ``questions=`` (or the constructor default) is used and ``output`` is
        the :class:`SystemOneResponse`.

        Args:
            prompt: The state text (or ``state["input"]`` when ``system_prompt`` is set).
            output_type: Pydantic model to derive questions from and parse into.
            structured_output: Explicit config; its ``output_type`` wins.
            model: Model route override.
            system_prompt: Background instructions sent as ``state["context"]``.
                Unlike text LLM clients no default system prompt is injected.
            max_tokens: Ignored (no generated output).
            temperature: Ignored (no sampling).
            use_tools: Ignored.
            tools: Ignored.
            questions: Explicit question map (overrides ``output_type`` derivation).
            state: Explicit state, replacing the prompt-derived one.

        Returns:
            An :class:`InvokeResult`; ``raw_response`` carries the full API
            response (answers with probabilities and confidence).

        Raises:
            InvokeError: Wrapping any failure (configuration, schema, API, transport).
        """
        config_ = self._build_invoke_structured_config(output_type, structured_output)
        resolved_type = config_.output_type if config_ else None
        resolved_model = self._resolve_model(model)
        try:
            resolved_questions = self._resolve_questions(questions, resolved_type)
            request_state = self._coerce_state(state) if state is not None else self._build_state(prompt, system_prompt)
            response = await self.system_one(request_state, resolved_questions, model=resolved_model)
            output: Any = (
                answers_to_type(response, resolved_type, noul_threshold=self.noul_threshold)
                if resolved_type is not None
                else response
            )
        except Exception as exc:
            raise self._handle_invoke_error(exc) from exc
        return self._build_invoke_result(
            output,
            resolved_type,
            response.model,
            self._usage_from(response),
            raw_response=response.model_dump(mode="json"),
        )

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse:
        """Not supported: System One has no tool-calling loop to resume.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "JevClient.resume() is not supported: System One answers typed questions in a single pass "
            "and never suspends on a tool call"
        )

    async def batch_ask(self, requests: List[Dict[str, Any]]) -> List[AIMessage]:
        """Run several :meth:`ask` calls concurrently.

        Args:
            requests: Keyword-argument dicts, one per :meth:`ask` call.

        Returns:
            The ``AIMessage`` for each request, in order.
        """
        return list(await asyncio.gather(*(self.ask(**request) for request in requests)))
