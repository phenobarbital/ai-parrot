"""Hooks a HOST (e.g. the Agent Studio service) registers to police the tools of the agents it builds.

Every hook is optional; absent means the previous behaviour. ``FEATURES`` is the boot-time probe: a host checks
``"toolkit_param_hook" in parrot.tools.host_hooks.FEATURES`` (an ``ImportError`` means an older parrot).

Toolkit-parameter hook (PA-9)
-----------------------------
``app[STUDIO_TOOLKIT_PARAM_HOOK] = hook`` with ``hook(slug, params, subject) -> params``:

* ``slug`` is the tool/toolkit slug, ``params`` a COPY of the constructor parameters (client values, then the
  server-managed fill), ``subject`` a :class:`~parrot.tools.tooling_policy.ToolingSubject` (tenant, agent id, actor and
  the ``phase``: ``write``/``activate`` at write time, ``attach`` for a live assignment, ``build`` for a stored agent).
* it returns the FINAL parameters: it may add, replace or remove keys (force a directory, ``programs``…). The special
  key ``exclude_tools`` (a sequence of method names) is applied to the constructed instance, whatever its constructor
  accepts, and can only ADD to the class's own exclusions.
* it may raise :class:`~parrot.tools.tooling_policy.ToolParamRefused` naming the refused parameters. Any other error,
  an awaitable or a non-mapping result also refuses (fail closed).

The hook runs on every path that constructs a toolkit for a Studio agent: at write time (policy enforcement, dry
run: the result is discarded), on a live assignment, and at build time of a stored agent (which fails closed).

TOOL_CALL guardrails (PA-10)
----------------------------
``app[STUDIO_TOOL_CALL_GUARDRAILS] = [guardrail, ...]`` — the existing TOOL_CALL guardrail protocol
(:class:`parrot.bots.guardrails.base.Guardrail`: ``async check(content, ctx) -> GuardrailResult``). Every Studio-built
bot gets each of them on its TOOL_CALL pipeline, so they run before every tool call with
``ctx.extras["arguments"]`` (the call's arguments) and ``ctx.tool_name``. Each guardrail is wrapped per bot: it sees
``ctx.extras["studio"] == {"tenant", "agent_id", "agent", "visibility"}`` of THAT bot, a raising guardrail BLOCKS
(fail closed) whatever its own ``on_error``, and a BLOCK's ``reason`` is the tool's refusal that reaches the LLM and the
audit line. The direct ``POST /tools/{slug}/execute`` route runs the same guardrails (``agent`` is ``None`` there).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from parrot.tools.tooling_policy import ToolParamRefused

if TYPE_CHECKING:  # pragma: no cover
    from parrot.tools.spec import NormalizedTooling
    from parrot.tools.tooling_policy import ToolingSubject

logger = logging.getLogger(__name__)

STUDIO_TOOLKIT_PARAM_HOOK = "studio_toolkit_param_hook"
STUDIO_TOOL_CALL_GUARDRAILS = "studio_tool_call_guardrails"
EXCLUDE_TOOLS_KEY = "exclude_tools"
FEATURES = frozenset({"toolkit_param_hook", "tool_call_guardrails"})

ToolkitParamHook = Callable[[str, dict[str, Any], "ToolingSubject"], Mapping[str, Any]]

__all__ = [
    "EXCLUDE_TOOLS_KEY",
    "FEATURES",
    "STUDIO_TOOLKIT_PARAM_HOOK",
    "STUDIO_TOOL_CALL_GUARDRAILS",
    "ToolParamRefused",
    "ToolkitParamHook",
    "apply_exclude_tools",
    "bind_host_tool_call_guardrails",
    "bind_tenant_allow_list_guardrail",
    "check_toolkit_params",
    "host_tool_call_pipeline",
    "run_toolkit_param_hook",
    "split_exclude_tools",
]


def _refuse(slug: str, params: list[str] | None = None) -> ToolParamRefused:
    return ToolParamRefused(params or [], item=slug)


def _copy_plain(value: Any) -> Any:
    """``value`` with every nested dict / list / set / tuple copied; any other object (a store, a client) is shared.

    The hook may mutate what it is given: copying the containers keeps that away from the caller's spec, while a
    server-managed object in the params (``artifact_store``) must never be copied.
    """
    if isinstance(value, dict):
        return {key: _copy_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_plain(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_plain(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return type(value)(_copy_plain(item) for item in value)
    return value


def run_toolkit_param_hook(
    hook: ToolkitParamHook, slug: str, params: Mapping[str, Any], subject: "ToolingSubject"
) -> dict[str, Any]:
    """The final parameters of ``slug`` after ``hook`` (a new dict); raises :class:`ToolParamRefused`.

    The hook gets a copy, so mutating it never reaches the caller's dict. Fails closed on any other exception, an
    awaitable and a non-mapping result.
    """
    try:
        result = hook(slug, _copy_plain(dict(params)), subject)
    except ToolParamRefused as exc:
        if not exc.item:
            exc.item = slug
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("toolkit param hook failed for %r; refusing (fail closed)", slug)
        raise _refuse(slug) from exc
    if inspect.isawaitable(result):
        getattr(result, "close", lambda: None)()
        logger.error("toolkit param hook for %r is asynchronous; refusing (it must be synchronous)", slug)
        raise _refuse(slug)
    if not isinstance(result, Mapping):
        logger.error("toolkit param hook for %r returned %s, expected a mapping; refusing", slug, type(result).__name__)
        raise _refuse(slug)
    final = dict(result)
    exclude = final.get(EXCLUDE_TOOLS_KEY)
    if exclude is not None and (
        isinstance(exclude, (str, bytes)) or not all(isinstance(name, str) for name in _as_iterable(exclude))
    ):
        logger.error("toolkit param hook for %r returned a malformed exclude_tools; refusing", slug)
        raise _refuse(slug, [EXCLUDE_TOOLS_KEY])
    return final


def _as_iterable(value: Any) -> list[Any]:
    try:
        return list(value)
    except TypeError:
        return [object()]


def split_exclude_tools(params: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """``(params without exclude_tools, the forced exclusions)``."""
    rest = dict(params)
    return rest, tuple(rest.pop(EXCLUDE_TOOLS_KEY, None) or ())


def apply_exclude_tools(instance: Any, exclude: tuple[str, ...]) -> None:
    """Hide ``exclude`` methods of a constructed toolkit (instance-level; the class's own exclusions are kept)."""
    if not exclude:
        return
    current = tuple(getattr(instance, EXCLUDE_TOOLS_KEY, ()) or ())
    instance.exclude_tools = tuple(dict.fromkeys((*current, *exclude)))


def check_toolkit_params(
    app: Mapping[str, Any], tooling: "NormalizedTooling", *, subject: "ToolingSubject"
) -> None:
    """Write-time dry run: the host hook sees every toolkit spec's parameters and may refuse them.

    A no-op without a registered hook. The hook's result is discarded here (forced values are applied when the
    toolkit is constructed); only a refusal matters. Raises :class:`ToolParamRefused` (a ``TenantToolingRefused``).
    """
    hook = app.get(STUDIO_TOOLKIT_PARAM_HOOK)
    if hook is None:
        return
    for spec in tooling.toolkits:
        if spec.slug.lower() in subject.held:  # stored and unchanged: the build re-checks it; an unrelated edit stays possible
            continue
        run_toolkit_param_hook(hook, spec.slug, spec.params, subject)


# -- TOOL_CALL guardrails (PA-10) ----------------------------------------------------------------------------------


def _host_guardrail(inner: Any, studio: Mapping[str, Any]) -> Any:
    """``inner`` wrapped for one Studio bot: bot context in ``ctx.extras["studio"]``, fail-closed on any error."""
    from parrot.bots.guardrails.base import Guardrail, GuardrailContext, GuardrailResult, GuardrailStage

    class _HostToolCallGuardrail(Guardrail):
        stages = {GuardrailStage.TOOL_CALL}
        on_error = "fail_closed"

        def __init__(self) -> None:
            self.name = str(getattr(inner, "name", None) or type(inner).__name__)
            self.priority = int(getattr(inner, "priority", 0) or 0)

        async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
            scoped = ctx.model_copy(update={"extras": {**ctx.extras, "studio": dict(studio)}})
            result = inner.check(content, scoped)
            if inspect.isawaitable(result):
                result = await result
            return result

    return _HostToolCallGuardrail()


def bind_host_tool_call_guardrails(pipeline: Any, guardrails: Any, studio: Mapping[str, Any]) -> int:
    """Register the host's guardrails on ``pipeline`` (a bot's TOOL_CALL pipeline) for the bot described by
    ``studio``; returns how many were registered. An object without a ``check`` method is a configuration error."""
    count = 0
    for guardrail in guardrails or ():
        if not callable(getattr(guardrail, "check", None)):
            raise TypeError(f"{type(guardrail).__name__} is not a guardrail: it has no check(content, ctx)")
        pipeline.add(_host_guardrail(guardrail, studio))
        count += 1
    return count


def host_tool_call_pipeline(guardrails: Any, studio: Mapping[str, Any]) -> Any:
    """A stand-alone TOOL_CALL pipeline of the host's guardrails (for tool calls made outside a bot)."""
    from parrot.bots.guardrails.pipeline import GuardrailPipeline

    pipeline = GuardrailPipeline()
    bind_host_tool_call_guardrails(pipeline, guardrails, studio)
    return pipeline


# -- per-tenant allow-lists at CALL time (PA-5, review fix 7) --------------------------------------------------------------


def _governed_entry(tool_manager: Any, tool_name: str) -> Any:
    """The resolver entry the registered tool ``tool_name`` was built from, or ``None`` (MCP / ad-hoc tools)."""
    from parrot.tools.manager import get_toolkit_owner
    from parrot.tools.resolver import get_toolkit_resolver

    resolver = get_toolkit_resolver()
    tool = tool_manager.get_tool(tool_name)
    if tool is not None:
        cls = type(get_toolkit_owner(tool) or tool)
        entry = resolver.entry(cls.__name__)
        if entry is not None and resolver.resolve(entry.slug) is cls:
            return entry
    return resolver.entry(tool_name)


def bind_tenant_allow_list_guardrail(pipeline: Any, policy: Any, tenant: str | None, tool_manager: Any) -> bool:
    """Enforce the host's per-tenant allow-lists (``tenant_builtin_tools`` / ``tenant_toolkits``) when a tool is CALLED.

    The lists are write-time checks (an unchanged stored tool is exempt so an unrelated edit stays possible and a
    stored agent still builds), so shrinking a tenant's list would otherwise leave every stored agent running the
    removed tool. This guardrail closes that: a call to a built-in / host toolkit the tenant no longer has is BLOCKED
    (``builtin_not_permitted`` / ``toolkit_unavailable``). Nothing is registered (returns ``False``) when there is no
    tenant or the policy has neither callback, so hosts that do not use the lists see no change.
    """
    if not tenant or policy is None or (
        getattr(policy, "tenant_builtin_tools", None) is None and getattr(policy, "tenant_toolkits", None) is None
    ):
        return False
    from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailContext, GuardrailResult, GuardrailStage

    class _TenantAllowList(Guardrail):
        name = "tenant-allow-list"
        stages = {GuardrailStage.TOOL_CALL}
        priority = -100
        on_error = "fail_closed"

        async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
            entry = _governed_entry(tool_manager, ctx.tool_name or "")
            if entry is None:
                return GuardrailResult(action=GuardrailAction.PASS)
            if entry.is_host:
                enabled, code = policy.enabled_toolkits(tenant), "toolkit_unavailable"
            else:
                enabled, code = policy.enabled_builtin_tools(tenant), "builtin_not_permitted"
            if enabled is not None and entry.slug.lower() not in enabled:
                return GuardrailResult(
                    action=GuardrailAction.BLOCK, reason=f"{code}: '{entry.slug}' is not enabled for this tenant"
                )
            return GuardrailResult(action=GuardrailAction.PASS)

    pipeline.add(_TenantAllowList())
    return True
