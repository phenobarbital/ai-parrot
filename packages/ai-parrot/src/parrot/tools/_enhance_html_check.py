"""HTML validator for LLM-enhanced output (FEAT-197, TASK-1325).

Shared by the infographic enhance pass and the interactive-artifact render
pipeline. Uses stdlib ``html.parser`` — no new dependencies.

Checks:
- Every ``<script src="...">`` URL must be in the ``allowed_bundles`` whitelist
  (matching both URL and SRI hash).
- Every ``<link rel="stylesheet" href="...">`` URL must likewise be whitelisted.
- Inline ``<script>`` blocks (no ``src``) are allowed.
- Inline ``<style>`` blocks are allowed.

Raises ``code='ENHANCE_OUTPUT_INVALID'`` on any policy violation. The concrete
exception type is pluggable via ``error_cls`` so callers can keep their own
structured error class (``InfographicValidationError`` by default, or e.g.
``InteractiveValidationError``).
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class _ExternalResourceCollector(HTMLParser):
    """Collect all external ``<script src>`` and ``<link rel=stylesheet>`` tags."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[Dict[str, Optional[str]]] = []
        self.links: List[Dict[str, Optional[str]]] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        attrs_d = dict(attrs)
        if tag == "script" and attrs_d.get("src"):
            self.scripts.append(
                {
                    "src": attrs_d["src"],
                    "integrity": attrs_d.get("integrity"),
                }
            )
        elif (
            tag == "link"
            and (attrs_d.get("rel") or "").lower() == "stylesheet"
            and attrs_d.get("href")
        ):
            self.links.append(
                {
                    "href": attrs_d["href"],
                    "integrity": attrs_d.get("integrity"),
                }
            )


def validate_enhanced_html(
    html: str,
    allowed_bundles: Iterable[Any],
    error_cls: Optional[Callable[[str, Dict[str, Any]], Exception]] = None,
) -> None:
    """Raise ENHANCE_OUTPUT_INVALID if the HTML references disallowed resources.

    ``allowed_bundles`` must be an iterable of objects with at least::

        .scope: str            — "cdn" or "inline"
        .url: Optional[str]    — CDN URL (required when scope='cdn')
        .sri_hash: Optional[str] — SRI hash (required when scope='cdn')

    Args:
        html: Full HTML document returned by the LLM enhance step.
        allowed_bundles: Iterable of ``JSBundle`` instances from the template.
        error_cls: Factory ``(code, detail) -> Exception`` used to build the
            raised error. Defaults to ``InfographicValidationError`` for
            backward compatibility; the interactive pipeline passes
            ``InteractiveValidationError``.

    Raises:
        Exception: Built by ``error_cls`` with code ``ENHANCE_OUTPUT_INVALID``
            on any policy violation.
    """
    if error_cls is None:
        # Inline import to avoid circular dependency at module load time.
        from parrot.tools.infographic_toolkit import InfographicValidationError
        error_cls = InfographicValidationError

    collector = _ExternalResourceCollector()
    collector.feed(html)

    # Build index: (url, sri_hash) → bundle
    cdn_index: Dict[Tuple[Optional[str], Optional[str]], Any] = {
        (b.url, b.sri_hash): b
        for b in allowed_bundles
        if getattr(b, "scope", None) == "cdn"
        and getattr(b, "url", None)
        and getattr(b, "sri_hash", None)
    }

    for tag in collector.scripts:
        key = (tag["src"], tag.get("integrity"))
        if key not in cdn_index:
            raise error_cls(
                "ENHANCE_OUTPUT_INVALID",
                {
                    "reason": "external script outside whitelist",
                    "src": tag["src"],
                    "integrity": tag.get("integrity"),
                },
            )

    for tag in collector.links:
        key = (tag["href"], tag.get("integrity"))
        if key not in cdn_index:
            raise error_cls(
                "ENHANCE_OUTPUT_INVALID",
                {
                    "reason": "external stylesheet outside whitelist",
                    "href": tag["href"],
                    "integrity": tag.get("integrity"),
                },
            )
