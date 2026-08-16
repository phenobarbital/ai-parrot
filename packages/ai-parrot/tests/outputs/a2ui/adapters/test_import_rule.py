"""G8 one-way import-rule guard for ``parrot.outputs.a2ui.adapters``.

Mirrors ``tests/outputs/a2ui/recipes/test_import_rule.py``: the adapters
subpackage bridges legacy output models to A2UI envelopes, so it is exactly the
place where an agent/client import would sneak back into the a2ui core.
"""

from pathlib import Path

_ADAPTERS_DIR = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "parrot"
    / "outputs"
    / "a2ui"
    / "adapters"
)

_FORBIDDEN_IMPORTS = (
    "parrot.tools.dataset_manager",
    "parrot.bots",
    "parrot.clients",
)


def _python_files():
    assert _ADAPTERS_DIR.is_dir(), f"expected adapters subpackage at {_ADAPTERS_DIR}"
    yield from _ADAPTERS_DIR.rglob("*.py")


def test_adapters_subpackage_has_no_forbidden_imports():
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
        "G8 one-way import-rule violation in parrot.outputs.a2ui.adapters:\n"
        + "\n".join(offenders)
    )


def test_adapters_subpackage_importable_without_agents_or_clients():
    # Fresh interpreter so module state from other tests cannot mask a violation.
    import subprocess
    import sys

    src_dir = _ADAPTERS_DIR.parents[3]  # .../src
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(src_dir)!r})\n"
        "from parrot.outputs.a2ui.adapters import infographic_response_to_envelope\n"
        "assert infographic_response_to_envelope is not None\n"
        "forbidden = ('parrot.tools.dataset_manager', 'parrot.bots', 'parrot.clients')\n"
        "loaded = [m for m in sys.modules "
        "if any(m == f or m.startswith(f + '.') for f in forbidden)]\n"
        "assert not loaded, f'forbidden modules loaded: {loaded}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
