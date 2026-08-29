"""G8 one-way import-rule guard for ``parrot.outputs.a2ui.adapters``,
``parrot.outputs.a2ui.catalog.basic``, ``parrot.outputs.a2ui.compat``, and
``parrot.outputs.a2ui.runtime``.

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

Extended again (FEAT-469 TASK-2570) to ``runtime/``. Unlike the three guards
above, ``runtime/adapters.py`` *does* need ``parrot.tools``/``parrot.memory``
— it is the adapter binding the runtime's ``Protocol``s to those subsystems.
G8 is preserved by importing them lazily (inside method bodies) or under
``if TYPE_CHECKING:`` — so the ``runtime/`` guard below is AST-based and
checks only true *module-level* (unconditional, top-of-file) imports, not
line text: a naive substring/line scanner would false-positive on every
correctly-scoped lazy import in ``adapters.py``.
"""

import ast
from pathlib import Path

_A2UI_DIR = Path(__file__).resolve().parents[4] / "src" / "parrot" / "outputs" / "a2ui"
_ADAPTERS_DIR = _A2UI_DIR / "adapters"
_CATALOG_BASIC_DIR = _A2UI_DIR / "catalog" / "basic"
_COMPAT_FILE = _A2UI_DIR / "compat.py"
_RUNTIME_DIR = _A2UI_DIR / "runtime"

_FORBIDDEN_IMPORTS = (
    "parrot.tools.dataset_manager",
    "parrot.bots",
    "parrot.clients",
)

#: G8's full invariant for `runtime/`: no module-level `parrot.bots`/
#: `parrot.clients`/`parrot.tools`/`parrot.memory` import (TASK-2569/2570).
_RUNTIME_FORBIDDEN_MODULE_PREFIXES = (
    "parrot.bots",
    "parrot.clients",
    "parrot.tools",
    "parrot.memory",
)


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for an `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`) guard."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _module_level_forbidden_offenders(paths, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    """AST-based: only true module-level imports (not lazy, not TYPE_CHECKING-guarded)."""
    offenders: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # top-level statements ONLY — skips If/FunctionDef bodies
            if isinstance(node, ast.If) and _is_type_checking_test(node.test):
                continue  # `if TYPE_CHECKING:` — erased at runtime, G8-exempt
            if isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == p or alias.name.startswith(p + ".") for p in forbidden_prefixes):
                        offenders.append(f"{path}:{node.lineno}: import {alias.name}")
                continue
            else:
                continue
            if any(module_name == p or module_name.startswith(p + ".") for p in forbidden_prefixes):
                offenders.append(f"{path}:{node.lineno}: from {module_name} import ...")
    return offenders


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


def _run_import_probe(
    src_dir: Path,
    import_stmt: str,
    sanity_assert: str,
    forbidden: tuple[str, ...] = ("parrot.tools.dataset_manager", "parrot.bots", "parrot.clients"),
) -> None:
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
        f"forbidden = {forbidden!r}\n"
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


def test_runtime_has_no_forbidden_module_level_imports():
    """G8 (FEAT-469): no module-level parrot.bots/clients/tools/memory import
    anywhere under `runtime/` — lazy (inside a method) and TYPE_CHECKING-guarded
    imports are exempt (that IS the sanctioned pattern, per `adapters.py`)."""
    assert _RUNTIME_DIR.is_dir(), f"expected runtime subpackage at {_RUNTIME_DIR}"
    offenders = _module_level_forbidden_offenders(_RUNTIME_DIR.rglob("*.py"), _RUNTIME_FORBIDDEN_MODULE_PREFIXES)
    assert not offenders, "G8 one-way import-rule violation in parrot.outputs.a2ui.runtime:\n" + "\n".join(offenders)


def test_runtime_importable_without_agents_tools_or_memory():
    """Proves the lazy imports in `adapters.py` really are lazy: merely importing
    `runtime` must not load `parrot.tools`/`parrot.memory` as a side effect."""
    _run_import_probe(
        _RUNTIME_DIR.parents[3],  # .../src
        "from parrot.outputs.a2ui.runtime import A2UIRuntime, FunctionExecutor, SurfaceStateStore, PendingCallRegistry\n"
        "from parrot.outputs.a2ui.runtime.adapters import ConversationMemorySurfaceStore, ToolManagerExecutor",
        "assert A2UIRuntime is not None and ToolManagerExecutor is not None",
        forbidden=_RUNTIME_FORBIDDEN_MODULE_PREFIXES,
    )
