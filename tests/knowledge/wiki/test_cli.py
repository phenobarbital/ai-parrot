"""Tests for the ``wikitoolkit`` / ``parrot wiki`` CLI.

Drives the click commands end-to-end with ``CliRunner`` against temp
repositories — real SQLite plane, no git dependency (``--no-git``),
no LLM.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki import cli as cli_module
from parrot.knowledge.wiki.cli import _changed_files_from_git, wiki
from parrot.knowledge.wiki.project import (
    config_path,
    load_project_config,
    wiki_write_lock,
)

PY_STORE = '"""A tiny key-value store module."""\n\n\nclass Store:\n    """In-memory key-value store."""\n\n    def get(self, key):\n        """Fetch a value."""\n        return key\n'
PY_UTIL = '"""Utility helpers."""\n\n\ndef helper(key):\n    """Return the key unchanged."""\n    return key\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake repository."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(PY_STORE, encoding="utf-8")
    (tmp_path / "pkg" / "util.py").write_text(PY_UTIL, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Demo\n\nA demo project.", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, repo: Path, *extra: str):
    result = runner.invoke(
        wiki, ["build", "--path", str(repo), "--no-git", *extra]
    )
    assert result.exit_code == 0, result.output
    return result


def _store_dir(repo: Path) -> Path:
    """The directory the writer lock guards — beside the store, not the root."""
    return load_project_config(repo).storage_path(repo)


class TestBuildLock:
    def test_build_refuses_while_another_writer_holds_the_lock(self, runner, repo):
        with wiki_write_lock(_store_dir(repo)) as held:
            assert held is True
            result = runner.invoke(
                wiki, ["build", "--path", str(repo), "--no-git"]
            )
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
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v2."""\n', encoding="utf-8"
        )
        result = _build(runner, repo)
        assert "1 ingested" in result.output

    def test_deleted_file_pruned(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").unlink()
        result = _build(runner, repo)
        assert "removed" in result.output
        page = runner.invoke(
            wiki, ["page", "file:pkg/util.py", "--path", str(repo)]
        )
        assert page.exit_code != 0

    def test_custom_name_and_backend(self, runner, repo):
        _build(runner, repo, "--name", "kb", "--backend", "memory")
        config = load_project_config(repo)
        assert config.wiki_name == "kb"
        assert config.backend == "memory"
        result = runner.invoke(
            wiki, ["query", "store", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output


class TestQuery:
    def test_query_returns_packed_stubs(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "key value store", "--path", str(repo)]
        )
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
        result = runner.invoke(
            wiki, ["query", "anything", "--path", str(repo)]
        )
        assert result.exit_code != 0
        assert "wikitoolkit build" in result.output

    def test_query_no_results_message(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "zzzqqqxyzzy", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "No wiki results" in result.output

    def _store_dir(self, repo: Path) -> str:
        return str(repo / ".parrot" / "wiki")

    def test_query_table_renders_human_output(self, runner, repo):
        # Ported llmwiki capability: --table shows a Rich table.
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "key value store", "--path", str(repo), "--table"]
        )
        assert result.exit_code == 0, result.output
        assert "LLM Wiki" in result.output
        assert "Score" in result.output and "store.py" in result.output

    def test_query_body_hydrates_top_hit(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            ["query", "key value store", "--path", str(repo),
             "--body", "--json"],
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert rows and rows[0].get("body"), "top hit body not hydrated"

    def test_query_store_targets_prebuilt_store(self, runner, repo):
        # Ported llmwiki capability: query an arbitrary pre-built store
        # directly (here the project's own plane by absolute --store),
        # without needing .parrot/wiki.json resolution.
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["query", "utility helpers", "--store",
                   self._store_dir(repo), "--json"]
        )
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
        result = runner.invoke(
            wiki, ["query", "utility helpers", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.output)
        assert any(r["concept_id"] == "file:pkg/util.py" for r in rows)

    def test_query_store_missing_dir_errors(self, runner, repo):
        result = runner.invoke(
            wiki, ["query", "x", "--store", str(repo / "does-not-exist")]
        )
        assert result.exit_code != 0
        assert "No wiki store directory" in result.output

    def test_query_store_missing_db_errors(self, runner, repo):
        # Directory exists but holds no wiki.db → friendly guidance.
        (repo / "emptystore").mkdir()
        result = runner.invoke(
            wiki, ["query", "x", "--store", str(repo / "emptystore")]
        )
        assert result.exit_code != 0
        assert "No wiki database" in result.output

    def test_page_and_related_accept_store(self, runner, repo):
        _build(runner, repo)
        sd = self._store_dir(repo)
        page = runner.invoke(
            wiki, ["page", "file:pkg/store.py", "--store", sd]
        )
        assert page.exit_code == 0, page.output
        rel = runner.invoke(wiki, ["related", "dir:pkg", "--store", sd])
        assert rel.exit_code == 0, rel.output


class TestPageAndRelated:
    def test_page_full_read(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["page", "file:pkg/store.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "In-memory key-value store" in result.output

    def test_page_max_tokens_truncates(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki,
            [
                "page", "file:pkg/store.py",
                "--path", str(repo), "--max-tokens", "5",
            ],
        )
        assert result.exit_code == 0
        assert "truncated" in result.output

    def test_related_shows_contains_edge(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["related", "file:pkg/store.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "dir:pkg" in result.output
        assert "contains" in result.output


class TestUpsert:
    def test_upsert_explicit_path(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v2."""\n', encoding="utf-8"
        )
        result = runner.invoke(
            wiki, ["upsert", "pkg/util.py", "--path", str(repo)]
        )
        assert result.exit_code == 0, result.output
        assert "Upserted 1" in result.output
        page = runner.invoke(
            wiki, ["page", "file:pkg/util.py", "--path", str(repo)]
        )
        assert "v2" in page.output

    def test_upsert_preserves_incoming_edges(self, runner, repo):
        _build(runner, repo)
        (repo / "pkg" / "util.py").write_text(
            '"""Utility helpers v3."""\n', encoding="utf-8"
        )
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
        result = runner.invoke(
            wiki, ["upsert", "pkg/util.py", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "removed 1" in result.output

    def test_upsert_ignores_excluded_dirs(self, runner, repo):
        _build(runner, repo)
        state = repo / ".parrot" / "wiki.json"
        assert state.exists()
        result = runner.invoke(
            wiki, ["upsert", ".parrot/wiki.json", "--path", str(repo)]
        )
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

        result = runner.invoke(
            wiki, ["upsert", "docs/legacy_wiki/index.md", "--path", str(repo)]
        )
        assert result.exit_code == 0
        assert "No wiki-relevant files" in result.output

    def test_upsert_skips_while_another_writer_holds_the_lock(
        self, runner, repo, monkeypatch
    ):
        # The git post-commit hook must never stall behind a build that
        # can run for minutes, nor write the store underneath it.
        monkeypatch.setattr(cli_module, "UPSERT_LOCK_WAIT_SECONDS", 0.1)
        _build(runner, repo)
        with wiki_write_lock(_store_dir(repo)) as held:
            assert held is True
            result = runner.invoke(
                wiki, ["upsert", "pkg/util.py", "--path", str(repo)]
            )
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
        result = runner.invoke(
            wiki, ["upsert", "a.py", "--path", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "not built" in result.output


class TestStatusAndExport:
    def test_status_json(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["status", "--path", str(repo), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["stats"]["pages"] >= 3
        assert payload["stale_sources"] == 0

    def test_export_markdown_bundle(self, runner, repo):
        _build(runner, repo)
        result = runner.invoke(
            wiki, ["export", "--path", str(repo), "-o", "docs/wiki"]
        )
        assert result.exit_code == 0, result.output
        out = repo / "docs" / "wiki"
        assert (out / "index.md").exists()
        assert any(out.rglob("*store.py*"))


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


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
            check=True, capture_output=True, text=True,
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
            scores=DimensionScores(
                density=density, novelty=novelty, durability=durability
            ),
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
        return light, heavy, "fake-light-model"

    def _fake_build_novelty_scorer(root, config, store):
        return _FakeNoveltyScorer()

    monkeypatch.setattr(cli_module, "_build_triage_adapters", _fake_build_adapters)
    monkeypatch.setattr(cli_module, "_build_novelty_scorer", _fake_build_novelty_scorer)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.PageIndexToolkit", _FakePageIndexToolkit
    )
    monkeypatch.setenv("WIKI_LIGHTWEIGHT_MODEL", "stub:light")
    monkeypatch.setenv("WIKI_MODEL", "stub:heavy")
    return light, heavy


class TestSupervisedIngestModes:
    """FEAT-402 (TASK-2075): mode-flag handling for `wikitoolkit ingest`."""

    def test_cli_ingest_mode_flags_exclusive(self, runner, repo, docs_folder):
        # No mode flag at all.
        result = runner.invoke(
            wiki, ["ingest", str(docs_folder), "--path", str(repo)]
        )
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

    def test_cli_ingest_missing_charter_errors(
        self, runner, repo, docs_folder, stub_ingest_wiring
    ):
        result = runner.invoke(
            wiki, ["ingest", str(docs_folder), "--path", str(repo), "--dry-run"]
        )
        assert result.exit_code != 0
        assert "charter" in result.output.lower()

    def test_cli_ingest_missing_model_errors(self, runner, repo, docs_folder):
        result = runner.invoke(
            wiki, ["ingest", str(docs_folder), "--path", str(repo), "--dry-run"]
        )
        assert result.exit_code != 0
        assert "model" in result.output.lower()


class TestSupervisedIngestDryRun:
    def test_cli_ingest_dry_run(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring
    ):
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
        assert not (store_dir / "pageindex").exists() or not any(
            (store_dir / "pageindex").iterdir()
        )

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
    def test_cli_ingest_review_apply(
        self, runner, repo, docs_folder, charter_file, stub_ingest_wiring
    ):
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
    def test_cli_ingest_auto_audit_flags(
        self, runner, repo, charter_file, stub_ingest_wiring
    ):
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
