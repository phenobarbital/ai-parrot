"""Verification tests for the FEAT-462 integration deletion + dependency
cleanup.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 7 + Module 8.
Task: TASK-2476.
"""

from __future__ import annotations

import pytest


class TestIntegrationsDeleted:
    def test_openlit_integration_not_importable(self) -> None:
        with pytest.raises(ImportError):
            import parrot.observability.openlit_integration  # noqa: F401

    def test_traceloop_integration_not_importable(self) -> None:
        with pytest.raises(ImportError):
            import parrot.observability.traceloop_integration  # noqa: F401

    def test_no_traceloop_in_init_all(self) -> None:
        import parrot.observability as obs

        assert "init_traceloop" not in obs.__all__
        assert "setup_traceloop" not in obs.__all__
        assert "shutdown_traceloop" not in obs.__all__

    def test_init_traceloop_raises_import_error(self) -> None:
        with pytest.raises(ImportError):
            from parrot.observability import init_traceloop  # noqa: F401

    def test_setup_traceloop_raises_import_error(self) -> None:
        with pytest.raises(ImportError):
            from parrot.observability import setup_traceloop  # noqa: F401

    def test_no_remaining_references_in_src(self) -> None:
        """No importable-code reference to the deleted modules remains in
        packages/ai-parrot/src/ (docstring mentions of the removal itself
        are fine)."""
        import pathlib

        src_root = (
            pathlib.Path(__file__).resolve().parents[3] / "src" / "parrot"
        )
        assert src_root.is_dir(), src_root
        offenders = []
        for path in src_root.rglob("*.py"):
            text = path.read_text()
            for needle in (
                "openlit_integration",
                "traceloop_integration",
                "init_openlit",
                "init_traceloop",
                "setup_traceloop",
                "shutdown_traceloop",
            ):
                if needle in text:
                    offenders.append((path, needle))
        # The __init__.py docstring explicitly documents the removal — allow
        # that single, expected mention; fail on anything else.
        unexpected = [
            (p, n) for p, n in offenders if p.name != "__init__.py"
        ]
        assert not unexpected, f"Unexpected references remain: {unexpected}"


class TestDependencyCleanup:
    def test_no_conflicting_groups_for_openlit(self) -> None:
        """Workspace pyproject.toml's tool.uv.conflicts has no entry
        referencing the observability-openlit extra."""
        import pathlib
        import tomllib

        workspace_root = pathlib.Path(__file__).resolve().parents[5]
        pyproject = workspace_root / "pyproject.toml"
        assert pyproject.is_file(), pyproject
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        conflicts = data["tool"]["uv"]["conflicts"]
        for pair in conflicts:
            for entry in pair:
                assert entry.get("extra") != "observability-openlit", (
                    f"Found observability-openlit in conflicts: {pair}"
                )

    def test_extras_still_exist_with_empty_deps(self) -> None:
        """observability-openlit / observability-traceloop extras still
        exist (backward compat) but no longer pull the SDKs."""
        import pathlib
        import tomllib

        pkg_root = pathlib.Path(__file__).resolve().parents[3]
        pyproject = pkg_root / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        extras = data["project"]["optional-dependencies"]
        assert "observability-openlit" in extras
        assert "observability-traceloop" in extras
        for dep in extras["observability-openlit"]:
            assert "openlit" not in dep.lower()
        for dep in extras["observability-traceloop"]:
            assert "traceloop" not in dep.lower()

    def test_openlit_not_a_dependency_anywhere(self) -> None:
        """No package's pyproject.toml declares openlit or traceloop-sdk."""
        import pathlib

        workspace_root = pathlib.Path(__file__).resolve().parents[5]
        offenders = []
        for pyproject in workspace_root.glob("**/pyproject.toml"):
            if ".venv" in pyproject.parts or "node_modules" in pyproject.parts:
                continue
            text = pyproject.read_text()
            if '"openlit' in text or "'openlit" in text:
                offenders.append(pyproject)
            if '"traceloop-sdk' in text or "'traceloop-sdk" in text:
                offenders.append(pyproject)
        assert not offenders, f"openlit/traceloop-sdk still declared in: {offenders}"
