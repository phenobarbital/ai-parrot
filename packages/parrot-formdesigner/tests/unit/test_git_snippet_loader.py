"""Unit tests for GitSnippetLoader — FEAT-459 / TASK-3164."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from parrot_formdesigner.core.snippets import SnippetIntegrityError, SnippetTierUnavailableError
from parrot_formdesigner.services.event_registry import _clear_event_registry_for_tests
from parrot_formdesigner.services.snippets.git_loader import GitSnippetLoader


@pytest.fixture(autouse=True)
def _clear_registry():
    _clear_event_registry_for_tests()
    yield
    _clear_event_registry_for_tests()


def _write_bundle(
    root: Path,
    name: str,
    *,
    handler_ref: str,
    tier: str = "pure",
    source: str = "def run(ctx): return {}",
) -> None:
    bundle_dir = root / name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "run.py").write_text(source)
    sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "handler_ref": handler_ref,
                "event": "onBeforeSubmit",
                "python_sha256": sha256,
                "manifest": {"tier": tier},
            }
        )
    )


@pytest.fixture
def snippet_root(tmp_path: Path) -> Path:
    _write_bundle(tmp_path, "pure_example", handler_ref="pure_example.onBeforeSubmit")
    return tmp_path


async def _fake_project(ctx, bundle):  # pragma: no cover — not reached in these tests
    raise AssertionError("should not execute")


async def _fake_execute(bundle, ctx):  # pragma: no cover — not reached in these tests
    raise AssertionError("should not execute")


async def test_discover_returns_valid_bundle(snippet_root: Path) -> None:
    loader = GitSnippetLoader(snippet_root)
    bundles = await loader.discover()
    assert len(bundles) == 1
    assert bundles[0].handler_ref == "pure_example.onBeforeSubmit"
    assert bundles[0].tenant is None


async def test_git_loader_rejects_hash_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path, "bad", handler_ref="bad.onBeforeSubmit")
    # Corrupt the source AFTER writing a valid hash for the original content.
    (tmp_path / "bad" / "run.py").write_text("def run(ctx): return {'tampered': True}")
    loader = GitSnippetLoader(tmp_path)
    with pytest.raises(SnippetIntegrityError):
        await loader.discover()


async def test_git_loader_rejects_tier3_without_gvisor(tmp_path: Path) -> None:
    _write_bundle(tmp_path, "brokered", handler_ref="b.onBeforeSubmit", tier="brokered")
    loader = GitSnippetLoader(tmp_path)

    with pytest.raises(SnippetTierUnavailableError):
        await loader.register_all(
            project_context=_fake_project, execute=_fake_execute, gvisor_available=lambda: False
        )


async def test_git_loader_duplicate_ref_raises(tmp_path: Path) -> None:
    """Two bundles claiming the SAME handler_ref must fail registration."""
    _write_bundle(tmp_path, "one", handler_ref="dup.onBeforeSubmit")
    _write_bundle(tmp_path, "two", handler_ref="dup.onBeforeSubmit")
    loader = GitSnippetLoader(tmp_path)

    with pytest.raises(ValueError):
        await loader.register_all(project_context=_fake_project, execute=_fake_execute)


async def test_resolve_current_returns_none_for_unknown_key(snippet_root: Path) -> None:
    loader = GitSnippetLoader(snippet_root)
    await loader.discover()
    result = await loader.resolve_current(tenant=None, handler_ref="nonexistent.onBeforeSubmit")
    assert result is None
