from typing import Any, Dict, List, Optional, Type, Union
import re
import logging
from datetime import datetime
import asyncio
from pathlib import Path
import json
import traceback
import tiktoken
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, ConfigDict
from langchain.tools import BaseTool
import markdown
from weasyprint import HTML, CSS
from navconfig import BASE_DIR
from .abstract import BaseAbstractTool


logging.getLogger("weasyprint").setLevel(logging.ERROR)  # Suppress WeasyPrint warnings
# Suppress tiktoken warnings
logging.getLogger("tiktoken").setLevel(logging.ERROR)
logging.getLogger("fontTools.ttLib.ttFont").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset.timer").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)


MODEL_CTX = {
    "gpt-4.1": 32_000,
    "gpt-4o-32k": 32_000,
    "gpt-4o-8k": 8_000,
}

def count_tokens(text: str, model: str = "gpt-4.1") -> int:
    enc = tiktoken.encoding_for_model(model)
    return len(enc.encode(text))

class PDFPrintInput(BaseModel):
    """
    Input schema for the PDFPrint.  Users can supply:
    • text (required): the transcript or Markdown to saved as PDF File.
    • output_filename: (Optional) a custom filename (including extension) for the generated PDF.
    """
    # Add a model_config to prevent additional properties
    model_config = ConfigDict(extra='forbid')

    text: str = Field(..., description="The text (plaintext or Markdown) to convert to PDF File")
    # If you’d like users to control the output filename/location:
    file_prefix: str | None = Field(
        default="document",
        description="Stem for the output file. Timestamp and extension added automatically."
    )
    template_name: Optional[str] = Field(
        None,
        description="Name of the HTML template (e.g. 'report.html') to render"
    )
    template_vars: Optional[Dict[str, str]] = Field(
        None,
        description="Dict of variables to pass into the template (e.g. title, author, date)"
    )
    stylesheets: Optional[List[str]] = Field(
        None,
        description="List of CSS file paths (relative to your templates dir) to apply"
    )


class PDFPrintTool(BaseAbstractTool):
    """Tool that saves a PDF file from content."""
    name: str = "pdf_print_tool"
    description: str = (
        "Generates a PDF file from the provided text content. "
        "The content can be in plaintext or Markdown format. "
        "You can also specify an output filename prefix for the output PDF."
    )
    # output_dir: Optional[Path] = BASE_DIR.joinpath("static", "documents", "pdf")
    env: Optional[Environment] = None
    templates_dir: Optional[Path] = None

    # Add a proper args_schema for tool-calling compatibility
    args_schema: Type[BaseModel] = PDFPrintInput


    def __init__(
        self,
        *args,
        templates_dir: Path = BASE_DIR.joinpath('templates'),
        **kwargs
    ):
        """Initialize the PDF Print Tool."""
        super().__init__(*args, **kwargs)
        # Initialize Jinja2 environment for HTML templates
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True
        )
        self.templates_dir = templates_dir

    def _default_output_dir(self) -> Path:
        """Get default output directory for PDF files."""
        return self.static_dir.joinpath('documents', 'pdf')

    def is_markdown(self, text: str) -> bool:
        """Determine if the text appears to be Markdown formatted."""
        if not text or not isinstance(text, str):
            return False

        # Corrección: Separar los caracteres problemáticos y el rango
        if re.search(r"^[#*_>`\[\d-]", text.strip()[0]):  # Check if first char is a Markdown marker
            return True

        # Check for common Markdown patterns
        if re.search(r"#{1,6}\s+", text):  # Headers
            return True
        if re.search(r"\*\*.*?\*\*", text):  # Bold
            return True
        if re.search(r"_.*?_", text):  # Italic
            return True
        if re.search(r"`.*?`", text):  # Code
            return True
        if re.search(r"\[.*?\]\(.*?\)", text):  # Links
            return True
        if re.search(r"^\s*[\*\-\+]\s+", text, re.MULTILINE):  # Unordered lists
            return True
        if re.search(r"^\s*\d+\.\s+", text, re.MULTILINE):  # Ordered lists
            return True
        if re.search(r"```.*?```", text, re.DOTALL):  # Code blocks
            return True

        return False

    async def _generate_content(self, payload: PDFPrintInput) -> Dict[str, Any]:
        """Main method to generate a PDF from query."""
        content = payload.text.strip()
        if not content:
            raise ValueError("The text content cannot be empty.")
        # Determine if the content is Markdownd
        is_markdown = self.is_markdown(content)
        if is_markdown:
            # Convert Markdown to HTML
            content = markdown.markdown(content, extensions=['tables'])
        if payload.template_name is None:
            tmpl = self.env.get_template("report.html")
        else:
            tpl = payload.template_name
            if not tpl.endswith('.html'):
                tpl += '.html'
            try:
                tmpl = self.env.get_template(str(tpl))
                context = {"body": content, **(payload.template_vars or {})}
                content = tmpl.render(**context)
            except Exception as e:
                # use a generic template if the specified one fails
                print(f"Error loading template {tpl}: {e}")
        # Attach the CSS objects:
        css_list = []
        for css_file in payload.stylesheets or []:
            css_path = self.templates_dir / css_file
            css_list.append( CSS(filename=str(css_path)) )
        # add the tables CSS:
        css_list.append(
            CSS(
                filename=str(self.templates_dir / "css" / "base.css")
            )
        )
        # Generate filename and output path
        output_filename = self.generate_filename(
            prefix=payload.file_prefix or "document",
            extension="pdf"
        )
        output_path = self.output_dir.joinpath(output_filename)
        output_path = self.validate_output_path(output_path)
        url = self.to_static_url(output_path)
        try:
            HTML(
                string=content,
                base_url=str(self.templates_dir)
            ).write_pdf(
                output_path,
                stylesheets=css_list
            )
            print(f"PDF generated: {output_path}")
            return {
                "status": "success",
                "message": "PDF generated successfully.",
                "text": payload.text,
                "url": url,
                "static_url": self.relative_url(url),
                "filename": output_path,
                "file_path": self.output_dir,
            }
        except Exception as e:
            print(f"Error in _generate_podcast: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    def _generate_payload(
        self,
        **kwargs
    ) -> PDFPrintInput:
        # Extract "text" and "file_prefix" from args
        text = kwargs.pop("text", None)
        file_prefix = kwargs.pop("file_prefix", None)
        if not text:
            raise ValueError("The 'text' field is required for PDF generation.")
        if not isinstance(text, str):
            raise ValueError("The 'text' field must be a string.")

        payload_dict = {
            "text": text,
            "file_prefix": file_prefix,
            **kwargs
        }
        return PDFPrintInput(
            **{k: v for k, v in payload_dict.items() if v is not None}
        )
