"""Studio reference catalogs (FEAT-467 TASK-2519).

    GET /api/v1/astudio/catalog/base-classes
    GET /api/v1/astudio/catalog/llm-clients
    GET /api/v1/astudio/catalog/tools
    GET /api/v1/astudio/catalog/vector-stores

All four reuse existing sources of truth (no new registries), mirroring
``tools_catalog.py``'s pattern: module-level cache built on first
request, best-effort imports with swallowed failures, sorted stable
output. The ``tools`` catalog reuses ``tools_catalog._CATALOG_CACHE``
directly (same process-wide cache as ``GET /api/v1/tools/catalog``, not
a Studio-local duplicate) so the two endpoints return identical shapes
and never build the registry twice.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import parrot.bots as bots_module
from navigator_auth.decorators import is_authenticated, user_session
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.stores import supported_stores

import parrot.handlers.tools_catalog as tools_catalog_module
from parrot.handlers.tools_catalog import _build_catalog

from ._base import StudioBaseView
from .models import StudioError

_BASE_CLASSES_CACHE: list[dict] | None = None
_LLM_CLIENTS_CACHE: list[dict] | None = None
_VECTOR_STORES_CACHE: list[dict] | None = None


def _type_str(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "Any"
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", str(annotation))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _introspect_configurable_params(cls: type) -> dict[str, dict[str, Any]]:
    """Public, configurable constructor params for a base-class row.

    Per spec: keep params carrying a default OR a type annotation; drop
    ``self``, ``*args``/``**kwargs``, and underscore-prefixed (private)
    params.

    Args:
        cls: The bot base class to introspect.

    Returns:
        A dict of param name -> ``{default?, type?}``.
    """
    try:
        sig = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for pname, param in sig.parameters.items():
        if pname == "self" or pname.startswith("_"):
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        has_default = param.default is not inspect.Parameter.empty
        has_annotation = param.annotation is not inspect.Parameter.empty
        if not (has_default or has_annotation):
            continue
        entry: dict[str, Any] = {}
        if has_default:
            entry["default"] = _json_safe(param.default)
        if has_annotation:
            entry["type"] = _type_str(param.annotation)
        out[pname] = entry
    return out


def _build_base_classes_catalog() -> list[dict]:
    """Introspect ``parrot.bots.__all__`` into a catalog of base-class rows.

    Lazy exports (``_LAZY_ATTRS`` — ``VoiceBot``/``InfoAgent``) that fail
    to import (missing optional deps) degrade to
    ``{"available": False, "error": ...}`` rows instead of raising.

    Returns:
        Sorted (by name) list of base-class descriptor dicts.
    """
    rows: list[dict] = []
    lazy_names = set(getattr(bots_module, "_LAZY_ATTRS", {}))
    for name in sorted(bots_module.__all__):
        is_lazy = name in lazy_names
        try:
            cls = getattr(bots_module, name)
        except Exception as exc:  # pylint: disable=broad-except
            rows.append(
                {
                    "name": name,
                    "lazy": is_lazy,
                    "available": False,
                    "error": str(exc),
                }
            )
            continue
        doc = (cls.__doc__ or "").strip()
        rows.append(
            {
                "name": name,
                "module": cls.__module__,
                "docstring": doc.split("\n")[0].strip() if doc else None,
                "params": _introspect_configurable_params(cls),
                "lazy": is_lazy,
                "available": True,
            }
        )
    return rows


def _build_llm_clients_catalog() -> list[dict]:
    """Resolve ``SUPPORTED_CLIENTS`` into a catalog of LLM client rows.

    Zero-arg lazy-loader callables (values that are ``callable`` but not
    themselves a ``type``) are called to resolve the real class — guarded
    so a missing optional dependency degrades to
    ``{"available": False, "error": ...}`` instead of raising.

    Returns:
        Sorted (by provider key) list of LLM client descriptor dicts.
    """
    rows: list[dict] = []
    for provider, value in sorted(SUPPORTED_CLIENTS.items()):
        is_lazy = callable(value) and not isinstance(value, type)
        try:
            cls = value() if is_lazy else value
        except Exception as exc:  # pylint: disable=broad-except
            rows.append(
                {
                    "provider": provider,
                    "lazy": True,
                    "available": False,
                    "error": str(exc),
                }
            )
            continue
        rows.append(
            {
                "provider": provider,
                "class_name": cls.__name__,
                "lazy": is_lazy,
                "available": True,
                "default_model": getattr(cls, "_default_model", None),
            }
        )
    return rows


def _build_vector_stores_catalog() -> list[dict]:
    """Wrap ``parrot.stores.supported_stores`` into catalog rows.

    Mirrors ``VectorStoreHelper.supported_stores()`` (``handlers/stores/
    helpers.py``) — the dict maps slug -> bare class NAME (not a dotted
    path), so no import-availability probing is attempted here either
    (consistent with that existing precedent).

    Returns:
        Sorted (by slug) list of ``{slug, class_name}`` dicts.
    """
    return [{"slug": slug, "class_name": class_name} for slug, class_name in sorted(supported_stores.items())]


@is_authenticated()
@user_session()
class StudioCatalogHandler(StudioBaseView):
    """``/api/v1/astudio/catalog/{kind}`` — reference catalogs (GET-only)."""

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )

    async def get(self):
        kind = self.request.match_info.get("kind")
        if kind == "base-classes":
            return self.json_response(await self._get_base_classes())
        if kind == "llm-clients":
            return self.json_response(await self._get_llm_clients())
        if kind == "tools":
            return self.json_response(await self._get_tools())
        if kind == "vector-stores":
            return self.json_response(await self._get_vector_stores())
        return self._error(f"Unknown catalog '{kind}'.", status=404, code="not_found")

    @staticmethod
    async def _get_base_classes() -> list[dict]:
        global _BASE_CLASSES_CACHE
        if _BASE_CLASSES_CACHE is None:
            _BASE_CLASSES_CACHE = await asyncio.to_thread(_build_base_classes_catalog)
        return _BASE_CLASSES_CACHE

    @staticmethod
    async def _get_llm_clients() -> list[dict]:
        global _LLM_CLIENTS_CACHE
        if _LLM_CLIENTS_CACHE is None:
            _LLM_CLIENTS_CACHE = await asyncio.to_thread(_build_llm_clients_catalog)
        return _LLM_CLIENTS_CACHE

    @staticmethod
    async def _get_tools() -> list[dict]:
        # Reuse tools_catalog's OWN process-wide cache — same cache the
        # existing GET /api/v1/tools/catalog endpoint populates, so the
        # two never diverge and the registry is only ever built once.
        if tools_catalog_module._CATALOG_CACHE is None:
            tools_catalog_module._CATALOG_CACHE = await asyncio.to_thread(_build_catalog)
        return tools_catalog_module._CATALOG_CACHE

    @staticmethod
    async def _get_vector_stores() -> list[dict]:
        global _VECTOR_STORES_CACHE
        if _VECTOR_STORES_CACHE is None:
            _VECTOR_STORES_CACHE = _build_vector_stores_catalog()
        return _VECTOR_STORES_CACHE
