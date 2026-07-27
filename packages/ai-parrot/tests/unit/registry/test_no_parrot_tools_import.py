"""Import-hygiene test (FEAT-379): the StoreRouter FAN_OUT path and
AbstractBot's multi-store wiring must never *statically import*
``parrot_tools`` — not even under ``TYPE_CHECKING``. They type against
the narrow ``MultiSearch`` protocol instead (``parrot.models.MultiSearch``).

Scope note: a blanket repo-wide substring scan for ``"parrot_tools"`` is
NOT used here — ``parrot/tools/__init__.py`` implements a long-standing,
unrelated MetaPath-finder that dynamically redirects
``parrot.tools.<name>`` imports to ``parrot_tools.<name>`` at runtime
(predates this feature; several other core files reference the package
name only in docstrings/comments describing that mechanism). Rewriting
that dynamic-loading pattern is out of scope for FEAT-379, whose
decoupling requirement is specifically about ``StoreRouter`` and
``AbstractBot`` no longer statically importing the old
``MultiStoreSearchTool``. This test therefore checks those two modules
for real ``import parrot_tools`` / ``from parrot_tools ...`` statements
(AST-based, so it also flags TYPE_CHECKING-guarded imports).
"""
import ast
import pathlib

_CORE_MODULES = (
    "src/parrot/registry/routing/store_router.py",
    "src/parrot/bots/abstract.py",
)


def _imports_parrot_tools(path: pathlib.Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "parrot_tools" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "parrot_tools":
                return True
    return False


def test_store_router_and_abstract_bot_never_import_parrot_tools():
    """StoreRouter FAN_OUT and AbstractBot type only against MultiSearch."""
    ai_parrot_root = pathlib.Path(__file__).resolve().parents[3]
    offenders = [
        rel
        for rel in _CORE_MODULES
        if _imports_parrot_tools(ai_parrot_root / rel)
    ]
    assert offenders == [], f"core files still import parrot_tools: {offenders}"
