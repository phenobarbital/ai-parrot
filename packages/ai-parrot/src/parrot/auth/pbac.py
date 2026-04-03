"""PBAC (Policy-Based Access Control) setup and initialization for AI-Parrot.

This module provides the ``setup_pbac()`` async helper that boots the full
PBAC stack during application startup and wires it into the aiohttp app.

Typical usage in app.py::

    from parrot.auth.pbac import setup_pbac

    pdp, evaluator, guardian = await setup_pbac(app, policy_dir="policies")
    if evaluator is not None:
        resolver = PBACPermissionResolver(evaluator=evaluator)
        bot_manager.set_default_resolver(resolver)

Public API:
    - ``setup_pbac``: Initialize PBAC engine from YAML policies directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from navigator_auth.abac.pdp import PDP
    from navigator_auth.abac.guardian import Guardian
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator

logger = logging.getLogger("parrot.auth.pbac")


async def setup_pbac(
    app: web.Application,
    policy_dir: str = "policies",
    cache_ttl: int = 30,
    default_effect: Optional[object] = None,
) -> "tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]":
    """Initialize the PBAC engine and register it with the aiohttp application.

    Performs the following steps:
    1. Validates that the policy directory exists.
    2. Creates a ``YAMLStorage`` pointing at that directory.
    3. Creates ``PolicyEvaluator`` with short TTL cache (default 30s) for
       time-dependent policy freshness.
    4. Loads YAML policies via ``PolicyLoader.load_from_directory()``.
    5. Creates ``PDP(storage=yaml_storage)`` and attaches the evaluator.
    6. Calls ``PDP.setup(app)`` which registers:
       - ``app['security']`` → ``Guardian`` instance
       - ``app['abac']`` → ``PDP`` instance
       - ABAC middleware
       - ``POST /api/v1/abac/check`` (and other ABAC endpoints)

    Graceful degradation: if *policy_dir* does not exist or the imports
    fail (navigator-auth not installed), the function logs a warning and
    returns ``(None, None, None)``.  The application continues running
    with the existing default resolver (fail-open).

    Args:
        app: The aiohttp ``web.Application`` to register PBAC into.
        policy_dir: Path to directory containing ``*.yaml`` policy files.
            Defaults to ``"policies"`` (relative to the working directory).
        cache_ttl: Seconds before a cached policy decision expires.
            Use 30s (default) to support time-sensitive policies like
            business-hours restrictions.
        default_effect: Default ``PolicyEffect`` when no policy matches.
            Defaults to ``PolicyEffect.DENY`` (deny-by-default security model).

    Returns:
        A tuple ``(pdp, evaluator, guardian)`` where all three are not None
        when PBAC was successfully initialized.  Returns ``(None, None, None)``
        if the policy directory is missing, empty, or imports fail.

    Example::

        pdp, evaluator, guardian = await setup_pbac(
            app,
            policy_dir="/etc/parrot/policies",
            cache_ttl=30,
        )
    """
    try:
        from navigator_auth.abac.pdp import PDP
        from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader
        from navigator_auth.abac.policies.abstract import PolicyEffect
        from navigator_auth.abac.storages.yaml_storage import YAMLStorage
    except ImportError as exc:
        logger.warning(
            "navigator-auth ABAC module not available — PBAC disabled. (%s)",
            exc,
        )
        return None, None, None

    # Resolve and validate policy directory
    policy_path = Path(policy_dir)
    if not policy_path.exists() or not policy_path.is_dir():
        logger.warning(
            "PBAC policy directory '%s' not found or not a directory. "
            "PBAC disabled — using default resolver.",
            policy_dir,
        )
        return None, None, None

    # Determine default effect
    if default_effect is None:
        default_effect = PolicyEffect.DENY

    # Create PolicyEvaluator with short TTL for time-dependent policies
    evaluator = PolicyEvaluator(
        default_effect=default_effect,
        cache_ttl_seconds=cache_ttl,
    )

    # Load policies from YAML files in directory
    try:
        policies = PolicyLoader.load_from_directory(policy_path)
        evaluator.load_policies(policies)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "PBAC: error loading policies from '%s': %s. "
            "PBAC disabled.",
            policy_dir,
            exc,
        )
        return None, None, None

    logger.info(
        "PBAC initialized: %d policies loaded from '%s' (cache TTL: %ds, default: %s)",
        len(policies),
        policy_dir,
        cache_ttl,
        default_effect.name,
    )

    # Create YAMLStorage (PDP uses this for policy persistence / startup reload)
    yaml_storage = YAMLStorage(directory=str(policy_path))

    # Create and configure PDP
    try:
        pdp = PDP(storage=yaml_storage)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("PBAC: failed to create PDP: %s. PBAC disabled.", exc)
        return None, None, None

    # Attach our evaluator to the PDP so Guardian and the check endpoint
    # both use the same PolicyEvaluator instance.
    # HACK: Inject our evaluator via private attribute. Guardian and PDP
    # must share the same instance for consistent policy decisions.
    # TODO: Add PDP.set_evaluator() or constructor parameter in navigator-auth.
    pdp._evaluator = evaluator  # noqa: SLF001

    # Register Guardian, middleware, and REST endpoints
    try:
        pdp.setup(app)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("PBAC: PDP.setup(app) failed: %s. PBAC disabled.", exc)
        return None, None, None

    guardian = app.get("security")
    if guardian is None:
        logger.warning(
            "PBAC: PDP.setup() did not register 'security' in app. "
            "Guardian may not be available."
        )

    return pdp, evaluator, guardian
