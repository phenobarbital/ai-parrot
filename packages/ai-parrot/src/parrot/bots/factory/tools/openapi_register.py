"""Register a third-party OpenAPI spec as a runtime-discoverable toolkit.

This is how the factory turns "create an agent for LinkedIn" into a working
agent without a hand-written ``LinkedInToolkit``: download the OpenAPI spec,
materialise an ``OpenAPIToolkit`` subclass scoped to that service, register
it under a stable name in ``ToolkitRegistry`` and reference it by name in
the generated ``AgentDefinition.toolkits`` list.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from parrot.tools.decorators import tool
from parrot.tools.openapitoolkit import OpenAPIToolkit
from parrot.tools.registry import ToolkitRegistry


def _build_toolkit_subclass(service: str, spec: Any, **defaults: Any) -> type:
    """Create a thin OpenAPIToolkit subclass bound to a specific spec.

    The subclass is what gets registered: ``ToolkitRegistry`` indexes by name
    and instantiates the class with defaults (``service``, ``spec``) baked in
    so the YAML loader does not have to know the spec URL.
    """
    bound_spec = spec
    bound_service = service
    bound_defaults = defaults

    class _BoundOpenAPIToolkit(OpenAPIToolkit):
        __qualname__ = f"OpenAPIToolkit_{service}"

        def __init__(self, **kwargs: Any) -> None:
            merged = {**bound_defaults, **kwargs}
            super().__init__(
                spec=bound_spec,
                service=bound_service,
                **merged,
            )

    _BoundOpenAPIToolkit.__name__ = f"OpenAPIToolkit_{service}"
    return _BoundOpenAPIToolkit


async def register_openapi_toolkit(
    spec: str,
    service: str,
    *,
    base_url: Optional[str] = None,
    auth_type: str = "bearer",
    api_key_env: Optional[str] = None,
    toolkit_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Materialise + register an OpenAPI toolkit.

    Args:
        spec: URL, file path, JSON/YAML string, or dict containing the
            OpenAPI document.
        service: Logical service name used as tool-name prefix
            (e.g. ``"linkedin"``).
        base_url: Override the ``servers`` entry from the spec.
        auth_type: ``"bearer"``, ``"apikey"`` or ``"basic"``.
        api_key_env: Optional env var name to surface in the registration
            metadata so the YAML can reference it via interpolation.
        toolkit_name: Override the registry name (defaults to
            ``"openapi_<service>"``).

    Returns:
        Dict with ``toolkit_name`` (what to put in ``AgentDefinition.toolkits``)
        and a ``metadata`` block describing the registration.
    """
    name = toolkit_name or f"openapi_{service.lower()}"

    defaults: Dict[str, Any] = {"auth_type": auth_type}
    if base_url:
        defaults["base_url"] = base_url

    # Smoke-test the spec by instantiating once — prance will raise if invalid.
    probe = OpenAPIToolkit(spec=spec, service=service, base_url=base_url)
    operations = len(getattr(probe, "operations", {}) or {})

    toolkit_cls = _build_toolkit_subclass(service=service, spec=spec, **defaults)
    ToolkitRegistry.register(name, toolkit_cls)

    return {
        "toolkit_name": name,
        "metadata": {
            "service": service,
            "base_url": probe.base_url,
            "operations": operations,
            "auth_type": auth_type,
            "api_key_env": api_key_env,
        },
    }


@tool(name="register_openapi_toolkit",
      description="Download an OpenAPI spec and register a dynamic toolkit "
                  "for that service so the new agent can call it. Use this "
                  "when the user asks for an integration to a REST API that "
                  "has no native toolkit (e.g. LinkedIn, Notion). Returns "
                  "the toolkit name to add to AgentDefinition.toolkits.")
async def _register_openapi_toolkit_tool(
    spec: str,
    service: str,
    base_url: Optional[str] = None,
    auth_type: str = "bearer",
    api_key_env: Optional[str] = None,
) -> Dict[str, Any]:
    return await register_openapi_toolkit(
        spec=spec,
        service=service,
        base_url=base_url,
        auth_type=auth_type,
        api_key_env=api_key_env,
    )
