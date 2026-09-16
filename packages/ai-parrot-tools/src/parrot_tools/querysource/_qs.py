"""Lazy, patchable access to the optional ``querysource`` dependency (spec §3 M1)."""
from __future__ import annotations

from types import ModuleType
from typing import Any

from parrot._imports import lazy_import  # verified: packages/ai-parrot/src/parrot/_imports.py:110

_PACKAGE = "querysource"
_EXTRA = "db"

# Module-level slots so tests can monkeypatch (pattern: dataset_manager/sources/query_slug.py:20).
QS: Any = None
MultiQS: Any = None
QueryModel: Any = None
ComponentRegistry: Any = None


def _load(module_path: str) -> ModuleType:
    """Import ``module_path`` lazily; ImportError carries the ``pip install querysource`` hint."""
    return lazy_import(module_path, package_name=_PACKAGE, extra=_EXTRA)


def get_qs() -> type:
    """Return ``querysource.queries.qs.QS`` (qs.py:36), caching it in the ``QS`` slot."""
    global QS
    if QS is None:
        QS = _load("querysource.queries.qs").QS
    return QS


def get_multiqs() -> type:
    """Return ``querysource.queries.multi.MultiQS`` (multi/__init__.py:56)."""
    global MultiQS
    if MultiQS is None:
        MultiQS = _load("querysource.queries.multi").MultiQS
    return MultiQS


def get_query_model() -> type:
    """Return ``querysource.models.QueryModel`` (models.py:48)."""
    global QueryModel
    if QueryModel is None:
        QueryModel = _load("querysource.models").QueryModel
    return QueryModel


def get_component_registry() -> type:
    """Return ``querysource.queries.multi.registry.ComponentRegistry`` (registry.py:72)."""
    global ComponentRegistry
    if ComponentRegistry is None:
        ComponentRegistry = _load("querysource.queries.multi.registry").ComponentRegistry
    return ComponentRegistry


def get_exceptions() -> ModuleType:
    """Return the ``querysource.exceptions`` module (SlugNotFound, DataNotFound, QueryException, DriverError)."""
    return _load("querysource.exceptions")


def default_dsn() -> str:
    """Return ``querysource.conf.asyncpg_url`` (conf.py:44) — the DSN ``get_query_slug`` uses for public.queries."""
    return _load("querysource.conf").asyncpg_url


def installed_version() -> str:
    """Return ``querysource.version.__version__`` ("4.5.11" at spec time)."""
    return _load("querysource.version").__version__
