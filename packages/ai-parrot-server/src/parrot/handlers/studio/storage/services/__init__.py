"""Agent Studio services (spec §2.5). Lazy exports: each service lives in its own submodule."""
from importlib import import_module
from typing import Any

_EXPORTS = {
    "StudioLimits": "_common", "StudioClassAllowlist": "_common", "StudioToolingGate": "_common",
    "StudioServices": "_common", "build_studio_services": "_common",
    "StudioToolingService": "tooling", "StudioAgentService": "agents", "StudioAssetService": "assets",
    "StudioDraftService": "drafts", "StudioSkillCatalogService": "catalog",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
