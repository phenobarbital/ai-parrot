"""Tests for the ``wikitoolkit`` / ``parrot wiki`` CLI.

Drives the click commands end-to-end with ``CliRunner`` against temp
repositories — real SQLite plane, no git dependency (``--no-git``),
no LLM.
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki import cli as cli_module
from parrot.knowledge.wiki.cli import _changed_files_from_git, wiki
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.project import (
    config_path,
    load_project_config,
    wiki_write_lock,
)

# Patch through the imported module object rather than a dotted string:
# pkgutil.resolve_name (used by mock.patch and monkeypatch.setattr) walks
# attributes from `sys.modules['parrot']`, and `parrot` is a PEP 420
# namespace package whose submodule attributes are not reliably bound on
# CI — hence "module 'parrot' has no attribute 'bots'" even though the
# submodule imports fine. The module object sidesteps resolution entirely.
#
# `mock.patch`/`monkeypatch.setattr` resolve dotted string targets with
# pkgutil.resolve_name, which only walks attributes — it does NOT import
# submodules. Locally these resolved by accident because something else had
# already imported them; on CI nothing had, so patching died with
# "module ... has no attribute ...". Import them explicitly so the target
# resolves the same way in both environments.
import parrot.knowledge.pageindex.toolkit as _pageindex_toolkit  # noqa: F401

PY_STORE = '"""A tiny key-value store module."""\n\n\nclass Store:\n    """In-memory key-value store."""\n\n    def get(self, key):\n        """Fetch a value."""\n        return key\n'
PY_UTIL = '"""Utility helpers."""\n\n\ndef helper(key):\n    """Return the key unchanged."""\n    return key\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (tmp_path / "pkg" / "util.py").write_text(PY_UTIL, encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n\nA demo project.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, repo: Path, *extra: str):
    result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git", *extra])
    assert result.exit_code == 0, result.output
    return result


def _store_dir(repo: Path) -> Path:
    """The directory the writer lock guards — beside the store, not the root."""
    return load_project_config(repo).storage_path(repo)


class TestBuildLock:
    def test_build_refuses_while_another_writer_holds_the_lock(self, runner, repo):
        with wiki_write_lock(_store_dir(repo)) as held:
            assert held is True
            result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git"])
        assert result.exit_code != 0
        assert "in progress" in result.output.lower()

    def test_build_releases_the_lock_for_the_next_run(self, runner, repo):
        _build(runner, repo)
        _build(runner, repo)


class TestBuild:
    def test_build_creates_plane_and_config(self, runner, repo):
        result = _build(runner, repo)
        assert "built" in result.output
        assert config_path(repo).exists()
        config = load_project_config(repo)
        assert config.wiki_name == repo.name
        assert config.db_path(repo).exists()

    def test_rebuild_is_incremental(self, runner, repo):
        _build(runner, repo)
        result = _build(runner, repo)
        assert "0 ingested" in result.output
        assert "3 unchanged" in result.output

    def test_changed_file_reingested(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text('"""Utility helpers v2."""\n', encoding="utf-8")
        result = _build(runner, repo)
        assert "1 ingested" in result.output

    def test_deleted_file_pruned(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").unlink()
        result = _build(runner, repo)
        assert "removed" in result.output
        page = runner.invoke(wiki, ["page", "file:pkg/util.py", "--path", str(repo)])
        assert page.exit_code != 0

    def test_custom_name_and_backend(self, runner, repo):
        _build(runner, repo, "--name", "kb", "--backend", "memory")
        config = load_project_config(repo)
        assert config.wiki_name == "kb"
        assert config.backend == "memory"
        # FEAT-461: with no ENV/WIKI_ENV set, `build` auto-generates the
        # missing `local` overlay (`{"backend": "sqlite"}` — the no-VPN
        # default), which now outranks the persisted base backend for a
        # bare `query`. An explicit --backend flag still wins over that
        # overlay, so a follow-up read must repeat the same flag to reach
        # the custom "memory" plane just built.
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--backend", "memory"])
        assert result.exit_code == 0, result.output


class TestQuery:
    def test_query_returns_packed_stubs(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["query", "key value store", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "file:pkg/store.py" in result.output
        assert "wikitoolkit page" in result.output  # follow-up hint

    def test_query_json(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            ["query", "utility helpers", "--path", str(repo), "--json"],
        )
        assert result.exit_code == 0
        rows = json.loads(result.output)
        assert any(r["concept_id"] == "file:pkg/util.py" for r in rows)
        assert all(0.0 <= r["score"] <= 1.0 for r in rows)

    def test_query_without_build_fails_with_guidance(self, runner, repo):
        result = runner.invoke(wiki, ["query", "anything", "--path", str(repo)])
        assert result.exit_code != 0
        assert "wikitoolkit build" in result.output

    def test_query_no_results_message(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["query", "zzzqqqxyzzy", "--path", str(repo)])
        assert result.exit_code == 0
        assert "No wiki results" in result.output

    def _store_dir(self, repo: Path) -> str:
        return str(repo / ".parrot" / "wiki")

    def test_query_table_renders_human_output(self, runner, repo):
        # Ported llmwiki capability: --table shows a Rich table.
        _build(runner, repo)
        result = runner.invoke(wiki, ["query", "key value store", "--path", str(repo), "--table"])
        assert result.exit_code == 0, result.output
        assert "LLM Wiki" in result.output
        assert "Score" in result.output and "store.py" in result.output

    def test_query_body_hydrates_top_hit(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            ["query", "key value store", "--path", str(repo), "--body", "--json"],
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert rows and rows[0].get("body"), "top hit body not hydrated"

    def test_query_store_targets_prebuilt_store(self, runner, repo):
        # Ported llmwiki capability: query an arbitrary pre-built store
        # directly (here the project's own plane by absolute --store),
        # without needing .parrot/wiki.json resolution.
        _build(runner, repo)
        result = runner.invoke(wiki, ["query", "utility helpers", "--store", self._store_dir(repo), "--json"])
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert any(r["concept_id"] == "file:pkg/util.py" for r in rows)

    def test_query_store_env_var(self, runner, repo, monkeypatch):
        _build(runner, repo)
        monkeypatch.setenv("WIKI_STORE", self._store_dir(repo))
        result = runner.invoke(wiki, ["query", "store", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)

    def test_explicit_path_beats_wiki_store_env(self, runner, repo, monkeypatch):
        # An ambient WIKI_STORE must NOT redirect a --path-scoped query.
        _build(runner, repo)
        monkeypatch.setenv("WIKI_STORE", str(repo / "somewhere-else"))
        result = runner.invoke(wiki, ["query", "utility helpers", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert any(r["concept_id"] == "file:pkg/util.py" for r in rows)

    def test_query_store_missing_dir_errors(self, runner, repo):
        result = runner.invoke(wiki, ["query", "x", "--store", str(repo / "does-not-exist")])
        assert result.exit_code != 0
        assert "No wiki store directory" in result.output

    def test_query_store_missing_db_errors(self, runner, repo):
        # Directory exists but holds no wiki.db → friendly guidance.
        (repo / "emptystore").mkdir()
        result = runner.invoke(wiki, ["query", "x", "--store", str(repo / "emptystore")])
        assert result.exit_code != 0
        assert "No wiki database" in result.output

    def test_page_and_related_accept_store(self, runner, repo):
        _build(runner, repo)
        sd = self._store_dir(repo)
        page = runner.invoke(wiki, ["page", "file:pkg/store.py", "--store", sd])
        assert page.exit_code == 0, page.output
        rel = runner.invoke(wiki, ["related", "dir:pkg", "--store", sd])
        assert rel.exit_code == 0, rel.output


class TestPageAndRelated:
    def test_page_full_read(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["page", "file:pkg/store.py", "--path", str(repo)])
        assert result.exit_code == 0
        assert "In-memory key-value store" in result.output

    def test_page_max_tokens_truncates(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            [
                "page",
                "file:pkg/store.py",
                "--path",
                str(repo),
                "--max-tokens",
                "5",
            ],
        )
        assert result.exit_code == 0
        assert "truncated" in result.output

    def test_related_shows_contains_edge(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["related", "file:pkg/store.py", "--path", str(repo)])
        assert result.exit_code == 0
        assert "dir:pkg" in result.output
        assert "contains" in result.output


class TestUpsert:
    def test_upsert_explicit_path(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text('"""Utility helpers v2."""\n', encoding="utf-8")
        result = runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "Upserted 1" in result.output
        page = runner.invoke(wiki, ["page", "file:pkg/util.py", "--path", str(repo)])
        assert "v2" in page.output

    def test_upsert_preserves_incoming_edges(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text('"""Utility helpers v3."""\n', encoding="utf-8")
        runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        result = runner.invoke(
            wiki,
            ["related", "file:pkg/util.py", "--path", str(repo), "--json"],
        )
        rows = json.loads(result.output)
        rels = {(r["concept_id"], r["rel"]) for r in rows}
        assert ("dir:pkg", "contains") in rels

    def test_upsert_deleted_file_removes_pages(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").unlink()
        result = runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        assert result.exit_code == 0
        assert "removed 1" in result.output

    def test_upsert_ignores_excluded_dirs(self, runner, repo):
        _build(runner, repo)
        state = repo / ".parrot" / "wiki.json"
        assert state.exists()
        result = runner.invoke(wiki, ["upsert", ".parrot/wiki.json", "--path", str(repo)])
        assert result.exit_code == 0
        assert "No wiki-relevant files" in result.output

    def test_upsert_ignores_a_nested_wiki_bundle(self, runner, repo):
        # Incremental upsert must apply the same guardrail as a full
        # build: a directory that is itself a wiki export is not content.
        _build(runner, repo)
        bundle = repo / "docs" / "legacy_wiki"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "wiki_stats.json").write_text("{}", encoding="utf-8")
        (bundle / "index.md").write_text("# Legacy wiki\n", encoding="utf-8")

        result = runner.invoke(wiki, ["upsert", "docs/legacy_wiki/index.md", "--path", str(repo)])
        assert result.exit_code == 0
        assert "No wiki-relevant files" in result.output

    def test_upsert_skips_while_another_writer_holds_the_lock(self, runner, repo, monkeypatch):
        # The git post-commit hook must never stall behind a build that
        # can run for minutes, nor write the store underneath it.
        monkeypatch.setattr(cli_module, "UPSERT_LOCK_WAIT_SECONDS", 0.1)
        _build(runner, repo)
        with wiki_write_lock(_store_dir(repo)) as held:
            assert held is True
            result = runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        assert result.exit_code == 0
        assert "in progress" in result.output.lower()

    def test_upsert_proceeds_once_the_lock_is_free(self, runner, repo):
        _build(runner, repo)
        with wiki_write_lock(_store_dir(repo)) as held:
            assert held is True
        result = runner.invoke(wiki, ["upsert", "pkg/util.py", "--path", str(repo)])
        assert result.exit_code == 0
        assert "in progress" not in result.output.lower()

    def test_upsert_before_build_is_noop(self, runner, tmp_path):
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        result = runner.invoke(wiki, ["upsert", "a.py", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "not built" in result.output


class TestStatusAndExport:
    def test_status_json(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["status", "--path", str(repo), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["stats"]["pages"] >= 3
        assert payload["stale_sources"] == 0

    def test_export_markdown_bundle(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["export", "--path", str(repo), "-o", "docs/wiki"])
        assert result.exit_code == 0, result.output
        out = repo / "docs" / "wiki"
        assert (out / "index.md").exists()
        assert any(out.rglob("*store.py*"))


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class TestChangedFilesFromGit:
    """The post-commit hook's file-listing helper (merge-safe)."""

    @staticmethod
    def _init_repo(root: Path) -> None:
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@t.t")
        _git(root, "config", "user.name", "t")
        _git(root, "config", "commit.gpgsign", "false")

    def test_first_commit_reports_files(self, tmp_path: Path):
        self._init_repo(tmp_path)
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "init")
        assert _changed_files_from_git(tmp_path) == ["a.py"]

    def test_merge_commit_reports_merged_files(self, tmp_path: Path):
        # A plain `diff-tree HEAD` yields the (empty) combined diff for a
        # merge — the helper must instead report files brought in by the
        # merge relative to the first parent, or the wiki goes stale.
        self._init_repo(tmp_path)
        (tmp_path / "base.py").write_text("x = 1\n", encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "base")
        default_branch = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        _git(tmp_path, "checkout", "-q", "-b", "feature")
        (tmp_path / "feature.py").write_text("y = 2\n", encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "feature")

        _git(tmp_path, "checkout", "-q", default_branch)
        # Force a real merge commit (two parents), not a fast-forward.
        _git(tmp_path, "merge", "--no-ff", "-q", "-m", "merge", "feature")

        changed = _changed_files_from_git(tmp_path)
        assert "feature.py" in changed
        assert changed.count("feature.py") == 1  # deduped across parents


# ---------------------------------------------------------------------------
# Supervised ingestion (FEAT-402, TASK-2075) — `wikitoolkit ingest`
# ---------------------------------------------------------------------------

_CHARTER_YAML = """
version: "1"
scope:
  include:
    - id: decisions
      description: Technical or business decisions with their rationale.
  exclude:
    - id: social
      description: Small talk, purely social content.
weights:
  density: 0.40
  novelty: 0.35
  durability: 0.25
thresholds:
  admit: 0.75
  reject: 0.35
destinations:
  - wiki
  - archive
  - discard
calibration:
  near_fraction: 0.6
  uniform_fraction: 0.4
  min_agreement: 0.9
  on_low_agreement: widen_gray_zone
  gray_zone_step: 0.05
  autotune: propose
examples: []
examples_file: null
amendments: []
"""


class _FakeTriageAdapter:
    """Stub PageIndexLLMAdapter for triage — returns a canned TriageOutput."""

    def __init__(self, density=0.9, novelty=0.9, durability=0.9, sensitive=False):
        from parrot.knowledge.wiki.review import DimensionScores, TriageOutput

        self.output = TriageOutput(
            briefing="A dense, durable document with a clear decision.",
            scores=DimensionScores(density=density, novelty=novelty, durability=durability),
            claims=[],
            sensitive=sensitive,
        )
        self.calls = 0

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        self.calls += 1
        return self.output


class _FakeNoveltyScorer:
    """Stub NoveltyScorer — fixed novelty, no grounding/search dependency."""

    def __init__(self, novelty=0.9, backend="search-proxy"):
        self.novelty = novelty
        self.backend = backend

    async def score(self, claims, text):
        return self.novelty, self.backend


class _FakePageIndexToolkit:
    """Stub PageIndexToolkit — no LLM, no real tree storage."""

    def __init__(self, adapter, storage_dir, lightweight_model=None, **kwargs):
        self._counter = 0

    async def insert_content(self, tree_name, content, parent_node_id=None, hint=None):
        self._counter += 1
        node_id = f"node-{self._counter:04d}"
        return {
            "tree_name": tree_name,
            "new_node_ids": [node_id],
            "title": "Stub Doc",
            "summary": content[:80],
        }

    async def get_tree(self, tree_name):
        return {}


@pytest.fixture
def charter_file(repo: Path) -> Path:
    charter_dir = repo / ".parrot"
    charter_dir.mkdir(parents=True, exist_ok=True)
    charter_path = charter_dir / "charter.yaml"
    charter_path.write_text(_CHARTER_YAML, encoding="utf-8")
    return charter_path


@pytest.fixture
def docs_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "corpus"
    folder.mkdir()
    (folder / "decision.md").write_text(
        "# Migration decision\n\nWe decided to migrate the graph store.",
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def stub_ingest_wiring(monkeypatch):
    """Patch out every LLM-touching seam in the `ingest` command:
    triage adapters, novelty scorer, and PageIndexToolkit itself."""
    light = _FakeTriageAdapter()
    heavy = _FakeTriageAdapter()

    def _fake_build_adapters(lightweight_model, model):
        return light, heavy, "fake-light-model", True

    def _fake_build_novelty_scorer(root, config, store):
        return _FakeNoveltyScorer()

    monkeypatch.setattr(cli_module, "_build_triage_adapters", _fake_build_adapters)
    monkeypatch.setattr(cli_module, "_build_novelty_scorer", _fake_build_novelty_scorer)
    monkeypatch.setattr(_pageindex_toolkit, "PageIndexToolkit", _FakePageIndexToolkit)
    monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "stub:light")
    monkeypatch.setenv("WIKI_MODEL", "stub:heavy")
    return light, heavy


class TestSupervisedIngestModes:
    """FEAT-402 (TASK-2075): mode-flag handling for `wikitoolkit ingest`."""

    def test_cli_ingest_mode_flags_exclusive(self, runner, repo, docs_folder):
        # No mode flag at all.
        result = runner.invoke(wiki, ["ingest", str(docs_folder), "--path", str(repo)])
        assert result.exit_code != 0
        assert "mode" in result.output.lower()

        # Two mode flags at once.
        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--dry-run",
                "--auto",
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_cli_ingest_missing_charter_errors(self, runner, repo, docs_folder, stub_ingest_wiring):
        result = runner.invoke(wiki, ["ingest", str(docs_folder), "--path", str(repo), "--dry-run"])
        assert result.exit_code != 0
        assert "charter" in result.output.lower()

    def test_cli_ingest_missing_model_errors(self, runner, repo, docs_folder):
        result = runner.invoke(wiki, ["ingest", str(docs_folder), "--path", str(repo), "--dry-run"])
        assert result.exit_code != 0
        assert "model" in result.output.lower()


class TestSupervisedIngestCrossProviderModels:
    """Code-review fix: PageIndexToolkit builds its own internal light
    adapter by pairing the HEAVY adapter's client with the light model id
    string — so mixing providers between --lightweight-model and --model
    must NOT leak the light model id through to it (that would send one
    provider's client a foreign model id)."""

    def _invoke_with_spy(self, runner, repo, docs_folder, charter_file, monkeypatch, same_provider):
        captured = {}

        class _SpyToolkit(_FakePageIndexToolkit):
            def __init__(self, adapter, storage_dir, lightweight_model=None, **kwargs):
                captured["lightweight_model"] = lightweight_model
                super().__init__(adapter, storage_dir, lightweight_model=lightweight_model, **kwargs)

        def _fake_build_adapters(lightweight_model, model):
            return (
                _FakeTriageAdapter(),
                _FakeTriageAdapter(),
                "light-model-id",
                same_provider,
            )

        monkeypatch.setattr(cli_module, "_build_triage_adapters", _fake_build_adapters)
        monkeypatch.setattr(cli_module, "_build_novelty_scorer", lambda root, config, store: _FakeNoveltyScorer())
        monkeypatch.setattr(_pageindex_toolkit, "PageIndexToolkit", _SpyToolkit)
        monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "groq:llama")
        monkeypatch.setenv("WIKI_MODEL", "groq:llama-big" if same_provider else "anthropic:claude")

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        return captured

    def test_same_provider_passes_lightweight_model_through(self, runner, repo, docs_folder, charter_file, monkeypatch):
        captured = self._invoke_with_spy(runner, repo, docs_folder, charter_file, monkeypatch, same_provider=True)
        assert captured["lightweight_model"] == "light-model-id"

    def test_cross_provider_models_drop_lightweight_model(self, runner, repo, docs_folder, charter_file, monkeypatch):
        captured = self._invoke_with_spy(runner, repo, docs_folder, charter_file, monkeypatch, same_provider=False)
        assert captured["lightweight_model"] is None


class TestSupervisedIngestDryRun:
    def test_cli_ingest_dry_run(self, runner, repo, docs_folder, charter_file, stub_ingest_wiring):
        """--dry-run emits a manifest with null decisions and ingests nothing."""
        from parrot.knowledge.wiki.review import ManifestReader

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output

        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        assert manifest_path.exists()
        header, entries = ManifestReader(manifest_path).read()
        assert header.mode == "dry-run"
        assert header.charter_version == "1"
        assert len(entries) == 1
        assert entries[0].decision is None  # nothing decided yet

        # Nothing was ingested: no pages created.
        from parrot.knowledge.wiki.project import load_project_config

        config = load_project_config(repo)
        store_dir = config.storage_path(repo)
        assert not (store_dir / "pageindex").exists() or not any((store_dir / "pageindex").iterdir())

    def test_cli_ingest_dry_run_claims_stripped_without_extract(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring
    ):
        """--extract is off by default: claims are stripped from the manifest."""
        from parrot.knowledge.wiki.review import Claim, ManifestReader

        light, _heavy = stub_ingest_wiring
        light.output.claims = [Claim(text="A claim.")]

        runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        _header, entries = ManifestReader(manifest_path).read()
        assert entries[0].claims == []


class TestSupervisedIngestReview:
    def test_cli_ingest_review_apply(self, runner, repo, docs_folder, charter_file, stub_ingest_wiring):
        """--review applies edited decisions; re-run is idempotent."""
        from parrot.knowledge.wiki.review import ManifestReader

        dry = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert dry.exit_code == 0, dry.output
        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"

        # Simulate a human hand-editing the manifest: fill in `decision`.
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        edited = [lines[0]]
        for line in lines[1:]:
            row = json.loads(line)
            row["decision"] = row["proposed_action"]
            row["decision_source"] = "human"
            edited.append(json.dumps(row))
        manifest_path.write_text("\n".join(edited) + "\n", encoding="utf-8")

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--review",
                str(manifest_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Applied 1 decision" in result.output

        # Re-running --review on the same manifest is idempotent (no error,
        # no duplicate pages — WikiIngestOrchestrator.replace_source_slice
        # guarantees this at the store layer, verified in test_ingest.py).
        result2 = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--review",
                str(manifest_path),
            ],
        )
        assert result2.exit_code == 0, result2.output

        _header, entries = ManifestReader(manifest_path).read()
        assert entries[0].decision == entries[0].proposed_action


class TestSupervisedIngestAuto:
    def test_cli_ingest_auto_audit_flags(self, runner, repo, charter_file, stub_ingest_wiring):
        """--auto flags a stratified audit sample per charter fractions."""
        from parrot.knowledge.wiki.review import ManifestReader

        folder = repo.parent / "auto_corpus"
        folder.mkdir()
        for i in range(10):
            (folder / f"doc{i}.md").write_text(
                f"# Doc {i}\n\nSome durable decision content number {i}.",
                encoding="utf-8",
            )

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--auto",
                "--audit-rate",
                "0.5",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Audit sample" in result.output

        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        header, entries = ManifestReader(manifest_path).read()
        assert header.mode == "auto"
        assert all(e.decision == e.proposed_action for e in entries)
        audited = [e for e in entries if e.audit_sample]
        assert len(audited) == 5  # 50% of 10


class TestSupervisedIngestInteractive:
    def test_cli_ingest_interactive_prompts_before_apply(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring, monkeypatch
    ):
        """--interactive prompts complete before any apply-pipeline work."""
        prompt_order = []

        class _FakeSelect:
            def __init__(self, *args, **kwargs):
                pass

            def ask(self):
                prompt_order.append("prompted")
                return "admit"

        monkeypatch.setattr("questionary.select", lambda *a, **k: _FakeSelect())

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--interactive",
            ],
        )
        assert result.exit_code == 0, result.output
        assert prompt_order == ["prompted"]

        from parrot.knowledge.wiki.review import ManifestReader

        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        _header, entries = ManifestReader(manifest_path).read()
        assert entries[0].decision == "admit"
        assert entries[0].decision_source == "human"


# ---------------------------------------------------------------------------
# FEAT-451 (TASK-2357): widened SOURCE argument, DocumentAcquirer wiring,
# skip reporting.
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A tiny real PDF, written via pymupdf (goes through the loader branch)."""
    import pymupdf

    p = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "A durable architectural decision about migration.")
        doc.set_metadata({"title": "Decision Doc", "author": "Legal"})
        doc.save(str(p))
    finally:
        doc.close()
    return p


@pytest.fixture
def nested_corpus(tmp_path: Path) -> Path:
    """A top-level file plus a nested one, for --no-recursive testing."""
    folder = tmp_path / "nested_corpus"
    folder.mkdir()
    (folder / "top.md").write_text("# Top\n\nTop-level durable decision content.", encoding="utf-8")
    sub = folder / "sub"
    sub.mkdir()
    (sub / "nested.md").write_text("# Nested\n\nNested durable decision content.", encoding="utf-8")
    return folder


@pytest.fixture
def mixed_corpus(tmp_path: Path) -> Path:
    """One good .md + one undecodable .pdf, for skip-and-report testing."""
    folder = tmp_path / "mixed_corpus"
    folder.mkdir()
    (folder / "good.md").write_text("# Good doc\n\nSome durable decision content.", encoding="utf-8")
    (folder / "bad.pdf").write_bytes(b"not a real pdf at all")
    return folder


@pytest.fixture
def no_parrot_loaders(monkeypatch):
    """Force `from parrot_loaders... import ...` to raise ImportError —
    deterministic acquisition failure regardless of what real PDF/loader
    libraries happen to tolerate in this environment."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("simulated: ai-parrot-loaders not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class _FakeAiohttpContentStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class _FakeAiohttpResponse:
    def __init__(self, *, status, headers, chunks, url):
        self.status = status
        self.headers = headers
        self.content = _FakeAiohttpContentStream(chunks)
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeAiohttpGetContextManager:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _FakeAiohttpSession:
    def __init__(self, response):
        self._response = response

    def get(self, _url, **_kwargs):
        return _FakeAiohttpGetContextManager(self._response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def mock_aiohttp_pdf(monkeypatch, sample_pdf):
    """Mock a URL fetch that streams back the real sample_pdf's bytes, so
    downstream loader extraction actually succeeds, not just the fetch."""
    body = sample_pdf.read_bytes()
    resp = _FakeAiohttpResponse(
        status=200,
        headers={"Content-Type": "application/pdf"},
        chunks=[body],
        url="https://example.test/doc.pdf",
    )
    session = _FakeAiohttpSession(resp)
    monkeypatch.setattr(
        "parrot.knowledge.wiki.documents.aiohttp.ClientSession",
        lambda **kwargs: session,
    )


class TestIngestSourceArgument:
    """FEAT-451 (TASK-2357): SOURCE widened to dir | file | URL."""

    def test_single_file_dry_run(self, runner, repo, sample_pdf, charter_file, stub_ingest_wiring):
        """A single document path (not a directory) produces a one-entry manifest."""
        from parrot.knowledge.wiki.review import ManifestReader

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(sample_pdf),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output

        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        _header, entries = ManifestReader(manifest_path).read()
        assert len(entries) == 1

    def test_url_dry_run(self, runner, repo, charter_file, stub_ingest_wiring, mock_aiohttp_pdf):
        """An http(s):// SOURCE is fetched, extracted, and triaged."""
        result = runner.invoke(
            wiki,
            [
                "ingest",
                "https://example.test/doc.pdf",
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Triaged 1 document" in result.output

    def test_missing_path_clean_error(self, runner, repo):
        """A nonexistent SOURCE exits non-zero with a clean Click error —
        no traceback (resolve_sources raises click.ClickException)."""
        result = runner.invoke(
            wiki,
            ["ingest", "/no/such/path/at/all", "--path", str(repo), "--dry-run"],
        )
        assert result.exit_code != 0
        assert "Traceback" not in result.output

    def test_no_recursive(self, runner, repo, nested_corpus, charter_file, stub_ingest_wiring):
        """--no-recursive only walks the directory's immediate children."""
        from parrot.knowledge.wiki.review import ManifestReader

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(nested_corpus),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
                "--no-recursive",
            ],
        )
        assert result.exit_code == 0, result.output

        manifest_path = repo / ".parrot" / "wiki" / "ingest-manifest.jsonl"
        _header, entries = ManifestReader(manifest_path).read()
        assert len(entries) == 1
        assert entries[0].source_uri.endswith("top.md")

    def test_undecodable_skipped_and_reported(
        self,
        runner,
        repo,
        mixed_corpus,
        charter_file,
        stub_ingest_wiring,
        no_parrot_loaders,
    ):
        """One bad doc: skipped, counted, reported — run still succeeds and
        the other document is still triaged."""
        light, _heavy = stub_ingest_wiring
        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(mixed_corpus),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "skipped" in result.output.lower()
        assert "1" in result.output  # skipped count
        # router.triage() is never reached for the skipped document — the
        # only successful acquisition (and thus only triage call) is the
        # good .md.
        assert light.calls == 1

    def test_fetch_timeout_reaches_acquirer(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring, monkeypatch
    ):
        """--fetch-timeout reaches DocumentAcquirer.__init__."""
        captured: dict = {}
        orig_init = cli_module.DocumentAcquirer.__init__

        def _spy_init(self, *args, **kwargs):
            captured.update(kwargs)
            return orig_init(self, *args, **kwargs)

        monkeypatch.setattr(cli_module.DocumentAcquirer, "__init__", _spy_init)

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--dry-run",
                "--fetch-timeout",
                "5.5",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured.get("fetch_timeout") == 5.5

    def test_auto_reuses_acquired_no_double_acquisition(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring, monkeypatch
    ):
        """--auto passes the triage lane's AcquiredDocument into
        orch.ingest(acquired=...) — the document is acquired exactly once,
        not once for triage and again for apply."""
        import parrot.knowledge.wiki.documents as documents_module

        call_count = {"n": 0}
        orig_acquire = documents_module.DocumentAcquirer.acquire

        async def _counting_acquire(self, ref):
            call_count["n"] += 1
            return await orig_acquire(self, ref)

        monkeypatch.setattr(documents_module.DocumentAcquirer, "acquire", _counting_acquire)

        result = runner.invoke(
            wiki,
            [
                "ingest",
                str(docs_folder),
                "--path",
                str(repo),
                "--charter",
                str(charter_file),
                "--auto",
            ],
        )
        assert result.exit_code == 0, result.output
        assert call_count["n"] == 1

    def test_discover_documents_removed(self):
        assert not hasattr(cli_module, "_discover_documents")


def _second_repo(tmp_path: Path, runner: CliRunner, name: str = "other") -> Path:
    """Build a second, independent wiki project with colliding page ids."""
    other = tmp_path / name
    (other / "pkg").mkdir(parents=True)
    (other / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (other / "pkg" / "util.py").write_text(PY_UTIL, encoding="utf-8")
    (other / "README.md").write_text("# Other\n\nAnother demo project.", encoding="utf-8")
    _build(runner, other)
    return other


def _write_namespaces(repo: Path, namespaces: dict) -> None:
    """Declare namespaces in the repo's ``.parrot/wiki.json``."""
    path = config_path(repo)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["namespaces"] = namespaces
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the developer's real ~/.parrot/wikis.json out of the tests."""
    home = tmp_path / "parrot-home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


@pytest.mark.usefixtures("isolated_home")
class TestNamespaceReads:
    """FEAT-450 — ``--ns`` routing on query / page / related / status."""

    def test_query_broadcasts_and_qualifies(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})

        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert "file:pkg/store.py" in ids
        assert "other::file:pkg/store.py" in ids

    def test_query_ns_explicit(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})

        only_other = runner.invoke(
            wiki,
            ["query", "store", "--path", str(repo), "--ns", "other", "--json"],
        )
        assert only_other.exit_code == 0, only_other.output
        rows = json.loads(only_other.output)
        assert rows
        assert all(r["concept_id"].startswith("other::") for r in rows)

        only_local = runner.invoke(
            wiki,
            ["query", "store", "--path", str(repo), "--ns", "local", "--json"],
        )
        assert only_local.exit_code == 0, only_local.output
        rows = json.loads(only_local.output)
        assert rows
        assert all("::" not in r["concept_id"] for r in rows)

        broadcast = runner.invoke(
            wiki,
            ["query", "store", "--path", str(repo), "--ns", "all", "--json"],
        )
        assert broadcast.exit_code == 0, broadcast.output
        ids = {r["concept_id"] for r in json.loads(broadcast.output)}
        assert any(i.startswith("other::") for i in ids)
        assert any("::" not in i for i in ids)

    def test_query_unknown_namespace_errors(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--ns", "nope"])
        assert result.exit_code != 0
        assert "Unknown namespace" in result.output
        assert "other" in result.output

    def test_no_namespaces_is_unchanged(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert ids
        assert all("::" not in i for i in ids)

    def test_store_flag_never_federates(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        result = runner.invoke(
            wiki,
            [
                "query",
                "store",
                "--store",
                str(load_project_config(repo).storage_path(repo)),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert ids and all("::" not in i for i in ids)

    def test_explicit_path_beats_env_with_namespaces(self, runner, repo, tmp_path, monkeypatch):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        monkeypatch.setenv("WIKI_STORE", str(repo / "somewhere-else"))
        result = runner.invoke(
            wiki,
            ["query", "utility helpers", "--path", str(repo), "--json"],
        )
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert "file:pkg/util.py" in ids

    def test_page_and_related_with_qualified_id(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})

        page = runner.invoke(
            wiki,
            ["page", "other::file:pkg/store.py", "--path", str(repo)],
        )
        assert page.exit_code == 0, page.output
        assert "other::file:pkg/store.py" in page.output

        rel = runner.invoke(wiki, ["related", "other::dir:pkg", "--path", str(repo), "--json"])
        assert rel.exit_code == 0, rel.output
        rows = json.loads(rel.output)
        assert rows
        assert all(r["concept_id"].startswith("other::") for r in rows)

    def test_page_ns_option_qualifies_bare_id(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        page = runner.invoke(
            wiki,
            [
                "page",
                "file:pkg/store.py",
                "--path",
                str(repo),
                "--ns",
                "other",
                "--json",
            ],
        )
        assert page.exit_code == 0, page.output
        assert json.loads(page.output)["concept_id"] == "other::file:pkg/store.py"

    def test_status_lists_namespaces(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})

        result = runner.invoke(wiki, ["status", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "Namespaces:" in result.output
        assert "other" in result.output

        as_json = runner.invoke(wiki, ["status", "--path", str(repo), "--json"])
        assert as_json.exit_code == 0, as_json.output
        payload = json.loads(as_json.output)
        assert payload["namespaces"]["other"]["status"] == "ok"
        assert payload["skipped"] == []
        # The local plane's own numbers are untouched.
        assert payload["stats"]["pages"] > 0
        assert "namespaces" not in payload["stats"]

    def test_status_shows_unbuilt_namespace(self, runner, repo, tmp_path):
        _build(runner, repo)
        (tmp_path / "empty").mkdir()
        _write_namespaces(repo, {"empty": {"path": str(tmp_path / "empty")}})
        result = runner.invoke(wiki, ["status", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "unbuilt" in result.output
        assert "wikitoolkit build --path" in result.output

    def test_status_without_namespaces_is_unchanged(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["status", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "namespaces" not in payload
        assert "skipped" not in payload

    def test_query_notes_a_skipped_namespace(self, runner, repo, tmp_path):
        _build(runner, repo)
        (tmp_path / "empty").mkdir()
        _write_namespaces(repo, {"empty": {"path": str(tmp_path / "empty")}})
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "skipped: unbuilt" in result.output

    def test_global_registry_namespace_is_read(self, runner, repo, tmp_path, isolated_home):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "wikis.json").write_text(
            json.dumps({"version": 1, "namespaces": {"glob": {"path": str(other)}}}),
            encoding="utf-8",
        )
        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert any(i.startswith("glob::") for i in ids)


@pytest.mark.usefixtures("isolated_home")
class TestNamespaceRegistry:
    """FEAT-450 — ``wikitoolkit ns list|add|remove``."""

    def test_add_list_remove_repo_and_global(self, runner, repo, tmp_path, isolated_home):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)

        added = runner.invoke(
            wiki,
            ["ns", "add", "other", "--project", str(other), "--path", str(repo)],
        )
        assert added.exit_code == 0, added.output

        brain = tmp_path / "brain"
        brain.mkdir()
        added_global = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "brain",
                "--store",
                str(brain),
                "--global",
                "--path",
                str(repo),
            ],
        )
        assert added_global.exit_code == 0, added_global.output
        assert (isolated_home / "wikis.json").exists()

        listed = runner.invoke(wiki, ["ns", "list", "--path", str(repo), "--json"])
        assert listed.exit_code == 0, listed.output
        rows = {r["name"]: r for r in json.loads(listed.output)}
        assert rows["other"]["origin"] == "repo"
        assert rows["other"]["kind"] == "path"
        assert rows["other"]["built"] is True
        assert rows["brain"]["origin"] == "global"
        assert rows["brain"]["built"] is False

        # The repo config keeps its other settings, and the entry is
        # stored relative to the repo root so a clone still resolves it.
        config = load_project_config(repo)
        stored = config.namespaces["other"].path
        assert not Path(stored).is_absolute()
        assert (repo / stored).resolve() == other.resolve()
        assert config.wiki_name

        removed = runner.invoke(wiki, ["ns", "remove", "brain", "--global", "--path", str(repo)])
        assert removed.exit_code == 0, removed.output
        rows = {
            r["name"] for r in json.loads(runner.invoke(wiki, ["ns", "list", "--path", str(repo), "--json"]).output)
        }
        assert rows == {"other"}

    def test_add_rejects_reserved_name(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        result = runner.invoke(
            wiki,
            ["ns", "add", "all", "--project", str(other), "--path", str(repo)],
        )
        assert result.exit_code != 0
        assert "reserved" in result.output

    def test_add_rejects_zero_or_two_sources(self, runner, repo, tmp_path):
        _build(runner, repo)
        none = runner.invoke(wiki, ["ns", "add", "x", "--path", str(repo)])
        assert none.exit_code != 0 and "exactly one" in none.output
        both = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "x",
                "--project",
                str(tmp_path),
                "--store",
                str(tmp_path),
                "--path",
                str(repo),
            ],
        )
        assert both.exit_code != 0 and "exactly one" in both.output

    def test_add_rejects_duplicate_in_same_registry(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        args = ["ns", "add", "other", "--project", str(other), "--path", str(repo)]
        assert runner.invoke(wiki, args).exit_code == 0
        again = runner.invoke(wiki, args)
        assert again.exit_code != 0 and "already exists" in again.output

    def test_repo_entry_shadowing_global_is_noted(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        assert (
            runner.invoke(
                wiki,
                [
                    "ns",
                    "add",
                    "dup",
                    "--project",
                    str(other),
                    "--global",
                    "--path",
                    str(repo),
                ],
            ).exit_code
            == 0
        )
        shadow = runner.invoke(
            wiki,
            ["ns", "add", "dup", "--project", str(other), "--path", str(repo)],
        )
        assert shadow.exit_code == 0, shadow.output
        assert "shadows the global namespace" in shadow.output

    def test_add_vault_requires_obsidian(self, runner, repo, tmp_path):
        _build(runner, repo)
        plain = tmp_path / "notes"
        plain.mkdir()
        rejected = runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(plain), "--path", str(repo)],
        )
        assert rejected.exit_code != 0
        assert ".obsidian" in rejected.output

        (plain / ".obsidian").mkdir()
        accepted = runner.invoke(
            wiki,
            ["ns", "add", "notes", "--vault", str(plain), "--path", str(repo)],
        )
        assert accepted.exit_code == 0, accepted.output
        assert "wikitoolkit build --path" in accepted.output
        assert load_project_config(repo).namespaces["notes"].kind == "vault"

    def test_add_database_defaults_to_arangodb_backend(self, runner, repo):
        _build(runner, repo)
        added = runner.invoke(
            wiki,
            ["ns", "add", "legis", "--database", "wiki_legis", "--path", str(repo)],
        )
        assert added.exit_code == 0, added.output
        assert load_project_config(repo).namespaces["legis"].backend == "arangodb"

    def test_add_database_accepts_registered_extra_backend(self, runner, repo):
        """FEAT-449 M7: --database entries may name a satellite-registered
        backend (e.g. 'ontology_legal') instead of forcing 'arangodb'."""
        _build(runner, repo)
        added = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "legal",
                "--database",
                "legal_db",
                "--backend",
                "ontology_legal",
                "--path",
                str(repo),
            ],
        )
        assert added.exit_code == 0, added.output
        assert load_project_config(repo).namespaces["legal"].backend == "ontology_legal"

    def test_add_database_still_accepts_explicit_arangodb(self, runner, repo):
        _build(runner, repo)
        added = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "legis",
                "--database",
                "wiki_legis",
                "--backend",
                "arangodb",
                "--path",
                str(repo),
            ],
        )
        assert added.exit_code == 0, added.output
        assert load_project_config(repo).namespaces["legis"].backend == "arangodb"

    def test_add_store_rejects_non_local_backend(self, runner, repo, tmp_path):
        _build(runner, repo)
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        rejected = runner.invoke(
            wiki,
            [
                "ns",
                "add",
                "legal",
                "--store",
                str(store_dir),
                "--backend",
                "ontology_legal",
                "--path",
                str(repo),
            ],
        )
        assert rejected.exit_code != 0
        assert "not valid for --store" in rejected.output
        assert "legal" not in load_project_config(repo).namespaces

    def test_add_store_still_accepts_sqlite_and_memory(self, runner, repo, tmp_path):
        _build(runner, repo)
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        added = runner.invoke(
            wiki,
            ["ns", "add", "mem", "--store", str(store_dir), "--backend", "memory", "--path", str(repo)],
        )
        assert added.exit_code == 0, added.output
        assert load_project_config(repo).namespaces["mem"].backend == "memory"

    def test_remove_missing_namespace_errors(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["ns", "remove", "ghost", "--path", str(repo)])
        assert result.exit_code != 0 and "No namespace" in result.output

    def test_list_without_namespaces(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(wiki, ["ns", "list", "--path", str(repo)])
        assert result.exit_code == 0, result.output
        assert "No namespaces declared" in result.output


@pytest.mark.usefixtures("isolated_home")
class TestNamespaceWrites:
    """FEAT-450 U2 — ``remember`` / ``note`` / ``link`` with ``--ns``."""

    @staticmethod
    def _setup(runner, repo, tmp_path) -> Path:
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        return other

    def test_remember_ns_writes_foreign_only(self, runner, repo, tmp_path):
        other = self._setup(runner, repo, tmp_path)
        saved = runner.invoke(
            wiki,
            ["remember", "zebra fact", "--ns", "other", "--path", str(repo), "--json"],
        )
        assert saved.exit_code == 0, saved.output

        in_other = runner.invoke(wiki, ["query", "zebra", "--path", str(other), "--json"])
        assert "zebra" in in_other.output

        in_local = runner.invoke(
            wiki,
            ["query", "zebra", "--path", str(repo), "--ns", "local", "--json"],
        )
        assert "zebra" not in in_local.output

    def test_remember_defaults_to_local(self, runner, repo, tmp_path):
        other = self._setup(runner, repo, tmp_path)
        assert runner.invoke(wiki, ["remember", "okapi fact", "--path", str(repo), "--json"]).exit_code == 0
        assert (
            "okapi"
            in runner.invoke(
                wiki,
                ["query", "okapi", "--path", str(repo), "--ns", "local", "--json"],
            ).output
        )
        assert "okapi" not in runner.invoke(wiki, ["query", "okapi", "--path", str(other), "--json"]).output

    def test_remember_ns_all_is_rejected(self, runner, repo, tmp_path):
        self._setup(runner, repo, tmp_path)
        result = runner.invoke(wiki, ["remember", "x", "--ns", "all", "--path", str(repo)])
        assert result.exit_code != 0
        assert "exactly one namespace" in result.output

    def test_remember_ns_unknown_is_rejected(self, runner, repo, tmp_path):
        self._setup(runner, repo, tmp_path)
        result = runner.invoke(wiki, ["remember", "x", "--ns", "ghost", "--path", str(repo)])
        assert result.exit_code != 0 and "Unknown namespace" in result.output

    def test_store_and_ns_together_are_rejected(self, runner, repo, tmp_path):
        self._setup(runner, repo, tmp_path)
        result = runner.invoke(
            wiki,
            [
                "remember",
                "x",
                "--ns",
                "other",
                "--store",
                str(load_project_config(repo).storage_path(repo)),
            ],
        )
        assert result.exit_code != 0
        assert "different planes" in result.output

    def test_note_and_link_with_ns(self, runner, repo, tmp_path):
        other = self._setup(runner, repo, tmp_path)
        noted = runner.invoke(
            wiki,
            [
                "note",
                "other::file:pkg/store.py",
                "a foreign note",
                "--ns",
                "other",
                "--path",
                str(repo),
                "--json",
            ],
        )
        assert noted.exit_code == 0, noted.output
        page = runner.invoke(wiki, ["page", "file:pkg/store.py", "--path", str(other)])
        assert "a foreign note" in page.output

        linked = runner.invoke(
            wiki,
            [
                "link",
                "file:pkg/store.py",
                "file:pkg/util.py",
                "--ns",
                "other",
                "--path",
                str(repo),
                "--json",
            ],
        )
        assert linked.exit_code == 0, linked.output
        rel = runner.invoke(wiki, ["related", "other::file:pkg/store.py", "--path", str(repo), "--json"])
        assert "other::file:pkg/util.py" in rel.output

    def test_mismatched_qualified_id_is_rejected(self, runner, repo, tmp_path):
        self._setup(runner, repo, tmp_path)
        result = runner.invoke(
            wiki,
            [
                "note",
                "elsewhere::file:pkg/store.py",
                "text",
                "--ns",
                "other",
                "--path",
                str(repo),
            ],
        )
        assert result.exit_code != 0
        assert "belongs to namespace" in result.output

    def test_local_write_rejects_qualified_id(self, runner, repo, tmp_path):
        self._setup(runner, repo, tmp_path)
        result = runner.invoke(
            wiki,
            ["note", "other::file:pkg/store.py", "text", "--path", str(repo)],
        )
        assert result.exit_code != 0
        assert "pass `--ns other`" in result.output


@pytest.mark.usefixtures("isolated_home")
class TestNamespaceReviewRegressions:
    """Regressions from the FEAT-450 code review (F3, F4, F6, L2)."""

    def test_ns_add_resolves_a_relative_project_path(self, runner, repo, tmp_path):
        """F3 — a typed relative path must resolve to what the user meant."""
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            rel = os.path.relpath(other, cwd)
            added = runner.invoke(wiki, ["ns", "add", "sib", "--project", rel, "--path", str(repo)])
        assert added.exit_code == 0, added.output
        stored = load_project_config(repo).namespaces["sib"].path
        assert (repo / stored).resolve() == other.resolve()

        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        assert result.exit_code == 0, result.output
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert any(i.startswith("sib::") for i in ids)

    def test_ns_add_global_stores_an_absolute_path(self, runner, repo, tmp_path, isolated_home):
        """F3 — a global entry is read back relative to PARROT_HOME."""
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            rel = os.path.relpath(other, cwd)
            added = runner.invoke(
                wiki,
                [
                    "ns",
                    "add",
                    "glob",
                    "--project",
                    rel,
                    "--global",
                    "--path",
                    str(repo),
                ],
            )
        assert added.exit_code == 0, added.output
        stored = json.loads((isolated_home / "wikis.json").read_text(encoding="utf-8"))["namespaces"]["glob"]["path"]
        assert Path(stored).is_absolute()
        assert Path(stored).resolve() == other.resolve()

        result = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
        ids = {row["concept_id"] for row in json.loads(result.output)}
        assert any(i.startswith("glob::") for i in ids)

    def test_status_ns_reports_that_namespace(self, runner, repo, tmp_path):
        """F4 — the header must describe the plane the counters came from."""
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})

        scoped = json.loads(
            runner.invoke(
                wiki,
                ["status", "--path", str(repo), "--ns", "other", "--json"],
            ).output
        )
        local = json.loads(
            runner.invoke(
                wiki,
                ["status", "--path", str(repo), "--ns", "local", "--json"],
            ).output
        )
        assert scoped["namespace"] == "other"
        assert scoped["wiki_name"] == "other"
        assert Path(scoped["storage_dir"]).resolve() == (load_project_config(other).storage_path(other).resolve())
        # Source staleness is a local-manifest concept — absent, not faked.
        assert scoped["sources"] is None
        assert scoped["stale_sources"] is None
        # ...and it is genuinely the other plane's numbers.
        assert scoped["stats"]["pages"] == local["stats"]["pages"]
        assert "namespace" not in local

    def test_status_ns_text_output_names_the_namespace(self, runner, repo, tmp_path):
        _build(runner, repo)
        other = _second_repo(tmp_path, runner)
        _write_namespaces(repo, {"other": {"path": str(other)}})
        result = runner.invoke(wiki, ["status", "--path", str(repo), "--ns", "other"])
        assert result.exit_code == 0, result.output
        assert "Namespace : other" in result.output
        assert "Sources   :" not in result.output

    def test_concurrent_global_ns_add_keeps_both(self, runner, repo, tmp_path, isolated_home):
        """F6 — the registry read-modify-write is serialised."""
        import threading

        _second_repo(tmp_path, runner)
        results: list[int] = []
        barrier = threading.Barrier(2)

        def add(name: str) -> None:
            target = tmp_path / name
            target.mkdir(exist_ok=True)
            barrier.wait()
            results.append(
                CliRunner()
                .invoke(
                    wiki,
                    [
                        "ns",
                        "add",
                        name,
                        "--store",
                        str(target),
                        "--global",
                        "--path",
                        str(repo),
                    ],
                )
                .exit_code
            )

        threads = [threading.Thread(target=add, args=(n,)) for n in ("aa", "bb")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == [0, 0]
        registry = json.loads((isolated_home / "wikis.json").read_text(encoding="utf-8"))
        assert set(registry["namespaces"]) == {"aa", "bb"}

    def test_build_keeps_pages_of_another_corpus(self, runner, repo, tmp_path):
        """L2 — a repo build must not wipe a vault ingested into its plane."""
        from parrot.knowledge.wiki.cli import _ingest_files, _open_sources
        from parrot.knowledge.wiki.vault_scan import scan_vault

        _build(runner, repo)
        vault = tmp_path / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "Note.md").write_text("# Note\n\nzebra\n", encoding="utf-8")

        config = load_project_config(repo)
        store = create_wiki_store(config.storage_path(repo), wiki_name=config.wiki_name)
        sources = _open_sources(repo, config, store=store)
        scan, _stats = scan_vault(vault)
        asyncio.run(_ingest_files(store, sources, vault, scan, force=True))
        assert asyncio.run(store.get_page("file:Note.md")) is not None

        _build(runner, repo)

        assert asyncio.run(store.get_page("file:Note.md")) is not None
        assert asyncio.run(store.get_page("file:pkg/store.py")) is not None

    def test_build_still_prunes_its_own_deleted_files(self, runner, repo):
        """...while build's own pruning is unchanged."""
        _build(runner, repo)
        config = load_project_config(repo)
        store = create_wiki_store(config.storage_path(repo), wiki_name=config.wiki_name)
        assert asyncio.run(store.get_page("file:pkg/util.py")) is not None
        (repo / "pkg" / "util.py").unlink()
        _build(runner, repo)
        assert asyncio.run(store.get_page("file:pkg/util.py")) is None
