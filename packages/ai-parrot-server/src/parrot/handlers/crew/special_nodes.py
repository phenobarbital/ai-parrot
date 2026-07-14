"""Curated special-node catalog for the crew builder UI.

Exposes the list of "special nodes" — crew members that are not LLM agents
(e.g. the deterministic tool-execution node). The frontend uses this
catalog to present non-agent node types when composing a crew.

Mirrors the curated-catalog pattern of ``tool_catalog.py``: entries are
hand-picked and carry display metadata plus a JSON-Schema-ish
``config_schema`` fragment describing the node's configuration.

Route:
    GET /api/v1/crew/special_nodes
"""
from __future__ import annotations

from typing import Any, Dict, List

from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session


CREW_SPECIAL_NODE_CATALOG: List[Dict[str, Any]] = [
    {
        "slug": "tool_node",
        "name": "ToolNode",
        "display_name": "Deterministic Tool Call",
        "description": (
            "Executes a tool directly with statically declared args/kwargs "
            "— no LLM tokens are spent. String values support {input} and "
            "{nodes.<node_name>.output} template placeholders resolved "
            "deterministically from prior node results at run time. The "
            "result is wrapped as an agent-execution result, so the node "
            "participates in every crew execution mode (sequential, "
            "parallel, flow, loop)."
        ),
        "category": "deterministic",
        "type": "special_node",
        "config_schema": {
            "node_id": {
                "type": "string",
                "description": "Unique node identifier within the crew",
            },
            "tool": {
                "type": "string",
                "description": (
                    "Tool slug to execute — see GET /api/v1/crew/tools "
                    "for the available tool catalog"
                ),
            },
            "args": {
                "type": "array",
                "items": {},
                "description": "Positional arguments passed to the tool",
            },
            "kwargs": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Keyword arguments passed to the tool. String values "
                    "may embed {input} or {nodes.<node_name>.output} "
                    "template placeholders."
                ),
            },
            "description": {
                "type": "string",
                "description": "Optional display description for the node",
            },
        },
    },
]


@is_authenticated()
@user_session()
class CrewSpecialNodeCatalogHandler(BaseView):
    """Returns the curated special-node catalog for the crew builder UI."""

    _logger_name: str = "Parrot.CrewSpecialNodeCatalogHandler"

    def post_init(self, *args, **kwargs) -> None:
        self.logger = logging.getLogger(self._logger_name)

    async def get(self) -> Any:
        """Return the curated special-node catalog as a JSON array."""
        return self.json_response(CREW_SPECIAL_NODE_CATALOG)
