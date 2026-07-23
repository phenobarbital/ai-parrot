"""G8 one-way import-rule guard for `parrot.outputs.a2ui.recipes` (FEAT-324, Module 1).

Mirrors the static-scan style of `packages/ai-parrot/tests/outputs/a2ui/test_no_exec.py`:
`parrot.outputs.a2ui.recipes` must never (transitively) import
`parrot.tools.dataset_manager`, `parrot.bots`, or `parrot.clients`.
"""

from pathlib import Path

_RECIPES_DIR = Path(__file__).resolve().parents[4] / "src" / "parrot" / "outputs" / "a2ui" / "recipes"

_FORBIDDEN_IMPORTS = (
    "parrot.tools.dataset_manager",
    "parrot.bots",
    "parrot.clients",
)


def _python_files():
    assert _RECIPES_DIR.is_dir(), f"expected recipes subpackage at {_RECIPES_DIR}"
    yield from _RECIPES_DIR.rglob("*.py")


def test_recipes_subpackage_has_no_forbidden_imports():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for forbidden in _FORBIDDEN_IMPORTS:
                if forbidden in stripped:
                    offenders.append(f"{path}:{lineno}: {stripped}")
    assert not offenders, (
        "G8 one-way import-rule violation in parrot.outputs.a2ui.recipes:\n"
        + "\n".join(offenders)
    )


def test_recipes_subpackage_importable_without_dataset_manager():
    # Importing the subpackage in a fresh interpreter must not transitively
    # pull in DatasetManager, agents, or LLM clients. Runs in a subprocess so
    # module state from other tests in this session cannot mask a violation.
    # ``src`` is prepended explicitly (mirroring packages/ai-parrot/conftest.py)
    # so this resolves against THIS worktree's src layout, not whatever path
    # an editable install's .pth file happens to point at.
    import subprocess
    import sys

    src_dir = _RECIPES_DIR.parents[3]  # .../src
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(src_dir)!r})\n"
        "import parrot.outputs.a2ui.recipes as recipes_pkg\n"
        "assert recipes_pkg.InfographicRecipe is not None\n"
        "forbidden = ('parrot.tools.dataset_manager', 'parrot.bots', 'parrot.clients')\n"
        "loaded = [m for m in sys.modules if any(m == f or m.startswith(f + '.') for f in forbidden)]\n"
        "assert not loaded, f'forbidden modules loaded: {loaded}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
