"""FlowStateSerializer — type registry + ormsgpack (FEAT-399, TASK-2047).

Hybrid serialization for checkpoint payloads: registered Pydantic models
round-trip with type identity via a small type registry; everything else
degrades to a tagged repr and marks the operation ``lossy`` instead of
raising. Never pickle (spec §2/§7).
"""
from __future__ import annotations

import logging
import uuid
from collections import ChainMap
from datetime import datetime
from typing import Any

import ormsgpack
from pydantic import BaseModel

from parrot.models.responses import AIMessage

_TYPE_KEY = "__type__"
_DATA_KEY = "data"
_REPR_KEY = "__repr__"
_LOSSY_TAG = "lossy"
_DATETIME_TAG = "__datetime__"
_UUID_TAG = "__uuid__"
_ESCAPED_DICT_TAG = "__escaped_dict__"

logger = logging.getLogger(__name__)

#: Types every :class:`FlowStateSerializer` round-trips, by tag.
#:
#: Process-wide by necessity, not by preference. A ``FlowStateSerializer`` is
#: constructed independently by the checkpointer *and* by each store, and a
#: store decodes with its own — so an instance-level registration could make
#: a model encode correctly and still come back degraded on the way out.
#: Populate it at import time (e.g. from a dev-loop/dev-flow models module),
#: the same way node types register themselves against ``NODE_REGISTRY``.
_DEFAULT_TYPES: dict[str, type[BaseModel]] = {}


def register_checkpoint_type(model_cls: type[BaseModel], tag: str | None = None) -> str:
    """Register a Pydantic type for every :class:`FlowStateSerializer` instance.

    Without this a model is not an error — it degrades to its ``repr`` and
    the checkpoint is flagged ``lossy``. That is a reasonable default for a
    payload nobody reads back, and a silent problem for a flow that routes on
    a node's typed result, or a resume path that needs to restore a typed
    dev-loop output (``ResearchOutput``, ``DevelopmentOutput``, ...).

    Idempotent: re-registering the exact same class under the same tag is a
    no-op. Registering a *different* class under a tag already claimed by
    another class raises, since silently rebinding the tag would make every
    already-persisted checkpoint referencing it decode as the wrong type.

    Args:
        model_cls: The Pydantic ``BaseModel`` subclass to register.
        tag: Optional explicit type tag; defaults to the fully qualified
            class name (``module.QualName``).

    Returns:
        The tag the class was registered under.

    Raises:
        ValueError: If ``tag`` is already registered to a different class.
    """
    tag = tag or f"{model_cls.__module__}.{model_cls.__qualname__}"
    existing = _DEFAULT_TYPES.get(tag)
    if existing is not None and existing is not model_cls:
        raise ValueError(
            f"register_checkpoint_type: tag {tag!r} is already registered to "
            f"{existing!r}; cannot re-register it to {model_cls!r}."
        )
    _DEFAULT_TYPES[tag] = model_cls
    return tag


class FlowStateSerializer:
    """Encode/decode checkpoint payloads with a Pydantic type registry.

    Registered model classes are encoded as ``{"__type__": tag, "data":
    model.model_dump(mode="json")}`` and reconstructed via
    ``model_cls.model_validate()`` on decode. Unregistered objects
    (including unregistered Pydantic models) degrade to
    ``{"__type__": "lossy", "__repr__": repr(obj)}`` — this never raises
    and instead signals the degradation via ``encode_with_meta()``'s
    ``lossy`` flag.

    ``Exception``/``BaseException`` instances are always encoded as a
    structured ``{"type": ..., "message": ..., "repr": ...}`` dict —
    never as reconstructable objects (spec §7: ``FlowContext.errors``
    holds live Exceptions; checkpoints must never attempt to rebuild
    them on resume).

    ``datetime``/``uuid.UUID`` are explicitly tagged (not left to
    ormsgpack's own encoding) — ``ormsgpack.unpackb()`` does not restore
    them to their original type on its own, it returns plain strings, so
    without tagging they would silently lose type fidelity (never
    flagged ``lossy``, since the round-trip technically "succeeds").

    A plain ``dict`` whose own keys happen to collide with the reserved
    ``"__type__"`` sentinel (e.g. a tool result naturally shaped like
    ``{"__type__": "lossy", ...}``) is escaped in a tagged wrapper on
    encode so ``decode()`` can tell a real envelope apart from user data
    that merely looks like one, instead of misinterpreting it.
    """

    def __init__(self) -> None:
        self.logger = logger
        # A ChainMap over the process-wide defaults rather than a copy of
        # them, so registration order stops mattering. Serializers are built
        # independently in several places (here, the checkpointer, and each
        # store) and construct lazily, at whatever moment a flow first
        # checkpoints. With a snapshot, a model registered globally after the
        # first serializer was built would round-trip on the way in and
        # degrade on the way out.
        self._registry: Any = ChainMap({}, _DEFAULT_TYPES)
        # Pre-register known result types (spec §6 Integration Points).
        self.register(AIMessage)

    def register(self, model_cls: type[BaseModel], tag: str | None = None) -> str:
        """Register a Pydantic model class under a type tag (instance-local).

        Args:
            model_cls: The Pydantic ``BaseModel`` subclass to register.
            tag: Optional explicit type tag; defaults to the fully
                qualified class name (``module.QualName``).

        Returns:
            The tag the class was registered under.
        """
        tag = tag or f"{model_cls.__module__}.{model_cls.__qualname__}"
        self._registry[tag] = model_cls
        return tag

    @property
    def registry(self) -> dict[str, type[BaseModel]]:
        """The types this serializer round-trips, process-wide defaults included."""
        return dict(self._registry)

    def _tag_for_class(self, cls: type) -> str | None:
        for tag, registered_cls in self._registry.items():
            if registered_cls is cls:
                return tag
        return None

    @staticmethod
    def encode_error(exc: BaseException) -> dict[str, str]:
        """Encode an exception as a structured, JSON-safe dict.

        Args:
            exc: The exception instance to encode.

        Returns:
            ``{"type": ClassName, "message": str(exc), "repr": repr(exc)}``.
        """
        return {
            "type": type(exc).__name__,
            "message": str(exc),
            "repr": repr(exc),
        }

    def _encode_value(self, value: Any, lossy_flag: list[bool]) -> Any:
        if value is None or isinstance(value, (str, int, float, bool, bytes)):
            return value

        if isinstance(value, datetime):
            # ormsgpack round-trips datetime as a plain string on unpackb
            # (verified: it does NOT reconstruct a datetime object) — tag
            # it explicitly so decode restores a real datetime instead of
            # silently degrading type fidelity without flagging `lossy`
            # (code review finding, FEAT-399).
            return {_TYPE_KEY: _DATETIME_TAG, _DATA_KEY: value.isoformat()}

        if isinstance(value, uuid.UUID):
            # Same rationale as datetime above.
            return {_TYPE_KEY: _UUID_TAG, _DATA_KEY: str(value)}

        if isinstance(value, BaseException):
            return self.encode_error(value)

        if isinstance(value, BaseModel):
            tag = self._tag_for_class(type(value))
            if tag is not None:
                dumped = value.model_dump(mode="json")
                return {
                    _TYPE_KEY: tag,
                    _DATA_KEY: self._encode_value(dumped, lossy_flag),
                }
            lossy_flag[0] = True
            self.logger.debug(
                "FlowStateSerializer: unregistered Pydantic model %s degraded "
                "to lossy repr",
                type(value).__name__,
            )
            return {_TYPE_KEY: _LOSSY_TAG, _REPR_KEY: repr(value)}

        if isinstance(value, dict):
            encoded = {
                str(k): self._encode_value(v, lossy_flag) for k, v in value.items()
            }
            if _TYPE_KEY in encoded:
                # Collision guard: a real dict from user/tool data happens
                # to contain our reserved sentinel key (e.g. a tool result
                # shaped like {"__type__": "lossy", ...}). Without this,
                # decode would misinterpret it as one of our own envelopes
                # and silently return the wrong value instead of the
                # original dict (code review finding, FEAT-399). Escape it
                # in a tagged wrapper so decode can tell the two apart.
                return {_TYPE_KEY: _ESCAPED_DICT_TAG, _DATA_KEY: encoded}
            return encoded

        if isinstance(value, (list, tuple)):
            return [self._encode_value(v, lossy_flag) for v in value]

        # Anything else (arbitrary custom object) degrades to a tagged repr
        # instead of raising — never fail the flow on serialization.
        lossy_flag[0] = True
        self.logger.debug(
            "FlowStateSerializer: %s degraded to lossy repr", type(value).__name__
        )
        return {_TYPE_KEY: _LOSSY_TAG, _REPR_KEY: repr(value)}

    @staticmethod
    def _default_hook(obj: Any) -> Any:
        """Last-resort ormsgpack ``default=`` hook.

        Everything is pre-processed into ormsgpack-native types by
        ``_encode_value`` before packing, so this should rarely fire; it
        exists as a safety net so ``packb`` itself never raises.
        """
        return repr(obj)

    def encode_with_meta(self, obj: Any) -> tuple[bytes, bool]:
        """Encode ``obj`` to ormsgpack bytes, reporting lossy degradation.

        Args:
            obj: Arbitrary structure (dict/list/Pydantic model/primitive).

        Returns:
            Tuple of ``(packed_bytes, lossy)`` where ``lossy`` is True if
            any value in the structure degraded to a tagged repr.
        """
        prepared, lossy = self.to_safe_with_meta(obj)
        packed = ormsgpack.packb(prepared, default=self._default_hook)
        return packed, lossy

    def to_safe_with_meta(self, obj: Any) -> tuple[Any, bool]:
        """Recursively convert ``obj`` into a JSON-safe structure.

        This is the per-value transform step used internally by
        ``encode_with_meta()`` before the final ormsgpack ``packb()`` — it
        applies the same type-registry tag-enveloping and lossy
        degradation, but stops short of byte-packing. Callers that need a
        JSON-safe (dict/list/primitive) representation of arbitrary
        per-node values — e.g. ``ContextSnapshot.results``/``.responses``,
        which are typed ``dict[str, Any]`` and are packed again as part of
        the *whole* checkpoint by the store layer — use this instead of
        ``encode_with_meta()`` to avoid double-encoding to bytes.

        Args:
            obj: Arbitrary structure (dict/list/Pydantic model/primitive).

        Returns:
            Tuple of ``(safe_structure, lossy)``.
        """
        lossy_flag = [False]
        safe = self._encode_value(obj, lossy_flag)
        return safe, lossy_flag[0]

    def from_safe(self, safe: Any) -> Any:
        """Reconstruct values produced by ``to_safe_with_meta()``.

        Args:
            safe: A JSON-safe structure previously produced by
                ``to_safe_with_meta()``.

        Returns:
            The reconstructed structure — registered models rebuilt via
            ``model_validate``, lossy envelopes replaced by their repr
            string, everything else returned as plain dict/list/primitives.
        """
        return self._decode_value(safe)

    def encode(self, obj: Any) -> bytes:
        """Encode ``obj`` to ormsgpack bytes (discarding the lossy flag).

        Args:
            obj: Arbitrary structure (dict/list/Pydantic model/primitive).

        Returns:
            The packed bytes.
        """
        data, _ = self.encode_with_meta(obj)
        return data

    def _decode_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            if _TYPE_KEY in value:
                tag = value[_TYPE_KEY]
                if tag == _LOSSY_TAG:
                    return value.get(_REPR_KEY)
                if tag == _DATETIME_TAG:
                    return datetime.fromisoformat(value[_DATA_KEY])
                if tag == _UUID_TAG:
                    return uuid.UUID(value[_DATA_KEY])
                if tag == _ESCAPED_DICT_TAG:
                    # Unwrap a collision-escaped plain dict (see the encode
                    # side's collision guard) — the inner dict is already
                    # encoded, just recurse into its values.
                    inner = value.get(_DATA_KEY, {})
                    return {k: self._decode_value(v) for k, v in inner.items()}
                model_cls = self._registry.get(tag)
                if model_cls is not None:
                    return model_cls.model_validate(
                        self._decode_value(value.get(_DATA_KEY))
                    )
                # Unknown tag: never dynamically import/reconstruct —
                # return the raw envelope so the caller can inspect it.
                return {k: self._decode_value(v) for k, v in value.items()}
            return {k: self._decode_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._decode_value(v) for v in value]
        return value

    def decode(self, data: bytes) -> Any:
        """Decode ormsgpack bytes produced by ``encode``/``encode_with_meta``.

        Args:
            data: Packed bytes.

        Returns:
            The reconstructed structure: registered models rebuilt via
            ``model_validate``, lossy envelopes replaced by their repr
            string, everything else returned as plain dict/list/primitives.
        """
        raw = ormsgpack.unpackb(data)
        return self._decode_value(raw)
