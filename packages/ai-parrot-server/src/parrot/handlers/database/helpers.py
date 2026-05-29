"""
HTTP handler exposing DatabaseAgent metadata for frontend interaction.

Provides REST endpoints for database agent configuration data:
- GET /api/v1/agents/database/roles          - List UserRole enum values
- GET /api/v1/agents/database/formats        - List OutputFormat enum values
- GET /api/v1/agents/database/intents        - List QueryIntent enum values
- GET /api/v1/agents/database/drivers        - List supported database drivers
- GET /api/v1/agents/database/schemas        - List cached schema metadata
- GET /api/v1/agents/database/schemas/{name} - Detail for a single cached schema
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from ...bots.database.models import (
    OutputFormat,
    QueryIntent,
    UserRole,
)
from ...bots.database.agent import DatabaseAgent


# Supported database drivers — mirrors DatabaseToolkit._DRIVER_MAP
SUPPORTED_DRIVERS: List[Dict[str, str]] = [
    {
        "name": "postgresql",
        "label": "PostgreSQL",
        "toolkit": "PostgresToolkit",
    },
    {
        "name": "bigquery",
        "label": "Google BigQuery",
        "toolkit": "BigQueryToolkit",
    },
    {
        "name": "influxdb",
        "label": "InfluxDB",
        "toolkit": "InfluxDBToolkit",
    },
    {
        "name": "elasticsearch",
        "label": "Elasticsearch",
        "toolkit": "ElasticToolkit",
    },
    {
        "name": "documentdb",
        "label": "AWS DocumentDB",
        "toolkit": "DocumentDBToolkit",
    },
    {
        "name": "mongodb",
        "label": "MongoDB",
        "toolkit": "DocumentDBToolkit",
    },
    {
        "name": "sql",
        "label": "Generic SQL",
        "toolkit": "SQLToolkit",
    },
]


def _enum_to_list(enum_cls: type) -> List[Dict[str, str]]:
    """Serialize a ``str`` enum into a list of ``{value, label}`` dicts."""
    return [
        {"value": member.value, "label": member.name.replace("_", " ").title()}
        for member in enum_cls
    ]


def _get_database_agent(
    request: web.Request,
    agent_id: Optional[str] = None,
) -> Optional[DatabaseAgent]:
    """Look up a DatabaseAgent from the bot manager.

    Args:
        request: The incoming aiohttp request.
        agent_id: Optional agent identifier.  When ``None`` the first
            ``DatabaseAgent`` registered in the bot manager is returned.

    Returns:
        A ``DatabaseAgent`` instance or ``None``.
    """
    bot_manager = request.app.get("bot_manager")
    if bot_manager is None:
        return None

    if agent_id:
        bot = bot_manager._bots.get(agent_id)
        return bot if isinstance(bot, DatabaseAgent) else None

    # Return the first DatabaseAgent found
    return next(
        (
            bot
            for bot in bot_manager._bots.values()
            if isinstance(bot, DatabaseAgent)
        ),
        None,
    )


@is_authenticated()
@user_session()
class DatabaseRolesHandler(BaseView):
    """Return the list of available ``UserRole`` values."""

    async def get(self, **kwargs: Any) -> web.Response:
        """List all user roles.

        ---
        summary: List database agent user roles
        tags:
        - Database Agent
        responses:
            "200":
                description: List of user role options
        """
        return self.json_response(
            {"roles": _enum_to_list(UserRole)},
            status=200,
        )


@is_authenticated()
@user_session()
class DatabaseFormatsHandler(BaseView):
    """Return the list of available ``OutputFormat`` values."""

    async def get(self, **kwargs: Any) -> web.Response:
        """List all output formats.

        ---
        summary: List database agent output formats
        tags:
        - Database Agent
        responses:
            "200":
                description: List of output format options
        """
        return self.json_response(
            {"formats": _enum_to_list(OutputFormat)},
            status=200,
        )


@is_authenticated()
@user_session()
class DatabaseIntentsHandler(BaseView):
    """Return the list of available ``QueryIntent`` values."""

    async def get(self, **kwargs: Any) -> web.Response:
        """List all query intents.

        ---
        summary: List database agent query intents
        tags:
        - Database Agent
        responses:
            "200":
                description: List of query intent options
        """
        return self.json_response(
            {"intents": _enum_to_list(QueryIntent)},
            status=200,
        )


@is_authenticated()
@user_session()
class DatabaseDriversHandler(BaseView):
    """Return the list of supported database drivers."""

    async def get(self, **kwargs: Any) -> web.Response:
        """List supported database drivers.

        ---
        summary: List supported database drivers and their toolkits
        tags:
        - Database Agent
        responses:
          "200":
            description: List of supported drivers
        """
        return self.json_response(
            {"drivers": SUPPORTED_DRIVERS},
            status=200,
        )


@is_authenticated()
@user_session()
class DatabaseSchemasHandler(BaseView):
    """Return cached schema metadata from a running ``DatabaseAgent``."""

    async def get(self, **kwargs: Any) -> web.Response:
        """List cached schemas or detail a single schema.

        ---
        summary: List cached schema metadata
        tags:
        - Database Agent
        parameters:
        - name: agent_id
          in: query
          required: false
          schema:
            type: string
          description: Optional agent identifier
        - name: name
          in: path
          required: false
          schema:
            type: string
          description: Schema name for detail view
        responses:
          "200":
            description: Cached schema information
          "404":
            description: Agent or schema not found
        """
        agent_id = self.request.query.get("agent_id")
        schema_name: Optional[str] = self.request.match_info.get("name")

        agent = _get_database_agent(self.request, agent_id)
        if agent is None:
            return self.error(
                "No DatabaseAgent found. Ensure one is registered in the bot manager.",
                status=404,
            )

        cache_manager = getattr(agent, "cache_manager", None)
        if cache_manager is None:
            return self.json_response({"schemas": []}, status=200)

        # Collect schemas from all partitions
        all_schemas: Dict[str, Any] = {}
        for ns, partition in cache_manager._partitions.items():
            for sname, schema_meta in partition.schema_cache.items():
                all_schemas[sname] = {
                    "database_name": schema_meta.database_name,
                    "schema": schema_meta.schema,
                    "database_type": schema_meta.database_type,
                    "table_count": schema_meta.table_count,
                    "view_count": schema_meta.view_count,
                    "total_rows": schema_meta.total_rows,
                    "partition": ns,
                    "tables": list(schema_meta.tables.keys()),
                    "views": list(schema_meta.views.keys()),
                }

        if schema_name:
            if schema_name not in all_schemas:
                return self.error(
                    f"Schema '{schema_name}' not found in cache.",
                    status=404,
                )
            return self.json_response(all_schemas[schema_name], status=200)

        return self.json_response(
            {"schemas": list(all_schemas.values())},
            status=200,
        )
