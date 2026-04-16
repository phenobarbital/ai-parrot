"""
Infographic Template Definitions.

Templates define the expected block sequence for an infographic,
allowing users to select a pre-built layout and get deterministic
structure from the LLM output.

Each template specifies:
    - An ordered list of block specs (type + constraints)
    - A description used in the LLM prompt
    - Optional theme defaults

Users can also define custom templates programmatically.
"""
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

from .infographic import BlockType


class BlockSpec(BaseModel):
    """Specification for a single block slot in a template.

    Tells the LLM what type of block to generate and provides
    constraints/hints for that slot.
    """
    block_type: BlockType = Field(..., description="Expected block type for this slot")
    required: bool = Field(True, description="Whether this block must be present")
    description: Optional[str] = Field(
        None,
        description="Hint for the LLM about what content this slot should contain"
    )
    min_items: Optional[int] = Field(
        None,
        description="Minimum number of items (for lists, hero_cards, timeline, progress)"
    )
    max_items: Optional[int] = Field(
        None,
        description="Maximum number of items"
    )
    constraints: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Additional constraints passed to the LLM (e.g., {'chart_type': 'bar'})"
    )


class InfographicTemplate(BaseModel):
    """Defines the structure and block order for an infographic layout."""
    name: str = Field(..., description="Template identifier (e.g., 'basic', 'executive')")
    description: str = Field(..., description="Human-readable template description")
    block_specs: List[BlockSpec] = Field(
        ...,
        description="Ordered list of block specifications"
    )
    default_theme: Optional[str] = Field(
        None,
        description="Default color theme for this template"
    )

    def to_prompt_instruction(self) -> str:
        """Generate LLM prompt instructions from this template.

        Returns:
            Formatted string describing the expected block structure.
        """
        lines = [
            f"Generate an infographic using the '{self.name}' layout.",
            f"Description: {self.description}",
            "",
            "The infographic MUST contain the following blocks IN THIS EXACT ORDER:",
            "",
        ]
        has_tab_view = any(
            spec.block_type == BlockType.TAB_VIEW for spec in self.block_specs
        )
        for idx, spec in enumerate(self.block_specs, 1):
            required_tag = "REQUIRED" if spec.required else "OPTIONAL"
            line = f"  {idx}. [{required_tag}] {spec.block_type.value}"
            if spec.description:
                line += f" - {spec.description}"
            if spec.min_items is not None:
                line += f" (min {spec.min_items} items)"
            if spec.max_items is not None:
                line += f" (max {spec.max_items} items)"
            if spec.constraints:
                constraint_str = ", ".join(
                    f"{k}={v}" for k, v in spec.constraints.items()
                )
                line += f" [{constraint_str}]"
            lines.append(line)

        lines.append("")
        lines.append(
            "Each block must include the 'type' field matching the block type above."
        )

        # Extended instructions for tab_view blocks
        if has_tab_view:
            lines.append("")
            lines.append("─── TAB VIEW INSTRUCTIONS ───────────────────────────────────")
            lines.append("")
            lines.append("For the 'tab_view' block, use this exact JSON structure:")
            lines.append("""  {
    "type": "tab_view",
    "style": "pills",
    "active_tab": "<id of first tab>",
    "tabs": [
      {
        "id": "<unique-slug>",
        "label": "<Tab Button Text>",
        "icon": "<optional emoji or CSS class>",
        "blocks": [ ... nested blocks ... ]
      },
      ...
    ]
  }""")
            lines.append("")
            lines.append("Tab pane 'blocks' may contain any of these block types:")
            lines.append(
                "  summary, bullet_list, table, accordion, checklist, chart,"
                " hero_card, timeline, callout, progress, divider, quote, image"
            )
            lines.append("")
            lines.append("NESTING CONSTRAINTS (strictly enforced):")
            lines.append("  - tab_view blocks MUST be at the top level only (no nested tab_views)")
            lines.append("  - accordion blocks inside tabs MUST NOT contain nested accordions")
            lines.append("  - Maximum nesting depth is 3 levels")
            lines.append("")
            lines.append("CONTENT GUIDELINES:")
            lines.append("  - The first tab should contain an overview or introduction")
            lines.append("  - Each tab should have a clear, distinct purpose")
            lines.append("  - Tab ids must be unique URL-safe slugs (e.g., 'overview', 'phases', 'qa')")
            lines.append("")
            lines.append("For 'accordion' blocks inside tabs:")
            lines.append("""  {
    "type": "accordion",
    "items": [
      {
        "title": "<section title>",
        "number": <optional step number>,
        "number_color": "<optional hex color>",
        "badge": "<optional badge text>",
        "badge_color": "<optional hex color>",
        "expanded": false,
        "content_blocks": [ ... flat blocks only ... ]
      }
    ]
  }""")
            lines.append("")
            lines.append("─────────────────────────────────────────────────────────────")

        return "\n".join(lines)


# ──────────────────────────────────────────────
# Built-in Templates
# ──────────────────────────────────────────────

TEMPLATE_BASIC = InfographicTemplate(
    name="basic",
    description="Simple overview infographic with title, key metrics, summary, chart, and takeaways.",
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Main title and subtitle for the infographic",
        ),
        BlockSpec(
            block_type=BlockType.HERO_CARD,
            description="3-5 key metric cards highlighting the most important numbers",
            min_items=3,
            max_items=5,
        ),
        BlockSpec(
            block_type=BlockType.SUMMARY,
            description="Executive summary of findings (2-3 paragraphs)",
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Primary data visualization",
        ),
        BlockSpec(
            block_type=BlockType.BULLET_LIST,
            description="Key takeaways or action items",
            min_items=3,
            max_items=8,
        ),
    ],
)


TEMPLATE_EXECUTIVE = InfographicTemplate(
    name="executive",
    description="Executive briefing with metrics, analysis, supporting data, and recommendations.",
    default_theme="corporate",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Report title, author, and date",
        ),
        BlockSpec(
            block_type=BlockType.HERO_CARD,
            description="4-6 KPI cards with trend indicators",
            min_items=4,
            max_items=6,
        ),
        BlockSpec(
            block_type=BlockType.SUMMARY,
            description="Executive summary and strategic context",
        ),
        BlockSpec(
            block_type=BlockType.DIVIDER,
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Primary trend chart",
            constraints={"chart_type": "line"},
        ),
        BlockSpec(
            block_type=BlockType.TABLE,
            description="Detailed data breakdown",
        ),
        BlockSpec(
            block_type=BlockType.DIVIDER,
        ),
        BlockSpec(
            block_type=BlockType.CALLOUT,
            description="Key risk or opportunity callout",
            required=False,
        ),
        BlockSpec(
            block_type=BlockType.BULLET_LIST,
            description="Recommendations and next steps",
            min_items=3,
            max_items=6,
        ),
    ],
)


TEMPLATE_DASHBOARD = InfographicTemplate(
    name="dashboard",
    description="Data-heavy dashboard with multiple metrics, charts, and tables.",
    default_theme="dark",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Dashboard title and time period",
        ),
        BlockSpec(
            block_type=BlockType.HERO_CARD,
            description="6-8 KPI metric cards",
            min_items=6,
            max_items=8,
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Primary trend visualization",
            constraints={"chart_type": "line"},
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Distribution or composition chart",
            constraints={"chart_type": "pie"},
        ),
        BlockSpec(
            block_type=BlockType.TABLE,
            description="Detailed metrics table with all data",
        ),
        BlockSpec(
            block_type=BlockType.PROGRESS,
            description="Goal completion indicators",
            required=False,
        ),
    ],
)


TEMPLATE_COMPARISON = InfographicTemplate(
    name="comparison",
    description="Side-by-side comparison infographic for evaluating options or periods.",
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Comparison title and what is being compared",
        ),
        BlockSpec(
            block_type=BlockType.SUMMARY,
            description="Overview of what is being compared and why",
        ),
        BlockSpec(
            block_type=BlockType.TABLE,
            description="Feature/metric comparison table",
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Visual comparison chart",
            constraints={"chart_type": "bar"},
        ),
        BlockSpec(
            block_type=BlockType.CALLOUT,
            description="Winner or recommendation callout",
        ),
        BlockSpec(
            block_type=BlockType.BULLET_LIST,
            description="Key differences and conclusions",
        ),
    ],
)


TEMPLATE_TIMELINE_REPORT = InfographicTemplate(
    name="timeline",
    description="Chronological report showing progress or history over time.",
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Report title and time span covered",
        ),
        BlockSpec(
            block_type=BlockType.SUMMARY,
            description="Overview of the timeline and key milestones",
        ),
        BlockSpec(
            block_type=BlockType.TIMELINE,
            description="Chronological events with dates and descriptions",
            min_items=4,
        ),
        BlockSpec(
            block_type=BlockType.CHART,
            description="Trend chart over the timeline period",
            constraints={"chart_type": "area"},
        ),
        BlockSpec(
            block_type=BlockType.BULLET_LIST,
            description="Key learnings or future outlook",
        ),
    ],
)


TEMPLATE_MINIMAL = InfographicTemplate(
    name="minimal",
    description="Minimal infographic with just a title, summary, and key points.",
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Title and subtitle",
        ),
        BlockSpec(
            block_type=BlockType.SUMMARY,
            description="Main content summary",
        ),
        BlockSpec(
            block_type=BlockType.BULLET_LIST,
            description="Key points",
        ),
    ],
)


TEMPLATE_MULTI_TAB = InfographicTemplate(
    name="multi_tab",
    description=(
        "Multi-section report organized as tabbed views. Ideal for methodology "
        "documentation, process guides, multi-phase projects, and complex reports "
        "with 3-7 distinct logical sections that benefit from navigable tabs."
    ),
    default_theme="light",
    block_specs=[
        BlockSpec(
            block_type=BlockType.TITLE,
            description="Main report title and optional subtitle",
            required=True,
        ),
        BlockSpec(
            block_type=BlockType.TAB_VIEW,
            description=(
                "Tabbed navigation containing 3-7 tabs. Each tab has a unique id, "
                "label, optional icon, and a list of content blocks. The first tab "
                "should contain an overview or introduction."
            ),
            required=True,
            min_items=3,
            max_items=7,
        ),
    ],
)


# ──────────────────────────────────────────────
# Template Registry
# ──────────────────────────────────────────────

class InfographicTemplateRegistry:
    """Registry of available infographic templates.

    Provides built-in templates and allows users to register custom ones.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, InfographicTemplate] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register all built-in templates."""
        for tpl in (
            TEMPLATE_BASIC,
            TEMPLATE_EXECUTIVE,
            TEMPLATE_DASHBOARD,
            TEMPLATE_COMPARISON,
            TEMPLATE_TIMELINE_REPORT,
            TEMPLATE_MINIMAL,
            TEMPLATE_MULTI_TAB,
        ):
            self._templates[tpl.name] = tpl

    def register(self, template: InfographicTemplate) -> None:
        """Register a custom template.

        Args:
            template: The template to register.
        """
        self._templates[template.name] = template

    def get(self, name: str) -> InfographicTemplate:
        """Get a template by name.

        Args:
            name: Template identifier.

        Returns:
            The matching InfographicTemplate.

        Raises:
            KeyError: If template name is not found.
        """
        try:
            return self._templates[name]
        except KeyError:
            available = ", ".join(sorted(self._templates.keys()))
            raise KeyError(
                f"Infographic template '{name}' not found. "
                f"Available templates: {available}"
            ) from None

    def list_templates(self) -> List[str]:
        """List all registered template names.

        Returns:
            Sorted list of template names.
        """
        return sorted(self._templates.keys())

    def list_templates_detailed(self) -> List[Dict[str, str]]:
        """List all templates with descriptions.

        Returns:
            List of dicts with 'name' and 'description' keys.
        """
        return [
            {"name": t.name, "description": t.description}
            for t in sorted(self._templates.values(), key=lambda x: x.name)
        ]


# Module-level singleton registry
infographic_registry = InfographicTemplateRegistry()
