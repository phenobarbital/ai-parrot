"""HTML validator for LLM-enhanced output (FEAT-197, TASK-1325).

Shared by the infographic enhance pass and the interactive-artifact render
pipeline. Uses stdlib ``html.parser`` — no new dependencies.

Checks:
- Every ``<script src="...">`` URL must be in the ``allowed_bundles`` whitelist
  (matching both URL and SRI hash).
- Every ``<link rel="stylesheet" href="...">`` URL must likewise be whitelisted.
- Inline ``<script>`` blocks (no ``src``) are allowed.
- Inline ``<style>`` blocks are allowed.
- Inline event handlers (``on*`` attributes), ``javascript:`` URIs, ``<base href>``,
  and ``<meta http-equiv="refresh">`` are always rejected regardless of whitelist.

Raises ``code='ENHANCE_OUTPUT_INVALID'`` on any policy violation. The concrete
exception type is pluggable via ``error_cls`` so callers can keep their own
structured error class (``InfographicValidationError`` by default, or e.g.
``InteractiveValidationError``).
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# Attribute names whose values can carry JS execution (beyond src/href).
_JS_URI_ATTRS = frozenset({"href", "src", "action", "formaction", "data"})


class _ExternalResourceCollector(HTMLParser):
    """Collect external resources and dangerous patterns from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[Dict[str, Optional[str]]] = []
        self.links: List[Dict[str, Optional[str]]] = []
        # Each entry is a human-readable description of the violation.
        self.dangerous: List[str] = []

    def handle_starttag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        attrs_d = dict(attrs)

        # --- existing external-resource collection ---
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

        # --- dangerous pattern checks ---

        # Inline event handlers: any on* attribute on any element.
        for attr_name in attrs_d:
            if attr_name.lower().startswith("on"):
                self.dangerous.append(
                    f"inline event handler '{attr_name}' on <{tag}>"
                )

        # javascript: URI in any navigable/loadable attribute.
        for attr_name in _JS_URI_ATTRS:
            val = (attrs_d.get(attr_name) or "").strip().lower()
            # Strip whitespace/control chars that browsers normalise away.
            val_stripped = "".join(c for c in val if c > " ")
            if val_stripped.startswith("javascript:"):
                self.dangerous.append(
                    f"javascript: URI in '{attr_name}' on <{tag}>"
                )

        # <base href> — redirects all relative URLs to an attacker-controlled origin.
        if tag == "base" and attrs_d.get("href"):
            self.dangerous.append("<base href> tag")

        # <meta http-equiv="refresh"> — client-side redirect / phishing vector.
        if tag == "meta":
            equiv = (attrs_d.get("http-equiv") or "").lower().strip()
            if equiv == "refresh":
                self.dangerous.append("<meta http-equiv=refresh>")


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

    # Reject dangerous patterns before the whitelist check.
    if collector.dangerous:
        raise error_cls(
            "ENHANCE_OUTPUT_INVALID",
            {
                "reason": "dangerous HTML pattern",
                "violations": collector.dangerous,
            },
        )

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
