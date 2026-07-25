"""Evaluation context: the subject (user/employee) side of a rule evaluation.

Port of nav-rewards ``EvalContext`` decoupled from aiohttp and navigator_auth:
``request`` is opaque, and session-object extraction is parameterizable.
Unifies the three duplicated context builders behind ``from_user()``.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator, MutableMapping
from datetime import date, datetime, time
from typing import Any, Optional, TYPE_CHECKING

from .registry import FunctionRegistry, default_registry

if TYPE_CHECKING:
    from .environment import Environment

# Store keys that never make it into the flattened scalar view.
_NON_SCALAR_KEYS = frozenset(
    {"request", "connection", "user", "session", "userinfo", "user_keys", "logger"}
)


def _as_scalar(value: Any) -> Any:
    """Normalize a value for the flat view; return MISSING-safe scalars.

    datetimes/dates/times become ISO-8601 strings (the same normalization the
    Rust backend expects). Lists of scalars pass through; anything else is
    returned as None to signal "not flattenable".
    """
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        items = [_as_scalar(v) for v in value]
        return [i for i in items if i is not None]
    return None


def _extract_fields(obj: Any) -> dict[str, Any]:
    """Best-effort dict view of a user object (dict, datamodel, pydantic)."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                return dict(method())
            except Exception:  # pragma: no cover - defensive
                continue
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {}


class EvalContext(dict, MutableMapping):
    """Evaluation context built from a subject (user) and session data.

    Behaves as a mapping whose missing keys resolve to ``False`` (so rules can
    probe optional attributes safely), with attribute-style access into the
    underlying store.
    """

    def __init__(
        self,
        request: Any = None,
        user: Any = None,
        session: Any = None,
        connection: Any = None,
        *args: Any,
        session_object_key: Optional[str] = None,
        **kwargs: Any,
    ):
        self.store = {
            "userinfo": {},
            "request": request,
            "connection": connection,
            "user": user if user is not None else {},
            "session": session if session is not None else {},
        }
        if session:
            self.store["programs"] = session.get("programs", [])
        self._columns = list(self.store.keys())
        self.update(*args, **kwargs)
        if user is not None:
            user_fields = _extract_fields(user)
            self.store["user_keys"] = list(user_fields.keys())
        if session_object_key and session_object_key in self.store["session"]:
            self.store["userinfo"] = self.store["session"][session_object_key]
        self._computed_cache: dict[str, Any] = {}
        self.logger = logging.getLogger("navrules.EvalContext")

    # ------------------------------------------------------------------
    # Construction helpers (unifies the 3 duplicated builders in rewards)
    # ------------------------------------------------------------------
    @classmethod
    def from_user(
        cls,
        user: Any,
        session: Optional[dict] = None,
        **extra: Any,
    ) -> "EvalContext":
        """Build a context from a user object with a synthetic session.

        Args:
            user: The subject being evaluated (dict or model object).
            session: Optional explicit session dict; when omitted a minimal
                one is synthesized from the user's fields.
            **extra: Additional context attributes (e.g. worked_hours=9.5).
        """
        if session is None:
            fields = _extract_fields(user)
            email = fields.get("email")
            session = {
                "username": email,
                "id": email,
                "email": email,
                **{
                    k: v
                    for k, v in fields.items()
                    if _as_scalar(v) is not None
                },
            }
        return cls(request=None, user=user, session=session, **extra)

    def __missing__(self, key: str) -> bool:
        return False

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Write entries into the store (not the underlying dict)."""
        for mapping in args:
            for key, value in dict(mapping).items():
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def items(self):
        return self.store.items()

    def keys(self) -> list:
        return self._columns

    def set(self, key: str, value: Any) -> None:
        self.store[key] = value
        if key not in self._columns:
            self._columns.append(key)

    # --- magic methods (behavior preserved from rewards) ---
    def __len__(self) -> int:
        return len(self.store)

    def __str__(self) -> str:
        return f"<{type(self).__name__}({self.store})>"

    def __repr__(self) -> str:
        return f"<{type(self).__name__}({self.store})>"

    def __contains__(self, key: str) -> bool:
        return key in self._columns

    def __iter__(self) -> Iterator:
        yield from self.store

    def __delitem__(self, key: str) -> None:
        del self.store[key]
        if key in self._columns:
            self._columns.remove(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.store[key] = value
        if key not in self._columns:
            self._columns.append(key)

    def __getitem__(self, key: str) -> Any:
        try:
            return self.store[key]
        except KeyError:
            return self.__missing__(key)

    def __getattr__(self, key: str) -> Any:
        try:
            return super().__getattribute__("store")[key]
        except KeyError as ex:
            raise AttributeError(key) from ex

    def __setattr__(self, key: str, value: Any) -> None:
        if key == "store":
            super().__setattr__(key, value)
        else:
            self.store[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self.store[key]
        except KeyError as ex:
            raise AttributeError(key) from ex

    # ------------------------------------------------------------------
    # Computed values (ex "achievements")
    # ------------------------------------------------------------------
    async def get_computed(
        self,
        function_path: str,
        env: "Environment",
        registry: Optional[FunctionRegistry] = None,
        **kwargs: Any,
    ) -> Any:
        """Calculate and cache a computed value via the function registry.

        The function receives ``(user, env, conn, **kwargs)`` where ``conn``
        is acquired from ``env.connection`` when available.
        """
        cache_key = f"{function_path}_{hash(str(sorted(kwargs.items())))}"
        if cache_key in self._computed_cache:
            return self._computed_cache[cache_key]

        registry = registry or default_registry
        func = registry.get_function(function_path)
        if not func:
            self.logger.warning("Computed function %r not found", function_path)
            return None
        try:
            if env.connection:
                async with await env.connection.acquire() as conn:
                    value = await func(self.user, env, conn, **kwargs)
            else:
                value = await func(self.user, env, None, **kwargs)
            self._computed_cache[cache_key] = value
            return value
        except Exception as err:
            self.logger.error(
                "Error calculating computed value %r: %s", function_path, err
            )
            return None

    def clear_computed_cache(self) -> None:
        """Clear the computed-value cache."""
        self._computed_cache.clear()

    # ------------------------------------------------------------------
    # Flat scalar view (feeds the condition matcher / Rust backend)
    # ------------------------------------------------------------------
    def flatten(self, env: Optional["Environment"] = None) -> dict[str, Any]:
        """Produce the flat scalar dict used for declarative matching.

        Keys are emitted with explicit prefixes (``ctx.<key>``/``env.<key>``)
        plus bare aliases where ctx wins over env — mirroring the resolution
        order of the condition DSL. Precedence inside ctx: session scalars <
        user fields < direct store entries.
        """
        flat: dict[str, Any] = {}

        session = self.store.get("session") or {}
        if isinstance(session, dict):
            for key, value in session.items():
                scalar = _as_scalar(value)
                if scalar is not None:
                    flat[key] = scalar
        for key, value in _extract_fields(self.store.get("user")).items():
            scalar = _as_scalar(value)
            if scalar is not None:
                flat[key] = scalar
        for key, value in self.store.items():
            if key in _NON_SCALAR_KEYS or key == "programs" or key.startswith("_"):
                continue
            scalar = _as_scalar(value)
            if scalar is not None:
                flat[key] = scalar
        programs = _as_scalar(self.store.get("programs"))
        if programs is not None:
            flat["programs"] = programs

        result = {f"ctx.{key}": value for key, value in flat.items()}
        result.update(flat)  # bare aliases (ctx priority)
        if env is not None:
            for key, value in env.to_dict().items():
                scalar = _as_scalar(value)
                if scalar is None:
                    continue
                result[f"env.{key}"] = scalar
                result.setdefault(key, scalar)  # ctx wins on bare collision
        return result
