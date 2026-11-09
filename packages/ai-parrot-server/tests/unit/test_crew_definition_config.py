"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from parrot import conf


_SETTING_NAMES = {
    "CREW_DEFINITION_STORAGE",
    "CREW_DEFINITION_PG_DSN",
    "CREW_DEFINITION_MIGRATION",
}


class _FakeConfig:
    """Minimal isolated replacement for the navconfig reader."""

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, fallback: object = None) -> object:
        """Return a configured value or its fallback."""
        return self._values.get(key, fallback)

    def getboolean(self, key: str, fallback: bool = False) -> bool:
        """Return a configured boolean or its fallback."""
        return bool(self._values.get(key, fallback))


def _evaluate_settings(values: dict[str, object], default_dsn: object) -> dict[str, object]:
    """Evaluate only crew-definition declarations against isolated inputs."""
    source_path = Path(conf.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in _SETTING_NAMES
    ]
    assert {node.targets[0].id for node in assignments} == _SETTING_NAMES

    namespace: dict[str, Any] = {"config": _FakeConfig(values), "default_dsn": default_dsn}
    isolated_module = ast.Module(body=assignments, type_ignores=[])
    exec(compile(isolated_module, str(source_path), "exec"), namespace)
    return {name: namespace[name] for name in _SETTING_NAMES}


def test_default_backend_and_migration() -> None:
    """Default to Redis, no migration, and no Postgres DSN when absent."""
    settings = _evaluate_settings({}, default_dsn=None)

    assert settings == {
        "CREW_DEFINITION_STORAGE": "redis",
        "CREW_DEFINITION_PG_DSN": None,
        "CREW_DEFINITION_MIGRATION": False,
    }


@pytest.mark.parametrize("default_dsn", [None, object()])
def test_configured_values_and_dsn_fallback(default_dsn: object) -> None:
    """Prefer an explicit Postgres DSN and otherwise preserve the default."""
    explicit_dsn = object()
    configured = _evaluate_settings(
        {
            "CREW_DEFINITION_STORAGE": "postgres",
            "CREW_DEFINITION_PG_DSN": explicit_dsn,
            "CREW_DEFINITION_MIGRATION": True,
        },
        default_dsn=default_dsn,
    )
    fallback = _evaluate_settings({"CREW_DEFINITION_STORAGE": "postgres"}, default_dsn=default_dsn)

    assert configured["CREW_DEFINITION_STORAGE"] == "postgres"
    assert configured["CREW_DEFINITION_PG_DSN"] is explicit_dsn
    assert configured["CREW_DEFINITION_MIGRATION"] is True
    assert fallback["CREW_DEFINITION_PG_DSN"] is default_dsn
