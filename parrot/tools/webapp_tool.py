from typing import Optional
from pathlib import Path
from pydantic import BaseModel, Field
from .abstract import AbstractTool
from ..generators import (
    StreamlitGenerator,
    ReactGenerator,
    HTMLGenerator
)

class WebAppGeneratorInput(BaseModel):
    """Input schema for the WebAppGeneratorTool."""
    description: Optional[str] = Field(
        default='WebApp',
        description=(
            "Detailed description of the web application to build. "
            "Include features, functionality, data to display, and any design preferences."
        )
    )
    app_type: Optional[str] = Field(
        default='streamlit',
        description=(
            "Type of web application to generate:\n"
            "- streamlit: Python-based data apps with interactive widgets\n"
            "- react: Modern single-page applications with React\n"
            "- html: Standalone HTML pages with vanilla JavaScript"
        )
    )
    requirements: Optional[str] = Field(
        default=None,
        description="Additional technical requirements or constraints"
    )
    save_file: Optional[bool] = Field(
        default=False,
        description="Whether to save the generated code to a file"
    )


class WebAppGeneratorTool(AbstractTool):
    """
    Tool that enables agents to generate complete web applications.

    This tool wraps the web app generators and makes them available to agents
    through the tool manager system.
    """
    args_schema = WebAppGeneratorInput

    def __init__(
        self,
        llm_client,
        output_dir: Optional[Path] = None,
        default_type: str = 'streamlit'
    ):
        """
        Initialize the WebApp Generator Tool.

        Args:
            llm_client: LLM client instance for generation
            output_dir: Directory to save generated apps
            default_type: Default app type if not specified
        """
        super().__init__()

        self.name = "web_app_generator"
        self.description = (
            "Generates complete, production-ready web applications based on descriptions. "
            "Supports Streamlit (Python data apps), React (interactive SPAs), and HTML (standalone pages). "
            "Use this when the user asks to create a dashboard, app, web page, or interactive tool. "
            "The tool will generate fully functional code that can be immediately deployed."
        )

        # Initialize generators
        self.generators = {
            'streamlit': StreamlitGenerator(llm_client, output_dir),
            'react': ReactGenerator(llm_client, output_dir),
            'html': HTMLGenerator(llm_client, output_dir)
        }

        self.default_type = default_type

        # Define input schema for the tool
        self.input_schema = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "Detailed description of the web application to build. "
                        "Include features, functionality, data to display, and any design preferences."
                    )
                },
                "app_type": {
                    "type": "string",
                    "enum": ["streamlit", "react", "html"],
                    "description": (
                        "Type of web application to generate:\n"
                        "- streamlit: Python-based data apps with interactive widgets\n"
                        "- react: Modern single-page applications with React\n"
                        "- html: Standalone HTML pages with vanilla JavaScript"
                    )
                },
                "requirements": {
                    "type": "string",
                    "description": "Additional technical requirements or constraints"
                },
                "save_file": {
                    "type": "boolean",
                    "description": "Whether to save the generated code to a file"
                }
            },
            "required": ["description"],
            "additionalProperties": False
        }

    async def _execute(
        self,
        description: Optional[str] = 'WebApp',
        app_type: Optional[str] = None,
        requirements: Optional[str] = None,
        save_file: bool = False,
        **kwargs
    ) -> str:
        """
        Execute the web app generation.

        Args:
            description: Description of the app to build
            app_type: Type of app (streamlit, react, html)
            requirements: Additional requirements
            save_file: Whether to save to file

        Returns:
            String describing the generated app with code
        """
        app_type = app_type or self.default_type

        if app_type not in self.generators:
            return f"Error: Unknown app type '{app_type}'. Choose from: streamlit, react, html"

        generator = self.generators[app_type]

        try:
            # Generate the app
            response = await generator.generate(
                description=description,
                additional_requirements=requirements,
                save_to_file=save_file,
                **kwargs
            )

            if not response.output:
                return "Failed to generate web application. Please try again with more details."

            output = response.output

            # Build response message
            result = [
                f"✓ Successfully generated {app_type.upper()} application!",
                f"\nTitle: {output.title}",
                f"Description: {output.description}",
                f"\nFeatures:",
            ]
            result.extend(f"  • {feature}" for feature in output.features)

            if hasattr(output, 'requirements'):
                result.append(f"\nRequirements: {', '.join(output.requirements)}")

            if save_file and hasattr(response, 'metadata') and 'saved_path' in response.metadata:
                result.append(f"\n✓ Saved to: {response.metadata['saved_path']}")

            result.append(
                f"\nGenerated Code:\n```{self._get_language(app_type)}\n{output.code}\n```"
            )

            return "\n".join(result)

        except Exception as e:
            return f"Error generating {app_type} app: {str(e)}"

    def _get_language(self, app_type: str) -> str:
        """Get the code language identifier for markdown."""
        languages = {
            'streamlit': 'python',
            'react': 'jsx',
            'html': 'html'
        }
        return languages.get(app_type, 'text')
