"""Helper façade for the infographic template and theme registries.

Wraps parrot.models.infographic_templates.infographic_registry and
parrot.models.infographic.theme_registry so SDK consumers don't need
to import registry singletons directly.
"""
from __future__ import annotations

from typing import Dict, List, Union

from parrot.models.infographic import ThemeConfig, theme_registry
from parrot.models.infographic_templates import (
    InfographicTemplate,
    infographic_registry,
)


def list_templates(
    detailed: bool = False,
) -> Union[List[str], List[Dict[str, str]]]:
    """List available infographic template names.

    Args:
        detailed: When True, return list of dicts with name + description.

    Returns:
        Sorted list of names, or sorted list of detailed dicts when
        ``detailed=True``.
    """
    if detailed:
        return infographic_registry.list_templates_detailed()
    return infographic_registry.list_templates()


def get_template(name: str) -> InfographicTemplate:
    """Retrieve a template by name.

    Args:
        name: Template identifier.

    Returns:
        The matching InfographicTemplate instance.

    Raises:
        KeyError: If the template name is not registered.
    """
    return infographic_registry.get(name)


def register_template(
    template: Union[InfographicTemplate, dict],
) -> InfographicTemplate:
    """Register a custom infographic template.

    Accepts either an InfographicTemplate instance or a raw dict that
    will be validated via InfographicTemplate.model_validate. Returns
    the validated template instance.

    Args:
        template: InfographicTemplate instance or a dict conforming to
            the InfographicTemplate schema.

    Returns:
        The registered InfographicTemplate instance.

    Raises:
        TypeError: If ``template`` is neither a dict nor an
            ``InfographicTemplate`` instance.
        pydantic.ValidationError: If the dict payload is malformed.
    """
    if isinstance(template, dict):
        template = InfographicTemplate.model_validate(template)
    elif not isinstance(template, InfographicTemplate):
        raise TypeError(
            "register_template() expects an InfographicTemplate or dict, "
            f"got {type(template).__name__}"
        )
    infographic_registry.register(template)
    return template


def list_themes(
    detailed: bool = False,
) -> Union[List[str], List[Dict[str, str]]]:
    """List available infographic theme names.

    Args:
        detailed: When True, return list of dicts with name and key
            colour tokens (primary, neutral_bg, body_bg).

    Returns:
        Sorted list of names, or sorted list of detailed dicts when
        ``detailed=True``.
    """
    if detailed:
        return theme_registry.list_themes_detailed()
    return theme_registry.list_themes()


def get_theme(name: str) -> ThemeConfig:
    """Retrieve a theme by name.

    Args:
        name: Theme identifier.

    Returns:
        The matching ThemeConfig instance.

    Raises:
        KeyError: If the theme name is not registered.
    """
    return theme_registry.get(name)


def register_theme(
    theme: Union[ThemeConfig, dict],
) -> ThemeConfig:
    """Register a custom infographic theme.

    Accepts either a ThemeConfig instance or a raw dict that will be
    validated via ThemeConfig.model_validate. Returns the validated
    theme instance.

    Args:
        theme: ThemeConfig instance or a dict conforming to the
            ThemeConfig schema.

    Returns:
        The registered ThemeConfig instance.

    Raises:
        TypeError: If ``theme`` is neither a dict nor a ``ThemeConfig``
            instance.
        pydantic.ValidationError: If the dict payload is malformed.
    """
    if isinstance(theme, dict):
        theme = ThemeConfig.model_validate(theme)
    elif not isinstance(theme, ThemeConfig):
        raise TypeError(
            "register_theme() expects a ThemeConfig or dict, "
            f"got {type(theme).__name__}"
        )
    theme_registry.register(theme)
    return theme
