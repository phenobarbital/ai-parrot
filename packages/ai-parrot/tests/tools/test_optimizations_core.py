"""Core ``parrot.tools.optimizations`` package (FEAT-633 C35)."""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

MOVED = ("base", "models", "policy", "inspection_models", "inspection", "reader")


def test_core_import_without_parrot_tools(monkeypatch) -> None:
    """The core reader imports even when ai-parrot-tools is unavailable."""
    monkeypatch.setitem(sys.modules, "parrot_tools", None)
    reader = importlib.import_module("parrot.tools.optimizations.reader")
    assert hasattr(reader, "BoundedSourceToolkit")


@pytest.mark.parametrize("name", MOVED)
def test_legacy_path_is_the_same_module(name: str) -> None:
    """The legacy parrot_tools path aliases the very same module object."""
    pytest.importorskip("parrot_tools")
    legacy = importlib.import_module(f"parrot_tools.tool_optimizations.{name}")
    assert legacy is importlib.import_module(f"parrot.tools.optimizations.{name}")


def test_policy_imports_without_fcntl() -> None:
    """policy.py has no module-level fcntl dependency (checked in a clean interpreter)."""
    code = (
        "import sys, parrot.tools\n"
        "sys.modules['fcntl'] = None\n"
        "import parrot.tools.optimizations.policy as p; assert p.WorktreeLock"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_worktree_lock_excludes_second_holder(tmp_path: Path) -> None:
    """A second lock on the same file times out while the first is held."""
    from parrot.tools.optimizations.policy import LockTimeoutError, WorktreeLock

    path = tmp_path / "x.lock"
    async with WorktreeLock(path, 1.0):
        with pytest.raises(LockTimeoutError):
            async with WorktreeLock(path, 0.2):
                pass
    async with WorktreeLock(path, 1.0):
        pass


def test_bounded_source_template_points_at_core() -> None:
    """The packaged template names the core class and has no requires_dist."""
    import parrot.mcp as mcp_pkg

    text = (Path(mcp_pkg.__file__).parent / "_toolkit_templates" / "bounded-source.yaml").read_text()
    assert "class: parrot.tools.optimizations.reader.BoundedSourceToolkit" in text
    assert "requires_dist" not in text
    assert "requires_pip" not in text
