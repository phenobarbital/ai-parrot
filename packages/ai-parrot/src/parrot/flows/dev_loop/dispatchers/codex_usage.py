"""Decode ``codex exec --json`` usage events (FEAT-783 M4).

This codec deliberately lives outside ``_shared.py`` so sibling dispatchers do
not acquire Codex-specific parsing or an OpenAI client dependency.
"""

from __future__ import annotations

from typing import Any, Optional

from parrot.models.basic import CompletionUsage


class CodexUsageCodec:
    """Fold a Codex JSONL event stream into one terminal usage observation."""

    _USAGE_KEYS = ("usage", "total_token_usage")
    # Subtrees that carry agent/tool payloads (``item.completed`` command output, MCP
    # tool results, messages). Their content is arbitrary user data, so a ``usage``
    # key there must never be mistaken for the turn's usage. Verified against a real
    # ``codex exec --json`` stream: usage arrives top-level on ``turn.completed``.
    _OPAQUE_KEYS = frozenset({"item", "items"})

    def __init__(self) -> None:
        self._usage: Optional[dict[str, Any]] = None
        self._auth_mode: Optional[str] = None
        self._plan_type: Optional[str] = None
        self._source_cost_usd: Optional[float] = None

    @classmethod
    def _find_value(cls, value: Any, keys: tuple[str, ...]) -> Any:
        """Return the first matching value from a nested JSON value, skipping opaque payload subtrees."""
        if isinstance(value, dict):
            for key in keys:
                if key in value and value[key] is not None:
                    return value[key]
            for key, nested in value.items():
                if key in cls._OPAQUE_KEYS:
                    continue
                found = cls._find_value(nested, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_value(nested, keys)
                if found is not None:
                    return found
        return None

    def observe(self, event: dict[str, Any]) -> None:
        """Fold one stream event; the last terminal usage observation wins."""
        usage = self._find_value(event, self._USAGE_KEYS)
        if isinstance(usage, dict):
            self._usage = dict(usage)

        auth_mode = self._find_value(event, ("auth_mode",))
        if auth_mode is not None:
            self._auth_mode = str(auth_mode)
        plan_type = self._find_value(event, ("plan_type",))
        if plan_type is not None:
            self._plan_type = str(plan_type)

        cost_microusd = self._find_value(event, ("cost_microusd",))
        if cost_microusd is not None:
            self._source_cost_usd = float(cost_microusd) / 1_000_000

    def result(self) -> Optional[CompletionUsage]:
        """Return the terminal usage, or ``None`` when none was reported."""
        if self._usage is None:
            return None
        return CompletionUsage.model_validate(self._usage)

    @property
    def source_cost_usd(self) -> Optional[float]:
        """Return provider-reported cost for reconciliation only."""
        return self._source_cost_usd

    def pricing_policy(self) -> Optional[str]:
        """Return ``subscription`` for ChatGPT plans or ``billed`` for API keys."""
        auth_mode = (self._auth_mode or "").strip().lower().replace("-", "_")
        if auth_mode in {"api", "api_key", "apikey"}:
            return "billed"
        if "chatgpt" in auth_mode or self._plan_type:
            return "subscription"
        return None
