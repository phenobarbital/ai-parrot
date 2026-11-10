"""Declare and discover platform-neutral queued commands."""

import logging
import math
import re
from typing import Any, Callable, List, Optional, Sequence

from .models import ParseMode, QueuedCommand, QueuedCommandSpec

LOGGER = logging.getLogger(__name__)
COMMAND_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")


def queued_command(
    command: str,
    description: str = "",
    parse_mode: ParseMode = "raw",
    *,
    aliases: Sequence[str] = (),
    prepare: Optional[str] = None,
    max_runtime: float = 1800.0,
    max_queue_wait: float = 1800.0,
    max_concurrent: int = 2,
    concurrency_group: Optional[str] = None,
) -> Callable:
    """Attach validated queued-command metadata and return the original function.

    Args:
        command: Canonical routing name.
        description: User-facing command description.
        parse_mode: Argument parsing strategy.
        aliases: Additional routing names, which may contain hyphens.
        prepare: Optional preparation-hook method name.
        max_runtime: Maximum execution time in seconds.
        max_queue_wait: Maximum queue wait in seconds.
        max_concurrent: Maximum concurrent executions for the command or group.
        concurrency_group: Optional shared concurrency group.

    Returns:
        A decorator that returns its input function unchanged.

    Raises:
        ValueError: If the canonical name or execution limits are invalid.
    """

    if COMMAND_PATTERN.fullmatch(command) is None:
        raise ValueError("command must match ^[a-z0-9_]{1,32}$")
    if isinstance(max_runtime, bool) or not isinstance(max_runtime, (int, float)) or not math.isfinite(max_runtime):
        raise ValueError("max_runtime must be a positive finite number")
    if max_runtime <= 0:
        raise ValueError("max_runtime must be a positive finite number")
    if (
        isinstance(max_queue_wait, bool)
        or not isinstance(max_queue_wait, (int, float))
        or not math.isfinite(max_queue_wait)
        or max_queue_wait <= 0
    ):
        raise ValueError("max_queue_wait must be a positive finite number")
    if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or max_concurrent < 1:
        raise ValueError("max_concurrent must be a positive integer")

    spec = QueuedCommandSpec(
        command=command,
        description=description,
        parse_mode=parse_mode,
        aliases=tuple(aliases),
        prepare=prepare,
        max_runtime=float(max_runtime),
        max_queue_wait=float(max_queue_wait),
        max_concurrent=max_concurrent,
        concurrency_group=concurrency_group,
    )

    def decorator(fn: Callable) -> Callable:
        fn._queued_command = spec
        return fn

    return decorator


def discover_queued_commands(agent: Any) -> List[QueuedCommand]:
    """Discover public bound methods and skip commands with invalid hooks."""

    commands: List[QueuedCommand] = []
    seen: set[str] = set()

    for attr_name in dir(agent):
        if attr_name.startswith("_"):
            continue
        method = getattr(agent, attr_name, None)
        if method is None or not callable(method):
            continue
        spec = queued_spec_of(method)
        if not isinstance(spec, QueuedCommandSpec) or spec.command in seen:
            continue

        prepare_method: Optional[Callable[..., Any]] = None
        if spec.prepare is not None:
            candidate = getattr(agent, spec.prepare, None)
            if not callable(candidate):
                LOGGER.error(
                    "Skipping queued command %s: prepare hook %s is missing or not callable",
                    spec.command,
                    spec.prepare,
                )
                continue
            prepare_method = candidate

        seen.add(spec.command)
        commands.append(
            QueuedCommand(
                spec=spec,
                method_name=attr_name,
                method=method,
                prepare=prepare_method,
            )
        )

    return commands


def queued_spec_of(method: Any) -> Optional[QueuedCommandSpec]:
    """Read queued-command metadata from bound or plain methods."""

    return getattr(method, "_queued_command", None)
