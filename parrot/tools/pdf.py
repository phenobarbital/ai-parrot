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


class PDFPrintTool(BaseTool):
    """Tool that saves a PDF file from content."""
    name: str = "pdf_print_tool"
    description: str = (
        "Generates a PDF file from the provided text content. "
        "The content can be in plaintext or Markdown format. "
        "You can also specify an output filename prefix for the output PDF."
    )
    output_dir: Optional[Path] = BASE_DIR.joinpath("static", "documents", "pdf")
    env: Optional[Environment] = None
    templates_dir: Optional[Path] = None

    # Add a proper args_schema for tool-calling compatibility
    args_schema: Type[BaseModel] = PDFPrintInput


    def __init__(
        self,
        name: str = "pdf_print_tool",
        templates_dir: Path = BASE_DIR.joinpath('templates'),
        output_dir: str = None,
        **kwargs
    ):
        """Initialize the PDF Print Tool."""
        super().__init__(**kwargs)
        self.output_dir = Path(output_dir) if output_dir else BASE_DIR.joinpath("static", "documents", "pdf")
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
        # Initialize Jinja2 environment for HTML templates
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True
        )
        self.templates_dir = templates_dir

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

    async def _generate_pdf(self, payload: PDFPrintInput) -> dict:
        """Main method to generate a PDF from query."""
        content = payload.text.strip()
        if not content:
            raise ValueError("The text content cannot be empty.")
        # try:
        #     model = payload.template_vars.get("llm_model", "gpt-4.1")
        # except AttributeError:
        #     model = "gpt-4.1"
        # # 1) Count the tokens in the content
        # # This is useful for debugging and ensuring we don’t exceed model limits
        # if not isinstance(content, str):
        #     raise ValueError("Content must be a string.")
        # token_count = count_tokens(content, model)
        # # 2) If they’re over the limit, warn & split
        # max_tokens = MODEL_CTX.get(model, 32_000)
        # if token_count > max_tokens:
        #     self.logger.warning(
        #         f"⚠️ Your document is {token_count} tokens long, "
        #         f"which exceeds the {max_tokens}-token context window of {model}."
        #     )
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

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = payload.file_prefix or "document"
        # Generate a unique filename based on the current timestamp
        output_filename = f"{prefix}_{timestamp}.pdf"
        output_path = self.output_dir.joinpath(output_filename)
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
                "file_path": self.output_dir,
                "timestamp": timestamp,
                "filename": output_path
            }
        except Exception as e:
            print(f"Error in _generate_podcast: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    async def _arun(
        self,
        text: str,
        file_prefix: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        LangChain will call this with keyword args matching PDFPrintInput, e.g.:
        _arun(text="Hello", output_dir="documents/", …)
        """
        try:
            # 1) Build a dict of everything LangChain passed us
            payload_dict = {
                "text": text,
                "file_prefix": file_prefix,
                **kwargs
            }
            # 2) Let Pydantic validate & coerce
            payload = PDFPrintInput(**{k: v for k, v in payload_dict.items() if v is not None})
            # 3) Call the “real” generator
            return await self._generate_pdf(payload)
        except Exception as e:
            print(f"❌ Error in PDFPrint._arun: {e}")
            print(traceback.format_exc())
            return {"error": str(e)}

    # Mirror the same signature for the synchronous runner:
    def _run(
        self,
        text: Union[str, Dict[str, Any]],
        file_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synchronous entrypoint. If text_or_json is a JSON string, we load it first.
        Otherwise, assume it’s already a dict of the correct shape.
        """
        try:
            if isinstance(text, str):
                data = json.loads(text)
                # We expect a JSON‐dict with keys matching PodcastInput
            elif isinstance(text, dict):
                data = text
            else:
                return {"error": "Invalid payload type. Must be JSON string or dict."}
            # Validate with PodcastInput
            payload = PDFPrintInput(file_prefix=file_prefix, **data)
        except Exception as e:
            return {"error": f"Invalid input: {e}"}

        loop = asyncio.get_event_loop()
        if loop.is_running():
            return loop.run_until_complete(self._generate_pdf(payload))
        else:
            return loop.run_until_complete(self._generate_pdf(payload))
