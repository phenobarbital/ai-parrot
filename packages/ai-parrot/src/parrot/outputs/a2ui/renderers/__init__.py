"""A2UI renderer registry and contract (Module 4, core side).

Core ships only the renderer *contract* — :class:`RendererCapabilities`,
:class:`AbstractA2UIRenderer`, and the register/resolve functions. ALL concrete
renderers live in ``ai-parrot-visualizations`` under the ``parrot.outputs.a2ui_renderers``
PEP 420 namespace, behind the ``a2ui`` / ``a2ui-pdf`` extras (spec G8).

Resolution copies the ``EmbeddingRegistry`` dispatch shape: look up the registry
first; if the name is unknown, ``importlib.import_module`` the satellite module
(which self-registers on import), then re-read the registry. A missing satellite
raises an actionable :class:`ImportError` naming the pip extra.
"""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel

from parrot.outputs.a2ui.models import CreateSurface

__all__ = [
    "AbstractA2UIRenderer",
    "RendererCapabilities",
    "get_a2ui_renderer",
    "register_a2ui_renderer",
]

logger = logging.getLogger(__name__)

#: PEP 420 namespace where satellite renderer modules live.
_RENDERER_NAMESPACE = "parrot.outputs.a2ui_renderers"

#: Pip extra that ships the renderers.
_A2UI_EXTRA = "ai-parrot-visualizations[a2ui]"

def _extra_for(name: str) -> str:
    """Return the pip extra that ships the renderer ``name``.

    Any renderer whose name contains ``"pdf"`` needs the heavier ``a2ui-pdf`` extra.
    """
    return "ai-parrot-visualizations[a2ui-pdf]" if "pdf" in name else _A2UI_EXTRA


class RendererCapabilities(BaseModel):
    """Declared capabilities of an A2UI renderer (spec §2 Data Models).

    Attributes:
        interactive: Whether the surface supports live interaction.
        supports_actions: Whether the renderer can dispatch component actions.
        supports_updates: Whether the renderer supports incremental updates.
        output: The output mime type (e.g. ``"text/html"``, ``"application/pdf"``)
            or the literal ``"live"`` for interactive live surfaces.
    """

    interactive: bool
    supports_actions: bool
    supports_updates: bool
    output: str


class AbstractA2UIRenderer(ABC):
    """Abstract base for every A2UI renderer (spec §2 New Public Interfaces).

    Subclasses MUST declare a :class:`RendererCapabilities` class attribute
    ``capabilities`` and implement the async :meth:`render`.
    """

    #: Renderer capabilities; every concrete renderer must set this.
    capabilities: RendererCapabilities

    @abstractmethod
    async def render(
        self, envelope: CreateSurface, *, bake: bool = True
    ) -> "Any | str":
        """Render an envelope to a ``RenderedArtifact`` (baked) or a string.

        Args:
            envelope: The validated ``createSurface`` envelope to render.
            bake: When ``True``, resolve all data-model bindings and produce a
                self-contained ``RenderedArtifact`` (Module 6). When ``False``,
                a live/string representation may be returned.

        Returns:
            A ``RenderedArtifact`` (from Module 6) or a string, per the renderer.
        """
        raise NotImplementedError


#: Core registry of renderer classes, keyed by name.
_RENDERERS: dict[str, type[AbstractA2UIRenderer]] = {}


def register_a2ui_renderer(
    name: str, capabilities: RendererCapabilities
) -> Callable[[type[AbstractA2UIRenderer]], type[AbstractA2UIRenderer]]:
    """Register an A2UI renderer class under ``name``.

    Args:
        name: The renderer name used with :func:`get_a2ui_renderer`.
        capabilities: The renderer's declared capabilities; also assigned to the
            class as its ``capabilities`` attribute.

    Returns:
        The class decorator.

    Raises:
        TypeError: If ``capabilities`` is not a :class:`RendererCapabilities`.
    """
    if not isinstance(capabilities, RendererCapabilities):
        raise TypeError(
            f"register_a2ui_renderer({name!r}) requires a RendererCapabilities "
            f"instance, got {type(capabilities)!r}."
        )

    def decorator(
        cls: type[AbstractA2UIRenderer],
    ) -> type[AbstractA2UIRenderer]:
        cls.capabilities = capabilities
        _RENDERERS[name] = cls
        logger.debug("Registered A2UI renderer %r (%s)", name, cls.__name__)
        return cls

    return decorator


def get_a2ui_renderer(name: str) -> type[AbstractA2UIRenderer]:
    """Resolve a renderer class by name, importing its satellite module if needed.

    Args:
        name: The renderer name (e.g. ``"ssr_html"``, ``"pdf"``).

    Returns:
        The registered renderer class.

    Raises:
        ImportError: If the satellite module cannot be imported (message names the
            required pip extra), or if the module imported but did not register.
    """
    if name in _RENDERERS:
        return _RENDERERS[name]

    module_path = f"{_RENDERER_NAMESPACE}.{name}"
    extra = _extra_for(name)
    try:
        importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import A2UI renderer '{name}' from '{module_path}': {exc}. "
            f"Install the renderer backend with: pip install {extra}"
        ) from exc

    if name not in _RENDERERS:
        raise ImportError(
            f"Module '{module_path}' imported but did not register a renderer named "
            f"'{name}'. Ensure it calls @register_a2ui_renderer('{name}', ...)."
        )
    return _RENDERERS[name]
