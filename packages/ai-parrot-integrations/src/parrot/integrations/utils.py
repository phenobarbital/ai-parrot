"""Shared utilities for integration wrappers (Telegram, MS Teams, etc.)."""
import shlex


def parse_kwargs(text: str) -> dict:
    """Parse 'key=val key2="quoted val"' into a kwargs dict.

    Supports quoted values so multi-word strings survive as a single value:
        report="Read this loudly" max_lines=5

    Non key=val tokens become positional: arg0, arg1, etc.

    Args:
        text: The argument string to parse.

    Returns:
        Dict of parsed keyword arguments.
    """
    if not text or not text.strip():
        return {}
    # Strip trailing commas on tokens (e.g. "a=1, b=2") for backward
    # compatibility with the old Telegram parser.
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    parts = [p.rstrip(",") for p in parts if p != ","]
    kwargs: dict = {}
    positional_idx = 0
    for part in parts:
        if "=" in part:
            key, _, val = part.partition("=")
            kwargs[key.strip()] = val.strip()
        else:
            kwargs[f"arg{positional_idx}"] = part
            positional_idx += 1
    return kwargs
