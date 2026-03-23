from abc import ABC, abstractmethod
from typing import Optional, Type, Dict, Any, Union
import datetime
from pathlib import Path
from pydantic import BaseModel
from navconfig.logging import logging
from ..models.responses import AIMessage


class WebAppGenerator(ABC):
    """
    Base class for web application generators.

    Subclass this to create generators for specific app types (Streamlit, React, etc.)
    """

    def __init__(
        self,
        llm_client,
        output_dir: Optional[Path] = None
    ):
        """
        Initialize the generator.

        Args:
            llm_client: LLM client instance (GoogleClient, OpenAIClient, etc.)
            output_dir: Optional directory to save generated apps
        """
        self.llm = llm_client
        self.output_dir = output_dir
        self.app_type = self.__class__.__name__.replace('Generator', '').lower()
        self.logger = logging.getLogger(
            f'Parrot.Generator.{self.app_type}'
        )

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Return the system prompt template for this generator.

        Should include placeholders for: {user_description}, {additional_requirements},
        {high_quality_example}
        """
        pass

    @abstractmethod
    def get_output_schema(self) -> Type[BaseModel]:
        """Return the Pydantic schema for structured output."""
        pass

    @abstractmethod
    def get_examples(self) -> str:
        """Return high-quality example code to guide the LLM."""
        pass

    def build_prompt(
        self,
        user_description: str,
        additional_requirements: str = "",
        **kwargs
    ) -> str:
        """
        Build the complete generation prompt.

        Args:
            user_description: User's description of desired app
            additional_requirements: Extra technical requirements
            **kwargs: Additional template variables

        Returns:
            Formatted prompt string
        """
        template = self.get_system_prompt()
        examples = self.get_examples()

        return template.format(
            user_description=user_description,
            additional_requirements=additional_requirements,
            high_quality_example=examples,
            **kwargs
        )

    async def generate(
        self,
        description: str,
        additional_requirements: Optional[str] = None,
        use_structured_output: bool = True,
        save_to_file: bool = False,
        filename: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs
    ) -> AIMessage:
        """
        Generate a web application based on description.

        Args:
            description: Detailed description of the app to build
            additional_requirements: Optional extra requirements
            use_structured_output: Whether to use structured output schema
            save_to_file: Whether to save generated code to file
            filename: Custom filename (auto-generated if None)
            temperature: LLM temperature for generation
            max_tokens: Maximum tokens for generation
            **kwargs: Additional arguments passed to LLM

        Returns:
            AIMessage with generated app code
        """
        self.logger.info(f"Generating {self.app_type} app...")

        # Build the prompt
        prompt = self.build_prompt(
            user_description=description,
            additional_requirements=additional_requirements or ""
        )

        # Get structured output schema
        output_schema = self.get_output_schema() if use_structured_output else None

        # Generate with LLM
        response = await self.llm.ask(
            prompt=prompt,
            structured_output=output_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        # Validate and optionally save
        if response.output:
            code = self._extract_code(response.output)
            validation = self.validate_output(code)

            if not validation['valid']:
                self.logger.warning(f"Generated code has issues: {validation['errors']}")

            if save_to_file:
                filepath = self._save_to_file(response.output, filename)
                self.logger.info(f"Saved app to: {filepath}")
                response.metadata = response.metadata or {}
                response.metadata['saved_path'] = str(filepath)

        return response

    def _extract_code(self, output: Union[BaseModel, str]) -> str:
        """Extract code string from output."""
        if isinstance(output, str):
            return output
        if hasattr(output, 'code'):
            return output.code
        return str(output)

    def _save_to_file(self, output: BaseModel, filename: Optional[str] = None) -> Path:
        """Save generated code to file."""
        if self.output_dir is None:
            raise ValueError("output_dir must be set to save files")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            # Auto-generate filename from title or timestamp
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            title = getattr(output, 'title', f'{self.app_type}_app')
            title = title.lower().replace(' ', '_')
            filename = f"{title}_{timestamp}"

        # Add appropriate extension
        extension = self._get_file_extension()
        if not filename.endswith(extension):
            filename += extension

        filepath = self.output_dir / filename
        filepath.write_text(output.code)

        return filepath

    def _get_file_extension(self) -> str:
        """Get appropriate file extension for this app type."""
        extensions = {
            'streamlit': '.py',
            'react': '.jsx',
            'html': '.html'
        }
        return extensions.get(self.app_type, '.txt')

    def validate_output(self, code: str) -> Dict[str, Any]:
        """
        Validate the generated code.

        Override in subclasses for app-specific validation.

        Returns:
            Dict with 'valid', 'errors', 'warnings' keys
        """
        return {
            "valid": True,
            "errors": [],
            "warnings": []
        }
