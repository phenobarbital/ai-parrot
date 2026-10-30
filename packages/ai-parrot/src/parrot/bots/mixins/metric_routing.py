"""Metric default-shape slot of the output-mode chain (FEAT-756 M8)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.metrics.context import bind_metric_match, resolve_metric_tenant
from parrot.metrics.registry import MetricRegistry
from parrot.models.outputs import OutputMode
from parrot.registry.routing.route_labels import OutputShape, is_inline_component, set_output_shape

_LOGGER = logging.getLogger(__name__)


class MetricRoutingMixin:
    """explicit > router (phrasing) > METRIC > agent default.

    MRO contract: ``class X(IntentRouterMixin, MetricRoutingMixin, BasicAgent)``.
    """

    metric_registry: Optional[MetricRegistry] = None
    metric_route_threshold: Optional[float] = None

    def __init__(self, **kwargs: Any) -> None:
        registry = kwargs.pop("metric_registry", None)
        threshold = kwargs.pop("metric_route_threshold", None)
        super().__init__(**kwargs)
        if registry is not None:
            self.configure_metric_router(registry, threshold=threshold)
        elif threshold is not None:
            self.metric_route_threshold = threshold

        from parrot.bots.mixins.intent_router import IntentRouterMixin

        mro = type(self).__mro__
        if IntentRouterMixin in mro and mro.index(IntentRouterMixin) > mro.index(MetricRoutingMixin):
            _LOGGER.warning(
                "IntentRouterMixin follows MetricRoutingMixin in %s; metric routing may outrank phrasing routing",
                type(self).__name__,
            )

    def configure_metric_router(self, registry: MetricRegistry, *, threshold: Optional[float] = None) -> None:
        """Attach (or replace) the registry after construction."""
        self.metric_registry = registry
        if threshold is not None:
            self.metric_route_threshold = threshold

    def _hint_channel_available(self) -> bool:
        """FEAT-755 channel probe (merged on dev; kept guarded so a rename degrades to abstain)."""
        try:
            from parrot.registry.routing import route_labels  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _metric_caller_id(ctx: Any) -> Optional[str]:
        """Return the calling user's id from the request context, so private metrics stay owner-only."""
        if ctx is None:
            return None
        user_id = getattr(ctx, "user_id", None)
        kwargs = getattr(ctx, "kwargs", None)
        if not user_id and isinstance(kwargs, dict):
            user_id = kwargs.get("user_id")
        return str(user_id) if user_id else None

    async def _resolve_output_mode(self, query: str, ctx: Any) -> Optional[OutputMode]:
        resolved = await super()._resolve_output_mode(query, ctx)  # type: ignore[misc]
        if resolved is not None or self.metric_registry is None:
            return resolved
        try:
            tenant = resolve_metric_tenant(None, ctx)
            match = await self.metric_registry.resolve(query, tenant=tenant, user_id=self._metric_caller_id(ctx))
            if match is None:
                return None
            if self.metric_route_threshold is not None and match.score < self.metric_route_threshold:
                return None

            kwargs = getattr(ctx, "kwargs", None) if ctx is not None else None
            if isinstance(kwargs, dict):
                kwargs["metric_match"] = match
            bind_metric_match(match)
            if ctx is not None:
                ctx.intent_score = match.score

            component = match.metric.default_shape.component
            if self._hint_channel_available() and is_inline_component(component):
                return set_output_shape(ctx, OutputShape(OutputMode.A2UI, component))
            return None
        except Exception as exc:  # never break a turn
            _LOGGER.warning("metric routing failed: %s", exc)
            return None
