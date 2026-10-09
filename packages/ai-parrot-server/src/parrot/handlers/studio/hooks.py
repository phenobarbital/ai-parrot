"""Host hooks of the Studio runtime: ONE place that names every ``app[...]`` key a host may register.

Every hook is optional and absent = the previous behaviour. A host registers them on the aiohttp ``app`` before
startup completes; importing a name from here is also the host's boot-time feature probe (an ``ImportError`` means
the installed parrot does not have that hook).
"""

from __future__ import annotations

from parrot.handlers.catalog_decorator import (  # noqa: F401  (re-exported)
    CATALOG_KINDS,
    STUDIO_CATALOG_DECORATOR,
    CatalogDecorator,
)

from parrot.tools.host_hooks import (  # noqa: E402,F401  (re-exported)
    FEATURES,
    STUDIO_TOOLKIT_PARAM_HOOK,
    ToolkitParamHook,
    ToolParamRefused,
)

__all__ = [
    "CATALOG_KINDS",
    "FEATURES",
    "STUDIO_CATALOG_DECORATOR",
    "STUDIO_TOOLKIT_PARAM_HOOK",
    "CatalogDecorator",
    "ToolParamRefused",
    "ToolkitParamHook",
]
