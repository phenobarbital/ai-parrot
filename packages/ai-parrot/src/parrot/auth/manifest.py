"""In-package YAML manifest loader for per-agent credential configuration.

Parses a ``credentials:`` block (inline or from a file) into a list of
:class:`~parrot.auth.credentials.ProviderCredentialConfig` entries, with
env-var substitution for option values.

Expected YAML shape
-------------------
.. code-block:: yaml

    credentials:
      - provider: workiq
        auth: obo
        options:
          scope: api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask

      - provider: jira
        auth: oauth2

      - provider: fireflies
        auth: static_key
        options:
          capture_url: ${FIREFLIES_CAPTURE_URL}
          vault_key: fireflies:api_key

      - provider: myservice
        auth: mcp
        options:
          vault_key: myservice:token
          auth_url: https://myservice.example.com/auth

Environment variable substitution
----------------------------------
Option values of the form ``${VAR_NAME}`` are substituted with the value of
the corresponding environment variable.  ``${VAR_NAME:-default}`` syntax is
also supported (the part after ``:-`` is used when the variable is unset or
empty).  Missing variables (without a default) are silently expanded to an
empty string.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .credentials import ProviderCredentialConfig

__all__ = [
    "load_credentials_manifest",
    "parse_credentials_block",
]

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_credentials_manifest(
    source: Union[str, Path],
    *,
    key: str = "credentials",
) -> List[ProviderCredentialConfig]:
    """Load credential provider configs from a YAML file.

    Args:
        source: Absolute or relative path to the YAML manifest file.
        key: Top-level YAML key that holds the list.  Defaults to
            ``"credentials"``.

    Returns:
        Parsed list of :class:`ProviderCredentialConfig` entries.
        Returns an empty list if the file does not exist or the key is absent.

    Raises:
        ImportError: If PyYAML is not installed.
        ValueError: If the YAML structure under *key* is not a list.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required for the manifest loader: uv add pyyaml"
        ) from exc

    path = Path(source)
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    block = data.get(key, [])
    return parse_credentials_block(block)


def parse_credentials_block(
    block: Optional[List[Dict[str, Any]]],
    *,
    expand_env: bool = True,
) -> List[ProviderCredentialConfig]:
    """Parse a raw ``credentials:`` list (already parsed from YAML) into configs.

    Args:
        block: List of raw dicts (the value of the ``credentials:`` YAML key).
            ``None`` and empty list are accepted and return ``[]``.
        expand_env: When ``True`` (default), expand ``${VAR}`` / ``${VAR:-default}``
            substitutions in option string values.

    Returns:
        Parsed list of :class:`ProviderCredentialConfig`.

    Raises:
        ValueError: If *block* is not a list.
    """
    if not block:
        return []

    if not isinstance(block, list):
        raise ValueError(
            f"parse_credentials_block: expected a list, got {type(block).__name__}"
        )

    configs: List[ProviderCredentialConfig] = []
    for entry in block:
        if not isinstance(entry, dict):
            continue
        provider = entry.get("provider", "")
        auth = entry.get("auth", "")
        raw_options: Dict[str, Any] = entry.get("options") or {}

        if expand_env:
            raw_options = _expand_env_vars(raw_options)

        configs.append(
            ProviderCredentialConfig(
                provider=provider,
                auth=auth,  # type: ignore[arg-type]  # validated by Pydantic
                options=raw_options,
            )
        )

    return configs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _expand_env_vars(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively expand ``${VAR}`` and ``${VAR:-default}`` in string values.

    Args:
        mapping: Dict whose string values may contain env-var references.

    Returns:
        A new dict with substituted string values.  Non-string values and
        nested dicts/lists are traversed recursively.
    """
    result: Dict[str, Any] = {}
    for k, v in mapping.items():
        result[k] = _expand_value(v)
    return result


def _expand_value(value: Any) -> Any:
    """Expand env-var references in *value* (recursively for dicts/lists)."""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(_substitute, value)
    if isinstance(value, dict):
        return {k: _expand_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_value(item) for item in value]
    return value


def _substitute(match: re.Match) -> str:
    """Replace a single ``${VAR}`` or ``${VAR:-default}`` match."""
    spec = match.group(1)
    if ":-" in spec:
        var_name, default = spec.split(":-", 1)
        return os.environ.get(var_name.strip()) or default
    return os.environ.get(spec.strip(), "")
