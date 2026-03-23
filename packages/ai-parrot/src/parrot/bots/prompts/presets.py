"""Preset registry for common PromptBuilder configurations.

Provides named factory functions so YAML agent definitions and BotManager
can reference prompt stacks by name (e.g., "default", "voice", "agent").

See spec: sdd/specs/composable-prompt-layer.spec.md (Section 3.4)
"""
from __future__ import annotations

from typing import Dict, Callable

from .builder import PromptBuilder


_PRESETS: Dict[str, Callable[[], PromptBuilder]] = {
    "default": PromptBuilder.default,
    "minimal": PromptBuilder.minimal,
    "voice": PromptBuilder.voice,
    "agent": PromptBuilder.agent,
}


def register_preset(name: str, factory: Callable[[], PromptBuilder]) -> None:
    """Register a named preset.

    Args:
        name: The preset name (e.g., "my-custom-preset").
        factory: A callable that returns a fresh PromptBuilder instance.
    """
    _PRESETS[name] = factory


def get_preset(name: str) -> PromptBuilder:
    """Get a preset by name. Returns a fresh builder each time.

    Args:
        name: The preset name.

    Returns:
        A new PromptBuilder instance from the named factory.

    Raises:
        KeyError: If the preset name is not registered.
    """
    if name not in _PRESETS:
        raise KeyError(
            f"Unknown preset: '{name}'. "
            f"Available: {list(_PRESETS.keys())}"
        )
    return _PRESETS[name]()


def list_presets() -> list[str]:
    """List available preset names.

    Returns:
        List of registered preset names.
    """
    return list(_PRESETS.keys())
