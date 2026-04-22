"""YAML override loader for ``StoreRouterConfig`` (FEAT-111 Module 2).

Merges hardcoded Pydantic defaults with per-agent YAML overrides using
the same precedence semantics as ``IntentRouterConfig.custom_keywords``.

Usage::

    from parrot.registry.routing import load_store_router_config

    cfg = load_store_router_config("/path/to/router.yaml")
    cfg = load_store_router_config({"top_n": 3, "margin_threshold": 0.20})
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from parrot.registry.routing.models import StoreRouterConfig

_logger = logging.getLogger(__name__)

_PathLike = Union[str, Path]


def load_store_router_config(
    path_or_dict: Union[_PathLike, dict],
) -> StoreRouterConfig:
    """Load a ``StoreRouterConfig`` from a YAML file or a pre-parsed dict.

    Scalar fields present in the source override the Pydantic model defaults.
    ``custom_rules`` from the source are appended to (not replacing) any rules
    already present in the defaults — following the precedence pattern of
    ``IntentRouterConfig.custom_keywords``.

    On any error (missing file, malformed YAML, Pydantic validation failure)
    the function logs the problem and returns ``StoreRouterConfig()`` (all
    defaults).  It **never** raises.

    Args:
        path_or_dict: Either a filesystem path (``str`` or :class:`pathlib.Path`)
            pointing to a YAML file, or a pre-parsed ``dict`` containing
            override values.

    Returns:
        A fully-validated ``StoreRouterConfig``.
    """
    raw: dict

    if isinstance(path_or_dict, dict):
        raw = path_or_dict
    else:
        path = Path(path_or_dict)
        if not path.exists():
            _logger.warning(
                "StoreRouter YAML config not found: %s — using defaults", path
            )
            return StoreRouterConfig()

        try:
            with path.open("r", encoding="utf-8") as fh:
                content = fh.read()
            loaded = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            _logger.error(
                "Malformed YAML in StoreRouter config %s: %s — using defaults",
                path,
                exc,
            )
            return StoreRouterConfig()
        except OSError as exc:
            _logger.error(
                "Cannot read StoreRouter config %s: %s — using defaults", path, exc
            )
            return StoreRouterConfig()

        if not isinstance(loaded, dict):
            _logger.error(
                "StoreRouter config %s did not produce a mapping — using defaults",
                path,
            )
            return StoreRouterConfig()

        raw = loaded

    try:
        return StoreRouterConfig.model_validate(raw)
    except ValidationError as exc:
        _logger.error(
            "StoreRouter config validation failed: %s — using defaults", exc
        )
        return StoreRouterConfig()
