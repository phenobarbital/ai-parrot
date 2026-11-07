"""CLI coverage for the ontology vocabulary store (FEAT-824 TASK-5267)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from click.testing import CliRunner, Result

from parrot.cli import cli
from parrot.conf import default_dsn


def test_cli_commands_registered() -> None:
    """The lazy ontology group exposes all seven task commands."""
    result = CliRunner().invoke(cli, ["ontology", "--help"])

    assert result.exit_code == 0, result.output
    for command in ("init-schema", "register", "publish", "version", "export", "snapshot", "publish-catalog"):
        assert command in result.output


def test_top_level_help_keeps_ontology_drivers_lazy() -> None:
    """Rendering the ontology lazy entry does not import asyncpg or rdflib."""
    script = (
        "from click.testing import CliRunner\n"
        "from parrot.cli import cli\n"
        "import sys\n"
        "cli._lazy_commands = {'ontology': 'parrot.knowledge.ontology.vocabulary.cli'}\n"
        "cli._lazy_extras = {}\n"
        "result = CliRunner().invoke(cli, ['--help'])\n"
        "print('MARKER', result.exit_code, 'asyncpg' in sys.modules, 'rdflib' in sys.modules)\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)

    completed = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True, env=env)

    marker = next(line for line in completed.stdout.splitlines() if line.startswith("MARKER "))
    assert marker == "MARKER 0 False False"


def test_missing_ontology_module_uses_extra_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing lazy target reports the ontology-store installation hint."""
    import parrot.cli as cli_module

    real_import = cli_module.importlib.import_module
    module_path = "parrot.knowledge.ontology.vocabulary.cli"

    def missing_target(name: str) -> ModuleType:
        if name == module_path:
            raise ModuleNotFoundError(name=name)
        return real_import(name)

    monkeypatch.setattr(cli_module.importlib, "import_module", missing_target)
    result = CliRunner().invoke(cli, ["ontology"])

    assert result.exit_code == 1
    assert "ai-parrot[ontology-store]: pip install ai-parrot[ontology-store]" in result.output


def test_snapshot_from_turtle_offline(
    tmp_path: Path,
    golden_v1: bytes,
    golden_base_iri: str,
) -> None:
    """Offline Turtle input builds v1.sqlite without resolving a database DSN."""
    turtle_file = tmp_path / "legal.ttl"
    destination = tmp_path / "snapshots"
    turtle_file.write_bytes(golden_v1)

    result = CliRunner().invoke(
        cli,
        [
            "ontology",
            "snapshot",
            "legal_es",
            "--from-turtle",
            str(turtle_file),
            "--base-iri",
            golden_base_iri,
            "--dest",
            str(destination),
        ],
        env={"ONTOLOGY_PG_DSN": ""},
    )

    assert result.exit_code == 0, result.output
    assert destination.joinpath("legal_es", "v1.sqlite").is_file()


@pytest.mark.asyncio
async def test_publish_and_version(
    pg_pool: Any,
    pg_schema_name: str,
    tmp_path: Path,
    golden_v1: bytes,
    golden_base_iri: str,
) -> None:
    """The CLI initializes, registers, publishes, and reads version one."""
    dsn = os.environ.get("ONTOLOGY_PG_DSN") or default_dsn
    if dsn is None:
        pytest.skip("needs live Postgres (ONTOLOGY_PG_DSN or parrot.conf.default_dsn)")
    turtle_file = tmp_path / "legal.ttl"
    turtle_file.write_bytes(golden_v1)
    runner = CliRunner()

    async def invoke(arguments: list[str]) -> Result:
        return await asyncio.to_thread(runner.invoke, cli, arguments)

    common = ["--dsn", dsn, "--schema", pg_schema_name]
    initialized = await invoke(["ontology", "init-schema", *common])
    registered = await invoke(
        ["ontology", "register", "legal_es", "--base-iri", golden_base_iri, *common]
    )
    published = await invoke(["ontology", "publish", "legal_es", str(turtle_file), *common])
    current = await invoke(["ontology", "version", "legal_es", *common])

    assert initialized.exit_code == 0, initialized.output
    assert registered.exit_code == 0, registered.output
    assert published.exit_code == 0, published.output
    assert "version=1" in published.output and "changed=true" in published.output
    assert current.exit_code == 0, current.output
    assert current.output.strip() == "1"
