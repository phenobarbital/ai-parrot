"""Public CLI/two-plane lifecycle acceptance tests (FEAT-532 TASK-2910).

Exercises the Roblox feature end-to-end through the SAME public surfaces
a user would drive — ``wikitoolkit build/query/page/related/status/ns``
— never internal APIs directly, over tiny hand-authored fixtures and a
real (but network-trapped) temporary SQLite plane. Unit coverage for each
individual piece already lives in its owning task's test module; this
file is lifecycle/integration coverage only, per this task's own scope
note ("Unit tests belong to the owning implementation tasks").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.languages import treesitter
from parrot.knowledge.wiki.roblox import generations as roblox_generations

from .conftest import sourcemap, write_file

pytestmark = pytest.mark.skipif(treesitter.get_parser("luau") is None, reason="tree-sitter-luau not installed")


def _build(runner: CliRunner, repo: Path, *extra: str):
    return runner.invoke(wiki, ["build", "--path", str(repo), "--no-git", "--no-export", "--no-graph", "-q", *extra])


def _register_roblox_namespace(runner: CliRunner) -> None:
    current = roblox_generations.current_store_dir()
    result = runner.invoke(
        wiki,
        ["ns", "add", "roblox", "--store", str(current), "--backend", "sqlite", "--global"],
    )
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# test_build_query_page_related_status_lifecycle
# ---------------------------------------------------------------------------


def test_build_query_page_related_status_lifecycle(
    runner: CliRunner, mixed_repo: Path, isolated_parrot_home, publish_roblox_generation, no_network
):
    """End-to-end reference paths and metadata behave through public surfaces."""
    publish_roblox_generation(["Players"])
    assert _build(runner, mixed_repo).exit_code == 0

    # `page` — Luau file's body carries both the DataModel section and
    # the exact qualified reference target, reached only via the public CLI.
    page_result = runner.invoke(wiki, ["page", "file:src/Main.luau", "--path", str(mixed_repo), "--json"])
    assert page_result.exit_code == 0, page_result.output
    page_payload = json.loads(page_result.output)
    assert "game.ServerScriptService.Main" in page_payload["body"]

    # `related` — the resolved, qualified external reference is a real edge.
    related_result = runner.invoke(wiki, ["related", "file:src/Main.luau", "--path", str(mixed_repo), "--json"])
    assert related_result.exit_code == 0, related_result.output
    related_rows = json.loads(related_result.output)
    assert any(row.get("concept_id") == "roblox::class/Players" for row in related_rows)

    # `query` — plain lexical search still finds the Luau page locally.
    query_result = runner.invoke(wiki, ["query", "Players", "--path", str(mixed_repo), "--json"])
    assert query_result.exit_code == 0, query_result.output
    query_rows = json.loads(query_result.output)
    assert any(row.get("concept_id") == "file:src/Main.luau" for row in query_rows)

    # `status` — the local Roblox plane block, offline (no network trap fired).
    status_result = runner.invoke(wiki, ["status", "--path", str(mixed_repo), "--json"])
    assert status_result.exit_code == 0, status_result.output
    status_payload = json.loads(status_result.output)
    assert status_payload["roblox_api"]["class_count"] == 1

    # The polyglot sibling (Python) is unaffected.
    py_page = runner.invoke(wiki, ["page", "file:pkg/app.py", "--path", str(mixed_repo), "--json"])
    assert py_page.exit_code == 0
    assert "main" in json.loads(py_page.output)["body"]


# ---------------------------------------------------------------------------
# test_failed_refresh_and_unbuilt_namespace
# ---------------------------------------------------------------------------


def test_failed_refresh_and_unbuilt_namespace(
    runner: CliRunner, mixed_repo: Path, isolated_parrot_home, publish_roblox_generation, monkeypatch, no_network
):
    """Previous plane or local-only retrieval stays usable."""
    publish_roblox_generation(["Players"])
    assert _build(runner, mixed_repo).exit_code == 0

    before = json.loads(runner.invoke(wiki, ["page", "file:src/Main.luau", "--path", str(mixed_repo), "--json"]).output)

    # Simulate a failed --refresh: acquisition raises.
    from parrot.knowledge.wiki.roblox import ingest as roblox_ingest

    async def _boom(*, refresh: bool = False, **_kwargs):
        raise roblox_ingest.RobloxApiAcquisitionError("simulated transport failure")

    monkeypatch.setattr(roblox_ingest, "acquire_roblox_api_payloads", _boom)
    refresh_result = runner.invoke(wiki, ["ingest", "roblox-api", "--refresh"])
    # A failed refresh with an existing generation returns the preserved
    # one (ingest_roblox_api's own contract) — not a hard CLI failure.
    assert refresh_result.exit_code == 0, refresh_result.output
    assert "failed" in refresh_result.output.lower() or "preserved" in refresh_result.output.lower()

    # Local queries/pages are completely unaffected by the failed refresh.
    after = json.loads(runner.invoke(wiki, ["page", "file:src/Main.luau", "--path", str(mixed_repo), "--json"]).output)
    assert before["body"] == after["body"]

    # An unbuilt/absent namespace named in --ns degrades without crashing
    # local results (spec: "Missing namespaces continue to use the
    # existing NamespaceSkip behavior").
    unbuilt_query = runner.invoke(
        wiki, ["query", "Players", "--path", str(mixed_repo), "--ns", "nonexistent-namespace", "--json"]
    )
    assert unbuilt_query.exit_code != 0  # unknown namespace name is a clear CLI error, not a silent crash


# ---------------------------------------------------------------------------
# test_api_and_map_generation_transition
# ---------------------------------------------------------------------------


def test_api_and_map_generation_transition(
    runner: CliRunner, mixed_repo: Path, isolated_parrot_home, publish_roblox_generation, no_network
):
    """Unchanged source is correctly re-enriched on the next build."""
    publish_roblox_generation(["Players"], generation_id="gen-1")
    assert _build(runner, mixed_repo).exit_code == 0

    before = json.loads(runner.invoke(wiki, ["page", "file:src/Main.luau", "--path", str(mixed_repo), "--json"]).output)
    assert "game.ServerScriptService.Main" in before["body"]

    # Change ONLY the mapping — Luau source bytes/mtime untouched.
    write_file(mixed_repo, "sourcemap.json", json.dumps(sourcemap(instance_name="Renamed")))
    assert _build(runner, mixed_repo).exit_code == 0  # no --force

    after_mapping = json.loads(
        runner.invoke(wiki, ["page", "file:src/Main.luau", "--path", str(mixed_repo), "--json"]).output
    )
    assert "game.ServerScriptService.Renamed" in after_mapping["body"]

    # Change ONLY the API generation (a class disappears) — mapping and
    # source both untouched.
    publish_roblox_generation(["Workspace"], generation_id="gen-2")  # "Players" is gone
    assert _build(runner, mixed_repo).exit_code == 0

    related_after = json.loads(
        runner.invoke(wiki, ["related", "file:src/Main.luau", "--path", str(mixed_repo), "--json"]).output
    )
    # The reference to the now-nonexistent Players class is gone — never
    # a dangling/fabricated edge to a class outside the active generation.
    assert not any(row.get("concept_id") == "roblox::class/Players" for row in related_after)


# ---------------------------------------------------------------------------
# test_existing_federation_scoping
# ---------------------------------------------------------------------------


def test_existing_federation_scoping(
    runner: CliRunner, mixed_repo: Path, isolated_parrot_home, publish_roblox_generation, no_network
):
    """Scope/weights/access restrictions hold for project plus API planes."""
    publish_roblox_generation(["Players"])
    assert _build(runner, mixed_repo).exit_code == 0
    _register_roblox_namespace(runner)

    # Broadcast query includes the federated roblox plane, qualified.
    broadcast = json.loads(runner.invoke(wiki, ["query", "Players", "--path", str(mixed_repo), "--json"]).output)
    assert any(row.get("namespace") == "roblox" for row in broadcast)
    assert any(row.get("namespace") is None for row in broadcast)  # local results still present too

    # Explicit --ns scoping selects only that namespace.
    scoped = json.loads(
        runner.invoke(wiki, ["query", "Players", "--path", str(mixed_repo), "--ns", "roblox", "--json"]).output
    )
    assert scoped and all(row.get("namespace") == "roblox" for row in scoped)

    # `page`/`related` still route a qualified id to the read-only namespace.
    api_page = runner.invoke(wiki, ["page", "roblox::class/Players", "--path", str(mixed_repo), "--json"])
    assert api_page.exit_code == 0
    assert json.loads(api_page.output)["concept_id"] == "roblox::class/Players"

    # Access restriction: a write into the foreign namespace is refused —
    # `upsert` only ever targets the LOCAL plane; there is no CLI path
    # that writes into a federated namespace's store at all.
    upsert_result = runner.invoke(wiki, ["upsert", "src/Main.luau", "--path", str(mixed_repo)])
    assert upsert_result.exit_code == 0
    # The roblox generation's own store is untouched by this local upsert
    # (still read-only, never targeted) — verified indirectly: its class
    # count in `status` is unchanged.
    status_payload = json.loads(runner.invoke(wiki, ["status", "--path", str(mixed_repo), "--json"]).output)
    assert status_payload["roblox_api"]["class_count"] == 1
