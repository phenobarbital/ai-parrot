"""Decorator for declaring agent methods as Telegram bot commands."""
from typing import Any, Callable, Dict, List, Optional


def telegram_command(
    command: str,
    description: str = "",
    parse_mode: str = "keyword",
) -> Callable:
    """Mark an agent method as a Telegram slash command.

    The decorator stores metadata on the function via `_telegram_command`.
    Registration with aiogram happens at bot startup (not at decoration time).

    Args:
        command: Command name without leading slash (e.g. "question").
        description: One-line description shown in the Telegram menu.
        parse_mode: How to parse user input after the command.
            - "keyword": `/cmd key=val key2=val2` → method(**kwargs)
            - "positional": `/cmd arg1 arg2` → method(*args)
            - "raw": `/cmd <everything>` → method(text)
    """
    def decorator(fn: Callable) -> Callable:
        fn._telegram_command = {
            "command": command,
            "description": description or fn.__doc__ or f"Calls {fn.__name__}()",
            "parse_mode": parse_mode,
        }
        return fn
    return decorator


def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]:
    """Scan an agent instance for methods decorated with @telegram_command.

    Returns a list of dicts, each containing:
        - command: str (e.g. "question")
        - description: str
        - parse_mode: str
        - method_name: str (the actual method name on the agent)
        - method: bound method reference
    """
    commands: List[Dict[str, Any]] = []
    seen: set = set()

    for attr_name in dir(agent):
        if attr_name.startswith("_"):
            continue
        attr: Optional[Callable] = getattr(agent, attr_name, None)
        if attr is None or not callable(attr):
            continue
        meta = getattr(attr, "_telegram_command", None)
        if meta is None:
            continue
        cmd_name = meta["command"]
        if cmd_name in seen:
            continue
        seen.add(cmd_name)
        commands.append({
            **meta,
            "method_name": attr_name,
            "method": attr,
        })
    return commands
