"""On-disk loader for the interactive HTML artifact catalog.

The catalog ships two kinds of entries under
``parrot/tools/interactive/catalog/``:

- ``libraries/*.md`` — YAML frontmatter describing a vetted JS library plus
  fenced ``## Usage`` / ``## Types`` / ``## Inline`` code blocks. Parsed into
  :class:`~parrot.models.interactive.LibraryEntry`.
- ``templates/<name>.html`` + ``templates/<name>.meta.yaml`` — a self-contained
  HTML skeleton with ``<!-- SLOT:name -->`` markers and a ``<!--HEAD-->`` marker,
  plus metadata (description, default theme, allowed libraries). Parsed into
  :class:`~parrot.models.interactive.ScaffoldTemplate` (slots auto-derived from
  the skeleton).

The registry follows the eager-load + index pattern of
:class:`~parrot.skills.file_registry.SkillFileRegistry`. A module-level singleton
is exposed via :func:`get_interactive_catalog`.

This module also owns the deterministic presentation layer reused by the
toolkit: :data:`BASE_CSS`, the theme variable map, and :func:`build_head`, which
assembles the ``<head>`` injection (base CSS + theme variables + allow-listed
bundle ``<script>``/``<link>`` tags) that replaces a skeleton's ``<!--HEAD-->``
marker.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import frontmatter  # type: ignore[import-untyped]
import yaml

from parrot.models.infographic import JSBundle
from parrot.models.interactive import LibraryEntry, ScaffoldTemplate

logger = logging.getLogger(__name__)

#: Directory holding the bundled catalog (libraries/ + templates/).
CATALOG_DIR = Path(__file__).resolve().parent / "catalog"

#: Sentinel prefix marking an SRI hash that must be regenerated (see SRI.md).
PLACEHOLDER_SRI_PREFIX = "sha384-REGENERATEME"

#: Marker in a skeleton's <head> where build_head() injects CSS + bundle tags.
HEAD_MARKER = "<!--HEAD-->"

#: Regex matching a <!-- SLOT:name --> placeholder.
_SLOT_RE = re.compile(r"<!--\s*SLOT:([A-Za-z0-9_]+)\s*-->")


# ---------------------------------------------------------------------------
# Deterministic presentation layer (base CSS + themes + <head> builder)
# ---------------------------------------------------------------------------

BASE_CSS = """
:root {
  --ip-bg: #f1f5f9; --ip-card: #ffffff; --ip-border: #e2e8f0;
  --ip-text: #0f172a; --ip-muted: #64748b; --ip-primary: #6366f1;
  --ip-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--ip-bg); color: var(--ip-text); font-family: var(--ip-font); }
.ip-container { max-width: 1100px; margin: 0 auto; padding: 32px 20px; }
.ip-header { margin-bottom: 24px; }
.ip-header h1 { font-size: 1.75rem; margin: 0 0 4px; }
.ip-subtitle { color: var(--ip-muted); margin: 0; }
.ip-card { background: var(--ip-card); border: 1px solid var(--ip-border); border-radius: 12px; padding: 20px; margin-bottom: 20px; }
.ip-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }
.ip-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }
.ip-notes, .ip-prose { color: var(--ip-text); line-height: 1.6; }
.ip-footer { margin-top: 24px; color: var(--ip-muted); font-size: 0.875rem; }
.ip-stepper-indicator { color: var(--ip-muted); font-size: 0.875rem; margin-bottom: 12px; }
.ip-stepper-controls { display: flex; gap: 12px; justify-content: flex-end; margin-top: 16px; }
.ip-btn { padding: 8px 18px; border-radius: 8px; border: 1px solid var(--ip-border); background: var(--ip-card); color: var(--ip-text); cursor: pointer; }
.ip-btn[disabled] { opacity: 0.5; cursor: not-allowed; }
.ip-btn-primary { background: var(--ip-primary); border-color: var(--ip-primary); color: #fff; }
[data-step][hidden] { display: none; }
""".strip()

#: Theme name -> CSS variable overrides applied on top of BASE_CSS.
THEMES: Dict[str, Dict[str, str]] = {
    "light": {},
    "dark": {
        "--ip-bg": "#0f172a", "--ip-card": "#1e293b", "--ip-border": "#334155",
        "--ip-text": "#f1f5f9", "--ip-muted": "#94a3b8", "--ip-primary": "#818cf8",
    },
}


def _theme_css(theme: Optional[str]) -> str:
    """Return a CSS ``:root`` override block for ``theme`` (empty when default)."""
    overrides = THEMES.get(theme or "light", {})
    if not overrides:
        return ""
    body = " ".join(f"{k}: {v};" for k, v in overrides.items())
    return f":root {{ {body} }}"


def _is_stylesheet(bundle: JSBundle) -> bool:
    """Heuristic: a CDN bundle whose URL ends in ``.css`` is a stylesheet."""
    return bundle.scope == "cdn" and bool(bundle.url) and bundle.url.endswith(".css")


def _bundle_tag(bundle: JSBundle) -> str:
    """Render a single bundle as its HTML ``<link>``/``<script>`` tag."""
    if bundle.scope == "inline":
        return f"<script>{bundle.inline or ''}</script>"
    if _is_stylesheet(bundle):
        return (
            f'<link rel="stylesheet" href="{bundle.url}" '
            f'integrity="{bundle.sri_hash}" crossorigin="anonymous">'
        )
    return (
        f'<script src="{bundle.url}" integrity="{bundle.sri_hash}" '
        f'crossorigin="anonymous"></script>'
    )


def build_head(bundles: Iterable[JSBundle], theme: Optional[str] = None) -> str:
    """Assemble the ``<head>`` injection for a skeleton's ``<!--HEAD-->`` marker.

    Emits the base stylesheet, optional theme overrides, then the allow-listed
    bundle tags (stylesheets first, then scripts) so the libraries are available
    before any inline content runs.

    Args:
        bundles: The resolved bundles to inject (script + stylesheet).
        theme: Optional theme name applied as CSS-variable overrides.

    Returns:
        An HTML fragment safe to splice into a document ``<head>``.
    """
    bundle_list = list(bundles)
    links = [_bundle_tag(b) for b in bundle_list if _is_stylesheet(b)]
    scripts = [_bundle_tag(b) for b in bundle_list if not _is_stylesheet(b)]
    parts = [f"<style>{BASE_CSS}\n{_theme_css(theme)}</style>", *links, *scripts]
    return "\n  ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Fenced-block extraction for library .md bodies
# ---------------------------------------------------------------------------

def _extract_section_code(body: str, section: str) -> Optional[str]:
    """Return the first fenced code block under a ``## section`` heading.

    Args:
        body: The markdown body (post-frontmatter).
        section: Section title to look for (case-insensitive, e.g. ``"Usage"``).

    Returns:
        The code block contents (without the fences) or ``None`` when absent.
    """
    pattern = re.compile(
        rf"^##\s+{re.escape(section)}\s*$.*?^```[^\n]*\n(.*?)^```",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).rstrip("\n") if m else None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class InteractiveCatalogRegistry:
    """Eager-loading registry of catalog libraries and scaffold templates.

    Args:
        catalog_dir: Root directory containing ``libraries/`` and ``templates/``.
            Defaults to the bundled :data:`CATALOG_DIR`.
    """

    def __init__(self, catalog_dir: Optional[Path] = None) -> None:
        self.catalog_dir = catalog_dir or CATALOG_DIR
        self._libraries: Dict[str, LibraryEntry] = {}
        self._templates: Dict[str, ScaffoldTemplate] = {}
        self._loaded = False
        self.logger = logging.getLogger(self.__class__.__name__)

    # -- loading -----------------------------------------------------------

    def load(self) -> "InteractiveCatalogRegistry":
        """Load (or reload) all libraries and templates from disk.

        Returns:
            ``self`` for chaining. Individual malformed entries are logged and
            skipped rather than aborting the whole load.
        """
        self._libraries.clear()
        self._templates.clear()
        self._load_libraries()
        self._load_templates()
        self._loaded = True
        return self

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    async def ensure_loaded_async(self) -> None:
        """Load the catalog in a thread pool executor to avoid blocking the event loop.

        Call this from async contexts (aiohttp handlers, async tool methods) before
        the first synchronous catalog access. Subsequent calls are no-ops.
        """
        if not self._loaded:
            import asyncio
            await asyncio.to_thread(self.load)

    def _load_libraries(self) -> None:
        lib_dir = self.catalog_dir / "libraries"
        if not lib_dir.is_dir():
            self.logger.warning("Interactive catalog libraries dir missing: %s", lib_dir)
            return
        for md in sorted(lib_dir.glob("*.md")):
            try:
                entry = self._parse_library(md)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Skipping malformed library %s: %s", md.name, exc)
                continue
            if entry.name in self._libraries:
                self.logger.error("Duplicate library name '%s' — skipping %s", entry.name, md.name)
                continue
            if entry.bundle.scope == "cdn" and str(entry.bundle.sri_hash or "").startswith(
                PLACEHOLDER_SRI_PREFIX
            ):
                self.logger.warning(
                    "Library '%s' uses a PLACEHOLDER SRI hash — its CDN asset will be "
                    "blocked by the browser until regenerated (see catalog/SRI.md).",
                    entry.name,
                )
            if (
                entry.css_bundle is not None
                and entry.css_bundle.scope == "cdn"
                and str(entry.css_bundle.sri_hash or "").startswith(PLACEHOLDER_SRI_PREFIX)
            ):
                self.logger.warning(
                    "Library '%s' CSS bundle uses a PLACEHOLDER SRI hash — its "
                    "stylesheet will be blocked by the browser until regenerated "
                    "(see catalog/SRI.md).",
                    entry.name,
                )
            self._libraries[entry.name] = entry

    def _parse_library(self, md: Path) -> LibraryEntry:
        post = frontmatter.load(str(md))
        meta = dict(post.metadata)
        body = post.content or ""
        scope = str(meta.get("scope", "cdn"))

        if scope == "inline":
            inline_src = _extract_section_code(body, "Inline")
            if not inline_src:
                raise ValueError("inline library requires a '## Inline' code block")
            bundle = JSBundle(name=meta["name"], scope="inline", inline=inline_src)
            css_bundle = None
        else:
            bundle = JSBundle(
                name=meta["name"],
                scope="cdn",
                url=meta["url"],
                sri_hash=meta["sri_hash"],
            )
            css_bundle = None
            if meta.get("css_url"):
                css_bundle = JSBundle(
                    name=f"{meta['name']}-css",
                    scope="cdn",
                    url=meta["css_url"],
                    sri_hash=meta["css_sri_hash"],
                )

        return LibraryEntry(
            name=meta["name"],
            description=meta["description"],
            category=meta["category"],
            bundle=bundle,
            css_bundle=css_bundle,
            usage_snippet=_extract_section_code(body, "Usage") or "",
            ts_types=_extract_section_code(body, "Types"),
        )

    def _load_templates(self) -> None:
        tpl_dir = self.catalog_dir / "templates"
        if not tpl_dir.is_dir():
            self.logger.warning("Interactive catalog templates dir missing: %s", tpl_dir)
            return
        for html_file in sorted(tpl_dir.glob("*.html")):
            try:
                tpl = self._parse_template(html_file)
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Skipping malformed template %s: %s", html_file.name, exc)
                continue
            if tpl.name in self._templates:
                self.logger.error("Duplicate template name '%s' — skipping %s", tpl.name, html_file.name)
                continue
            self._templates[tpl.name] = tpl

    def _parse_template(self, html_file: Path) -> ScaffoldTemplate:
        meta_file = html_file.with_suffix(".meta.yaml")
        meta: Dict[str, object] = {}
        if meta_file.is_file():
            meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
        html = html_file.read_text(encoding="utf-8")
        if HEAD_MARKER not in html:
            raise ValueError(f"template skeleton missing {HEAD_MARKER} marker")
        # Auto-derive slots from the skeleton (first-occurrence order, deduped).
        slots: List[str] = []
        for name in _SLOT_RE.findall(html):
            if name not in slots:
                slots.append(name)
        name = str(meta.get("name") or html_file.stem)
        return ScaffoldTemplate(
            name=name,
            description=str(meta.get("description", name)),
            html_skeleton=html,
            allowed_bundles=list(meta.get("allowed_bundles", []) or []),
            slots=slots,
            default_theme=meta.get("default_theme"),
        )

    # -- accessors ---------------------------------------------------------

    def get_library(self, name: str) -> LibraryEntry:
        """Return the library entry ``name`` or raise ``KeyError``."""
        self._ensure_loaded()
        try:
            return self._libraries[name]
        except KeyError:
            available = ", ".join(sorted(self._libraries)) or "(none)"
            raise KeyError(
                f"Interactive library '{name}' not found. Available: {available}"
            ) from None

    def get_template(self, name: str) -> ScaffoldTemplate:
        """Return the scaffold template ``name`` or raise ``KeyError``."""
        self._ensure_loaded()
        try:
            return self._templates[name]
        except KeyError:
            available = ", ".join(sorted(self._templates)) or "(none)"
            raise KeyError(
                f"Interactive template '{name}' not found. Available: {available}"
            ) from None

    def list_libraries(self) -> List[LibraryEntry]:
        """Return all loaded libraries, sorted by name."""
        self._ensure_loaded()
        return [self._libraries[k] for k in sorted(self._libraries)]

    def list_templates(self) -> List[ScaffoldTemplate]:
        """Return all loaded templates, sorted by name."""
        self._ensure_loaded()
        return [self._templates[k] for k in sorted(self._templates)]

    def render_prompt_index(self) -> str:
        """Render the static ``<interactive_catalog>`` prompt index.

        This block is injected once into the agent system prompt (configure-time)
        so the LLM knows which scaffolds and libraries exist — the two-tier
        pattern borrowed from the skills system. Zero per-turn cost.
        """
        self._ensure_loaded()
        lines = ["<interactive_catalog>", "  <templates>"]
        for tpl in self.list_templates():
            libs = ",".join(tpl.allowed_bundles)
            lines.append(
                f'    <template name="{tpl.name}" theme="{tpl.default_theme or "light"}"'
                f' libraries="{libs}" slots="{",".join(tpl.slots)}">'
            )
            lines.append(f"      {tpl.description.strip()}")
            lines.append("    </template>")
        lines.append("  </templates>")
        lines.append("  <libraries>")
        for lib in self.list_libraries():
            lines.append(lib.to_prompt_entry())
        lines.append("  </libraries>")
        lines.append("</interactive_catalog>")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_CATALOG: Optional[InteractiveCatalogRegistry] = None


def get_interactive_catalog() -> InteractiveCatalogRegistry:
    """Return the process-wide catalog singleton (not yet loaded).

    The catalog is loaded on first access via ``_ensure_loaded()`` (sync) or
    ``ensure_loaded_async()`` (async, thread-safe).  Async callers should call
    ``await catalog.ensure_loaded_async()`` before touching catalog data to
    avoid blocking the event loop with disk I/O.
    """
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = InteractiveCatalogRegistry()
    return _CATALOG
