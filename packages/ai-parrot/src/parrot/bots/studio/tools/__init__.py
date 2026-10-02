"""AgentStudio meta-agent tools (FEAT-467 TASK-2521).

Every MUTATING tool is HITL-gated (``requires_confirmation=True`` — FEAT-235
``ConfirmationGuard``) and constrained by construction to write ONLY:

- ``AGENTS_DIR/_drafts/`` (via ``save_agent_draft``) — the TASK-2513 draft
  pipeline; a draft only ever becomes live code through its own explicit
  ``POST .../activate`` endpoint, never from this agent directly.
- ``AGENTS_DIR/<agent>/{identity,kb,skills}/`` (via ``write_identity_file``/
  ``write_kb_file``/``write_skill_file``) — the TASK-2514 sandboxed asset
  directories.
- The registry's own YAML factory path (via ``create_yaml_agent``, reusing
  ``parrot.bots.factory.tools.finalize.finalize_agent_registration`` —
  the SAME function ``AgentFactoryOrchestrator`` calls).
- The shared skills catalog (via ``publish_skill_to_catalog`` — TASK-2515).

No tool accepts a raw filesystem path; every write target is built
internally from a caller-supplied ``agent_name``/``filename`` and validated
through the same sandboxing (``resolve_safe_path``) and per-kind filename
rules the Studio HTTP handlers use. There is NO tool capable of writing a
``.py`` module directly into ``AGENTS_DIR`` itself.

Package-layering note: this package lives in the CORE ``ai-parrot``
distribution, but several validation/persistence helpers it reuses (to
avoid duplicating logic — see each tool's docstring) live in the
``ai-parrot-server`` satellite (``parrot.handlers.studio.*``). Those are
imported LAZILY, function-body-local, mirroring the existing
``parrot.knowledge.graphindex.factory`` precedent of a core module
lazily importing from a satellite distribution only when the specific
feature is actually invoked (AgentStudio is a server-side-only surface;
core never imports ``ai-parrot-server`` at module-import time).

Layout: ``_context`` (shared helpers), ``drafts``, ``agents``, ``assets``,
``catalog``, ``introspection``. ``AGENTS_DIR`` and ``current_context`` are
re-exported here and the submodules read them from THIS package at call time,
so patching ``parrot.bots.studio.tools.<name>`` keeps taking effect.
"""

from __future__ import annotations

from parrot.conf import AGENTS_DIR
from parrot.utils.helpers import current_context

from ._context import (
    _refusal_code,
    _refusing,
    _require_agent_owner,
    _require_app,
    _require_user_id,
    _studio_partition_and_services,
    _unscoped_refusal,
)
from .agents import _db_create_agent, create_yaml_agent
from .assets import _db_put_asset, _write_asset_file, write_identity_file, write_kb_file, write_skill_file
from .catalog import _db_publish_skill, publish_skill_to_catalog
from .drafts import _db_save_bundle, save_agent_bundle, save_agent_draft
from .introspection import list_agent_base_classes, list_available_tools, list_existing_agents

__all__ = [
    "AGENTS_DIR",
    "build_studio_tools",
    "create_yaml_agent",
    "current_context",
    "list_agent_base_classes",
    "list_available_tools",
    "list_existing_agents",
    "publish_skill_to_catalog",
    "save_agent_bundle",
    "save_agent_draft",
    "write_identity_file",
    "write_kb_file",
    "write_skill_file",
    "_db_create_agent",
    "_db_publish_skill",
    "_db_put_asset",
    "_db_save_bundle",
    "_refusal_code",
    "_refusing",
    "_require_agent_owner",
    "_require_app",
    "_require_user_id",
    "_studio_partition_and_services",
    "_unscoped_refusal",
    "_write_asset_file",
]

def build_studio_tools(*, declarative_only: bool = False) -> list:
    """Return every AgentStudio meta-agent tool (FEAT-467 TASK-2521).

    ``declarative_only`` (tenant partitions, FEAT-621 X11) drops ``save_agent_draft`` (Python source) and adds
    ``save_agent_bundle`` (declarative drafts).
    """
    drafts = [save_agent_bundle] if declarative_only else [save_agent_draft]
    return [
        *drafts,
        create_yaml_agent,
        write_identity_file,
        write_kb_file,
        write_skill_file,
        publish_skill_to_catalog,
        list_agent_base_classes,
        list_available_tools,
        list_existing_agents,
    ]
