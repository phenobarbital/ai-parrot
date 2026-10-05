"""Remote-mode plumbing for the wikitoolkit CLI (FEAT-569)."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import click

from parrot.knowledge.wiki.project import WikiEffectiveConfig, WikiRemoteConfig, resolve_remote
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError


class RemoteCliError(click.ClickException):
    """A remote failure surfaced to the shell with exit code 2."""

    exit_code = 2


def remote_or_none(path_: str | None) -> tuple[Path, WikiEffectiveConfig, WikiRemoteConfig | None]:
    """Resolve the repository configuration without opening a wiki store."""
    from parrot.knowledge.wiki.cli import _resolve_project_effective

    root, effective = _resolve_project_effective(path_)
    return root, effective, resolve_remote(effective.config)


def remote_client(remote: WikiRemoteConfig, *, by: str | None = None) -> RemoteWikiClient:
    """Build a remote client with the configured or locally derived actor."""
    from parrot.knowledge.wiki.cli import _authoring_identity

    try:
        return RemoteWikiClient(remote, actor=remote.actor or _authoring_identity(by))
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


async def _call(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None,
    text: bool,
) -> Any:
    client = remote_client(remote, by=by)
    try:
        async with client:
            if text:
                return await client.call_tool_text(tool, arguments)
            return await client.call_tool(tool, arguments)
    except RemoteWikiError as exc:
        raise RemoteCliError(str(exc)) from exc


def call_remote_text(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None = None,
) -> str:
    """Call a remote MCP tool and return its rendered text content."""
    from parrot.knowledge.wiki.cli import _run

    return _run(_call(remote, tool, arguments, by=by, text=True))


def call_remote(
    remote: WikiRemoteConfig,
    tool: str,
    arguments: dict[str, Any],
    *,
    by: str | None = None,
) -> dict[str, Any]:
    """Call a remote MCP tool and return its raw result envelope."""
    from parrot.knowledge.wiki.cli import _run

    return _run(_call(remote, tool, arguments, by=by, text=False))


def refuse_remote(command: str, hint: str = "") -> NoReturn:
    """Reject a local-only command while remote mode is active."""
    extra = f" — {hint}" if hint else ""
    raise click.UsageError(f"`wikitoolkit {command}` is not available in remote mode{extra}")


def remote_aware(
    *,
    proxied: bool,
    tool: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Resolve remote mode before a command body and refuse unsupported commands.

    The optional tool name is retained as command metadata for callers that
    need it; command implementations pass explicit arguments to the helpers.
    """

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = click.get_current_context()
            ctx.ensure_object(dict)
            _root, _effective, remote = remote_or_none(kwargs.get("path_"))
            ctx.obj["remote"] = remote
            if remote is None:
                return func(*args, **kwargs)
            if kwargs.get("store_opt") or kwargs.get("backend_opt"):
                raise click.UsageError("--store/--backend cannot be combined with remote mode (remote is configured)")
            if not proxied:
                command = ctx.command_path.removeprefix("wiki ")
                refuse_remote(command)
            return func(*args, **kwargs)

        wrapper.__remote_tool__ = tool  # type: ignore[attr-defined]
        return wrapper

    return deco
