"""End-to-end ``adr`` CLI ``--ns`` behaviour against a live foreign namespace (FEAT-675).

Covers the write commands (``sync``/``generate``/``review``) and ``export``
with a real local sqlite plane plus a second built project registered as a
foreign namespace via ``wikitoolkit ns add`` — the scenario issue
6500603d22d4 left untested after FEAT-578's read-path federation fix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki

_ADR = "# {text}\n\n## Context\nSome context.\n\n## Decision\n{text}\n\n## Consequences\nSome consequences.\n"


@dataclass
class _Planes:
    local: Path
    other: Path
    decision_id: str


def _make_project(base: Path, name: str, decision_text: str) -> Path:
    """One-ADR project; both planes share the ADR filename, hence the decision id."""
    root = base / name
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-shared.md").write_text(_ADR.format(text=decision_text), encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "mod.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    return root


def _invoke(runner: CliRunner, *args: str):
    return runner.invoke(wiki, list(args))


def _error_code(result) -> str:
    return json.loads(result.stderr or result.output)["error"]["code"]


def _dossier(runner: CliRunner, root: Path, query: str, ns: str | None = None) -> dict:
    args = ["adr", "why", query, "--json", "--path", str(root)]
    if ns is not None:
        args += ["--ns", ns]
    result = _invoke(runner, *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def planes(tmp_path: Path, runner: CliRunner) -> _Planes:
    """A built local project plus a built foreign project registered as ``other``."""
    other = _make_project(tmp_path, "other", "Use milvus")
    local = _make_project(tmp_path, "local", "Use pgvector")
    for root in (other, local):
        result = _invoke(runner, "build", "--path", str(root), "--no-graph", "--quiet")
        assert result.exit_code == 0, result.output
    result = _invoke(runner, "ns", "add", "other", "--project", str(other), "--path", str(local))
    assert result.exit_code == 0, result.output

    foreign = _dossier(runner, local, "milvus", ns="other")["documented"]
    assert [hit["title"] for hit in foreign] == ["Use milvus"]
    local_hits = _dossier(runner, local, "pgvector")["documented"]
    assert [hit["title"] for hit in local_hits] == ["Use pgvector"]
    # Same ADR filename -> same rel_path-derived id in both planes.
    assert foreign[0]["decision_id"] == local_hits[0]["decision_id"]
    return _Planes(local=local, other=other, decision_id=foreign[0]["decision_id"])


def _write_commands(decision_id: str) -> list[list[str]]:
    return [
        ["sync"],
        ["generate", "src/mod.py"],
        ["review", decision_id, "--action", "accept", "--expected-revision", "1", "--actor", "human:test"],
    ]


class TestForeignNamespaceWrites:
    def test_write_commands_reject_foreign_namespace(self, runner, planes):
        for command in _write_commands(planes.decision_id):
            result = _invoke(runner, "adr", *command, "--ns", "other", "--json", "--path", str(planes.local))
            assert result.exit_code == 2, (command, result.output)
            assert _error_code(result) == "ADR_INVALID_ARGUMENT", command
            assert "local project root" in (result.stderr or result.output)

    def test_rejected_review_leaves_both_planes_untouched(self, runner, planes):
        result = _invoke(
            runner,
            "adr",
            "review",
            planes.decision_id,
            "--action",
            "reject",
            "--expected-revision",
            "1",
            "--actor",
            "human:test",
            "--ns",
            "other",
            "--json",
            "--path",
            str(planes.local),
        )
        assert result.exit_code == 2, result.output

        foreign = _dossier(runner, planes.local, "milvus", ns="other")
        local = _dossier(runner, planes.local, "pgvector")
        for dossier, title in ((foreign, "Use milvus"), (local, "Use pgvector")):
            (hit,) = dossier["documented"]
            assert hit["title"] == title
            assert hit["revision"] == 1
            assert hit["review_status"] == "unreviewed"
        # The foreign project's own view of its plane is unchanged too.
        own = _dossier(runner, planes.other, "milvus")
        assert [(h["revision"], h["review_status"]) for h in own["documented"]] == [(1, "unreviewed")]

    def test_write_commands_reject_unknown_namespace(self, runner, planes):
        for command in _write_commands(planes.decision_id):
            result = _invoke(runner, "adr", *command, "--ns", "nope", "--json", "--path", str(planes.local))
            assert result.exit_code == 2, (command, result.output)
            assert _error_code(result) == "ADR_INVALID_ARGUMENT", command
            assert "Unknown namespace 'nope'" in (result.stderr or result.output)

    def test_write_commands_accept_explicit_local(self, runner, planes):
        result = _invoke(runner, "adr", "sync", "--ns", "local", "--json", "--path", str(planes.local))
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["unchanged"] == 1
        assert payload["diagnostics"] == []

        result = _invoke(
            runner,
            "adr",
            "review",
            planes.decision_id,
            "--action",
            "accept",
            "--expected-revision",
            "1",
            "--actor",
            "human:test",
            "--ns",
            "local",
            "--json",
            "--path",
            str(planes.local),
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["review_status"] == "accepted"
        # The write landed in the local plane only; the foreign one is untouched.
        (foreign_hit,) = _dossier(runner, planes.local, "milvus", ns="other")["documented"]
        assert (foreign_hit["revision"], foreign_hit["review_status"]) == (1, "unreviewed")


class TestExportNamespace:
    def test_export_reads_the_selected_namespace(self, runner, planes):
        foreign = _invoke(runner, "adr", "export", planes.decision_id, "--ns", "other", "--path", str(planes.local))
        assert foreign.exit_code == 0, foreign.output
        assert "Use milvus" in foreign.output
        assert "pgvector" not in foreign.output

        local = _invoke(runner, "adr", "export", planes.decision_id, "--path", str(planes.local))
        assert local.exit_code == 0, local.output
        assert "Use pgvector" in local.output
        assert "milvus" not in local.output

    def test_export_rejects_unknown_namespace(self, runner, planes):
        result = _invoke(runner, "adr", "export", planes.decision_id, "--ns", "nope", "--path", str(planes.local))
        assert result.exit_code == 2, result.output
        assert "ADR_INVALID_ARGUMENT" in (result.stderr or result.output)


class TestSingleNamespaceSelector:
    @pytest.mark.parametrize("selector", ["local,other", "other,local", "other, local"])
    def test_multi_namespace_selector_is_rejected(self, runner, planes, selector):
        commands = [
            ["why", "milvus", "--json"],
            ["lookup", "sym:src/mod.py#run", "--json"],
            ["sync", "--json"],
            *[[*command, "--json"] for command in _write_commands(planes.decision_id)[1:]],
        ]
        for command in commands:
            result = _invoke(runner, "adr", *command, "--ns", selector, "--path", str(planes.local))
            assert result.exit_code == 2, (command, result.output)
            assert _error_code(result) == "ADR_INVALID_ARGUMENT", command
            assert "exactly one namespace" in (result.stderr or result.output)

        export = _invoke(runner, "adr", "export", planes.decision_id, "--ns", selector, "--path", str(planes.local))
        assert export.exit_code == 2, export.output
        assert "exactly one namespace" in (export.stderr or export.output)
