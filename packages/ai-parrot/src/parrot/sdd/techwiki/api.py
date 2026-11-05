"""API reference generator — static analysis via griffe, one Markdown page per module."""

from __future__ import annotations

import ast
import importlib.resources
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.sdd.techwiki.config import TechwikiConfig

if TYPE_CHECKING:
    import griffe
    import jinja2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedPage:
    """One rendered API reference page."""

    module: str
    section: str
    title: str
    body: str


class GriffeUnavailable(RuntimeError):
    """Raised when the optional static-analysis dependency is unavailable."""


def _import_griffe() -> "griffe":
    """Import griffe only when reference generation is requested.

    Returns:
        The griffe module.

    Raises:
        GriffeUnavailable: If the ``techwiki`` optional extra is not installed.
    """
    try:
        import griffe as griffe_module
    except ImportError as exc:
        raise GriffeUnavailable("griffe is not installed. Install with: pip install ai-parrot[techwiki]") from exc
    return griffe_module


def _safe(obj: Any, name: str, default: Any = None) -> Any:
    """Read a griffe attribute without letting alias resolution errors escape.

    griffe raises ``AliasResolutionError`` (not ``AttributeError``) when an alias such as
    ``from typing import overload`` points outside the loaded packages, so ``getattr(..., default)``
    alone is not enough.
    """
    try:
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001
        return default


def _members(obj: Any) -> dict[str, Any]:
    """Return an object's members without relying on a griffe version-specific type."""
    members = _safe(obj, "members", {})
    return members if isinstance(members, dict) else {}


def _is_alias(obj: Any) -> bool:
    """Return whether ``obj`` is an alias (import or re-export) without resolving it."""
    return bool(_safe(obj, "is_alias", False))


def _module_tree(module: Any) -> list[Any]:
    """Return a module and all statically discovered child modules."""
    modules = [module]
    for member in _members(module).values():
        if not _is_alias(member) and _safe(member, "is_module", False):
            modules.extend(_module_tree(member))
    return modules


def _root_exists(source_root: Path, module_root: str) -> bool:
    """Whether ``module_root`` (possibly dotted) exists as a package directory or module under ``source_root``."""
    base = source_root.joinpath(*module_root.split("."))
    return base.is_dir() or base.with_suffix(".py").is_file()


def load_packages(cfg: TechwikiConfig, root: Path) -> "list[griffe.Module]":
    """Statically load every configured root with griffe, one tree per distribution.

    Each distribution's own ``src`` is the only search path for its roots. Loading the shared ``parrot``
    namespace with every ``src`` at once does not work: the core ``parrot/__init__.py`` makes ``parrot`` a
    regular package, so griffe never merges the satellites' PEP 420 portions (store backends, provider
    clients, server handlers...). Loading each portion on its own and merging the *pages* by module name
    (see :func:`generate`) keeps every satellite module in the reference. A root that a distribution does
    not contain is skipped, so griffe is never allowed to fall back to an installed copy.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        The loaded root modules in configuration order.
    """
    griffe_module = _import_griffe()
    modules = []
    for package in cfg.packages:
        source_root = root / package.src
        for module_root in package.roots:
            if _root_exists(source_root, module_root):
                modules.append(griffe_module.load(module_root, search_paths=[source_root]))
    return modules


def _syntax_errors(cfg: TechwikiConfig, root: Path) -> list[dict[str, str]]:
    """Report configured source files that do not parse.

    griffe silently drops a module with a syntax error (it only logs), so ``--strict`` could never
    notice shrinking coverage; parsing the sources ourselves makes the loss visible.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        One ``{"module", "reason"}`` entry per unparseable file, sorted by module.
    """
    skipped: list[dict[str, str]] = []
    for package in cfg.packages:
        source_root = root / package.src
        for module_root in package.roots:
            base = source_root.joinpath(*module_root.split("."))
            files = (
                sorted(base.rglob("*.py"))
                if base.is_dir()
                else ([base.with_suffix(".py")] if base.with_suffix(".py").is_file() else [])
            )
            for path in files:
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except SyntaxError as exc:
                    reason = f"SyntaxError: {exc.msg} (line {exc.lineno})"
                except (UnicodeDecodeError, ValueError) as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                else:
                    continue
                parts = list(path.relative_to(source_root).with_suffix("").parts)
                if parts and parts[-1] == "__init__":
                    parts.pop()
                skipped.append({"module": ".".join(parts), "reason": reason})
    return sorted(skipped, key=lambda item: item["module"])


def _module_all(module: Any) -> set[str] | None:
    """Return the module's ``__all__`` names as resolved by griffe, if it declares any."""
    exported = _safe(module, "exports", None)
    if exported is None:
        return None
    try:
        return {str(item) for item in exported}
    except TypeError:
        return None


def is_public(obj: "griffe.Object") -> bool:
    """Determine whether a griffe object should be rendered.

    Args:
        obj: Griffe member being considered.

    Returns:
        Whether the member is public under its containing module's rules.
    """
    name = str(_safe(obj, "name", "") or "")
    if not name or name.startswith("_"):
        return False
    parent = _safe(obj, "parent")
    if parent is None or not _safe(parent, "is_module", False):
        return True
    exports = _module_all(parent)
    if exports is not None:
        return name in exports
    if _is_alias(obj):
        # Without __all__, only re-exports that stay inside the documented top-level package are public;
        # `import os` / `from typing import Any` style aliases are noise.
        target = str(_safe(obj, "target_path", "") or "")
        top = str(_safe(parent, "path", "") or "").split(".", 1)[0]
        return not target or not top or target.split(".", 1)[0] == top
    return True


def _line_number(obj: Any) -> int:
    """Return a stable source-order key for a griffe object."""
    return int(_safe(obj, "lineno", 0) or 0)


def _kind(obj: Any) -> str:
    """Classify a griffe object for the Markdown template."""
    if _is_alias(obj):
        return "alias"
    for kind in ("class", "function", "attribute"):
        if _safe(obj, f"is_{kind}", False):
            return kind
    return "member"


def _text(value: Any) -> str:
    """Render a griffe expression defensively across supported griffe versions."""
    return "" if value is None else str(value)


_FIELD_DESCRIPTION = re.compile(r"""description\s*=\s*(?P<q>['"])(?P<text>.*?)(?P=q)""")
_FIELD_DEFAULT = re.compile(r"""\bdefault\s*=\s*(?P<value>[^,)]+)""")


def _doc_parts(obj: Any) -> dict[str, Any]:
    """Split a Google style docstring into description, parameter, return, raise and attribute texts."""
    parts: dict[str, Any] = {"description": "", "params": {}, "returns": "", "raises": [], "attributes": {}}
    docstring = _safe(obj, "docstring")
    if docstring is None:
        return parts
    raw = str(_safe(docstring, "value", "") or "")
    try:
        sections = docstring.parse("google")
    except Exception:  # noqa: BLE001 - an unparseable docstring still renders verbatim
        parts["description"] = raw
        return parts
    texts: list[str] = []
    for section in sections:
        kind = str(getattr(getattr(section, "kind", None), "value", ""))
        if kind == "text":
            texts.append(str(section.value).strip())
        elif kind == "parameters":
            parts["params"] = {str(p.name): str(p.description or "") for p in section.value}
        elif kind == "attributes":
            parts["attributes"] = {str(a.name): str(a.description or "") for a in section.value}
        elif kind == "returns":
            parts["returns"] = " ".join(str(r.description or "").strip() for r in section.value).strip()
        elif kind == "raises":
            parts["raises"] = [
                {"type": _text(r.annotation), "description": str(r.description or "")} for r in section.value
            ]
    parts["description"] = "\n\n".join(text for text in texts if text)
    return parts


def _parameters(obj: Any, descriptions: dict[str, str]) -> list[dict[str, str]]:
    """Convert callable parameters into deterministic template data (``self``/``cls`` omitted)."""
    parameters = _safe(obj, "parameters", None)
    if parameters is None:
        return []
    try:
        values = list(parameters.values())
    except AttributeError:
        values = list(parameters)
    rows = []
    for index, parameter in enumerate(values):
        name = str(_safe(parameter, "name", ""))
        if index == 0 and name in {"self", "cls"}:
            continue
        kind = str(getattr(_safe(parameter, "kind"), "value", ""))
        prefix = "**" if kind == "variadic keyword" else "*" if kind == "variadic positional" else ""
        rows.append(
            {
                "name": f"{prefix}{name}",
                "annotation": _text(_safe(parameter, "annotation")),
                "default": _text(_safe(parameter, "default")),
                "description": descriptions.get(name, descriptions.get(f"{prefix}{name}", "")),
            }
        )
    return rows


def _signature(obj: Any) -> str:
    """Return a one-line callable signature, or an empty string when griffe cannot build one."""
    try:
        return str(obj.signature())
    except Exception:  # noqa: BLE001
        return ""


def _is_model_like(cls: Any) -> bool:
    """Whether a class declares Pydantic style or dataclass fields."""
    bases = [str(base) for base in _safe(cls, "bases", []) or []]
    decorators = [str(_safe(decorator, "value", decorator)) for decorator in _safe(cls, "decorators", []) or []]
    return any(base.rsplit(".", 1)[-1].endswith("BaseModel") for base in bases) or any(
        "dataclass" in decorator for decorator in decorators
    )


def _field_row(attr: Any, documented: dict[str, str]) -> dict[str, str]:
    """Build a ``Fields`` row (name, annotation, default, description) for a model attribute."""
    name = str(_safe(attr, "name", ""))
    value = _text(_safe(attr, "value"))
    description = documented.get(name, "")
    if value.startswith("Field("):
        match = _FIELD_DESCRIPTION.search(value)
        if match and not description:
            description = match.group("text")
        default_match = _FIELD_DEFAULT.search(value)
        value = default_match.group("value").strip() if default_match else ""
    docstring = _safe(attr, "docstring")
    if not description and docstring is not None:
        description = str(_safe(docstring, "value", "") or "").strip()
    return {
        "name": name,
        "annotation": _text(_safe(attr, "annotation")),
        "default": value,
        "description": description,
    }


def _alias_member(obj: Any, prefix: str, module_root: str) -> dict[str, Any]:
    """Render an alias as a one-line "re-exported from" entry, never a duplicate body."""
    name = str(_safe(obj, "name", ""))
    target = str(_safe(obj, "target_path", "") or "")
    link = ""
    if target and "." in target and target.split(".", 1)[0] == module_root:
        link = target.rsplit(".", 1)[0]
    return {
        "kind": "alias",
        "name": name,
        "full_name": f"{prefix}.{name}" if prefix else name,
        "target": target,
        "target_module": link,
    }


def _render_member(obj: Any, prefix: str = "", module_root: str = "") -> dict[str, Any]:
    """Build a serializable template representation of one public member."""
    if _is_alias(obj):
        return _alias_member(obj, prefix, module_root)
    name = str(_safe(obj, "name", ""))
    full_name = f"{prefix}.{name}" if prefix else name
    kind = _kind(obj)
    doc = _doc_parts(obj)
    item: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "full_name": full_name,
        "description": doc["description"],
        "parameters": [],
        "signature": "",
        "overloads": [],
        "returns": "",
        "returns_text": doc["returns"],
        "raises": doc["raises"],
        "annotation": _text(_safe(obj, "annotation")),
        "attributes": [],
        "fields": [],
        "methods": [],
        "classes": [],
    }
    if kind == "function":
        item["parameters"] = _parameters(obj, doc["params"])
        returns = _text(_safe(obj, "returns"))
        item["returns"] = "" if returns == "None" and not doc["returns"] else returns
        overloads = _safe(obj, "overloads", None) or []
        item["overloads"] = [sig for sig in (_signature(o) for o in overloads) if sig]
        item["signature"] = "" if item["overloads"] else _signature(obj)
    elif kind == "attribute":
        item["value"] = _text(_safe(obj, "value"))
    elif kind == "class":
        members = _members(obj)
        init = members.get("__init__")
        if init is not None and not _is_alias(init) and _safe(init, "is_function", False):
            init_doc = _doc_parts(init)
            item["parameters"] = _parameters(
                init, {**init_doc["params"], **doc["params"]}
            )  # __init__ merged into its class
            if not item["description"]:
                item["description"] = init_doc["description"]
        model_like = _is_model_like(obj)
        public = sorted((m for m in members.values() if is_public(m)), key=_line_number)
        for member in public:
            member_name = str(_safe(member, "name", ""))
            if _is_alias(member):
                continue
            labels = set(_safe(member, "labels", set()) or set())
            if _safe(member, "is_class", False):
                item["classes"].append(_render_member(member, full_name, module_root))
            elif _safe(member, "is_function", False):
                method = _render_member(member, full_name, module_root)
                method["kind"] = "method"
                item["methods"].append(method)
            elif _safe(member, "is_attribute", False):
                annotation = _text(_safe(member, "annotation"))
                if "property" in labels:
                    attr_doc = _doc_parts(member)
                    item["attributes"].append(
                        {"name": member_name, "annotation": annotation, "description": attr_doc["description"]}
                    )
                elif model_like and annotation and not annotation.startswith("ClassVar"):
                    item["fields"].append(_field_row(member, doc["attributes"]))
                elif annotation or doc["attributes"].get(member_name) or _doc_parts(member)["description"]:
                    # Undocumented, unannotated instance attributes (``self.x = ...``) are not public API surface.
                    item["attributes"].append(
                        {
                            "name": member_name,
                            "annotation": annotation,
                            "description": doc["attributes"].get(member_name) or _doc_parts(member)["description"],
                        }
                    )
    return item


def _source_link(module: Any, source_url: str | None, release: str | None, root: Path | None = None) -> str | None:
    """Return a stable source link when configuration and source location exist."""
    if not source_url or not release:
        return None
    filepath = _safe(module, "filepath", None)
    if filepath is None:
        return None
    path = str(filepath).replace("\\", "/")
    relative: str | None = None
    if root is not None:
        try:
            relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = None
    if relative is None:
        marker = "/packages/"
        relative = "packages/" + path.split(marker, 1)[1] if marker in path else Path(path).name
    return f"{source_url.rstrip('/')}/blob/{release}/{relative}"


_PACKAGE_TEMPLATE: "jinja2.Template | None" = None


def _public_members(mod: Any) -> list[Any]:
    """Return the members that render on ``mod``'s own page.

    A child module is never a member of its parent's page: it has a page of its own. An alias to one
    (a re-export) is, because it documents the parent's public surface.

    Args:
        mod: Statically loaded module.

    Returns:
        The public, non-module members, in member order.
    """
    return [
        member
        for member in _members(mod).values()
        if is_public(member) and (_is_alias(member) or not _safe(member, "is_module", False))
    ]


def _submodules(mod: Any) -> list[Any]:
    """Return ``mod``'s statically discovered child modules, private names excluded.

    Args:
        mod: Statically loaded module.

    Returns:
        The child modules, aliases and underscore-prefixed names excluded.
    """
    return [
        member
        for member in _members(mod).values()
        if not _is_alias(member)
        and _safe(member, "is_module", False)
        and not str(_safe(member, "name", "") or "").startswith("_")
    ]


def _has_page(mod: Any) -> bool:
    """Whether ``mod`` produces a page: it has public members, or a descendant that does.

    This mirrors :func:`render_module`'s own decision, so a package index never links a module that
    rendered nothing — such a link would leave an unresolvable ``ref:`` in the assembled bundle.

    Args:
        mod: Statically loaded module.

    Returns:
        Whether a page exists for ``mod``.
    """
    if _public_members(mod):
        return True
    return any(_has_page(child) for child in _submodules(mod))


def _package_template() -> "jinja2.Template":
    """Load and cache the packaged package-index template without importing documented packages.

    Returns:
        The compiled template for a package index page.

    Raises:
        GriffeUnavailable: If jinja2 is not installed.
    """
    global _PACKAGE_TEMPLATE  # noqa: PLW0603 - one process-wide compile of a packaged template
    if _PACKAGE_TEMPLATE is None:
        try:
            import jinja2
        except ImportError as exc:
            raise GriffeUnavailable("jinja2 is not installed. Install with: pip install ai-parrot[techwiki]") from exc
        template_path = importlib.resources.files("parrot.sdd.techwiki").joinpath("templates/package.md.j2")
        environment = jinja2.Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
        _PACKAGE_TEMPLATE = environment.from_string(template_path.read_text(encoding="utf-8"))
    return _PACKAGE_TEMPLATE


def render_module(
    mod: "griffe.Module",
    *,
    template: "jinja2.Template",
    source_url: str | None,
    release: str | None,
    root: Path | None = None,
    section: str = "API Reference",
) -> RenderedPage | None:
    """Render one module page, returning ``None`` when the module documents nothing.

    A module with public members renders those members. A package with none of its own — a namespace
    whose public names are re-exported lazily (``__getattr__``) or simply live in its submodules —
    renders an index page listing its declared ``__all__`` and its child module pages instead of
    disappearing, so re-exports elsewhere can link it.

    Args:
        mod: Statically loaded module.
        template: Jinja template for a module page.
        source_url: Base URL for source links.
        release: Release tag for source links.
        root: Repository root used to build repository-relative source links.
        section: Wiki section the page belongs to (``TechwikiConfig.reference_section``).

    Returns:
        A rendered page, or ``None`` for a module with neither public members nor a child module page.
        The page title is the bare module name: it becomes part of the wiki page name, which must stay
        free of ``:`` and the other characters ``actions/upload-artifact`` rejects.
    """
    module_name = str(_safe(mod, "path", None) or _safe(mod, "name", ""))
    module_root = module_name.split(".", 1)[0]
    members = _public_members(mod)
    if members:
        rendered_members = [
            _render_member(member, module_root=module_root)
            for member in sorted(members, key=lambda item: str(item.name))
        ]
        rendered = template.render(
            module=module_name,
            title=module_name,
            description=_doc_parts(mod)["description"],
            members=rendered_members,
            source_link=_source_link(mod, source_url, release, root),
        )
    else:
        submodules = sorted(
            str(_safe(child, "path", None) or _safe(child, "name", ""))
            for child in _submodules(mod)
            if _has_page(child)
        )
        if not submodules:
            return None
        rendered = _package_template().render(
            module=module_name,
            title=module_name,
            description=_doc_parts(mod)["description"],
            exports=sorted(_module_all(mod) or ()),
            submodules=submodules,
            source_link=_source_link(mod, source_url, release, root),
        )
    return RenderedPage(
        module=module_name,
        section=section,
        title=module_name,
        body=re.sub(r"\n{3,}", "\n\n", rendered).rstrip() + "\n",
    )


def _cell(value: object) -> str:
    """Escape a value for a Markdown table cell, wrapping non-empty text in backticks only when asked by the template."""
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _code_cell(value: object) -> str:
    """Render a table cell as inline code (empty stays empty); pipes are escaped so unions do not split cells."""
    text = str(value).replace("\n", " ").replace("|", "\\|").strip()
    return f"`{text}`" if text else ""


def _template() -> "jinja2.Template":
    """Load the packaged module template without importing documented packages."""
    try:
        import jinja2
    except ImportError as exc:
        raise GriffeUnavailable("jinja2 is not installed. Install with: pip install ai-parrot[techwiki]") from exc
    template_path = importlib.resources.files("parrot.sdd.techwiki").joinpath("templates/module.md.j2")
    environment = jinja2.Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    environment.filters["cell"] = _cell
    environment.filters["code"] = _code_cell
    return environment.from_string(template_path.read_text(encoding="utf-8"))


def generate(
    cfg: TechwikiConfig, root: Path, *, release: str | None = None
) -> tuple[list[RenderedPage], list[dict[str, str]]]:
    """Generate API reference pages for every configured static package.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.
        release: Optional source-link release tag.

    Returns:
        ``(pages, skipped)`` with parse/load failures represented in ``skipped``.
    """
    previous_level = logging.getLogger("griffe").level
    logging.getLogger("griffe").setLevel(logging.ERROR)  # docstring-lint warnings are not a reference problem
    try:
        return _generate(cfg, root, release)
    finally:
        logging.getLogger("griffe").setLevel(previous_level)


def _generate(cfg: TechwikiConfig, root: Path, release: str | None) -> tuple[list[RenderedPage], list[dict[str, str]]]:
    """Implement :func:`generate` (split out so the griffe log level is always restored)."""
    template = _template()
    pages: dict[str, RenderedPage] = {}
    skipped: list[dict[str, str]] = []
    if not cfg.packages:
        logger.warning("No packages configured under techwiki.packages; no API reference will be generated")
        return [], [{"module": "<configured packages>", "reason": "no packages configured"}]
    try:
        modules = load_packages(cfg, root)
    except GriffeUnavailable:
        raise
    except Exception as exc:
        logger.warning("Unable to load configured API roots: %s", exc)
        return [], [{"module": "<configured roots>", "reason": str(exc)}]
    skipped.extend(_syntax_errors(cfg, root))
    for root_module in modules:
        for module in _module_tree(root_module):
            try:
                page = render_module(
                    module,
                    template=template,
                    source_url=cfg.source_url,
                    release=release,
                    root=root,
                    section=cfg.reference_section,
                )
            except Exception as exc:
                module_name = str(getattr(module, "path", None) or getattr(module, "name", "<unknown>"))
                logger.warning("Unable to render %s: %s", module_name, exc)
                skipped.append({"module": module_name, "reason": str(exc)})
            else:
                if page is not None:
                    pages.setdefault(page.module, page)  # first configured distribution wins a duplicate module
    return sorted(pages.values(), key=lambda page: page.module), sorted(skipped, key=lambda item: item["module"])
