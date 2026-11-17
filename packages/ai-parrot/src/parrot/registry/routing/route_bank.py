"""``routes.yaml`` phrase-bank loading and merging (FEAT-755).

Layout mirrors the FEAT-707 per-tenant skills tree::

    <agent_root>/routes.yaml                      # agent-level bank
    <agent_root>/tenants/<tenant>/routes.yaml     # per-tenant override

Merge order is defaults <- agent <- tenant. Nothing here raises for a bad file:
a malformed bank is warned about and skipped.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final, Mapping, Optional, Sequence

import yaml
from pydantic import BaseModel, ConfigDict, Field

from parrot.skills.tenancy import TENANTS_DIRNAME, validate_tenant_id
from parrot.utils.paths import secure_path

logger = logging.getLogger(__name__)

ROUTES_FILENAME: Final[str] = "routes.yaml"


class RouteBankFile(BaseModel):
    """Schema of one ``routes.yaml``."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    routes: dict[str, list[str]] = Field(default_factory=dict)
    replace: bool = False
    threshold: Optional[float] = None
    margin: Optional[float] = None


class ResolvedRouteBanks(BaseModel):
    """Merged global bank, per-tenant banks, and optional threshold overrides."""

    routes: dict[str, list[str]] = Field(default_factory=dict)
    tenant_routes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    threshold: Optional[float] = None
    margin: Optional[float] = None


def agent_routes_path(agent_root: Path) -> Path:
    """Return ``agent_root/routes.yaml``."""
    return agent_root / ROUTES_FILENAME


def tenant_routes_path(agent_root: Path, tenant: str) -> Path:
    """Return the contained ``agent_root/tenants/<tenant>/routes.yaml``.

    Args:
        agent_root: Root directory of the agent definition.
        tenant: Untrusted tenant identifier.

    Returns:
        The contained path to the tenant route bank.

    Raises:
        ValueError: If the tenant id is invalid/reserved or the path escapes ``agent_root``.
    """
    return secure_path(agent_root, TENANTS_DIRNAME, validate_tenant_id(tenant), ROUTES_FILENAME, name="tenant id")


def load_route_bank(path: Path) -> Optional[RouteBankFile]:
    """Load and validate one ``routes.yaml``.

    Args:
        path: Route-bank file to load.

    Returns:
        The validated bank, or ``None`` when the file is missing or invalid.
    """
    try:
        if not path.is_file():
            return None
        content: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RouteBankFile.model_validate(content)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.warning("Skipping route bank %s: %s", path, exc)
        return None


def merge_route_banks(base: Mapping[str, Sequence[str]], *overlays: RouteBankFile) -> dict[str, list[str]]:
    """Merge ``base`` with each overlay from left to right.

    Args:
        base: Initial phrase bank.
        *overlays: Validated route-bank overlays.

    Returns:
        A new merged mapping. Input mappings and models are not mutated.
    """
    merged = {key: list(dict.fromkeys(utterances)) for key, utterances in base.items()}
    for overlay in overlays:
        for key, utterances in overlay.routes.items():
            if overlay.replace:
                merged[key] = list(dict.fromkeys(utterances))
                continue
            combined = [*merged.get(key, []), *utterances]
            merged[key] = list(dict.fromkeys(combined))
    return merged


def resolve_route_banks(
    agent_root: Optional[Path],
    *,
    defaults: Mapping[str, Sequence[str]],
    tenant_based: bool,
) -> ResolvedRouteBanks:
    """Resolve defaults <- agent file <- per-tenant files.

    Args:
        agent_root: Agent definition root, or ``None`` when no file tree exists.
        defaults: Built-in phrase bank.
        tenant_based: Whether to discover and merge tenant banks.

    Returns:
        The resolved global and per-tenant phrase banks.
    """
    default_routes = merge_route_banks(defaults)
    if agent_root is None:
        return ResolvedRouteBanks(routes=default_routes)

    agent_bank = load_route_bank(agent_routes_path(agent_root))
    global_routes = merge_route_banks(default_routes, *([agent_bank] if agent_bank is not None else []))
    threshold = agent_bank.threshold if agent_bank is not None else None
    margin = agent_bank.margin if agent_bank is not None else None
    tenant_routes: dict[str, dict[str, list[str]]] = {}

    if tenant_based:
        tenants_root = agent_root / TENANTS_DIRNAME
        try:
            entries = sorted(tenants_root.iterdir()) if tenants_root.is_dir() else []
        except OSError as exc:
            logger.warning("Skipping tenant route banks under %s: %s", tenants_root, exc)
            entries = []

        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
                path = tenant_routes_path(agent_root, entry.name)
            except (OSError, ValueError) as exc:
                logger.warning("Skipping tenant route bank %s: %s", entry, exc)
                continue
            tenant_bank = load_route_bank(path)
            overlays = [tenant_bank] if tenant_bank is not None else []
            tenant_routes[entry.name] = merge_route_banks(global_routes, *overlays)

    return ResolvedRouteBanks(
        routes=global_routes,
        tenant_routes=tenant_routes,
        threshold=threshold,
        margin=margin,
    )
