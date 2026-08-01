"""FlowStateSerializer — type registry + ormsgpack (FEAT-399, TASK-2047).

Hybrid serialization for checkpoint payloads: registered Pydantic models
round-trip with type identity via a small type registry; everything else
degrades to a tagged repr and marks the operation ``lossy`` instead of
raising. Never pickle (spec §2/§7).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import ormsgpack
from pydantic import BaseModel

from parrot.models.responses import AIMessage

_TYPE_KEY = "__type__"
_DATA_KEY = "data"
_REPR_KEY = "__repr__"
_LOSSY_TAG = "lossy"

logger = logging.getLogger(__name__)


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
    """

    def __init__(self) -> None:
        self.logger = logger
        self._registry: dict[str, type[BaseModel]] = {}
        # Pre-register known result types (spec §6 Integration Points).
        self.register(AIMessage)

    def register(self, model_cls: type[BaseModel], tag: str | None = None) -> str:
        """Register a Pydantic model class under a type tag.

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

        if isinstance(value, (datetime, uuid.UUID)):
            # ormsgpack serializes these natively; no wrapping needed.
            return value

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
            return {
                str(k): self._encode_value(v, lossy_flag) for k, v in value.items()
            }

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
