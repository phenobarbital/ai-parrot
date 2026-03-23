from typing import Dict, Any, List, Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, Template
from pydantic import BaseModel

class TemplateSection(BaseModel):
    """Defines a fillable section in the template."""
    name: str
    description: str
    content_type: str  # 'text', 'table', 'chart', 'image', 'list'
    required: bool = True
    example: Optional[str] = None

class ReportTemplate(BaseModel):
    """Defines a report template structure."""
    name: str
    description: str
    template_path: Path
    sections: List[TemplateSection]
    css_path: Optional[Path] = None

    def get_section_prompts(self) -> Dict[str, str]:
        """Generate prompts for LLM to fill each section."""
        prompts = {}
        for section in self.sections:
            prompt = (
                f"Generate {section.content_type} content for the "
                f"'{section.name}' section.\n"
                f"Description: {section.description}\n"
            )
            if section.example:
                prompt += f"Example format:\n{section.example}\n"
            prompts[section.name] = prompt
        return prompts

class TemplateRegistry:
    """Registry of available templates."""

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(templates_dir)
        )
        self._templates: Dict[str, ReportTemplate] = {}

    def register(self, template: ReportTemplate):
        """Register a template."""
        self._templates[template.name] = template

    def get(self, name: str) -> ReportTemplate:
        """Get a template by name."""
        return self._templates.get(name)

    def list(self) -> List[str]:
        """List available templates."""
        return list(self._templates.keys())

# Built-in templates
EXECUTIVE_SUMMARY_TEMPLATE = ReportTemplate(
    name="executive_summary",
    description="Executive summary report with key findings",
    template_path=Path("templates/executive_summary.html"),
    sections=[
        TemplateSection(
            name="title",
            description="Report title",
            content_type="text"
        ),
        TemplateSection(
            name="executive_summary",
            description="High-level overview (2-3 paragraphs)",
            content_type="text"
        ),
        TemplateSection(
            name="key_findings",
            description="Bullet points of main findings",
            content_type="list"
        ),
        TemplateSection(
            name="data_table",
            description="Supporting data in table format",
            content_type="table"
        ),
        TemplateSection(
            name="visualization",
            description="Chart showing trends",
            content_type="chart"
        ),
        TemplateSection(
            name="recommendations",
            description="Actionable recommendations",
            content_type="list"
        )
    ]
)
