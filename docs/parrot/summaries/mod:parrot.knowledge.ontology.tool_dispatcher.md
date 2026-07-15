---
type: Wiki Summary
title: parrot.knowledge.ontology.tool_dispatcher
id: mod:parrot.knowledge.ontology.tool_dispatcher
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Jinja2-based tool call dispatcher for the ontology pipeline (FEAT-158).
relates_to:
- concept: class:parrot.knowledge.ontology.tool_dispatcher.RenderError
  rel: defines
- concept: class:parrot.knowledge.ontology.tool_dispatcher.ToolCallDispatcher
  rel: defines
- concept: func:parrot.knowledge.ontology.tool_dispatcher.jira_accounts
  rel: defines
- concept: func:parrot.knowledge.ontology.tool_dispatcher.join_ids
  rel: defines
- concept: func:parrot.knowledge.ontology.tool_dispatcher.jql_quote
  rel: defines
- concept: func:parrot.knowledge.ontology.tool_dispatcher.map_attr
  rel: defines
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.knowledge.ontology.tool_dispatcher`

Jinja2-based tool call dispatcher for the ontology pipeline (FEAT-158).

``ToolCallDispatcher`` bridges graph traversal results to real tool invocations:

1. **Empty-team gate** — checks ``spec.empty_team_behavior`` before rendering.
2. **Jinja2 rendering** — renders ``ToolCallSpec.parameters`` with safety
   filters and the ``(graph, ctx, extras)`` namespace. Uses ``StrictUndefined``
   so missing bindings raise ``RenderError`` instead of silently producing
   ``"Undefined"``.
3. **Tool resolution** — calls ``ToolManager.get_tool(f"{toolkit}.{method}")``.
4. **Tool invocation** — calls ``tool.execute(**rendered, _permission_context=perm_ctx)``
   so the toolkit's own ``_pre_execute`` hook (e.g., ``JiraToolkit._pre_execute``
   at ``jiratoolkit.py:866``) resolves user-scoped OAuth credentials.

**PermissionContext**: ``ToolCallDispatcher`` resolves the existing
``parrot.auth.permission.PermissionContext`` class. The dispatcher builds one
from the ``user_context`` dict so toolkit hooks can read ``.user_id`` and
``.channel``. A ``UserSession`` (required by ``PermissionContext``) is created
with the user_id and an empty ``tenant_id`` / ``roles``. For production flows,
the concrete agent should override ``_get_permission_context()`` on
``OntologyRAGMixin`` to return a pre-built ``PermissionContext`` directly; this
dispatcher handles the plain-dict path.

**Credential resolution**: the dispatcher does NOT call ``CredentialResolver``
directly. Toolkits own their resolver; the dispatcher only forwards
``_permission_context``.

**autoescape=False**: Intentional. Outputs are JQL / plain-string query
parameters, not HTML. Safety lives in per-filter escapers (``jql_quote``,
``jira_accounts``, etc.).

## Classes

- **`RenderError(Exception)`** — Raised when Jinja2 template rendering fails (e.g., ``StrictUndefined``).
- **`ToolCallDispatcher`** — Renders and invokes a tool call specified by a ``ToolCallSpec``.

## Functions

- `def jql_quote(value: Any) -> str` — Escape a value for safe inclusion as a JQL string literal.
- `def jira_accounts(team: list[dict[str, Any]]) -> str` — Render a comma-separated list of Jira accountIds for a JQL clause.
- `def join_ids(items: list[dict[str, Any]], key: str='_id', sep: str=',') -> str` — Join the values of a given key across a list of dicts.
- `def map_attr(items: list[dict[str, Any]], key: str) -> list[Any]` — Extract a single attribute from each dict in a list.
