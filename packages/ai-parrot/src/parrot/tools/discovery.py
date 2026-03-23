"""
Multi-source tool discovery for ToolManager.

Two strategies:
1. FAST (declarative): Read TOOL_REGISTRY dicts from each source — no imports needed
2. FULL (walk): pkgutil.walk_packages — imports everything, finds all AbstractTool subclasses

Default: FAST for installed packages, FULL for plugins/ only.
"""
import importlib
import inspect
import logging
import pkgutil
from typing import Callable, Dict, Optional, Type, Union

from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger("parrot.tools.discovery")

# Default sources for discovery
DEFAULT_SOURCES = [
    "parrot_tools",       # ai-parrot-tools package
    "plugins.tools",      # user plugins
]

# Sources that use walk_packages (slow but automatic)
WALK_SOURCES = {"plugins.tools"}


def discover_from_registry(
    sources: list[str] | None = None,
) -> Dict[str, str]:
    """
    Fast discovery: read TOOL_REGISTRY dicts from package __init__.py.

    Returns:
        Dict[tool_name, dotted_path_to_class]
    """
    sources = sources or DEFAULT_SOURCES
    registry: Dict[str, str] = {}

    for source in sources:
        if source in WALK_SOURCES:
            continue  # Skip walk-only sources

        try:
            package = importlib.import_module(source)
        except ImportError:
            logger.debug("Source '%s' not installed, skipping", source)
            continue

        declared = getattr(package, "TOOL_REGISTRY", None)
        if declared and isinstance(declared, dict):
            registry.update(declared)
            logger.debug(
                "Loaded %d tools from %s.TOOL_REGISTRY",
                len(declared), source,
            )

    return registry


def discover_from_walk(
    sources: list[str] | None = None,
    filter_fn: Callable[[type], bool] | None = None,
) -> Dict[str, Type[Union[AbstractTool, AbstractToolkit]]]:
    """
    Full discovery: walk packages and find all AbstractTool/AbstractToolkit subclasses.
    Used for plugins/ where maintaining a registry is impractical.

    Returns:
        Dict[tool_name, tool_class]
    """
    sources = sources or list(WALK_SOURCES)
    registry: Dict[str, Type] = {}

    for source in sources:
        try:
            package = importlib.import_module(source)
        except ImportError:
            continue

        if not hasattr(package, "__path__"):
            continue

        for _importer, module_name, _is_pkg in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{source}.",
        ):
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                logger.debug("Skipping %s: %s", module_name, e)
                continue

            for attr_name, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, (AbstractTool, AbstractToolkit))
                    and obj not in (AbstractTool, AbstractToolkit)
                    and not getattr(obj, "_abstract", False)
                ):
                    if filter_fn and not filter_fn(obj):
                        continue
                    tool_name = getattr(obj, "name", attr_name)
                    registry[tool_name] = obj

    return registry


def discover_all(
    sources: list[str] | None = None,
) -> Dict[str, Union[str, Type]]:
    """
    Combined discovery: fast registry + walk for plugins.

    Returns dict where values are either:
    - str (dotted path, from registry — lazy, not yet imported)
    - Type (class, from walk — already imported)
    """
    registry: Dict[str, Union[str, Type]] = {}

    # Phase 1: Fast declarative registries
    registry.update(discover_from_registry(sources))

    # Phase 2: Walk plugins (slower but automatic)
    walk_sources = [
        s for s in (sources or DEFAULT_SOURCES)
        if s in WALK_SOURCES
    ]
    if walk_sources:
        walked = discover_from_walk(walk_sources)
        registry.update({name: cls for name, cls in walked.items()})

    logger.info("Discovered %d tools total", len(registry))
    return registry


def resolve_class(dotted_path: str) -> Type:
    """Resolve a dotted path string to an actual class.

    Args:
        dotted_path: e.g., "parrot_tools.jira.toolkit.JiraToolkit"

    Returns:
        The class object
    """
    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)
