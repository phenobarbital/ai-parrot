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
EXCLUDE_TOOLS_KEY = "exclude_tools"
FEATURES = frozenset({"toolkit_param_hook"})

ToolkitParamHook = Callable[[str, dict[str, Any], "ToolingSubject"], Mapping[str, Any]]

__all__ = [
    "EXCLUDE_TOOLS_KEY",
    "FEATURES",
    "STUDIO_TOOLKIT_PARAM_HOOK",
    "ToolParamRefused",
    "ToolkitParamHook",
    "apply_exclude_tools",
    "check_toolkit_params",
    "run_toolkit_param_hook",
    "split_exclude_tools",
]


def _refuse(slug: str, params: list[str] | None = None) -> ToolParamRefused:
    return ToolParamRefused(params or [], item=slug)


def run_toolkit_param_hook(
    hook: ToolkitParamHook, slug: str, params: Mapping[str, Any], subject: "ToolingSubject"
) -> dict[str, Any]:
    """The final parameters of ``slug`` after ``hook`` (a new dict); raises :class:`ToolParamRefused`.

    The hook gets a copy, so mutating it never reaches the caller's dict. Fails closed on any other exception, an
    awaitable and a non-mapping result.
    """
    try:
        result = hook(slug, dict(params), subject)
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
