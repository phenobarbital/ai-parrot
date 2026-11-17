"""FEAT-878 collection registry: key/index fields per user-store collection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionSpec:
    """One collection: its name, document key fields, and indexed fields."""

    name: str
    key_fields: tuple[str, ...]
    index_fields: tuple[str, ...] = ()


USER_CREDENTIALS = CollectionSpec("user_credentials", ("user_id", "name"), ("user_id",))
USER_LLM_KEYS = CollectionSpec("user_llm_keys", ("user_id", "provider"), ("user_id",))
USER_TOOLKIT_CONFIGS = CollectionSpec("user_toolkit_configs", ("user_id", "agent_id", "slug"), ("user_id", "agent_id"))
USER_MCP_CONFIGS = CollectionSpec("user_mcp_configs", ("user_id", "agent_id", "server_name"), ("user_id", "agent_id"))
TELEGRAM_USER_MCP_CONFIGS = CollectionSpec("telegram_user_mcp_configs", ("user_id", "name"), ("user_id",))
USERS_INTEGRATIONS = CollectionSpec("users_integrations", ("user_id", "provider"), ("user_id",))
DASHBOARDS = CollectionSpec("dashboards", ("dashboard_id",), ("module_id", "user_id"))
DASHBOARD_TABS = CollectionSpec("dashboard_tabs", ("dashboard_id", "tab_id"), ("dashboard_id",))

USER_STORE_COLLECTIONS: dict[str, CollectionSpec] = {
    spec.name: spec
    for spec in (
        USER_CREDENTIALS,
        USER_LLM_KEYS,
        USER_TOOLKIT_CONFIGS,
        USER_MCP_CONFIGS,
        TELEGRAM_USER_MCP_CONFIGS,
        USERS_INTEGRATIONS,
        DASHBOARDS,
        DASHBOARD_TABS,
    )
}

COLLECTION_SWITCH: dict[str, str] = {
    "user_credentials": "VAULT_STORE",
    "user_llm_keys": "BYOK_STORE",
    "user_toolkit_configs": "TOOLKIT_OVERRIDES_STORE",
    "user_mcp_configs": "MCP_CONFIGS_STORE",
    "telegram_user_mcp_configs": "TELEGRAM_MCP_STORE",
    "users_integrations": "INTEGRATIONS_STORE",
    "dashboards": "DASHBOARDS_STORE",
    "dashboard_tabs": "DASHBOARDS_STORE",
}
