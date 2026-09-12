from pathlib import Path

from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files

SECTION = """## Scope
x
## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/a.py` | CREATE | a |
| `tests/test_a.py` | CREATE | t |
| `pkg/a.py` | MODIFY | dup |

## Codebase Contract
- `not/this.py`
"""


def test_parse_task_files_from_template_section():
    assert parse_task_files(SECTION) == ["pkg/a.py", "tests/test_a.py"]
    assert parse_task_files("no section") == []


def test_fidelity_rejects_unexpected_and_sdd():
    r = check_fidelity(["a.py"], ["a.py", "b.py", "sdd/x.json"])
    assert not r.ok and r.unexpected == ["b.py", "sdd/x.json"] and r.sdd_touched == ["sdd/x.json"]
    assert check_fidelity(["a.py"], ["a.py"]).ok


_BANNED_CFG = '[lint]\nselect = ["TID251"]\n[lint.flake8-tidy-imports.banned-api]\n"requests".msg = "use aiohttp"\n"httpx".msg = "use aiohttp"\n'


def _sandbox(tmp_path: Path) -> Path:
    (tmp_path / "ruff.toml").write_text(_BANNED_CFG)  # ruff discovers the nearest ruff.toml above cwd
    (tmp_path / "pkg").mkdir()
    return tmp_path


async def test_check_banned_imports_flags_requests(tmp_path):
    root = _sandbox(tmp_path)
    (root / "pkg" / "a.py").write_text("import requests\n")
    lines = await check_banned_imports(str(root), ["pkg/a.py"])
    assert len(lines) == 1 and lines[0].startswith("pkg/a.py:1:")


async def test_check_banned_imports_clean_and_empty(tmp_path):
    root = _sandbox(tmp_path)
    (root / "pkg" / "a.py").write_text("x = 1\n")
    # Clean file → []
    lines = await check_banned_imports(str(root), ["pkg/a.py"])
    assert lines == []
    # Empty changed list → [] (ruff not spawned)
    lines = await check_banned_imports(str(root), [], ruff_bin="/nonexistent")
    assert lines == []


async def test_check_banned_imports_skips_non_python(tmp_path):
    root = _sandbox(tmp_path)
    # Non-Python files → [] without spawning ruff
    lines = await check_banned_imports(str(root), ["README.md", "cfg.toml"], ruff_bin="/nonexistent")
    assert lines == []


async def test_check_banned_imports_fails_closed_without_ruff(tmp_path):
    root = _sandbox(tmp_path)
    (root / "pkg" / "a.py").write_text("x = 1\n")
    lines = await check_banned_imports(str(root), ["pkg/a.py"], ruff_bin="/nonexistent/ruff")
    assert lines and lines[0].startswith("ruff:")
