"""Jinja2-based tool call dispatcher for the ontology pipeline (FEAT-158).

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
"""
from __future__ import annotations

import json as _json
import logging
import re
from typing import Any

from jinja2 import Environment, StrictUndefined, UndefinedError

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.manager import ToolManager

from .schema import ToolCallSpec


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class RenderError(Exception):
    """Raised when Jinja2 template rendering fails (e.g., ``StrictUndefined``).

    Attributes:
        field: The parameter field whose template triggered the error.
        message: The original ``UndefinedError`` or rendering message.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


# ---------------------------------------------------------------------------
# Jinja2 safety filters
# ---------------------------------------------------------------------------


def jql_quote(value: Any) -> str:
    """Escape a value for safe inclusion as a JQL string literal.

    Wraps the value in double quotes and escapes embedded double quotes and
    backslashes (adversarial input mitigation).

    Args:
        value: Any value to escape.

    Returns:
        A safely double-quoted string for use in a JQL expression.

    Example::

        >>> jql_quote('Jesús" OR project="OTHER')
        '"Jesús\\" OR project=\\"OTHER"'
    """
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def jira_accounts(team: list[dict[str, Any]]) -> str:
    """Render a comma-separated list of Jira accountIds for a JQL clause.

    Validates each element's ``jira_account_id`` field before inclusion.
    Raises ``ValueError`` if any accountId has an unexpected shape.

    Args:
        team: List of dicts, each expected to have a ``jira_account_id`` key.

    Returns:
        Comma-separated string of quoted accountIds suitable for a JQL
        ``assignee in (...)`` clause. Members without a valid accountId are
        silently skipped.

    Raises:
        ValueError: If any accountId fails the format validation
            (``[A-Za-z0-9:_\\-]+``).
    """
    ids: list[str] = []
    for member in team:
        acc = member.get("jira_account_id")
        if not acc or not isinstance(acc, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9:_\-]+", acc):
            raise ValueError(f"invalid jira accountId shape: {acc!r}")
        ids.append(jql_quote(acc))
    return ", ".join(ids)


def join_ids(
    items: list[dict[str, Any]],
    key: str = "_id",
    sep: str = ",",
) -> str:
    """Join the values of a given key across a list of dicts.

    Args:
        items: List of dicts.
        key: Key to extract from each dict.
        sep: Separator string.

    Returns:
        Joined string of extracted values.
    """
    return sep.join(str(item[key]) for item in items if key in item)


def map_attr(items: list[dict[str, Any]], key: str) -> list[Any]:
    """Extract a single attribute from each dict in a list.

    Args:
        items: List of dicts.
        key: Attribute key to extract.

    Returns:
        List of extracted values (``None`` for missing keys).
    """
    return [item.get(key) for item in items]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _GraphNamespace:
    """Thin wrapper exposing ``graph_result`` under both ``graph.rows`` and
    ``graph.team`` aliases for Jinja2 templates.

    Args:
        rows: The graph traversal result list.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.team = rows  # semantic alias used in YAML examples

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __bool__(self):
        return bool(self.rows)


def _build_permission_context(user_context: dict[str, Any]) -> PermissionContext:
    """Build a ``PermissionContext`` from a plain ``user_context`` dict.

    This supports the plain-dict path when the Mixin's
    ``_get_permission_context()`` returns a raw dict instead of a pre-built
    ``PermissionContext``. In production flows with a concrete agent, the
    agent should override the hook to return a fully-populated
    ``PermissionContext``.

    Args:
        user_context: Session dict with at least ``user_id`` and optionally
            ``channel``, ``tenant_id``, ``roles``.

    Returns:
        A ``PermissionContext`` with ``user_id`` and ``channel`` populated.
    """
    user_id = user_context.get("user_id") or ""
    if not user_id:
        logging.getLogger(__name__).warning(
            "ToolCallDispatcher: no user_id in user_context — "
            "permission context will be anonymous; toolkit OAuth will likely fail"
        )
        user_id = "anonymous"
    tenant_id = user_context.get("tenant_id", "")
    channel = user_context.get("channel")
    roles_raw = user_context.get("roles", [])
    roles: frozenset[str] = frozenset(roles_raw) if isinstance(roles_raw, (list, set, frozenset)) else frozenset()

    session = UserSession(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        roles=roles,
    )
    return PermissionContext(session=session, channel=channel)


def _render_value(value: Any, template_env: Environment, ns: dict[str, Any]) -> Any:
    """Recursively render a Jinja2 template value.

    - Strings are rendered as Jinja2 templates.
    - Lists are rendered element-wise.
    - Dicts are rendered value-wise.
    - All other scalars (int, bool, float, None) pass through unchanged.

    Args:
        value: The template value to render.
        template_env: Jinja2 ``Environment`` instance.
        ns: Template namespace dict (``graph``, ``ctx``, ``extras``).

    Returns:
        Rendered value.
    """
    if isinstance(value, str):
        return template_env.from_string(value).render(**ns)
    if isinstance(value, list):
        return [_render_value(item, template_env, ns) for item in value]
    if isinstance(value, dict):
        return {k: _render_value(v, template_env, ns) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# ToolCallDispatcher
# ---------------------------------------------------------------------------


class ToolCallDispatcher:
    """Renders and invokes a tool call specified by a ``ToolCallSpec``.

    Uses a single shared ``jinja2.Environment`` with ``StrictUndefined`` and
    the following registered safety filters:

    - ``jql_quote``: escape a value for JQL string literals.
    - ``jira_accounts``: validate and join Jira accountIds.
    - ``join_ids``: join ``_id`` values from a list of dicts.
    - ``map_attr``: extract an attribute from each dict in a list.
    - ``json``: serialize a value to a JSON string.

    **autoescape=False** is intentional. Outputs are non-HTML query strings;
    safety lives in the per-filter escapers above.

    Args:
        tool_manager: The ``ToolManager`` instance used for tool resolution.
    """

    def __init__(self, tool_manager: ToolManager) -> None:
        self._tool_manager = tool_manager
        self.logger = logging.getLogger(__name__)
        self._env = Environment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=False,
        )
        self._env.filters["jql_quote"] = jql_quote
        self._env.filters["jira_accounts"] = jira_accounts
        self._env.filters["join_ids"] = join_ids
        self._env.filters["map_attr"] = map_attr
        self._env.filters["json"] = lambda v: _json.dumps(v)

    async def dispatch(
        self,
        spec: ToolCallSpec,
        graph_result: list[dict[str, Any]],
        user_context: dict[str, Any],
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Render parameters and invoke the tool specified by ``spec``.

        Steps:
        1. **Empty-team gate**: if ``graph_result`` is empty, handle according
           to ``spec.empty_team_behavior``.
        2. **Render parameters**: render each value in ``spec.parameters`` as
           a Jinja2 template with ``(graph, ctx, extras)`` namespaces.
        3. **Resolve tool**: call ``ToolManager.get_tool(f"{toolkit}.{method}")``.
        4. **Invoke**: call ``tool.execute(**rendered, _permission_context=perm_ctx)``.
           ``AuthorizationRequired`` propagates unchanged for the Mixin to handle.

        Args:
            spec: ``ToolCallSpec`` from the matched ``TraversalPattern``.
            graph_result: Results from graph traversal.
            user_context: Session data (``user_id``, ``channel``, …).
            extras: Optional caller-supplied extras passed into the template
                namespace as ``extras.*``.

        Returns:
            ``{spec.result_binding: tool_output}``

        Raises:
            RenderError: When a template variable is undefined (StrictUndefined)
                or rendering otherwise fails.
            ValueError: When the tool is not registered, or when
                ``empty_team_behavior="fail"`` and ``graph_result`` is empty.
            AuthorizationRequired: When the toolkit's ``_pre_execute`` hook
                cannot resolve OAuth credentials. Propagated unchanged.
        """
        # 1. Empty-team gate
        if not graph_result:
            if spec.empty_team_behavior == "short_circuit":
                self.logger.info(
                    "ToolCallDispatcher: empty graph result, short-circuiting "
                    "(tool=%s.%s, binding=%s)",
                    spec.toolkit, spec.method, spec.result_binding,
                )
                return {spec.result_binding: {"empty": True, "items": []}}
            if spec.empty_team_behavior == "fail":
                raise ValueError("empty graph result, empty_team_behavior=fail")
            # "call_anyway" falls through

        # 2. Build template namespace
        graph_ns = _GraphNamespace(graph_result)
        ns: dict[str, Any] = {
            "graph": graph_ns,
            "ctx": {
                **user_context,
                "original_query": user_context.get("original_query"),
            },
            "extras": extras or {},
        }

        # 3. Render parameters
        rendered: dict[str, Any] = {}
        for field, template_value in spec.parameters.items():
            try:
                rendered[field] = _render_value(template_value, self._env, ns)
            except UndefinedError as exc:
                raise RenderError(field=field, message=str(exc)) from exc

        # 4. Resolve tool (synchronous)
        tool = self._tool_manager.get_tool(f"{spec.toolkit}.{spec.method}")
        if tool is None:
            raise ValueError(
                f"tool {spec.toolkit}.{spec.method} not registered in ToolManager"
            )

        # 5. Build PermissionContext and invoke
        # AuthorizationRequired propagates unchanged — the Mixin maps it to
        # ContextEnvelope(state="auth_required").
        perm_ctx = _build_permission_context(user_context)
        self.logger.info(
            "ToolCallDispatcher: invoking %s.%s for user=%s",
            spec.toolkit, spec.method, perm_ctx.user_id,
        )
        result = await tool.execute(**rendered, _permission_context=perm_ctx)

        return {spec.result_binding: result}
