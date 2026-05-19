"""Unit tests for parrot_tools.graphindex.flowtask."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_tools.graphindex.flowtask import GraphIndexComponent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def minimal_config(tenant_id: str = "test-tenant", tmp_path: Path | None = None) -> dict:
    """Return a minimal valid component config."""
    return {
        "tenant_id": tenant_id,
        "code_paths": [],
        "loader_sources": [],
        "skill_paths": [],
        "output_dir": str(tmp_path or "/tmp/gi_test"),
    }


# ---------------------------------------------------------------------------
# TestGraphIndexComponent
# ---------------------------------------------------------------------------


class TestGraphIndexComponent:
    @pytest.mark.asyncio
    async def test_context_manager_protocol(self, tmp_path):
        """Component works with async with pattern."""
        config = minimal_config(tmp_path=tmp_path)
        async with GraphIndexComponent(config) as comp:
            assert comp is not None
            assert comp._builder is not None

    @pytest.mark.asyncio
    async def test_exit_clears_builder(self, tmp_path):
        """After exiting async with, _builder is None."""
        config = minimal_config(tmp_path=tmp_path)
        comp = GraphIndexComponent(config)
        async with comp:
            pass
        assert comp._builder is None

    @pytest.mark.asyncio
    async def test_run_returns_dict(self, tmp_path):
        """run() must return a dict."""
        config = minimal_config(tmp_path=tmp_path)
        async with GraphIndexComponent(config) as comp:
            result = await comp.run()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_run_returns_build_result_keys(self, tmp_path):
        """run() result must contain BuildResult keys."""
        config = minimal_config(tmp_path=tmp_path)
        async with GraphIndexComponent(config) as comp:
            result = await comp.run()
        assert "tenant_id" in result
        assert "node_count" in result
        assert "edge_count" in result
        assert "errors" in result

    @pytest.mark.asyncio
    async def test_run_tenant_id_matches_config(self, tmp_path):
        """run() result tenant_id must match config."""
        config = minimal_config(tenant_id="my-org", tmp_path=tmp_path)
        async with GraphIndexComponent(config) as comp:
            result = await comp.run()
        assert result["tenant_id"] == "my-org"

    @pytest.mark.asyncio
    async def test_run_delegates_to_builder(self, tmp_path):
        """run() must call GraphIndexBuilder.build()."""
        config = minimal_config(tmp_path=tmp_path)

        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "tenant_id": "test-tenant",
            "node_count": 5,
            "edge_count": 3,
            "inferred_edge_count": 1,
            "report_path": None,
            "errors": [],
        }

        async with GraphIndexComponent(config) as comp:
            with patch.object(comp._builder, "build", AsyncMock(return_value=mock_result)):
                result = await comp.run()

        assert result["node_count"] == 5
        assert result["edge_count"] == 3

    @pytest.mark.asyncio
    async def test_run_outside_context_raises(self):
        """run() outside async with must raise RuntimeError."""
        comp = GraphIndexComponent({"tenant_id": "t"})
        with pytest.raises(RuntimeError, match="async context manager"):
            await comp.run()

    @pytest.mark.asyncio
    async def test_missing_tenant_id_raises(self):
        """Missing tenant_id in config must raise ValueError on __aenter__."""
        comp = GraphIndexComponent({})
        with pytest.raises(ValueError, match="tenant_id"):
            async with comp:
                pass

    @pytest.mark.asyncio
    async def test_sources_parsed_from_config(self, tmp_path):
        """SourceConfig is built from config code_paths, loader_sources, skill_paths."""
        config = {
            "tenant_id": "t",
            "code_paths": ["/src"],
            "loader_sources": ["file://doc.pdf"],
            "skill_paths": ["/skills"],
            "output_dir": str(tmp_path),
        }
        async with GraphIndexComponent(config) as comp:
            assert comp._sources is not None
            assert "/src" in comp._sources.code_paths
            assert "file://doc.pdf" in comp._sources.loader_sources
            assert "/skills" in comp._sources.skill_paths

    @pytest.mark.asyncio
    async def test_ignore_file_passed_to_builder(self, tmp_path):
        """ignore_file config key must be passed to the builder."""
        ignore_file = tmp_path / ".graphindexignore"
        ignore_file.write_text("*.log\n")
        config = {
            "tenant_id": "t",
            "output_dir": str(tmp_path),
            "ignore_file": str(ignore_file),
        }
        async with GraphIndexComponent(config) as comp:
            assert comp._builder._ignore_spec is not None


# ---------------------------------------------------------------------------
# TestPyprojectExtra
# ---------------------------------------------------------------------------


class TestPyprojectExtra:
    """Tests verifying the [graphindex] extra in packages/ai-parrot/pyproject.toml."""

    def _load_pyproject(self) -> dict:
        """Load and parse the pyproject.toml file."""
        import tomllib
        from pathlib import Path

        # Walk up from this test file to find the pyproject.toml
        # Test is in packages/ai-parrot-tools/tests/graphindex/
        # pyproject.toml is in packages/ai-parrot/
        here = Path(__file__).parent
        for _ in range(6):
            candidate = here / "packages" / "ai-parrot" / "pyproject.toml"
            if candidate.exists():
                with open(candidate, "rb") as f:
                    return tomllib.load(f)
            here = here.parent

        # Fallback: absolute path relative to repo root
        candidates = [
            Path("/home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-187-graphindex/packages/ai-parrot/pyproject.toml"),
            Path("/home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/pyproject.toml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                with open(candidate, "rb") as f:
                    return tomllib.load(f)

        pytest.skip("Could not locate packages/ai-parrot/pyproject.toml")

    def test_graphindex_extra_exists(self):
        """pyproject.toml must have a [graphindex] optional dependency group."""
        data = self._load_pyproject()
        extras = data.get("project", {}).get("optional-dependencies", {})
        assert "graphindex" in extras, "Missing [graphindex] extra in pyproject.toml"

    def test_graphindex_extra_has_required_deps(self):
        """[graphindex] extra must include rustworkx, tree-sitter, tree-sitter-languages, pathspec."""
        data = self._load_pyproject()
        deps = data["project"]["optional-dependencies"]["graphindex"]
        dep_names = [d.split(">=")[0].split("==")[0].strip() for d in deps]

        assert any("rustworkx" in d for d in dep_names), "Missing rustworkx"
        assert any("tree-sitter" in d and "languages" not in d for d in dep_names), "Missing tree-sitter"
        assert any("tree-sitter-languages" in d for d in dep_names), "Missing tree-sitter-languages"
        assert any("pathspec" in d for d in dep_names), "Missing pathspec"

    def test_graphindex_extra_no_faiss(self):
        """[graphindex] extra must NOT include faiss-cpu (already in core)."""
        data = self._load_pyproject()
        deps = data["project"]["optional-dependencies"]["graphindex"]
        assert not any("faiss" in d for d in deps), (
            "faiss-cpu must not be in [graphindex] extra — it is already in core dependencies"
        )
