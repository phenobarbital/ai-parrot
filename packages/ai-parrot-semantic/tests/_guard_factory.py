"""Explicit test-only PBAC factory for governed MCP startup fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from parrot.auth import DataPlanePolicyGuard, RlsRegistry


class FixturePolicyEvaluator:
    """Deterministic allow/deny evaluator loaded from fixture policy data."""

    def __init__(self, allow: bool) -> None:
        """Store the fixture's explicit decision."""
        self._allow = allow

    def check_access(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return the configured decision for a single protected resource."""
        del args, kwargs
        return SimpleNamespace(allowed=self._allow)

    def filter_resources(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
        """Return all resources only when the fixture explicitly permits them."""
        resources = args[2] if len(args) > 2 else kwargs["resource_names"]
        return SimpleNamespace(allowed=list(resources) if self._allow else [])


def build_guard(*, rls_registry: RlsRegistry, policy_dir: str) -> DataPlanePolicyGuard:
    """Load fixture allow/deny decisions; fail when configuration is missing."""
    policy_path = Path(policy_dir) / "decisions.json"
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        allow = data["allow"]
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("Fixture policy decisions are unavailable") from exc
    if not isinstance(allow, bool):
        raise ValueError("Fixture policy decision must be boolean")
    return DataPlanePolicyGuard(evaluator=FixturePolicyEvaluator(allow), rls_registry=rls_registry)
