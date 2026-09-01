"""Backend HTML design system — token composer (FEAT-493).

Composes a themed, layout-specific stylesheet from packaged CSS assets
and :meth:`ThemeConfig.to_css_variables`. Every backend-rendered HTML lane
(``interactive-html``, ``ssr-html``, ``pdf``, ``formats/infographic_html``)
shares this single composer instead of hand-rolling its own ``_STYLE``
constant.

Two orthogonal axes:

* ``theme`` — palette, resolved via ``theme_registry`` (``light``,
  ``dark``, ``corporate``, ``midnight``, ``petrol``).
* ``layout`` — density/structure (``report``, ``analytics``, ``print``).

Assets are read **once at import time**, mirroring the ``_CHART_JS_SOURCE``
pattern in ``interactive_html.py``: ``DesignSystem.stylesheet()`` is called
from an async ``render()``, and re-reading these files on every call would
block the event loop repeatedly for no benefit, since the bundled CSS never
changes at runtime.
"""
import logging
from pathlib import Path
from typing import ClassVar

from parrot.models.infographic import ThemeConfig, theme_registry

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).parent


def _read_asset(name: str) -> str | None:
    """Read a packaged CSS asset once at import time.

    Args:
        name: File name relative to this package, e.g. ``"base.css"``.

    Returns:
        The file contents, or ``None`` if the asset is missing. A missing
        asset must degrade the composed stylesheet, not crash the import
        of this module — a partially applied feature (e.g. before
        TASK-2708 lands ``layout-report.css`` / ``layout-print.css``)
        must still be importable.
    """
    path = _ASSETS_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Design-system asset not found: %s", path)
        return None


#: Read once at import time — never inside ``DesignSystem.stylesheet()``.
_BASE_CSS: str = _read_asset("base.css") or ""
_COMPONENTS_CSS: str = _read_asset("components.css") or ""

#: One entry per declared layout name. A missing file is ``None`` here and
#: handled as a warn-and-fall-back case by ``DesignSystem._resolve_layout``
#: — this keeps the composer importable even if a layout asset is absent
#: (e.g. mid-migration, before TASK-2708 shipped ``report``/``print``).
_LAYOUT_CSS: dict[str, str | None] = {
    "report": _read_asset("layout-report.css"),
    "analytics": _read_asset("layout-analytics.css"),
    "print": _read_asset("layout-print.css"),
}


class DesignSystem:
    """Composes a themed stylesheet from packaged CSS assets.

    Neither axis ever raises: an unknown theme or layout name is a
    cosmetic failure, logged as a warning and resolved to the default,
    never a render exception.
    """

    LAYOUTS: ClassVar[frozenset[str]] = frozenset({"report", "analytics", "print"})
    DEFAULT_THEME: ClassVar[str] = "light"
    DEFAULT_LAYOUT: ClassVar[str] = "analytics"

    #: Composed sheets, cached per ``(theme_name, layout_name)`` pair.
    _cache: ClassVar[dict[tuple[str, str], str]] = {}

    @classmethod
    def stylesheet(
        cls, theme: "str | ThemeConfig | None" = None, layout: str | None = None
    ) -> str:
        """Return the composed CSS for a ``(theme, layout)`` pair.

        Args:
            theme: A registered theme name, a :class:`ThemeConfig`
                instance, or ``None`` to use :attr:`DEFAULT_THEME`.
            layout: One of :attr:`LAYOUTS`, or ``None`` to use
                :attr:`DEFAULT_LAYOUT`.

        Returns:
            The composed CSS for this pair. Two calls with the same
            resolved pair return the identical cached string object.
        """
        theme_config, theme_key = cls._resolve_theme(theme)
        layout_key, layout_css = cls._resolve_layout(layout)

        cache_key = (theme_key, layout_key)
        cached = cls._cache.get(cache_key)
        if cached is not None:
            return cached

        sheet = "\n\n".join(
            part
            for part in (
                theme_config.to_css_variables(),
                _BASE_CSS,
                _COMPONENTS_CSS,
                layout_css or "",
            )
            if part
        )
        cls._cache[cache_key] = sheet
        return sheet

    @classmethod
    def _resolve_theme(cls, theme: "str | ThemeConfig | None") -> tuple[ThemeConfig, str]:
        """Resolve a theme argument to a ``(ThemeConfig, name)`` pair.

        Args:
            theme: A registered theme name, a :class:`ThemeConfig`
                instance, or ``None``.

        Returns:
            The resolved ``ThemeConfig`` and the name used to cache it.
            An unknown name logs a warning and falls back to
            :attr:`DEFAULT_THEME`.
        """
        if isinstance(theme, ThemeConfig):
            return theme, theme.name
        name = theme or cls.DEFAULT_THEME
        try:
            return theme_registry.get(name), name
        except KeyError:
            logger.warning(
                "Unknown design-system theme %r; falling back to %r.",
                name,
                cls.DEFAULT_THEME,
            )
            return theme_registry.get(cls.DEFAULT_THEME), cls.DEFAULT_THEME

    @classmethod
    def _resolve_layout(cls, layout: str | None) -> tuple[str, str | None]:
        """Resolve a layout argument to a ``(name, css)`` pair.

        Args:
            layout: One of :attr:`LAYOUTS`, or ``None``.

        Returns:
            The resolved layout name and its packaged CSS. An unknown
            name, or a declared-but-missing layout asset, logs a warning
            and falls back to :attr:`DEFAULT_LAYOUT`.
        """
        name = layout or cls.DEFAULT_LAYOUT
        css = _LAYOUT_CSS.get(name)
        if name not in cls.LAYOUTS or css is None:
            logger.warning(
                "Unknown or unavailable design-system layout %r; falling back to %r.",
                name,
                cls.DEFAULT_LAYOUT,
            )
            name = cls.DEFAULT_LAYOUT
            css = _LAYOUT_CSS.get(name)
        return name, css
