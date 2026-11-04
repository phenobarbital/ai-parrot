"""API reference generator — static analysis via griffe, one Markdown page per module."""

from __future__ import annotations

import importlib.resources
import logging
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


def _members(obj: Any) -> dict[str, Any]:
    """Return an object's members without relying on a griffe version-specific type."""
    members = getattr(obj, "members", {})
    return members if isinstance(members, dict) else {}


def _module_tree(module: Any) -> list[Any]:
    """Return a module and all statically discovered child modules."""
    modules = [module]
    for member in _members(module).values():
        if getattr(member, "is_module", False):
            modules.extend(_module_tree(member))
    return modules


def load_packages(cfg: TechwikiConfig, root: Path) -> "list[griffe.Module]":
    """Statically load every configured root with griffe.

    All configured source paths are supplied together for every root. This makes
    PEP 420 ``parrot`` portions visible as one namespace tree without importing
    the documented package.

    Args:
        cfg: Techwiki configuration.
        root: Repository root.

    Returns:
        The loaded root modules, one per unique configured import root.
    """
    griffe_module = _import_griffe()
    search_paths = [root / package.src for package in cfg.packages]
    roots = sorted({module_root for package in cfg.packages for module_root in package.roots})
    return [griffe_module.load(module_root, search_paths=search_paths) for module_root in roots]


def _module_all(module: Any) -> set[str] | None:
    """Return literal module ``__all__`` values, if static analysis resolved them."""
    exported = getattr(module, "all", None)
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
    name = getattr(obj, "name", "")
    if not name or name.startswith("_"):
        return False
    parent = getattr(obj, "parent", None)
    if parent is None or not getattr(parent, "is_module", False):
        return True
    exports = _module_all(parent)
    return exports is None or name in exports


def _line_number(obj: Any) -> int:
    """Return a stable source-order key for a griffe object."""
    return int(getattr(obj, "lineno", 0) or 0)


def _kind(obj: Any) -> str:
    """Classify a griffe object for the Markdown template."""
    for kind in ("class", "function", "attribute", "alias"):
        if getattr(obj, f"is_{kind}", False):
            return kind
    return "member"


def _annotation(value: Any) -> str:
    """Render a griffe annotation defensively across supported griffe versions."""
    if value is None:
        return ""
    return str(value)


def _parameters(obj: Any) -> list[dict[str, str]]:
    """Convert callable parameters into deterministic template data."""
    parameters = getattr(obj, "parameters", None)
    if parameters is None:
        return []
    try:
        values = parameters.values()
    except AttributeError:
        values = parameters
    return [
        {
            "name": str(getattr(parameter, "name", "")),
            "annotation": _annotation(getattr(parameter, "annotation", None)),
            "default": _annotation(getattr(parameter, "default", None)),
        }
        for parameter in values
    ]


def _render_member(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Build a serializable template representation of one public member."""
    name = str(getattr(obj, "name", ""))
    full_name = f"{prefix}.{name}" if prefix else name
    target = getattr(obj, "target_path", None) or getattr(obj, "canonical_path", None)
    item = {
        "name": name,
        "full_name": full_name,
        "kind": _kind(obj),
        "docstring": str(getattr(getattr(obj, "docstring", None), "value", "") or ""),
        "parameters": _parameters(obj),
        "returns": _annotation(getattr(obj, "returns", None)),
        "annotation": _annotation(getattr(obj, "annotation", None)),
        "target": str(target or ""),
        "children": [],
    }
    children = [member for member in _members(obj).values() if is_public(member)]
    item["children"] = [_render_member(member, full_name) for member in sorted(children, key=_line_number)]
    return item


def _source_link(module: Any, source_url: str | None, release: str | None) -> str | None:
    """Return a stable source link when configuration and source location exist."""
    if not source_url or not release:
        return None
    filepath = getattr(module, "filepath", None)
    if filepath is None:
        return None
    path = str(filepath).replace("\\", "/")
    marker = "/src/"
    relative = path.split(marker, 1)[-1] if marker in path else Path(path).name
    return f"{source_url.rstrip('/')}/blob/{release}/{relative}"


def render_module(
    mod: "griffe.Module",
    *,
    template: "jinja2.Template",
    source_url: str | None,
    release: str | None,
) -> RenderedPage | None:
    """Render one module page, returning ``None`` when it has no public members.

    Args:
        mod: Statically loaded module.
        template: Jinja template for a module page.
        source_url: Base URL for source links.
        release: Release tag for source links.

    Returns:
        A rendered page, or ``None`` for modules with no public members.
    """
    members = [member for member in _members(mod).values() if is_public(member)]
    if not members:
        return None
    module_name = str(getattr(mod, "path", None) or getattr(mod, "name", ""))
    rendered_members = [_render_member(member) for member in sorted(members, key=lambda item: str(item.name))]
    title = f"Reference: {module_name}"
    return RenderedPage(
        module=module_name,
        section="API Reference",
        title=title,
        body=template.render(
            module=module_name,
            title=title,
            members=rendered_members,
            source_link=_source_link(mod, source_url, release),
        ).rstrip()
        + "\n",
    )


def _template() -> "jinja2.Template":
    """Load the packaged module template without importing documented packages."""
    try:
        import jinja2
    except ImportError as exc:
        raise GriffeUnavailable("jinja2 is not installed. Install with: pip install ai-parrot[techwiki]") from exc
    template_path = importlib.resources.files("parrot.sdd.techwiki").joinpath("templates/module.md.j2")
    return jinja2.Template(template_path.read_text(encoding="utf-8"), keep_trailing_newline=True)


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
    template = _template()
    pages: list[RenderedPage] = []
    skipped: list[dict[str, str]] = []
    try:
        modules = load_packages(cfg, root)
    except GriffeUnavailable:
        raise
    except Exception as exc:
        logger.warning("Unable to load configured API roots: %s", exc)
        return [], [{"module": "<configured roots>", "reason": str(exc)}]
    for root_module in modules:
        for module in _module_tree(root_module):
            try:
                page = render_module(module, template=template, source_url=cfg.source_url, release=release)
            except Exception as exc:
                module_name = str(getattr(module, "path", None) or getattr(module, "name", "<unknown>"))
                logger.warning("Unable to render %s: %s", module_name, exc)
                skipped.append({"module": module_name, "reason": str(exc)})
            else:
                if page is not None:
                    pages.append(page)
    return sorted(pages, key=lambda page: page.module), sorted(skipped, key=lambda item: item["module"])
