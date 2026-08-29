"""G8 one-way import-rule guard for ``parrot.outputs.a2ui.adapters``,
``parrot.outputs.a2ui.catalog.basic``, and ``parrot.outputs.a2ui.compat``.

Mirrors ``tests/outputs/a2ui/recipes/test_import_rule.py``: the adapters
subpackage bridges legacy output models to A2UI envelopes, so it is exactly the
place where an agent/client import would sneak back into the a2ui core.
Extended (TASK-2548, spec §7 "ampliar adapters/test_import_rule.py para cubrir
catalog/basic/ y compat.py") to the two other TASK-2532+ modules explicitly
named by G8's invariant that had no dedicated guard yet: the vendored Basic
Catalog spec loader (``catalog/basic/``, which resolves ``$ref``s from
upstream JSON and must never itself reach back into agent/client territory)
and the legacy-dialect-to-v1.0 normalizer (``compat.py``, which only
``serialization.deserialize`` may call — spec §7 "Compat sólo de entrada").
"""

from pathlib import Path

_A2UI_DIR = Path(__file__).resolve().parents[4] / "src" / "parrot" / "outputs" / "a2ui"
_ADAPTERS_DIR = _A2UI_DIR / "adapters"
_CATALOG_BASIC_DIR = _A2UI_DIR / "catalog" / "basic"
_COMPAT_FILE = _A2UI_DIR / "compat.py"

_FORBIDDEN_IMPORTS = (
    "parrot.tools.dataset_manager",
    "parrot.bots",
    "parrot.clients",
)


def _python_files():
    assert _ADAPTERS_DIR.is_dir(), f"expected adapters subpackage at {_ADAPTERS_DIR}"
    yield from _ADAPTERS_DIR.rglob("*.py")


def _forbidden_import_offenders(paths) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            for forbidden in _FORBIDDEN_IMPORTS:
                if forbidden in stripped:
                    offenders.append(f"{path}:{lineno}: {stripped}")
    return offenders


def _run_import_probe(src_dir: Path, import_stmt: str, sanity_assert: str) -> None:
    """Run ``import_stmt`` in a fresh interpreter and assert no forbidden module loaded.

    Fresh interpreter so module state from other tests cannot mask a violation.
    """
    import subprocess
    import sys

    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(src_dir)!r})\n"
        f"{import_stmt}\n"
        f"{sanity_assert}\n"
        "forbidden = ('parrot.tools.dataset_manager', 'parrot.bots', 'parrot.clients')\n"
        "loaded = [m for m in sys.modules "
        "if any(m == f or m.startswith(f + '.') for f in forbidden)]\n"
        "assert not loaded, f'forbidden modules loaded: {loaded}'\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr


def test_adapters_subpackage_has_no_forbidden_imports():
    offenders = _forbidden_import_offenders(_python_files())
    assert not offenders, "G8 one-way import-rule violation in parrot.outputs.a2ui.adapters:\n" + "\n".join(offenders)


def test_adapters_subpackage_importable_without_agents_or_clients():
    _run_import_probe(
        _ADAPTERS_DIR.parents[3],  # .../src
        "from parrot.outputs.a2ui.adapters import infographic_response_to_envelope",
        "assert infographic_response_to_envelope is not None",
    )


def test_catalog_basic_has_no_forbidden_imports():
    assert _CATALOG_BASIC_DIR.is_dir(), f"expected catalog/basic subpackage at {_CATALOG_BASIC_DIR}"
    offenders = _forbidden_import_offenders(_CATALOG_BASIC_DIR.rglob("*.py"))
    assert not offenders, "G8 one-way import-rule violation in parrot.outputs.a2ui.catalog.basic:\n" + "\n".join(
        offenders
    )


def test_catalog_basic_importable_without_agents_or_clients():
    _run_import_probe(
        _CATALOG_BASIC_DIR.parents[4],  # .../src
        "from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID, load_spec",
        "assert BASIC_CATALOG_ID and load_spec is not None",
    )


def test_compat_has_no_forbidden_imports():
    assert _COMPAT_FILE.is_file(), f"expected compat module at {_COMPAT_FILE}"
    offenders = _forbidden_import_offenders([_COMPAT_FILE])
    assert not offenders, "G8 one-way import-rule violation in parrot.outputs.a2ui.compat:\n" + "\n".join(offenders)


def test_compat_importable_without_agents_or_clients():
    _run_import_probe(
        _COMPAT_FILE.parents[3],  # .../src
        "from parrot.outputs.a2ui.compat import is_legacy_envelope, normalize_legacy",
        "assert is_legacy_envelope is not None and normalize_legacy is not None",
    )
