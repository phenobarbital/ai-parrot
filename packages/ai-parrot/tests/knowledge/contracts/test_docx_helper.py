"""Tests for the public bookstore DOCX helper (TASK-3032).

The contracts library needs the same conversion the bookstore already
performs, so ``Bookstore._docx_to_markdown`` was extracted into a public
module-level ``docx_to_markdown``; the private method now delegates. These
tests pin that equivalence, the lazy-import error and the empty-content
guard.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import types
from pathlib import Path

import pytest

from parrot.knowledge.bookstore.library import (
    Bookstore,
    BookstoreError,
    docx_to_markdown,
)


class _FakeLoader:
    """Stand-in for ``MSWordLoader`` recording its conversion calls."""

    instances: list["_FakeLoader"] = []

    def __init__(self, path: str) -> None:
        self.path = path
        self.calls: list[Path] = []
        self.thread_names: list[str] = []
        _FakeLoader.instances.append(self)

    def docx_to_markdown(self, path: Path) -> str:
        self.calls.append(path)
        self.thread_names.append(__import__("threading").current_thread().name)
        return f"# {Path(path).stem}\n\nBody."


@pytest.fixture()
def fake_loaders(monkeypatch):
    """Install a fake ``parrot_loaders.docx`` module."""
    _FakeLoader.instances.clear()
    package = types.ModuleType("parrot_loaders")
    module = types.ModuleType("parrot_loaders.docx")
    module.MSWordLoader = _FakeLoader
    package.docx = module
    monkeypatch.setitem(sys.modules, "parrot_loaders", package)
    monkeypatch.setitem(sys.modules, "parrot_loaders.docx", module)
    return _FakeLoader


@pytest.fixture()
def missing_loaders(monkeypatch):
    """Make ``parrot_loaders.docx`` unimportable."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("no module named parrot_loaders")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "parrot_loaders", raising=False)
    monkeypatch.delitem(sys.modules, "parrot_loaders.docx", raising=False)


def _bookstore() -> Bookstore:
    """A Bookstore instance used only for its bound private method."""
    return Bookstore.__new__(Bookstore)


def test_public_helper_is_async_and_exported():
    assert inspect.iscoroutinefunction(docx_to_markdown)
    assert docx_to_markdown.__module__ == "parrot.knowledge.bookstore.library"


def test_private_method_delegates_to_the_public_helper():
    source = inspect.getsource(Bookstore._docx_to_markdown)
    assert "return await docx_to_markdown(path)" in source


@pytest.mark.asyncio
async def test_helper_and_private_method_return_identical_markdown(fake_loaders, tmp_path):
    path = tmp_path / "acme-msa.docx"
    path.write_bytes(b"not really a docx")

    public = await docx_to_markdown(path)
    private = await _bookstore()._docx_to_markdown(path)

    assert public == private == "# acme-msa\n\nBody."
    assert [loader.path for loader in fake_loaders.instances] == [str(path), str(path)]


@pytest.mark.asyncio
async def test_conversion_is_offloaded_to_a_thread(fake_loaders, tmp_path):
    path = tmp_path / "acme-msa.docx"
    path.write_bytes(b"x")

    await docx_to_markdown(path)

    loader = fake_loaders.instances[-1]
    assert loader.calls == [path]
    assert loader.thread_names[0] != asyncio.current_task().get_name()
    assert "MainThread" not in loader.thread_names[0]


@pytest.mark.asyncio
async def test_missing_loaders_raises_the_same_actionable_error(missing_loaders, tmp_path):
    path = tmp_path / "acme-msa.docx"
    path.write_bytes(b"x")

    with pytest.raises(BookstoreError, match="ai-parrot-loaders") as public_error:
        await docx_to_markdown(path)
    with pytest.raises(BookstoreError, match="ai-parrot-loaders") as private_error:
        await _bookstore()._docx_to_markdown(path)

    assert str(public_error.value) == str(private_error.value)
    assert isinstance(public_error.value.__cause__, ImportError)


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", ["", "   \n\t "])
async def test_empty_content_raises_the_same_error(monkeypatch, tmp_path, fake_loaders, empty):
    monkeypatch.setattr(_FakeLoader, "docx_to_markdown", lambda self, path: empty)
    path = tmp_path / "blank.docx"
    path.write_bytes(b"x")

    with pytest.raises(BookstoreError, match="No readable content found in blank.docx"):
        await docx_to_markdown(path)
    with pytest.raises(BookstoreError, match="No readable content found in blank.docx"):
        await _bookstore()._docx_to_markdown(path)


@pytest.mark.asyncio
async def test_conversion_errors_propagate_unchanged(monkeypatch, tmp_path, fake_loaders):
    def explode(self, path):
        raise RuntimeError("corrupt docx")

    monkeypatch.setattr(_FakeLoader, "docx_to_markdown", explode)
    path = tmp_path / "corrupt.docx"
    path.write_bytes(b"x")

    with pytest.raises(RuntimeError, match="corrupt docx"):
        await docx_to_markdown(path)
    with pytest.raises(RuntimeError, match="corrupt docx"):
        await _bookstore()._docx_to_markdown(path)
