"""``A2UIRuntime`` — the A2UI Agent Functions dispatch core (spec §3 Module 2).

Pure protocol: takes a deserialized renderer->agent envelope plus an
:class:`~parrot.outputs.a2ui.runtime.models.A2UICallContext` and returns a
:class:`~parrot.outputs.a2ui.runtime.models.DispatchResult` of already-
serialized agent->renderer envelopes. It knows nothing about HTTP, A2A,
bots, or tools — everything it needs arrives through the three injected
``Protocol``s declared in :mod:`parrot.outputs.a2ui.runtime` (G8 one-way
import rule: no module-level ``parrot.bots``/``parrot.clients``/
``parrot.tools``/``parrot.memory`` import; :data:`typing.TYPE_CHECKING`
only).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    CatalogValidationError,
    resolve_catalog,
)
from parrot.outputs.a2ui.models import (
    A2UIRendererMessage,
    ActionMessage,
    AgentFunctionResponse,
    CallAgentFunction,
    CallRendererFunction,
    ErrorMessage,
    FunctionCall,
    FunctionCallError,
)
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    A2UIErrorCode,
    DispatchResult,
    FunctionCallRecord,
    SurfaceState,
    error_envelope,
)
from parrot.outputs.a2ui.serialization import deserialize, serialize

if TYPE_CHECKING:  # pragma: no cover - import-rule guard (G8)
    from parrot.outputs.a2ui.catalog.base import FunctionDefinition
    from parrot.outputs.a2ui.runtime import (
        FunctionExecutor,
        PendingCallRegistry,
        SurfaceStateStore,
    )
    from parrot.tools.abstract import ToolResult

__all__ = ["A2UIRuntime"]

#: Maximum serialized size (bytes) of an ``action.dataModel`` payload before
#: it is rejected (spec §7 + AC-OQ5). Env-overridable.
A2UI_MAX_DATA_MODEL_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Round-trip ``value`` through JSON so it is guaranteed wire-safe.

    ``ToolResult.result`` is typed ``Any`` and may carry non-JSON-native
    values (e.g. ``datetime``); ``default=str`` stringifies anything
    :func:`json.dumps` cannot otherwise encode rather than raising.
    """
    return json.loads(json.dumps(value, default=str))


class A2UIRuntime:
    """Dispatches A2UI v1.0 renderer->agent envelopes (spec §2, §3 Module 2).

    Args:
        executor: Adapter over the agent's tool registry (TASK-2570's
            ``ToolManagerExecutor`` in production; a fake in tests).
        surfaces: Adapter storing the last ``dataModel`` per surface.
        pending: Adapter tracking agent->renderer calls awaiting correlation.
        catalog_id: The default catalog id used when no surface-specific one
            is known (e.g. for ``call_renderer()``'s own outbound calls).
    """

    def __init__(
        self,
        *,
        executor: FunctionExecutor,
        surfaces: SurfaceStateStore,
        pending: PendingCallRegistry,
        catalog_id: str = DEFAULT_CATALOG_ID,
    ) -> None:
        self._executor = executor
        self._surfaces = surfaces
        self._pending = pending
        self._catalog_id = catalog_id
        self.logger = logging.getLogger(__name__)

    async def dispatch(
        self,
        envelope: dict[str, Any] | A2UIRendererMessage,
        ctx: A2UICallContext,
    ) -> DispatchResult:
        """Dispatch a single renderer->agent envelope.

        Args:
            envelope: A raw JSON dict (goes through
                :func:`~parrot.outputs.a2ui.serialization.deserialize`) or an
                already-validated :class:`A2UIRendererMessage`.
            ctx: The call context built by the transport.

        Returns:
            A :class:`DispatchResult` carrying the already-serialized
            agent->renderer envelope(s) to return, and any structured turn/
            surface-state side effect.
        """
        message = self._normalize(envelope)
        if message is None:
            function_call_id, surface_id = self._fallback_identifiers(envelope)
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL,
                        "Malformed or unrecognized A2UI renderer-to-agent envelope.",
                        function_call_id=function_call_id,
                        surface_id=surface_id,
                    )
                ]
            )

        # Lazy expiry sweep — spec §7: TTL 900s, cleaned opportunistically on
        # each dispatch, no background reaper. ``resolve()`` itself is
        # responsible for treating an expired record as unknown; a
        # dedicated sweep hook is intentionally NOT part of the injected
        # Protocols (kept minimal — TASK-2570's adapter owns the TTL check).

        if message.call_agent_function is not None:
            return await self._dispatch_call_agent_function(message.call_agent_function, ctx)
        if message.action is not None:
            return await self._dispatch_action(message.action, ctx)
        if message.renderer_function_response is not None:
            return await self._dispatch_renderer_function_response(
                message.renderer_function_response.function_call_id,
                message.renderer_function_response.value,
                message.renderer_function_response.error,
                ctx,
            )
        if message.error is not None:
            return await self._dispatch_renderer_error(message.error, ctx)

        # Unreachable: A2UIRendererMessage._exactly_one_key guarantees one of
        # the four branches above matched.
        return DispatchResult(  # pragma: no cover
            messages=[
                error_envelope(A2UIErrorCode.INTERNAL, "Unrecognized renderer message.", function_call_id="unknown")
            ]
        )

    async def call_renderer(
        self,
        session_id: str,
        surface_id: str,
        call: str,
        args: dict[str, Any],
        *,
        catalog_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Register a pending agent->renderer call and build its envelope.

        Args:
            session_id: The session this call belongs to.
            surface_id: The surface this call targets.
            call: The renderer function name to invoke.
            args: Arguments for the renderer function.
            catalog_id: The catalog the function belongs to. Defaults to
                this runtime's own ``catalog_id`` — the official schema
                requires ``callFunction.catalogId`` on ``callRendererFunction``
                even though the shared :class:`FunctionCall` model does not.

        Returns:
            A tuple of ``(function_call_id, serialized_envelope)``.
        """
        resolved_catalog_id = catalog_id or self._catalog_id
        function_call_id = secrets.token_urlsafe(16)

        record = FunctionCallRecord(
            function_call_id=function_call_id,
            surface_id=surface_id,
            call=call,
            catalog_id=resolved_catalog_id,
            args=args,
            created_at=datetime.now(UTC),
        )
        # Register BEFORE returning — a fast renderer response must not race
        # the registration (spec §7).
        await self._pending.add(session_id, record)

        message = CallRendererFunction(
            functionCallId=function_call_id,
            callFunction=FunctionCall(call=call, args=args, catalogId=resolved_catalog_id),
        )
        return function_call_id, serialize(message)

    # -- envelope normalization / guards ---------------------------------

    def _normalize(self, envelope: dict[str, Any] | A2UIRendererMessage) -> A2UIRendererMessage | None:
        """Validate the envelope guard: one message key, ``version: "v1.0"``.

        Returns:
            The validated :class:`A2UIRendererMessage`, or ``None`` if the
            envelope is malformed, carries an agent->renderer key, or is
            otherwise not a valid renderer->agent envelope.
        """
        if isinstance(envelope, A2UIRendererMessage):
            return envelope
        try:
            message = deserialize(envelope)
        except (ValueError, TypeError) as exc:
            self.logger.info("Rejected malformed A2UI envelope: %s", exc)
            return None
        if not isinstance(message, A2UIRendererMessage):
            self.logger.info("Rejected non-renderer-to-agent A2UI envelope: %r", message)
            return None
        return message

    @staticmethod
    def _fallback_identifiers(envelope: Any) -> tuple[str | None, str | None]:
        """Best-effort ``(function_call_id, surface_id)`` from a raw envelope.

        Used only to build a schema-valid Generic Error when the envelope
        itself failed to validate (so we cannot rely on a parsed message).
        Exactly one of the two is returned (never both — the wire schema
        forbids it), preferring a ``functionCallId`` when both are present.
        A completely unidentifiable envelope (e.g. zero message keys) falls
        back to a fixed placeholder id, since the "Generic Error" wire shape
        has no representation for "no identifier available at all".
        """
        function_call_id: str | None = None
        surface_id: str | None = None
        if isinstance(envelope, dict):
            for key, value in envelope.items():
                if key == "version" or not isinstance(value, dict):
                    continue
                function_call_id = function_call_id or value.get("functionCallId")
            if function_call_id is None:
                for key, value in envelope.items():
                    if key == "version" or not isinstance(value, dict):
                        continue
                    surface_id = surface_id or value.get("surfaceId")
        if function_call_id is None and surface_id is None:
            function_call_id = "unknown"
        return function_call_id, surface_id

    # -- callAgentFunction -------------------------------------------------

    async def _dispatch_call_agent_function(self, call: CallAgentFunction, ctx: A2UICallContext) -> DispatchResult:
        fn = call.call_function

        surface_catalog_id: str | None = None
        existing_surface = await self._surfaces.get(ctx.session_id, call.surface_id)
        if existing_surface is not None:
            surface_catalog_id = existing_surface.catalog_id

        try:
            catalog_id = resolve_catalog(fn.catalog_id, surface_catalog_id)
        except CatalogValidationError:
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL,
                        "Cannot resolve which catalog this function call belongs to.",
                        function_call_id=call.function_call_id,
                    )
                ]
            )

        definition: FunctionDefinition | None = next(
            (d for d in self._executor.list_functions() if d.name == fn.call and d.catalog_id == catalog_id),
            None,
        )
        if definition is None:
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL,
                        f"Function {fn.call!r} is not registered in catalog {catalog_id!r}.",
                        function_call_id=call.function_call_id,
                    )
                ]
            )
        if definition.allowed_callers not in ("rendererOrAgent",):
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL,
                        f"Function {fn.call!r} may not be invoked by the renderer.",
                        function_call_id=call.function_call_id,
                    )
                ]
            )

        try:
            result = await self._executor.call(fn.call, fn.args, ctx)
        except Exception:
            self.logger.exception("A2UI callAgentFunction %r raised", fn.call)
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INTERNAL,
                        "The function raised an unexpected error.",
                        function_call_id=call.function_call_id,
                    )
                ]
            )

        return self._map_tool_result(result, call.function_call_id)

    def _map_tool_result(self, result: ToolResult, function_call_id: str) -> DispatchResult:
        """Map a ``ToolResult`` (duck-typed — G8 forbids importing it) to A->R envelopes."""
        status = getattr(result, "status", None)
        if status == "forbidden":
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.FORBIDDEN, "This function call was denied.", function_call_id=function_call_id
                    )
                ]
            )
        if status == "not_found":
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL,
                        f"Unknown function referenced by call {function_call_id!r}.",
                        function_call_id=function_call_id,
                    )
                ]
            )
        if not getattr(result, "success", False):
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.INTERNAL,
                        "The function did not complete successfully.",
                        function_call_id=function_call_id,
                    )
                ]
            )

        value = _json_safe(getattr(result, "result", None))
        response = AgentFunctionResponse(functionCallId=function_call_id, value=value)
        messages = [serialize(response)]

        envelope = getattr(getattr(result, "result", None), "a2ui_envelope", None)
        if isinstance(envelope, dict):
            messages.append(envelope)

        return DispatchResult(messages=messages)

    # -- action --------------------------------------------------------

    async def _dispatch_action(self, action: ActionMessage, ctx: A2UICallContext) -> DispatchResult:
        surface_state: SurfaceState | None = None

        if action.data_model is not None:
            size = len(json.dumps(action.data_model).encode("utf-8"))
            if size > A2UI_MAX_DATA_MODEL_BYTES:
                return DispatchResult(
                    messages=[
                        error_envelope(
                            A2UIErrorCode.INTERNAL,
                            "The submitted data model exceeds the maximum allowed size.",
                            surface_id=action.surface_id,
                        )
                    ]
                )

            existing = await self._surfaces.get(ctx.session_id, action.surface_id)
            catalog_id = existing.catalog_id if existing is not None else self._catalog_id
            surface_state = SurfaceState(
                surface_id=action.surface_id,
                catalog_id=catalog_id,
                data_model=action.data_model,
                updated_at=datetime.now(UTC),
            )
            await self._surfaces.put(ctx.session_id, surface_state)

        user_turn = self._build_action_turn(action)
        return DispatchResult(messages=[], user_turn=user_turn, surface_state=surface_state)

    def _build_action_turn(self, action: ActionMessage) -> str:
        """Build the structured turn text for an ``action`` (spec §8 resolved OQ).

        ``action.userMessage`` present -> a visible user turn carrying that
        text verbatim. Absent -> a system turn using the same
        ``{"type": "a2ui_action", "action": <envelope>}`` tag already
        consumed by Teams/Telegram/``integrations/a2ui_resume.py`` (FEAT-470
        TASK-2545) — this is exactly the shape TASK-2574 will route deep-link
        resume through in place of a direct ``build_structured_message()``
        call. Neither branch ever embeds ``dataModel``/``context`` in the
        text: it travels only through ``DispatchResult.surface_state`` ->
        ``_a2ui_surface_state`` (TASK-2575).
        """
        if action.user_message is not None:
            return action.user_message

        payload = serialize(action)
        payload["action"].pop("dataModel", None)
        return json.dumps({"type": "a2ui_action", "action": payload}, sort_keys=True)

    # -- renderer responses / errors -------------------------------------

    async def _dispatch_renderer_function_response(
        self,
        function_call_id: str,
        value: Any,
        error: FunctionCallError | None,
        ctx: A2UICallContext,
    ) -> DispatchResult:
        error_dict = error.model_dump(by_alias=True, mode="json") if error is not None else None
        record = await self._pending.resolve(ctx.session_id, function_call_id, value, error_dict)
        if record is None:
            return DispatchResult(
                messages=[
                    error_envelope(
                        A2UIErrorCode.NOT_FOUND,
                        "Unknown or expired function call id.",
                        function_call_id=function_call_id,
                    )
                ]
            )
        return DispatchResult(messages=[])

    async def _dispatch_renderer_error(self, error: ErrorMessage, ctx: A2UICallContext) -> DispatchResult:
        if error.function_call_id is not None:
            error_dict = {"code": error.code, "message": error.message}
            record = await self._pending.resolve(ctx.session_id, error.function_call_id, None, error_dict)
            if record is None:
                return DispatchResult(
                    messages=[
                        error_envelope(
                            A2UIErrorCode.NOT_FOUND,
                            "Unknown or expired function call id.",
                            function_call_id=error.function_call_id,
                        )
                    ]
                )
            return DispatchResult(messages=[])

        self.logger.warning(
            "Renderer reported a surface error (surfaceId=%s, code=%s): %s",
            error.surface_id,
            error.code,
            error.message,
        )
        return DispatchResult(messages=[])
