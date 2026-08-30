"""A2UI v1.0 wire message models.

This module ships the complete `A2UI v1.0 <https://a2ui.org/specification/v1.0-a2ui/>`_
message set as Pydantic v2 models. These classes ARE the wire: an
**envelope-by-key** shape (``{"version": "v1.0", "<messageKey>": {...}}``, exactly
one message key), a top-level-props ``Component`` (``child``/``children``,
``catalogId``, ``weight``, ``accessibility``, ``checks``, ``action``,
``metadata.extensions``), and the full v1.0 agent-to-renderer /
renderer-to-agent message set.

Verified against the vendored/pinned upstream schemas
(``google/A2UI@90157ec10f36cf8e192daa71c95d2684af20c756``,
``specification/v1_0/json/{common_types,agent_to_renderer,renderer_to_agent}.json``)
fetched during implementation of FEAT-470 TASK-2532. The permanent vendored
copies with a drift test land in TASK-2534
(``parrot.outputs.a2ui.catalog.basic.spec``).

Design invariants (spec FEAT-470, carried over from FEAT-273):

* **Greenfield / one-way import rule (G8)** — nothing in this module imports from
  ``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Only Pydantic v2
  and the standard library are used.
* **``version`` is injected only by ``serialization.serialize`` (G3)** — the
  envelope wrapper models (:class:`A2UIAgentMessage`, :class:`A2UIRendererMessage`)
  declare ``version: Literal["v1.0"]`` as a *validation* constraint (so
  ``deserialize``/``validate_message`` can check it), but nothing in this module
  ever *defaults* or *writes* it when building/dumping the inner per-message
  models (``CreateSurface``, ``ActionMessage``, ...) — that remains
  :mod:`parrot.outputs.a2ui.serialization`'s exclusive job.
* **Wire props are top-level** — component-specific catalog properties
  (``text``, ``url``, ...) are NOT nested under a ``properties`` key; they live
  at the top level of the ``Component`` object (``extra="allow"``). Presentation
  semantics that are NOT part of the official wire (renderer hints, optional
  bindings, parrot-only variants) belong in
  ``metadata.extensions.parrot_*`` — never as top-level component props.
* **Bindings are ``{"path": "..."}``** — the legacy ``{"$bind": "..."}`` syntax
  is a *read-only* compatibility concern, normalized by
  :mod:`parrot.outputs.a2ui.compat` (TASK-2533) before it ever reaches these
  models. ``is_valid_pointer``/``is_binding_expression``/``BINDING_KEY`` are kept
  here (unused by the new models themselves) purely so ``compat.py`` has a
  single source for JSON-Pointer shape checking.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

__all__ = [
    "BINDING_KEY",
    "A2UIAgentMessage",
    "A2UIMessageBase",
    "A2UIRendererMessage",
    "AccessibilityAttributes",
    "Action",
    "ActionMessage",
    "AgentFunctionResponse",
    "CallAgentFunction",
    "CallRendererFunction",
    "CheckRule",
    "ChildList",
    "ChildTemplate",
    "Component",
    "ComponentMetadata",
    "CreateSurface",
    "DataBinding",
    "DeleteSurface",
    "DynamicBoolean",
    "DynamicNumber",
    "DynamicString",
    "DynamicStringList",
    "ErrorMessage",
    "EventAction",
    "Extensions",
    "FunctionCall",
    "FunctionCallError",
    "RendererFunctionResponse",
    "SurfaceMetadata",
    "UpdateComponents",
    "UpdateDataModel",
    "ValidationResult",
    "is_binding_expression",
    "is_valid_pointer",
]

# ---------------------------------------------------------------------------
# Legacy binding syntax helpers (kept for parrot.outputs.a2ui.compat, TASK-2533)
# ---------------------------------------------------------------------------

#: Marker key used by the *legacy* (pre-v1.0) dialect to declare a data-model
#: binding, e.g. ``{"$bind": "/charts/blk-000/series"}``. The v1.0 wire uses
#: ``{"path": "/charts/blk-000/series"}`` instead (see :class:`DataBinding`).
#: Kept here only so :mod:`parrot.outputs.a2ui.compat` has one source of truth.
BINDING_KEY = "$bind"

#: RFC 6901 JSON Pointer *shape* (light syntax check only). A pointer is either
#: the empty string (whole document) or a sequence of ``/``-prefixed reference
#: tokens. Escaped characters ``~0``/``~1`` are permitted; raw whitespace and a
#: bare ``~`` are not.
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^/~\s]|~[01])*)*$")


def is_valid_pointer(pointer: str) -> bool:
    """Return whether ``pointer`` is a syntactically well-formed JSON Pointer.

    This is a *shape* check only (RFC 6901 grammar). It does NOT verify that the
    pointer resolves against any document — resolution is the bake pass's job.

    Args:
        pointer: The candidate JSON Pointer string.

    Returns:
        ``True`` if ``pointer`` matches the JSON Pointer grammar, else ``False``.
    """
    if not isinstance(pointer, str):
        return False
    # A non-empty pointer must start with "/"; the empty string is the whole doc.
    if pointer and not pointer.startswith("/"):
        return False
    return _JSON_POINTER_RE.match(pointer) is not None


def is_binding_expression(value: Any) -> bool:
    """Return whether ``value`` is a *legacy* data-model binding expression.

    A legacy binding is a mapping of the form ``{"$bind": "<json-pointer>"}``.
    The v1.0 wire uses :class:`DataBinding` (``{"path": "..."}"``) instead;
    this helper exists for :mod:`parrot.outputs.a2ui.compat` to detect the old
    shape during normalization.

    Args:
        value: Any candidate value.

    Returns:
        ``True`` if ``value`` is a legacy binding expression mapping, else
        ``False``.
    """
    return isinstance(value, dict) and BINDING_KEY in value


# ---------------------------------------------------------------------------
# Common types (spec §2 Data Models; verified against common_types.json)
# ---------------------------------------------------------------------------


class DataBinding(BaseModel):
    """A JSON-Pointer path to a value in the surface data model (v1.0 wire).

    Attributes:
        path: A JSON Pointer path to a value in the data model.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    path: str

    @field_validator("path")
    @classmethod
    def _check_pointer(cls, value: str) -> str:
        if not is_valid_pointer(value):
            raise ValueError(f"DataBinding.path {value!r} is not a well-formed JSON Pointer.")
        return value


class FunctionCall(BaseModel):
    """Invokes a named function (renderer-side or agent-side; see catalog).

    Attributes:
        call: The name of the function to call (or ``"@index"`` for the
            template-scope system function).
        args: Arguments passed to the function.
        catalog_id: The catalog ID for this function, overriding any
            surface-level default ``catalogId``. Some call sites (e.g.
            ``callRendererFunction``) require this to be present — that
            stricter constraint is enforced by jsonschema validation
            (TASK-2535), not by this shared model.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    call: str
    args: dict[str, Any] = Field(default_factory=dict)
    catalog_id: str | None = Field(default=None, alias="catalogId")


#: A value that can be a literal string, a data-model binding, or a function
#: call returning a string.
DynamicString = str | DataBinding | FunctionCall

#: A value that can be a literal number, a data-model binding, or a function
#: call returning a number.
DynamicNumber = float | int | DataBinding | FunctionCall

#: A value that can be a literal boolean, a data-model binding, or a function
#: call returning a boolean.
DynamicBoolean = bool | DataBinding | FunctionCall

#: A value that can be a literal list of strings, a data-model binding, or a
#: function call returning a string list.
DynamicStringList = list[str] | DataBinding | FunctionCall


class ChildTemplate(BaseModel):
    """A template for generating a dynamic list of children from a data list.

    Attributes:
        component_id: The component to use as a template.
        path: The path to the list of component property objects in the data
            model.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    component_id: str = Field(alias="componentId")
    path: str


#: Either a static list of child component ids, or a :class:`ChildTemplate`
#: generating children dynamically from a data-model list.
ChildList = list[str] | ChildTemplate


class EventAction(BaseModel):
    """The agent-side event dispatched by an :class:`Action`.

    Attributes:
        name: The name of the action to be dispatched to the agent.
        user_message: Optional human-readable message describing the action
            performed by the user.
        context: Key-value pairs for the action context (literals or dynamic
            values, resolved by the renderer before dispatch).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    user_message: DynamicString | None = Field(default=None, alias="userMessage")
    context: dict[str, Any] = Field(default_factory=dict)


class Action(BaseModel):
    """Interaction handler: either an agent-side event or a function call.

    Exactly one of ``event`` or ``function_call`` MUST be set.

    Attributes:
        event: Triggers an agent-side event.
        function_call: Executes a renderer- or agent-side function.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    event: EventAction | None = None
    function_call: FunctionCall | None = Field(default=None, alias="functionCall")

    @model_validator(mode="after")
    def _exactly_one(self) -> Action:
        if (self.event is None) == (self.function_call is None):
            raise ValueError("Action requires exactly one of 'event' or 'functionCall'.")
        return self


class CheckRule(BaseModel):
    """A single validation check rule applied to an input component.

    The ``condition`` evaluates (at render time, via ``FunctionEvaluator``,
    TASK-2537) to a :class:`ValidationResult`.

    Attributes:
        condition: Path or function call evaluating to a ``ValidationResult``.
        message: Optional fallback error message (plain string — verified
            against ``common_types.json#/$defs/CheckRule``, NOT a
            ``DynamicString`` as an earlier spec draft speculated).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    condition: FunctionCall | DataBinding
    message: str | None = None


class ValidationResult(BaseModel):
    """The result of evaluating a :class:`CheckRule` condition.

    Not part of the wire schema itself (a ``CheckRule.condition`` evaluates to
    this shape at render time) — this is the ``FunctionEvaluator`` (TASK-2537)
    contract.

    Attributes:
        valid: Whether the check passed.
        code: Optional machine-readable code for the failure.
        message: Optional human-readable message.
        severity: The severity of the result when ``valid`` is ``False``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    valid: bool
    code: str | None = None
    message: str | None = None
    severity: Literal["error", "warning", "info"] = "error"


class AccessibilityAttributes(BaseModel):
    """Attributes to enhance accessibility for assistive technologies.

    Attributes:
        label: A short accessible label.
        description: Additional accessible description.
        live: Controls screen reader announcements for dynamic updates.
        hidden: Hides the element and its children from assistive
            technologies when true.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    label: DynamicString | None = None
    description: DynamicString | None = None
    live: Literal["off", "polite", "assertive"] = "off"
    hidden: DynamicBoolean = False


#: Unicode-identifier key pattern for extension keys (UAX #31), mirroring
#: ``common_types.json#/$defs/Extensions``'s
#: ``^[\p{XID_Start}_][\p{XID_Continue}]*$`` pattern. Python's
#: ``str.isidentifier()`` is built on the same XID_Start/XID_Continue Unicode
#: properties (PEP 3131), so it is used directly instead of hand-rolling a
#: ``\p{...}``-based regex (unsupported by the stdlib ``re`` module).
_RESERVED_EXTENSION_PREFIX = "a2ui_"


class Extensions(RootModel[dict[str, Any]]):
    """Optional extension metadata (``metadata.extensions``).

    Keys MUST be Unicode identifiers (UAX #31). Keys starting with ``a2ui_``
    are reserved for official A2UI extensions — parrot's own presentation
    semantics use the ``parrot_*`` prefix instead (spec §7).
    """

    root: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_keys(self) -> Extensions:
        for key in self.root:
            if not isinstance(key, str) or not key.isidentifier():
                raise ValueError(f"Extensions key {key!r} is not a valid Unicode identifier " "(UAX #31).")
            if key.startswith(_RESERVED_EXTENSION_PREFIX):
                raise ValueError(
                    f"Extensions key {key!r} uses the reserved {_RESERVED_EXTENSION_PREFIX!r} "
                    "prefix, which is reserved for official A2UI extensions."
                )
        return self


class ComponentMetadata(BaseModel):
    """Optional component-level metadata for vendor extensions.

    Attributes:
        extensions: Vendor extension key/value pairs.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    extensions: Extensions | None = None


#: Surface-level metadata has the identical shape to component-level metadata
#: (``{"extensions": Extensions}``, ``additionalProperties: false``).
SurfaceMetadata = ComponentMetadata


class A2UIMessageBase(BaseModel):
    """Common, non-behavioral base for every A2UI v1.0 *inner* wire message.

    All ten concrete message payloads (``CreateSurface``, ..., ``ErrorMessage``)
    inherit from this so callers can do a single ``isinstance(x, A2UIMessageBase)``
    check to detect "this is an A2UI message" (e.g.
    :mod:`parrot.outputs.a2ui.emission`). The envelope wrappers
    (:class:`A2UIAgentMessage`, :class:`A2UIRendererMessage`) do NOT inherit
    from this — they are a distinct "version + exactly one message" concept.
    """

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# Component (v1.0 — top-level props, extra="allow")
# ---------------------------------------------------------------------------


class Component(BaseModel):
    """A single A2UI v1.0 UI component.

    Catalog-specific properties (e.g. ``text`` for ``Text``, ``url`` for
    ``Image``) live at the TOP LEVEL of this object (``extra="allow"``) — NOT
    nested under a ``properties`` key. This model captures the envelope
    properties shared across every catalog component
    (``common_types.json#/$defs/ComponentCommon`` plus the per-component
    ``child``/``children``/``weight``/``action`` conveniences that recur across
    most catalog components); full per-component schema validation (required
    catalog props, enums, ...) is jsonschema's job (TASK-2535).

    Attributes:
        id: The unique identifier for this component within the surface.
        component: The catalog component type name (e.g. ``"Text"``, ``"Row"``).
        catalog_id: The catalog ID for this component, overriding any
            surface-level default ``catalogId``.
        child: A reference to a single child component id.
        children: A static list of child component ids, or a
            :class:`ChildTemplate` generating them dynamically.
        weight: The relative flex weight within a ``Row``/``Column``.
        accessibility: Accessibility attributes.
        checks: Renderer-side validation checks (``Checkable`` components).
        action: The interaction handler for actionable components.
        metadata: Vendor extension metadata.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    component: str
    catalog_id: str | None = Field(default=None, alias="catalogId")
    child: str | None = None
    children: ChildList | None = None
    weight: float | None = None
    accessibility: AccessibilityAttributes | None = None
    checks: list[CheckRule] | None = None
    action: Action | None = None
    metadata: ComponentMetadata | None = None


# ---------------------------------------------------------------------------
# Agent -> Renderer messages (verified against agent_to_renderer.json)
# ---------------------------------------------------------------------------


class CreateSurface(A2UIMessageBase):
    """``createSurface`` — create a new surface and begin rendering it.

    Creating a surface implicitly instantiates the canonical reserved
    ``Surface`` container component with ``child: "root"``.

    Attributes:
        surface_id: Globally-unique (for the renderer's lifetime) surface id.
        catalog_id: The default catalog id for this surface. Components/
            function calls without an explicit ``catalogId`` use this.
        send_data_model: If true, the renderer sends the full data model back
            with every message. Defaults to ``False``.
        components: Inline components for a one-shot, SSR-friendly surface.
        data_model: The initial root data model object for the surface.
        metadata: Optional surface-level metadata.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    surface_id: str = Field(alias="surfaceId")
    catalog_id: str | None = Field(default=None, alias="catalogId")
    send_data_model: bool = Field(default=False, alias="sendDataModel")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")
    metadata: SurfaceMetadata | None = None


class UpdateComponents(A2UIMessageBase):
    """``updateComponents`` — update a surface with a new set of components.

    Can be sent multiple times. One component across all ``updateComponents``/
    inline ``createSurface`` components for a surface MUST have ``id="root"``.

    Attributes:
        surface_id: The surface to update.
        components: The new/updated components.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    surface_id: str = Field(alias="surfaceId")
    components: list[Component]


class UpdateDataModel(A2UIMessageBase):
    """``updateDataModel`` — update the data model for an existing surface.

    Attributes:
        surface_id: The surface whose data model is being updated.
        path: An optional path within the data model. Omitted (or ``"/"``)
            refers to the entire data model.
        value: The data to write at ``path``. REQUIRED (may be ``None``, which
            deletes the key/value at ``path``) — a missing ``value`` is a
            validation error, distinct from an explicit ``null``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    surface_id: str = Field(alias="surfaceId")
    path: str | None = None
    value: Any


class DeleteSurface(A2UIMessageBase):
    """``deleteSurface`` — delete an existing surface.

    Attributes:
        surface_id: The surface to delete.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    surface_id: str = Field(alias="surfaceId")


class CallRendererFunction(A2UIMessageBase):
    """``callRendererFunction`` — the agent asks the renderer to run a function.

    Attributes:
        function_call_id: Unique id for this call; the renderer MUST copy it
            into the matching ``rendererFunctionResponse``.
        call_function: The function to invoke. Note: for THIS message,
            ``callFunction.catalogId`` is REQUIRED by the official schema
            (stricter than the shared :class:`FunctionCall` model) — that
            stricter constraint is enforced by jsonschema validation
            (TASK-2535), not by Pydantic here.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    function_call_id: str = Field(alias="functionCallId")
    call_function: FunctionCall = Field(alias="callFunction")


class FunctionCallError(A2UIMessageBase):
    """An error object indicating failure of a function call.

    Attributes:
        code: Machine-readable error code.
        message: Human-readable error message.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    code: str
    message: str


class _FunctionResponseBase(A2UIMessageBase):
    """Shared shape for ``agentFunctionResponse``/``rendererFunctionResponse``.

    Exactly one of ``value``/``error`` MUST be present.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    function_call_id: str = Field(alias="functionCallId")
    value: Any = None
    error: FunctionCallError | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> _FunctionResponseBase:
        has_value = "value" in self.model_fields_set
        has_error = self.error is not None
        if has_value == has_error:
            raise ValueError(f"{type(self).__name__} requires exactly one of 'value' or 'error'.")
        return self


class AgentFunctionResponse(_FunctionResponseBase):
    """``agentFunctionResponse`` — the agent's response to a
    ``callAgentFunction``."""


# ---------------------------------------------------------------------------
# Renderer -> Agent messages (verified against renderer_to_agent.json)
# ---------------------------------------------------------------------------


class ActionMessage(A2UIMessageBase):
    """``action`` — a user-initiated action reported by the renderer.

    Attributes:
        name: The action name, from the component's ``action.event.name``.
        user_message: Optional human-readable description of the action,
            after resolving bindings.
        surface_id: The surface where the event originated.
        source_component_id: The component that triggered the event.
        timestamp: ISO 8601 timestamp of when the event occurred.
        context: Key-value pairs from ``action.event.context``, resolved.
        metadata: Optional client-side metadata sent back with the action.
        data_model: The surface's full data model, attached by the renderer
            when the owning surface was created with ``sendDataModel: true``.
            ``None`` means the renderer did not attach one (distinct from an
            explicitly empty ``{}``, which means the surface's data model is
            empty). Unlike :attr:`CreateSurface.data_model`, this defaults to
            ``None`` rather than ``{}`` because a surface always starts with
            *some* data model, whereas an ``action`` may or may not carry one
            at all.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    user_message: str | None = Field(default=None, alias="userMessage")
    surface_id: str = Field(alias="surfaceId")
    source_component_id: str = Field(alias="sourceComponentId")
    timestamp: str
    context: dict[str, Any]
    metadata: ComponentMetadata | None = None
    data_model: dict[str, Any] | None = Field(default=None, alias="dataModel")


class CallAgentFunction(A2UIMessageBase):
    """``callAgentFunction`` — the renderer asks the agent to run a function.

    Attributes:
        surface_id: The surface where the call originated.
        function_call_id: Unique id for this call; the agent MUST copy it
            into the matching ``agentFunctionResponse``.
        call_function: The function to invoke.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    surface_id: str = Field(alias="surfaceId")
    function_call_id: str = Field(alias="functionCallId")
    call_function: FunctionCall = Field(alias="callFunction")


class RendererFunctionResponse(_FunctionResponseBase):
    """``rendererFunctionResponse`` — the renderer's response to a
    ``callRendererFunction``."""


#: Error codes reserved for schema/catalog validation failures. An
#: :class:`ErrorMessage` using one of these codes MUST carry ``surfaceId`` and
#: ``path`` (and no ``functionCallId``); any other code is a "generic" error
#: that requires exactly one of ``surfaceId``/``functionCallId``.
_VALIDATION_ERROR_CODES = frozenset({"VALIDATION_FAILED", "UNALLOWED_PARENT", "UNALLOWED_CHILD"})


class ErrorMessage(A2UIMessageBase):
    """``error`` — a renderer-side error report.

    Covers both shapes in ``renderer_to_agent.json#/$defs/...error``:
    a "Validation Failed" error (``code`` in
    ``{VALIDATION_FAILED, UNALLOWED_PARENT, UNALLOWED_CHILD}``, requires
    ``surfaceId`` + ``path``), and a "Generic" error (any other ``code``,
    requires exactly one of ``surfaceId``/``functionCallId``).

    Attributes:
        code: The error code.
        message: A short description of the error.
        surface_id: The surface where the error occurred.
        path: JSON pointer to the field that failed validation
            (validation errors only).
        function_call_id: The function invocation this error responds to
            (generic errors only).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    code: str
    message: str
    surface_id: str | None = Field(default=None, alias="surfaceId")
    path: str | None = None
    function_call_id: str | None = Field(default=None, alias="functionCallId")

    @model_validator(mode="after")
    def _check_shape(self) -> ErrorMessage:
        if self.code in _VALIDATION_ERROR_CODES:
            if self.surface_id is None or self.path is None:
                raise ValueError(f"ErrorMessage with code {self.code!r} requires 'surfaceId' and 'path'.")
            if self.function_call_id is not None:
                raise ValueError(f"ErrorMessage with code {self.code!r} must not carry 'functionCallId'.")
        else:
            has_surface = self.surface_id is not None
            has_call = self.function_call_id is not None
            if has_surface == has_call:
                raise ValueError("Generic ErrorMessage requires exactly one of 'surfaceId' or " "'functionCallId'.")
        return self


# ---------------------------------------------------------------------------
# Envelopes (sobre por clave) — version + exactly one message key
# ---------------------------------------------------------------------------


class A2UIAgentMessage(BaseModel):
    """The agent-to-renderer wire envelope: ``version`` + exactly one message.

    ``serialize``/``deserialize`` (TASK-2533) are the only callers expected to
    construct/parse this directly; application code builds/consumes the inner
    message classes (``CreateSurface``, ...).

    Attributes:
        version: The A2UI protocol version. Always ``"v1.0"``.
        create_surface: The ``createSurface`` message, if this is one.
        update_components: The ``updateComponents`` message, if this is one.
        update_data_model: The ``updateDataModel`` message, if this is one.
        delete_surface: The ``deleteSurface`` message, if this is one.
        call_renderer_function: The ``callRendererFunction`` message, if this
            is one.
        agent_function_response: The ``agentFunctionResponse`` message, if
            this is one.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: Literal["v1.0"]
    create_surface: CreateSurface | None = Field(default=None, alias="createSurface")
    update_components: UpdateComponents | None = Field(default=None, alias="updateComponents")
    update_data_model: UpdateDataModel | None = Field(default=None, alias="updateDataModel")
    delete_surface: DeleteSurface | None = Field(default=None, alias="deleteSurface")
    call_renderer_function: CallRendererFunction | None = Field(default=None, alias="callRendererFunction")
    agent_function_response: AgentFunctionResponse | None = Field(default=None, alias="agentFunctionResponse")

    @model_validator(mode="after")
    def _exactly_one_key(self) -> A2UIAgentMessage:
        keys = (
            self.create_surface,
            self.update_components,
            self.update_data_model,
            self.delete_surface,
            self.call_renderer_function,
            self.agent_function_response,
        )
        present = sum(1 for k in keys if k is not None)
        if present != 1:
            raise ValueError("A2UIAgentMessage requires exactly one message key besides " f"'version', got {present}.")
        return self


class A2UIRendererMessage(BaseModel):
    """The renderer-to-agent wire envelope: ``version`` + exactly one message.

    Attributes:
        version: The A2UI protocol version. Always ``"v1.0"``.
        action: The ``action`` message, if this is one.
        call_agent_function: The ``callAgentFunction`` message, if this is one.
        renderer_function_response: The ``rendererFunctionResponse`` message,
            if this is one.
        error: The ``error`` message, if this is one.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: Literal["v1.0"]
    action: ActionMessage | None = None
    call_agent_function: CallAgentFunction | None = Field(default=None, alias="callAgentFunction")
    renderer_function_response: RendererFunctionResponse | None = Field(default=None, alias="rendererFunctionResponse")
    error: ErrorMessage | None = None

    @model_validator(mode="after")
    def _exactly_one_key(self) -> A2UIRendererMessage:
        keys = (
            self.action,
            self.call_agent_function,
            self.renderer_function_response,
            self.error,
        )
        present = sum(1 for k in keys if k is not None)
        if present != 1:
            raise ValueError(
                "A2UIRendererMessage requires exactly one message key besides " f"'version', got {present}."
            )
        return self


#: Convenience alias for typing an arbitrary agent-to-renderer inner message.
A2UIAgentInnerMessage = (
    CreateSurface | UpdateComponents | UpdateDataModel | DeleteSurface | CallRendererFunction | AgentFunctionResponse
)

#: Convenience alias for typing an arbitrary renderer-to-agent inner message.
A2UIRendererInnerMessage = ActionMessage | CallAgentFunction | RendererFunctionResponse | ErrorMessage
