from typing import List, Dict, Any, Optional
from pathlib import Path
from pydantic import BaseModel
import json
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa


class AppTemplate(BaseModel):
    """Template for app generation."""
    name: str
    description: str
    app_type: str  # streamlit, react, html
    base_structure: Dict[str, Any]
    required_features: List[str]
    optional_features: List[str]
    styling_theme: Dict[str, str]


class TemplateManager:
    """
    Manages reusable templates for web app generation.
    """

    def __init__(self, templates_dir: Path):
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._templates: Dict[str, AppTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        """Load templates from directory."""
        for template_file in self.templates_dir.glob("*.json"):
            with open(template_file) as f:
                data = json_decoder(f)
                template = AppTemplate(**data)
                self._templates[template.name] = template

    def create_template(
        self,
        name: str,
        app_type: str,
        description: str,
        base_structure: Dict[str, Any],
        required_features: List[str],
        optional_features: List[str] = None,
        styling_theme: Dict[str, str] = None
    ) -> AppTemplate:
        """Create a new template."""
        template = AppTemplate(
            name=name,
            description=description,
            app_type=app_type,
            base_structure=base_structure,
            required_features=required_features,
            optional_features=optional_features or [],
            styling_theme=styling_theme or {}
        )

        # Save to file
        template_file = self.templates_dir / f"{name}.json"
        with open(template_file, 'w') as f:
            json_encoder(template.model_dump(), f)

        self._templates[name] = template
        return template

    def get_template(self, name: str) -> Optional[AppTemplate]:
        """Get a template by name."""
        return self._templates.get(name)

    def list_templates(self) -> List[str]:
        """List all available templates."""
        return list(self._templates.keys())

    def generate_from_template(
        self,
        template_name: str,
        customization: Dict[str, Any],
        llm_client
    ) -> str:
        """Generate an app from a template with customization."""
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        prompt = f"""Generate a {template.app_type} application based on this template:

**Template:** {template.name}
{template.description}

**Required Features:**
{chr(10).join(f'- {f}' for f in template.required_features)}

**Customizations:**
{chr(10).join(f'- {k}: {v}' for k, v in customization.items())}

**Base Structure:**
{json.dumps(template.base_structure, indent=2)}

**Styling Theme:**
{json.dumps(template.styling_theme, indent=2)}

Generate complete code following the template structure with the specified customizations."""

        return prompt
