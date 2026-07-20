"""Models for Interactive HTML Artifacts ("vibe-coding" canvas).

This is the free-form counterpart to the structured ``Infographic`` system.
Where an infographic constrains the LLM to a fixed set of typed JSON blocks
rendered deterministically, an *interactive artifact* lets the LLM author the
HTML/JS directly — guided by a **catalog** of vetted JavaScript libraries and
HTML scaffold templates that is injected into the agent prompt.

Two pure-data models live here:

- :class:`LibraryEntry` — a single vetted JS library (Mermaid, ECharts,
  Grid.js, …) the LLM may use. It carries the :class:`~parrot.models.infographic.JSBundle`
  used by the SRI allow-list / CSP machinery, plus a usage snippet and optional
  TypeScript reference types that *guide* the LLM (the snippets are reference
  material — nothing is compiled; the LLM emits plain JavaScript).
- :class:`ScaffoldTemplate` — a deterministic HTML skeleton (``dashboard``,
  ``wizard``, ``diagram``, ``grid``, ``report``) with named ``<!-- SLOT:* -->``
  placeholders the LLM fills during the enhance pass.

The render envelope :class:`InteractiveRenderResult` mirrors
``InfographicRenderResult`` so the agent post-loop can treat both uniformly.

The catalog itself (loading entries from disk) lives in
``parrot.tools.interactive.catalog_registry`` to keep this module dependency-light.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .infographic import JSBundle  # reuse the vetted SRI/CSP bundle model


LibraryCategory = Literal["diagram", "chart", "grid", "wizard", "util"]


class LibraryEntry(BaseModel):
    """A single vetted JavaScript library the LLM may use in an artifact.

    The library's delivery is described by ``bundle`` (a CDN ``<script>`` with
    SRI, or an inline source block). Some libraries also ship a stylesheet —
    captured by the optional ``css_bundle`` (a ``JSBundle`` whose ``url`` points
    at a ``.css`` file). Both bundles flow into the enhance allow-list and the
    CSP ``script-src`` / ``style-src`` directives.

    ``usage_snippet`` and ``ts_types`` are *reference material* for the LLM: the
    snippet shows idiomatic usage and ``ts_types`` documents the API shape. They
    are never executed or compiled — the LLM emits plain JavaScript.
    """

    name: str = Field(..., description="Stable library identifier (e.g. 'mermaid').")
    description: str = Field(..., description="One-line summary shown in the prompt index.")
    category: LibraryCategory = Field(..., description="Coarse capability bucket.")
    bundle: JSBundle = Field(..., description="The script bundle (cdn or inline).")
    css_bundle: Optional[JSBundle] = Field(
        default=None,
        description="Optional companion stylesheet bundle (a JSBundle with a .css url).",
    )
    usage_snippet: str = Field(
        default="",
        description="Idiomatic HTML/JS usage example shown to the LLM (not executed).",
    )
    ts_types: Optional[str] = Field(
        default=None,
        description="Optional TypeScript reference types documenting the API (not compiled).",
    )

    def bundles(self) -> List[JSBundle]:
        """Return all bundles (script + optional stylesheet) for allow-listing."""
        out = [self.bundle]
        if self.css_bundle is not None:
            out.append(self.css_bundle)
        return out

    def to_prompt_entry(self) -> str:
        """Render this library as a compact prompt block for the catalog index."""
        lines = [
            f"  <library name=\"{self.name}\" category=\"{self.category}\">",
            f"    {self.description}",
        ]
        if self.bundle.scope == "cdn":
            lines.append(
                f"    script: {self.bundle.url}"
                f" (integrity=\"{self.bundle.sri_hash}\", crossorigin=\"anonymous\")"
            )
        else:
            lines.append("    script: inline bundle injected into the skeleton (no src needed)")
        if self.css_bundle is not None and self.css_bundle.scope == "cdn":
            lines.append(
                f"    stylesheet: {self.css_bundle.url}"
                f" (integrity=\"{self.css_bundle.sri_hash}\", crossorigin=\"anonymous\")"
            )
        if self.usage_snippet:
            lines.append("    usage:")
            lines.append(_indent(self.usage_snippet.strip(), "      | "))
        if self.ts_types:
            lines.append("    types:")
            lines.append(_indent(self.ts_types.strip(), "      | "))
        lines.append("  </library>")
        return "\n".join(lines)


class ScaffoldTemplate(BaseModel):
    """A deterministic HTML skeleton with named slots for the enhance pass.

    The skeleton is a complete, self-contained HTML document. ``<!-- SLOT:name -->``
    markers indicate where the LLM should inject content during the enhance pass;
    in deterministic mode they are replaced with an empty placeholder so the
    skeleton still renders standalone.

    ``allowed_bundles`` lists the library names (matching :attr:`LibraryEntry.name`)
    a render against this template may pull. The render tool rejects any requested
    library not in this list, keeping each template's attack surface explicit.
    """

    name: str = Field(..., description="Template identifier (e.g. 'wizard').")
    description: str = Field(..., description="Human-readable description for the LLM.")
    html_skeleton: str = Field(..., description="Self-contained HTML with <!-- SLOT:* --> markers.")
    allowed_bundles: List[str] = Field(
        default_factory=list,
        description="Library names this template may use (must exist in the catalog).",
    )
    slots: List[str] = Field(
        default_factory=list,
        description="Ordered list of slot names present in the skeleton.",
    )
    default_theme: Optional[str] = Field(
        default=None, description="Optional default theme hint for this template.",
    )

    def to_prompt_instruction(self) -> str:
        """Generate LLM prompt instructions describing this scaffold."""
        lines = [
            f"Scaffold template: '{self.name}'.",
            f"Description: {self.description}",
        ]
        if self.slots:
            lines.append("")
            lines.append("Fill these slots (replace the matching <!-- SLOT:name --> markers):")
            for slot in self.slots:
                lines.append(f"  - {slot}")
        if self.allowed_bundles:
            lines.append("")
            lines.append(
                "Allowed libraries for this template: "
                + ", ".join(self.allowed_bundles)
            )
        return "\n".join(lines)


class InteractiveRenderResult(BaseModel):
    """Envelope returned by ``InteractiveToolkit.render`` (return_direct=True).

    Mirrors ``InfographicRenderResult`` so the agent post-loop can handle both
    artifact families through a single isinstance branch.
    """

    artifact_id: str
    html_url: str
    html_inline: Optional[str] = None
    template_name: str
    theme: Optional[str] = None
    libraries_used: List[str] = Field(default_factory=list)
    enhanced: bool = False
    a2ui_envelope: Optional[Dict[str, Any]] = None


def _indent(text: str, prefix: str) -> str:
    """Prefix every line of ``text`` with ``prefix`` (prompt-formatting helper)."""
    return "\n".join(prefix + line for line in text.splitlines())
