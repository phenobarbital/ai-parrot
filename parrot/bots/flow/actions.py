"""
Action Registry — Lifecycle hooks for AgentsFlow nodes.

This module defines the ACTION_REGISTRY and all built-in action implementations.
Actions are executed as pre/post hooks on flow nodes and can:
- Log messages with template variables
- Send notifications to external channels
- Make HTTP webhook calls
- Emit metrics
- Extract and set context values
- Validate results against JSON schemas
- Transform results

Example:
    >>> from parrot.bots.flow.actions import ACTION_REGISTRY, LogAction
    >>> from parrot.bots.flow.definition import LogActionDef
    >>>
    >>> config = LogActionDef(level="info", message="Node {node_name} completed")
    >>> action = LogAction(config)
    >>> await action("my_node", "result_payload")
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, Union

import aiohttp
from navconfig.logging import logging

from .definition import (
    ActionDefinition,
    LogActionDef,
    MetricActionDef,
    NotifyActionDef,
    SetContextActionDef,
    TransformActionDef,
    ValidateActionDef,
    WebhookActionDef,
)


# ---------------------------------------------------------------------------
# Action Registry
# ---------------------------------------------------------------------------

ACTION_REGISTRY: Dict[str, Type["BaseAction"]] = {}


def register_action(action_type: str):
    """Decorator to register an action class in the ACTION_REGISTRY.

    Args:
        action_type: The string identifier for this action (e.g., "log", "webhook")

    Example:
        >>> @register_action("custom")
        ... class CustomAction(BaseAction):
        ...     async def __call__(self, node_name, payload, **ctx):
        ...         print(f"Custom action on {node_name}")
    """
    def decorator(cls: Type["BaseAction"]) -> Type["BaseAction"]:
        ACTION_REGISTRY[action_type] = cls
        return cls
    return decorator


# ---------------------------------------------------------------------------
# Base Action
# ---------------------------------------------------------------------------

class BaseAction(ABC):
    """Abstract base class for all flow lifecycle actions.

    Actions are executed as pre/post hooks on flow nodes. They receive:
    - node_name: The name of the node triggering the action
    - payload: For pre-actions this is the prompt, for post-actions the result
    - **ctx: Additional context (session_id, user_id, shared_context, etc.)

    Subclasses must implement `async def __call__`.
    """

    def __init__(self, config: ActionDefinition):
        """Initialize the action with its configuration.

        Args:
            config: Pydantic model with action-specific configuration
        """
        self.config = config
        self.logger = logging.getLogger(f"parrot.action.{self.__class__.__name__}")

    @abstractmethod
    async def __call__(
        self,
        node_name: str,
        payload: Any,
        **ctx: Any
    ) -> None:
        """Execute the action.

        Args:
            node_name: Name of the node triggering this action
            payload: Result (post) or prompt (pre) depending on when action runs
            **ctx: Additional context (session_id, user_id, shared_context, etc.)
        """


# ---------------------------------------------------------------------------
# Built-in Actions
# ---------------------------------------------------------------------------

@register_action("log")
class LogAction(BaseAction):
    """Log a message with template variables.

    Template variables:
    - {node_name}: Name of the node
    - {result}: The payload (result or prompt)
    - {prompt}: Alias for payload (for pre-actions)
    - Any key from ctx
    """

    config: LogActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Log the formatted message."""
        try:
            # Build template context
            template_ctx = {
                "node_name": node_name,
                "result": payload,
                "prompt": payload,
                **ctx
            }

            # Format message with available variables
            message = self._safe_format(self.config.message, template_ctx)

            # Log at configured level
            logger = logging.getLogger(f"parrot.action.{node_name}")
            log_method = getattr(logger, self.config.level, logger.info)
            log_method(message)

        except Exception as e:
            self.logger.warning(f"LogAction failed: {e}")

    @staticmethod
    def _safe_format(template: str, ctx: Dict[str, Any]) -> str:
        """Safely format template, ignoring missing keys."""
        try:
            return template.format(**ctx)
        except KeyError:
            # Fallback: replace known keys only
            result = template
            for key, value in ctx.items():
                result = result.replace(f"{{{key}}}", str(value))
            return result


@register_action("notify")
class NotifyAction(BaseAction):
    """Send a notification to a channel.

    Supported channels:
    - log: Just logs the notification
    - slack: Logs (actual integration out of scope)
    - teams: Logs (actual integration out of scope)
    - email: Logs (actual integration out of scope)
    """

    config: NotifyActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Send the notification."""
        try:
            # Build template context
            template_ctx = {
                "node_name": node_name,
                "result": payload,
                "prompt": payload,
                **ctx
            }

            message = LogAction._safe_format(self.config.message, template_ctx)
            channel = self.config.channel
            target = self.config.target or "default"

            # Log the notification (actual integrations would go here)
            self.logger.info(
                f"[{channel.upper()}] -> {target}: {message}"
            )

            # In a real implementation, this would call the appropriate API
            # For now, we just log to demonstrate the interface
            if channel == "slack":
                self.logger.debug(f"Would send to Slack channel: {target}")
            elif channel == "teams":
                self.logger.debug(f"Would send to Teams channel: {target}")
            elif channel == "email":
                self.logger.debug(f"Would send email to: {target}")

        except Exception as e:
            self.logger.warning(f"NotifyAction failed: {e}")


@register_action("webhook")
class WebhookAction(BaseAction):
    """Make an HTTP webhook call.

    Supports POST and PUT methods with optional headers and body template.
    """

    config: WebhookActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Execute the webhook call."""
        try:
            # Build template context
            template_ctx = {
                "node_name": node_name,
                "result": str(payload),
                "prompt": str(payload),
                **{k: str(v) for k, v in ctx.items()}
            }

            # Prepare body
            body: Optional[str] = None
            if self.config.body_template:
                body = LogAction._safe_format(self.config.body_template, template_ctx)

            # Make the HTTP request
            async with aiohttp.ClientSession() as session:
                method = self.config.method.lower()
                kwargs: Dict[str, Any] = {
                    "headers": self.config.headers or {}
                }

                if body:
                    kwargs["data"] = body
                    if "Content-Type" not in kwargs["headers"]:
                        kwargs["headers"]["Content-Type"] = "application/json"

                async with getattr(session, method)(
                    self.config.url,
                    **kwargs
                ) as response:
                    self.logger.debug(
                        f"Webhook {method.upper()} {self.config.url} "
                        f"-> {response.status}"
                    )

                    if response.status >= 400:
                        self.logger.warning(
                            f"Webhook returned error status: {response.status}"
                        )

        except Exception as e:
            self.logger.warning(f"WebhookAction failed: {e}")


@register_action("metric")
class MetricAction(BaseAction):
    """Emit a metric.

    This is an interface for metrics emission. The actual metric backend
    (Prometheus, StatsD, etc.) is out of scope - this logs the metric.
    """

    config: MetricActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Emit the metric."""
        try:
            # Build template context for tags
            template_ctx = {
                "node_name": node_name,
                "result": str(payload),
                "flow_name": ctx.get("flow_name", "unknown"),
                **{k: str(v) for k, v in ctx.items()}
            }

            # Format tags
            formatted_tags = {}
            for key, value in self.config.tags.items():
                formatted_tags[key] = LogAction._safe_format(value, template_ctx)

            # Log the metric (in production, would send to metrics backend)
            self.logger.info(
                f"METRIC: {self.config.name}={self.config.value} "
                f"tags={formatted_tags}"
            )

        except Exception as e:
            self.logger.warning(f"MetricAction failed: {e}")


@register_action("set_context")
class SetContextAction(BaseAction):
    """Extract a value from the result and set it in the shared context.

    Uses dot-notation to navigate nested structures (e.g., "result.decision.value").
    """

    config: SetContextActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Extract and set the context value."""
        try:
            # Get the shared context dict
            shared_context = ctx.get("shared_context")
            if shared_context is None:
                self.logger.warning(
                    f"SetContextAction: no shared_context provided for node {node_name}"
                )
                return

            # Extract value using dot notation
            value = self._extract_value(payload, self.config.value_from)

            # Set in context
            shared_context[self.config.key] = value

            self.logger.debug(
                f"SetContextAction: {self.config.key} = {value} "
                f"(from {self.config.value_from})"
            )

        except Exception as e:
            self.logger.warning(f"SetContextAction failed: {e}")

    @staticmethod
    def _extract_value(obj: Any, path: str) -> Any:
        """Extract a value from an object using dot notation.

        Args:
            obj: The object to extract from
            path: Dot-notation path (e.g., "result.decision.value")

        Returns:
            The extracted value, or None if path not found
        """
        parts = path.split(".")
        current = obj

        for part in parts:
            # Skip 'result' if it's the first part (payload is already the result)
            if part == "result" and current is obj:
                continue

            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            elif hasattr(current, "model_dump"):
                # Pydantic model
                current = current.model_dump().get(part)
            else:
                return None

        return current


@register_action("validate")
class ValidateAction(BaseAction):
    """Validate the result against a JSON schema.

    Behavior on validation failure depends on `on_failure`:
    - "raise": Raise ValueError
    - "skip": Log warning and continue
    - "fallback": Replace result with fallback_value (not implemented here)
    """

    config: ValidateActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        """Validate the payload against the schema."""
        try:
            import jsonschema

            # Convert payload to dict if needed
            data = payload
            if hasattr(payload, "model_dump"):
                data = payload.model_dump()
            elif not isinstance(payload, (dict, list, str, int, float, bool, type(None))):
                data = str(payload)

            # Validate
            try:
                jsonschema.validate(instance=data, schema=self.config.schema_)
                self.logger.debug(f"ValidateAction: validation passed for {node_name}")

            except jsonschema.ValidationError as ve:
                if self.config.on_failure == "raise":
                    raise ValueError(
                        f"Validation failed for node '{node_name}': {ve.message}"
                    ) from ve
                elif self.config.on_failure == "skip":
                    self.logger.warning(
                        f"ValidateAction: validation failed for {node_name}, "
                        f"skipping: {ve.message}"
                    )
                elif self.config.on_failure == "fallback":
                    self.logger.warning(
                        f"ValidateAction: validation failed for {node_name}, "
                        f"would use fallback: {self.config.fallback_value}"
                    )
                    # Actual fallback replacement would be handled by caller

        except ImportError:
            self.logger.error("ValidateAction requires 'jsonschema' package")
            raise
        except Exception as e:
            self.logger.warning(f"ValidateAction failed: {e}")
            if self.config.on_failure == "raise":
                raise


@register_action("transform")
class TransformAction(BaseAction):
    """Transform the result using a safe expression.

    Supports simple transformations like:
    - "result.lower()" - call method on result
    - "result.strip()" - call method
    - "result.upper()" - call method

    NOTE: This uses safe attribute access only, NOT eval().
    Complex transformations should use a proper expression language (CEL).
    """

    config: TransformActionDef

    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> Any:
        """Apply the transformation.

        Returns:
            The transformed value (for informational purposes;
            actual result modification is handled by the caller)
        """
        try:
            expression = self.config.expression
            result = self._safe_eval(payload, expression)

            self.logger.debug(
                f"TransformAction: {expression} -> {result}"
            )

            # Store transformed result in shared context if available
            shared_context = ctx.get("shared_context")
            if shared_context is not None:
                shared_context["_transformed_result"] = result

            return result

        except Exception as e:
            self.logger.warning(f"TransformAction failed: {e}")
            return payload

    @staticmethod
    def _safe_eval(obj: Any, expression: str) -> Any:
        """Safely evaluate a simple expression on an object.

        Only supports:
        - Method calls with no arguments (e.g., "result.lower()")
        - Attribute access (e.g., "result.value")

        Args:
            obj: The object to operate on
            expression: Simple expression string

        Returns:
            The result of the expression
        """
        # Remove "result." prefix if present
        if expression.startswith("result."):
            expression = expression[7:]

        current = obj

        # Parse the expression parts
        parts = expression.replace("()", "").split(".")

        for part in parts:
            is_method_call = expression.endswith("()")

            if current is None:
                return None

            if isinstance(current, dict):
                current = current.get(part, current)
            elif hasattr(current, part):
                attr = getattr(current, part)
                if is_method_call and callable(attr):
                    current = attr()
                else:
                    current = attr
            else:
                return current

        return current


# ---------------------------------------------------------------------------
# Factory Function
# ---------------------------------------------------------------------------

def create_action(config: ActionDefinition) -> BaseAction:
    """Create an action instance from a configuration.

    Args:
        config: Action definition (Pydantic model)

    Returns:
        Instantiated action ready to execute

    Raises:
        ValueError: If action type is not registered
    """
    action_type = config.type
    action_class = ACTION_REGISTRY.get(action_type)

    if action_class is None:
        raise ValueError(
            f"Unknown action type '{action_type}'. "
            f"Available: {list(ACTION_REGISTRY.keys())}"
        )

    return action_class(config)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    # Registry
    "ACTION_REGISTRY",
    "register_action",
    "create_action",
    # Base class
    "BaseAction",
    # Built-in actions
    "LogAction",
    "NotifyAction",
    "WebhookAction",
    "MetricAction",
    "SetContextAction",
    "ValidateAction",
    "TransformAction",
]
