"""Single slug → class authority for toolkits and tools (FEAT-622 M1).

Merges, in order: built-in explicit entries, ``parrot_tools.TOOL_REGISTRY`` and the host's declared
``plugins.tools.TOOL_REGISTRY`` (prefixed by ``HOST_TOOL_PREFIX``). Never mutates any registry.
"""

from __future__ import annotations

import importlib
import logging
import threading
import warnings
from typing import Literal

from pydantic import BaseModel

from parrot.tools.discovery import discover_from_walk, resolve_class
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger("parrot.tools.resolver")

_HOST_PACKAGE = "plugins.tools"


class ToolkitEntry(BaseModel, frozen=True):
    """One resolvable slug."""

    slug: str
    dotted_path: str | None  # None for built-in explicit entries (and walked classes)
    source: Literal["builtin", "parrot_tools", "host", "walk"]

    @property
    def is_host(self) -> bool:
        """Host code: a declared ``plugins.tools`` entry or one found by the deprecated walk fallback."""
        return self.source in ("host", "walk")


def _builtin_classes() -> dict[str, type]:
    """Lazily import the built-in explicit toolkit classes."""
    from parrot.knowledge.wiki import LLMWikiToolkit
    from parrot.tools.dataset_manager.tool import DatasetManager
    from parrot.tools.infographic_toolkit import InfographicToolkit

    return {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}


class ToolkitResolver:
    """Process-wide, lazily built, read-only resolver (spec §2 "Resolution rules")."""

    def __init__(self) -> None:
        # Re-entrant: building imports host modules, which may instantiate tools that ask this resolver again.
        self._lock = threading.RLock()
        self._entries: dict[str, ToolkitEntry] | None = None  # key: slug.lower()
        self._building: dict[str, ToolkitEntry] | None = None  # entries gathered so far by the building thread
        self._classes: dict[str, type] = {}  # key: slug.lower(); walked / explicit classes
        self._aliases: dict[str, str] = {}  # key: class_name.lower() → entry key (non-host entries only)

    def entries(self) -> list[ToolkitEntry]:
        """Every entry, sorted by slug (catalogue and policy use this)."""
        return sorted(self._ensure().values(), key=lambda item: item.slug)

    def entry(self, slug: str) -> ToolkitEntry | None:
        """Case-insensitive lookup by slug or class-name alias; returns entries whose class cannot be imported too."""
        entries = self._ensure()
        key = slug.lower()
        found = entries.get(key)
        if found is not None:
            return found
        alias = self._aliases.get(key)
        return entries.get(alias) if alias else None

    def canonical_slug(self, name: str) -> str | None:
        """Declared slug for a slug or class-name alias (``"JiraToolkit"`` → ``"jira"``); ``None`` when unknown."""
        found = self.entry(name)
        return found.slug if found else None

    def is_host_class(self, cls: type) -> bool:
        """True iff ``cls`` is the class of a host entry (declared ``host`` or walked), never stamped on the class."""
        for entry in self.entries():
            if entry.is_host and self.resolve(entry.slug) is cls:
                return True
        return False

    def resolve(self, slug: str) -> type | None:
        """Case-insensitive slug (or class-name alias) → class; ``None`` when unknown or unimportable."""
        found = self.entry(slug)
        if found is None:
            return None
        key = found.slug.lower()
        if found.dotted_path is None:
            return self._classes.get(key)
        try:
            cls = resolve_class(found.dotted_path)
        except (ImportError, AttributeError, ValueError):
            return None
        return cls

    def registry_paths(self) -> dict[str, str]:
        """Slug → dotted path of every non-host entry (built-ins from their class) (host paths are never listed)."""
        paths: dict[str, str] = {}
        for entry in self.entries():
            if entry.is_host:
                continue
            cls = self._classes.get(entry.slug.lower())
            dotted = entry.dotted_path or (f"{cls.__module__}.{cls.__qualname__}" if cls else None)
            if dotted:
                paths[entry.slug] = dotted
        return paths

    def reload(self) -> None:
        """Drop the cache (tests / hot reload only)."""
        with self._lock:
            self._entries = None
            self._building = None
            self._classes = {}
            self._aliases = {}

    def _ensure(self) -> dict[str, ToolkitEntry]:
        if self._entries is None:
            with self._lock:
                if self._entries is None:
                    if self._building is not None:
                        # Re-entrant call from a host module being imported by _build (same thread): answer from
                        # what is known so far instead of deadlocking; execution re-checks against the full set.
                        return self._building
                    try:
                        self._entries = self._build()
                    finally:
                        self._building = None
        return self._entries

    def _build(self) -> dict[str, ToolkitEntry]:
        """Apply rules 1–4 once."""
        entries: dict[str, ToolkitEntry] = {}
        self._building = entries
        for slug, cls in _builtin_classes().items():
            entries[slug.lower()] = ToolkitEntry(slug=slug, dotted_path=None, source="builtin")
            self._classes[slug.lower()] = cls
        try:
            declared = getattr(importlib.import_module("parrot_tools"), "TOOL_REGISTRY", None)
        except ImportError:
            declared = None
        if isinstance(declared, dict):
            for slug, dotted in declared.items():
                entries.setdefault(slug.lower(), ToolkitEntry(slug=slug, dotted_path=dotted, source="parrot_tools"))
        self._add_host_entries(entries)
        self._aliases = self._build_aliases(entries)
        return entries

    def _build_aliases(self, entries: dict[str, ToolkitEntry]) -> dict[str, str]:
        """Class-name → entry-key aliases so legacy YAML naming a toolkit by class resolves to its slug.

        Only non-host entries get an alias: host slugs are namespaced by ``HOST_TOOL_PREFIX`` and a
        class-name alias would bypass that namespace. A real slug always shadows an alias, and an
        alias claimed by two different entries is dropped as ambiguous.
        """
        aliases: dict[str, str] = {}
        ambiguous: set[str] = set()
        for key, entry in entries.items():
            if entry.is_host:
                continue
            if entry.dotted_path is not None:
                class_name = entry.dotted_path.rsplit(".", 1)[-1]
            else:
                cls = self._classes.get(key)
                class_name = cls.__name__ if cls else None
            if not class_name:
                continue
            alias = class_name.lower()
            if alias in entries:
                continue
            if alias in aliases and aliases[alias] != key:
                ambiguous.add(alias)
                continue
            aliases[alias] = key
        for alias in ambiguous:
            logger.warning("Toolkit class-name alias %r claimed by several slugs; dropped as ambiguous", alias)
            aliases.pop(alias, None)
        return aliases

    def _add_host_entries(self, entries: dict[str, ToolkitEntry]) -> None:
        """Rules 2–4: declared host registry, else deprecated walk fallback, else nothing."""
        try:
            package = importlib.import_module(_HOST_PACKAGE)
        except ImportError:
            return  # rule 4
        declared = getattr(package, "TOOL_REGISTRY", None)
        if not isinstance(declared, dict):
            warnings.warn(
                "plugins.tools without TOOL_REGISTRY is deprecated; declare TOOL_REGISTRY and HOST_TOOL_PREFIX",
                DeprecationWarning,
                stacklevel=2,
            )
            for slug, cls in discover_from_walk([_HOST_PACKAGE]).items():
                if slug.lower() not in entries:
                    entries[slug.lower()] = ToolkitEntry(slug=slug, dotted_path=None, source="walk")
                    self._classes[slug.lower()] = cls
            return
        prefix = getattr(package, "HOST_TOOL_PREFIX", None)
        for slug, dotted in declared.items():
            reason = self._host_rejection(slug, dotted, prefix, entries)
            if reason:
                logger.error("Rejected host toolkit %r (%s): %s", slug, dotted, reason)
                continue
            entries[slug.lower()] = ToolkitEntry(slug=slug, dotted_path=dotted, source="host")

    @staticmethod
    def _host_rejection(slug: str, dotted: str, prefix: object, entries: dict[str, ToolkitEntry]) -> str | None:
        """Return why a declared host entry is rejected (rule 2), or ``None`` when acceptable."""
        if not isinstance(prefix, str) or not prefix:
            return "plugins.tools declares no HOST_TOOL_PREFIX string"
        if not slug.startswith(prefix):
            return f"slug lacks the host prefix {prefix!r}"
        if slug.lower() in entries:
            return "slug collides with an existing built-in/parrot_tools slug"
        try:
            cls = resolve_class(dotted)
        except (ImportError, AttributeError, ValueError) as exc:
            return f"class cannot be imported: {exc}"
        tool_prefix = getattr(cls, "tool_prefix", None)
        if issubclass(cls, AbstractToolkit) and tool_prefix != prefix.rstrip("_"):
            return f"tool_prefix {tool_prefix!r} != {prefix.rstrip('_')!r}"
        return None


_RESOLVER: ToolkitResolver | None = None
_RESOLVER_LOCK = threading.Lock()


def get_toolkit_resolver() -> ToolkitResolver:
    """Return the process-wide resolver, building it lazily on first use."""
    global _RESOLVER  # noqa: PLW0603
    if _RESOLVER is None:
        with _RESOLVER_LOCK:
            if _RESOLVER is None:
                _RESOLVER = ToolkitResolver()
    return _RESOLVER
