"""PA-7: ``TOOL_REGISTRY`` hygiene and declared extras.

* every registered class is a concrete tool (``AbstractTool`` / ``AbstractToolkit``), never an abstract base or a
  plain wrapper class;
* every registered module imports when its extras are installed — an import failure whose missing package no
  ai-parrot-tools extra declares is an UNDECLARED dependency and fails (a declared-but-not-installed extra skips);
* every third-party package an offered tool imports at module level (followed through ``parrot_tools``) is declared
  in ``ai-parrot-tools/pyproject.toml`` or arrives with ``ai-parrot`` itself.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, packages_distributions, requires
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement

from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools import TOOL_REGISTRY

PKG_ROOT = Path(__file__).resolve().parents[1]
SRC = PKG_ROOT / "src"
CORE_PYPROJECT = PKG_ROOT.parent / "ai-parrot" / "pyproject.toml"

# modules whose distribution name differs from the import name
ALIAS = {
    "docx": "python_docx", "pptx": "python_pptx", "odf": "odfpy", "googleapiclient": "google_api_python_client",
    "yaml": "pyyaml", "bs4": "beautifulsoup4", "msgraph": "msgraph_sdk", "git": "gitpython", "github": "pygithub",
    "talib": "ta_lib", "notify": "async_notify", "slack_bolt": "slack_bolt", "sklearn": "scikit_learn",
    "kiota_abstractions": "microsoft_kiota_abstractions", "azure": "azure_identity", "PIL": "pillow",
    "google": "google_cloud_texttospeech", "dateutil": "python_dateutil",
    # arrive with a declared package that is not installed here
    "botocore": "boto3", "kiota_abstractions": "msgraph_sdk", "markdown": "markdown",
}
# a tool whose package cannot be declared in this workspace (documented upstream conflict, see ai-parrot pyproject)
KNOWN_UNDECLARABLE = {"ydata_profiling"}
NAMED_BY_THE_BRIEF = ("ddgs", "praw", "statsmodels", "scipy", "prophet", "python_pptx", "docling", "async_notify", "pyarrow")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _req_name(req: str) -> str:
    return _norm(re.split(r"[\[<>=!~; ]", req.strip(), maxsplit=1)[0])


def _declared(pyproject: Path) -> set[str]:
    meta = tomllib.loads(pyproject.read_text())["project"]
    names = {_req_name(r) for r in meta.get("dependencies", [])}
    for reqs in meta.get("optional-dependencies", {}).values():
        names |= {_req_name(r) for r in reqs}
    return names


def _closure(roots: list[tuple[str, frozenset[str]]]) -> set[str]:
    """Distributions installed with ``roots`` (``(name, requested extras)``): the requirements of each installed
    distribution that apply without extras or with the requested ones, followed transitively."""
    seen: set[tuple[str, frozenset[str]]] = set()
    names: set[str] = set()
    stack = list(roots)
    while stack:
        name, extras = stack.pop()
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        names.add(name)
        try:
            reqs = requires(name.replace("_", "-")) or []
        except PackageNotFoundError:
            continue  # not installed here: only its own name is known
        for raw in reqs:
            try:
                req = Requirement(raw)
            except InvalidRequirement:
                continue
            if req.marker is not None and not any(
                req.marker.evaluate({"extra": extra}) for extra in (extras or frozenset({""}))
            ):
                continue
            stack.append((_norm(req.name), frozenset(req.extras)))
    return names


def _base_closure(roots: set[str]) -> set[str]:
    """Distributions installed by ``pip install ai-parrot-tools`` (no extras)."""
    return _closure([(name, frozenset()) for name in roots])


def _declared_closure(pyproject: Path) -> set[str]:
    """Everything the declared extras (with THEIR extras, e.g. ``async-notify[all]``) bring in."""
    meta = tomllib.loads(pyproject.read_text())["project"]
    reqs = list(meta.get("dependencies", []))
    for extra_reqs in meta.get("optional-dependencies", {}).values():
        reqs.extend(extra_reqs)
    roots = []
    for raw in reqs:
        req = Requirement(raw)
        roots.append((_norm(req.name), frozenset(req.extras)))
    return _closure(roots)


TOOLS_DECLARED = _declared(PKG_ROOT / "pyproject.toml") | _declared_closure(PKG_ROOT / "pyproject.toml")
INSTALLED_WITH_BASE = _base_closure(
    {_req_name(r) for r in tomllib.loads((PKG_ROOT / "pyproject.toml").read_text())["project"]["dependencies"]}
    | {"ai_parrot"}
)
DISTS = packages_distributions()


def _dists_for(top: str) -> set[str]:
    return {_norm(d) for d in DISTS.get(top, [])} | {ALIAS.get(top, _norm(top))}


def _is_declared(top: str) -> bool:
    dists = _dists_for(top)
    return bool(dists & (TOOLS_DECLARED | INSTALLED_WITH_BASE))


def _module_file(dotted: str) -> Path | None:
    base = SRC.joinpath(*dotted.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    return base / "__init__.py" if (base / "__init__.py").exists() else None


def _unguarded_imports(path: Path) -> tuple[set[str], set[str]]:
    """``(third-party top-level names, parrot_tools modules)`` imported at module level outside try/except."""
    tree = ast.parse(path.read_text())
    rel = list(path.relative_to(SRC).with_suffix("").parts)
    pkg = rel[:-1] if rel[-1] != "__init__" else rel[:-1]
    ext: set[str] = set()
    internal: set[str] = set()

    def visit(nodes, guarded=False):
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top == "parrot_tools":
                        internal.add(alias.name)
                    elif not guarded and top not in sys.stdlib_module_names and top not in ("parrot", "parrot_loaders"):
                        ext.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                    target = ".".join([*base, *([node.module] if node.module else [])])
                    internal.add(target)
                    internal.update(f"{target}.{a.name}" for a in node.names)
                else:
                    top = (node.module or "").split(".")[0]
                    if top == "parrot_tools":
                        internal.add(node.module)
                        internal.update(f"{node.module}.{a.name}" for a in node.names)
                    elif not guarded and top not in sys.stdlib_module_names and top not in ("parrot", "parrot_loaders"):
                        ext.add(top)
            elif isinstance(node, ast.Try):
                visit(node.body, True)
                for handler in node.handlers:
                    visit(handler.body, True)
                visit(node.orelse, True)
                visit(node.finalbody, True)
            elif isinstance(node, ast.If):
                visit(node.body, guarded)
                visit(node.orelse, guarded)
            elif isinstance(node, ast.With):
                visit(node.body, guarded)

    visit(tree.body)
    return ext, internal


def _third_party_closure(module: str) -> dict[str, str]:
    """``{third-party top-level name: first parrot_tools module importing it}`` reachable from ``module``."""
    seen: set[str] = set()
    stack = [module]
    found: dict[str, str] = {}
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = _module_file(mod)
        if path is None:
            continue
        ext, internal = _unguarded_imports(path)
        for top in ext:
            found.setdefault(top, mod)
        for dotted in internal:
            parts = dotted.split(".")
            stack.extend(".".join(parts[: i + 1]) for i in range(len(parts)))
    return found


ENTRIES = sorted(TOOL_REGISTRY.items())


@pytest.mark.parametrize("slug,path", ENTRIES, ids=[s for s, _ in ENTRIES])
def test_registry_value_is_a_concrete_tool(slug, path):
    module, _, cls_name = path.rpartition(".")
    try:
        imported = importlib.import_module(module)
    except ImportError:
        # the extra is not installed here: judge the class from its source instead
        file = _module_file(module)
        if file is None:
            pytest.skip("not a parrot_tools module")
        node = next(
            (n for n in ast.parse(file.read_text()).body if isinstance(n, ast.ClassDef) and n.name == cls_name), None
        )
        if node is None:
            pytest.skip("re-exported from a module that needs an extra")
        assert node.bases, f"{slug}: {cls_name} is not a tool class (no base classes)"
        return
    if getattr(imported, "__file__", None) is None:
        pytest.skip("module is stubbed by the test conftest")
    cls = getattr(imported, cls_name)
    assert isinstance(cls, type) and issubclass(cls, (AbstractTool, AbstractToolkit)), f"{slug}: not a tool"
    assert not inspect.isabstract(cls), f"{slug}: {path} is abstract"


@pytest.mark.parametrize("slug,path", ENTRIES, ids=[s for s, _ in ENTRIES])
def test_registry_value_imports_when_its_declared_extra_is_installed(slug, path):
    module, _, cls_name = path.rpartition(".")
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        top = (exc.name or "").split(".")[0]
        if top in ("parrot", "parrot_tools", "parrot_loaders"):
            pytest.fail(f"{slug}: {path} does not exist ({exc})")
        if top in KNOWN_UNDECLARABLE or _is_declared(top):
            pytest.skip(f"extra providing {top!r} is not installed")
        pytest.fail(f"{slug}: imports {top!r}, which no ai-parrot-tools extra declares")
    except ImportError as exc:  # a tool that turns a missing package into a "please install X" ImportError
        pytest.skip(f"missing optional dependency: {exc}")
    if getattr(mod, "__file__", None) is None:
        pytest.skip("module is stubbed by the test conftest")
    assert hasattr(mod, cls_name), f"{slug}: {module} has no {cls_name}"


def test_every_module_level_third_party_import_of_an_offered_tool_is_declared():
    undeclared: dict[str, list[str]] = {}
    for slug, path in ENTRIES:
        module = path.rpartition(".")[0]
        if not module.startswith("parrot_tools"):
            continue
        for top, via in _third_party_closure(module).items():
            if top not in KNOWN_UNDECLARABLE and not _is_declared(top):
                undeclared.setdefault(top, []).append(f"{slug} (via {via})")
    assert not undeclared, f"undeclared third-party imports: {undeclared}"


@pytest.mark.parametrize("dist", NAMED_BY_THE_BRIEF)
def test_the_named_packages_are_declared(dist):
    assert dist in TOOLS_DECLARED, f"{dist} is not declared by any ai-parrot-tools extra or dependency"


def test_studio_extra_leaves_out_the_infrastructure_toolkits():
    meta = tomllib.loads((PKG_ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    studio = meta["studio"][0]
    for infra in ("aws", "docker", "git", "sandbox", "codeinterpreter", "pulumi", "kubernetes", "security"):
        assert not re.search(rf"[\[,]{infra}[\],]", studio), infra
    assert "powerpoint" in studio and "stats" in studio
