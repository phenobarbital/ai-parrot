"""
PDF Print Tool migrated to use AbstractTool framework.
"""
import re
import logging
from typing import Any, Dict, List, Optional
import asyncio
from datetime import datetime
from pathlib import Path
import traceback
import tiktoken
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, field_validator
import markdown
from weasyprint import HTML, CSS
from .abstract import AbstractTool


# Suppress various library warnings
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("tiktoken").setLevel(logging.ERROR)
logging.getLogger("fontTools.ttLib.ttFont").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset.timer").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)



def count_tokens(text: str, model: str = "gpt-4.1") -> int:
    """Count tokens in text using tiktoken."""
    try:
        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        # Fallback to rough character estimation
        return len(text) // 4


class PDFPrintArgs(BaseModel):
    """Arguments schema for PDFPrintTool."""

    text: str = Field(
        ...,
        description="The text content (plaintext or Markdown) to convert to PDF"
    )
    file_prefix: str = Field(
        "document",
        description="Prefix for the output filename (timestamp and extension added automatically)"
    )
    template_name: Optional[str] = Field(
        None,
        description="Name of the HTML template to use (e.g., 'report.html'). If None, uses default template"
    )
    template_vars: Optional[Dict[str, Any]] = Field(
        None,
        description="Dictionary of variables to pass to the template (e.g., title, author, date)"
    )
    stylesheets: Optional[List[str]] = Field(
        None,
        description="List of CSS file paths (relative to templates directory) to apply"
    )
    auto_detect_markdown: bool = Field(
        True,
        description="Whether to automatically detect and convert Markdown content to HTML"
    )

    @field_validator('text')
    @classmethod
    def validate_text(cls, v):
        if not v or not v.strip():
            raise ValueError("Text content cannot be empty")
        return v

    @field_validator('file_prefix')
    @classmethod
    def validate_file_prefix(cls, v):
        # Remove invalid filename characters
        if v:
            v = re.sub(r'[<>:"/\\|?*]', '_', v)
        return v or "document"

    @field_validator('template_name')
    @classmethod
    def validate_template_name(cls, v):
        if v and not v.endswith('.html'):
            v = f"{v}.html"
        return v


class PDFPrintTool(AbstractTool):
    """
    Tool for generating PDF documents from text content.

    This tool can process both plain text and Markdown content, converting them
    into professionally formatted PDF documents. It supports custom HTML templates,
    CSS styling, and variable substitution for dynamic content generation.

    Features:
    - Automatic Markdown detection and conversion
    - Custom HTML template support
    - CSS styling with multiple stylesheet support
    - Variable substitution in templates
    - Professional PDF output with proper formatting
    - Token counting for content analysis
    """

    name = "pdf_print"
    description = (
        "Generate PDF documents from text content. Supports both plain text and Markdown. "
        "Can use custom HTML templates and CSS styling. Perfect for creating reports, "
        "documentation, and formatted documents from text content."
    )
    args_schema = PDFPrintArgs

    def __init__(
        self,
        templates_dir: Optional[Path] = None,
        default_template: str = "report.html",
        default_stylesheets: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize the PDF Print Tool.

        Args:
            templates_dir: Directory containing HTML templates and CSS files
            default_template: Default template to use if none specified
            default_stylesheets: Default CSS files to include
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(**kwargs)

        # Set up templates directory
        if templates_dir is None:
            # Try to find templates directory relative to the tool
            possible_paths = [
                Path.cwd() / "templates",
                Path(__file__).parent.parent / "templates",
                self.static_dir / "templates" if self.static_dir else None
            ]

            for path in possible_paths:
                if path and path.exists():
                    templates_dir = path
                    break

            if templates_dir is None:
                # Create a basic templates directory
                templates_dir = self.static_dir / "templates" if self.static_dir else Path("templates")
                templates_dir.mkdir(parents=True, exist_ok=True)
                self._create_default_template(templates_dir)

        self.templates_dir = Path(templates_dir)
        self.default_template = default_template
        self.default_stylesheets = default_stylesheets or ["css/base.css"]

        # Initialize Jinja2 environment
        try:
            self.env = Environment(
                loader=FileSystemLoader(str(self.templates_dir)),
                autoescape=True
            )
            self.logger.info(
                f"PDF Print tool initialized with templates from: {self.templates_dir}"
            )
        except Exception as e:
            self.logger.error(f"Error initializing Jinja2 environment: {e}")
            raise ValueError(f"Failed to initialize PDF tool: {e}")

    def _default_output_dir(self) -> Path:
        """Get the default output directory for PDF files."""
        return self.static_dir / "documents" / "pdf"

    def _create_default_template(self, templates_dir: Path) -> None:
        """Create a default HTML template if none exists."""
        try:
            # Create directories
            (templates_dir / "css").mkdir(parents=True, exist_ok=True)

            # Default HTML template
            default_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title | default('Document') }}</title>
</head>
<body>
    <header>
        <h1>{{ title | default('Document') }}</h1>
        {% if author %}<p class="author">By: {{ author }}</p>{% endif %}
        {% if date %}<p class="date">{{ date }}</p>{% endif %}
    </header>

    <main>
        {{ body | safe }}
    </main>

    <footer>
        <p>Generated on {{ generated_date | default('') }}</p>
    </footer>
</body>
</html>"""

            # Default CSS
            default_css = """
body {
    font-family: 'Arial', sans-serif;
    line-height: 1.6;
    margin: 2cm;
    color: #333;
}

header {
    border-bottom: 2px solid #333;
    margin-bottom: 2em;
    padding-bottom: 1em;
}

h1 { color: #2c3e50; font-size: 2.5em; margin-bottom: 0.5em; }
h2 { color: #34495e; font-size: 2em; margin-top: 1.5em; }
h3 { color: #7f8c8d; font-size: 1.5em; margin-top: 1.2em; }

.author, .date { font-style: italic; color: #7f8c8d; margin: 0.5em 0; }

table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
}

th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: left;
}

th { background-color: #f2f2f2; font-weight: bold; }

code {
    background-color: #f4f4f4;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
}

pre {
    background-color: #f4f4f4;
    padding: 1em;
    border-radius: 5px;
    overflow-x: auto;
}

blockquote {
    border-left: 4px solid #3498db;
    margin: 1em 0;
    padding-left: 1em;
    font-style: italic;
}

footer {
    border-top: 1px solid #ddd;
    margin-top: 2em;
    padding-top: 1em;
    font-size: 0.9em;
    color: #7f8c8d;
}

@media print {
    body { margin: 1cm; }
    header { page-break-after: avoid; }
    h1, h2, h3 { page-break-after: avoid; }
}
"""
            # Write files
            with open(templates_dir / "report.html", 'w', encoding='utf-8') as f:
                f.write(default_html)

            with open(templates_dir / "css" / "base.css", 'w', encoding='utf-8') as f:
                f.write(default_css)

            self.logger.info("Created default template files")

        except Exception as e:
            self.logger.error(f"Error creating default template: {e}")

    def _is_markdown(self, text: str) -> bool:
        """Determine if the text appears to be Markdown formatted."""
        if not text or not isinstance(text, str):
            return False

        text = text.strip()
        if not text:
            return False

        # Check first character for Markdown markers
        first_char = text[0]
        if first_char in "#*_>`-":
            return True

        # Check if first character is a digit (for numbered lists)
        if first_char.isdigit() and re.match(r'^\d+\.', text):
            return True

        # Check for common Markdown patterns
        markdown_patterns = [
            r"#{1,6}\s+",                    # Headers
            r"\*\*.*?\*\*",                  # Bold
            r"__.*?__",                      # Bold alternative
            r"\*.*?\*",                      # Italic
            r"_.*?_",                        # Italic alternative
            r"`.*?`",                        # Inline code
            r"\[.*?\]\(.*?\)",               # Links
            r"^\s*[\*\-\+]\s+",             # Unordered lists
            r"^\s*\d+\.\s+",                # Ordered lists
            r"```.*?```",                    # Code blocks
            r"^\s*>\s+",                     # Blockquotes
            r"^\s*\|.*\|",                   # Tables
        ]

        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE | re.DOTALL):
                return True

        return False

    def _load_stylesheets(self, stylesheets: Optional[List[str]]) -> List[CSS]:
        """
        Load CSS stylesheets for PDF generation.

        Args:
            stylesheets: List of CSS file paths relative to templates directory

        Returns:
            List of CSS objects for WeasyPrint
        """
        css_objects = []

        # Use provided stylesheets or defaults
        css_files = stylesheets or self.default_stylesheets

        for css_file in css_files:
            try:
                css_path = self.templates_dir / css_file
                if css_path.exists():
                    css_objects.append(CSS(filename=str(css_path)))
                    self.logger.debug(f"Loaded stylesheet: {css_file}")
                else:
                    self.logger.warning(f"Stylesheet not found: {css_path}")
            except Exception as e:
                self.logger.error(f"Error loading stylesheet {css_file}: {e}")

        # Add base CSS if no stylesheets were loaded
        if not css_objects:
            try:
                base_css_path = self.templates_dir / "css" / "base.css"
                if base_css_path.exists():
                    css_objects.append(CSS(filename=str(base_css_path)))
                    self.logger.info("Added base.css as fallback stylesheet")
            except Exception as e:
                self.logger.error(f"Error loading base stylesheet: {e}")

        return css_objects

    async def _execute(
        self,
        text: str,
        file_prefix: str = "document",
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
        stylesheets: Optional[List[str]] = None,
        auto_detect_markdown: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute PDF generation with enhanced debugging.
        """
        try:
            self.logger.debug(
                f"Starting PDF generation with {len(text)} characters of content"
            )

            # Process content
            processed_content = self._process_content(
                text, auto_detect_markdown, template_name, template_vars
            )

            # Debug: Log the processed content length and first 500 chars
            self.logger.info(f"Processed content length: {len(processed_content)}")
            self.logger.debug(f"Processed content preview: {processed_content[:500]}...")

            # Load stylesheets
            css_objects = self._load_stylesheets(stylesheets)
            self.logger.info(f"Loaded {len(css_objects)} CSS stylesheets")

            # Generate filename and output path
            output_filename = self.generate_filename(
                prefix=file_prefix,
                extension="pdf",
                include_timestamp=True
            )

            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / output_filename
            output_path = self.validate_output_path(output_path)

            self.logger.info(f"Generating PDF: {output_path}")

            # Debug: Save HTML content to file for inspection
            debug_html_path = self.output_dir / f"{file_prefix}_debug.html"
            try:
                with open(debug_html_path, 'w', encoding='utf-8') as f:
                    f.write(processed_content)
                self.logger.info(f"Debug HTML saved to: {debug_html_path}")
            except Exception as e:
                self.logger.warning(f"Could not save debug HTML: {e}")

            # Generate PDF with detailed error handling
            try:
                # Create HTML object
                html_obj = HTML(
                    string=processed_content,
                    base_url=str(self.templates_dir)
                )

                # Generate PDF
                html_obj.write_pdf(
                    str(output_path),
                    stylesheets=css_objects
                )

                # Check if file was actually created
                if not output_path.exists():
                    raise Exception("PDF file was not created")

                file_size = output_path.stat().st_size
                if file_size == 0:
                    raise Exception("PDF file is empty (0 bytes)")

                self.logger.info(f"PDF generated successfully: {output_path} ({file_size} bytes)")

            except Exception as pdf_error:
                self.logger.error(f"PDF generation failed: {pdf_error}")

                # Try alternative approaches
                try:
                    self.logger.info("Attempting PDF generation with minimal HTML...")

                    # Create minimal HTML wrapper
                    minimal_html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Document</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 2cm; line-height: 1.6; }}
            h1, h2, h3 {{ color: #333; }}
            ul, ol {{ margin: 1em 0; }}
            li {{ margin: 0.5em 0; }}
        </style>
    </head>
    <body>
        {processed_content}
    </body>
    </html>"""

                    # Try with minimal HTML
                    HTML(string=minimal_html).write_pdf(str(output_path))

                    if output_path.exists() and output_path.stat().st_size > 0:
                        self.logger.info("PDF generated with minimal HTML approach")
                    else:
                        raise Exception("Minimal HTML approach also failed")

                except Exception as minimal_error:
                    self.logger.error(f"Minimal HTML approach failed: {minimal_error}")

                    # Last resort: plain text
                    try:
                        self.logger.info("Attempting PDF generation with plain text...")

                        plain_html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Document</title>
    </head>
    <body>
        <pre style="white-space: pre-wrap; font-family: Arial; margin: 2cm;">
    {text}
        </pre>
    </body>
    </html>"""

                        HTML(string=plain_html).write_pdf(str(output_path))

                        if not output_path.exists() or output_path.stat().st_size == 0:
                            raise Exception("Plain text approach also failed")

                        self.logger.warning("PDF generated with plain text fallback")

                    except Exception as plain_error:
                        self.logger.error(f"All PDF generation approaches failed: {plain_error}")
                        raise Exception(f"PDF generation completely failed. Last error: {plain_error}")

            # Generate URLs and results
            file_url = self.to_static_url(output_path)
            relative_url = self.relative_url(file_url)
            token_count = count_tokens(text)
            file_size = output_path.stat().st_size

            result = {
                "filename": output_filename,
                "file_path": str(output_path),
                "file_url": file_url,
                "relative_url": relative_url,
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "content_stats": {
                    "characters": len(text),
                    "tokens": token_count,
                    "was_markdown": auto_detect_markdown and self._is_markdown(text),
                    "template_used": template_name or self.default_template,
                    "stylesheets_count": len(css_objects)
                },
                "generation_info": {
                    "timestamp": datetime.now().isoformat(),
                    "templates_dir": str(self.templates_dir),
                    "output_dir": str(self.output_dir),
                    "debug_html_path": str(debug_html_path) if 'debug_html_path' in locals() else None
                }
            }

            self.logger.info(f"PDF generation completed: {file_size} bytes, {token_count} tokens")
            return result

        except Exception as e:
            self.logger.error(f"Error in PDF generation: {e}")
            self.logger.error(traceback.format_exc())
            raise


    def _process_content(
        self,
        text: str,
        auto_detect_markdown: bool,
        template_name: Optional[str],
        template_vars: Optional[Dict[str, Any]]
    ) -> str:
        """
        Enhanced content processing with better debugging.
        """
        content = text.strip()

        # Convert Markdown to HTML if needed
        if auto_detect_markdown and self._is_markdown(content):
            self.logger.info("Detected Markdown content, converting to HTML")
            try:
                content = markdown.markdown(
                    content,
                    extensions=['tables', 'fenced_code', 'nl2br', 'extra'],
                    output_format='html5'
                )
                self.logger.debug(f"Markdown converted. Length: {len(content)}")
            except Exception as e:
                self.logger.warning(f"Markdown conversion failed: {e}, using plain text")
                # Convert line breaks for plain text
                content = content.replace('\n', '<br>')

        # Apply template if specified
        if template_name:
            try:
                template = self.env.get_template(template_name)

                # Prepare template context
                context = {
                    "body": content,      # Keep for backward compatibility
                    "content": content,   # Add for your template
                    "generated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    **(template_vars or {})
                }

                content = template.render(**context)
                self.logger.info(f"Applied template: {template_name}")

            except Exception as e:
                self.logger.error(f"Error applying template {template_name}: {e}")

                # Create a simple HTML wrapper instead of using template
                title = template_vars.get('title', 'Document') if template_vars else 'Document'
                author = template_vars.get('author', '') if template_vars else ''

                content = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            {f'<p><em>By: {author}</em></p>' if author else ''}
            <p><em>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</em></p>
            <hr>
        </header>
        <main>
            {content}
        </main>
    </body>
    </html>"""
                self.logger.info("Applied simple HTML wrapper as template fallback")
        else:
            # No template specified - ensure we have a complete HTML document
            if not content.strip().startswith('<!DOCTYPE') and not content.strip().startswith('<html'):
                content = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Document</title>
    </head>
    <body>
        {content}
    </body>
    </html>"""
                self.logger.info("Added basic HTML wrapper to content")

        return content


    # Debugging helper function
    def debug_pdf_generation(self, tool_instance, text: str) -> Dict[str, Any]:
        """
        Debug helper to diagnose PDF generation issues.

        Args:
            tool_instance: Instance of PDFPrintTool
            text: Text content to debug

        Returns:
            Dictionary with debug information
        """
        debug_info = {
            "original_text_length": len(text),
            "is_markdown_detected": tool_instance._is_markdown(text),
            "templates_dir_exists": tool_instance.templates_dir.exists(),
            "templates_dir_path": str(tool_instance.templates_dir),
            "output_dir_exists": tool_instance.output_dir.exists(),
            "output_dir_path": str(tool_instance.output_dir),
            "available_templates": tool_instance.get_available_templates(),
            "available_stylesheets": tool_instance.get_available_stylesheets(),
        }

        # Test content processing
        try:
            processed = tool_instance._process_content(
                text, True, None, {"title": "Debug Test"}
            )
            debug_info["processed_content_length"] = len(processed)
            debug_info["processed_content_preview"] = processed[:500]
            debug_info["content_processing"] = "SUCCESS"
        except Exception as e:
            debug_info["content_processing"] = f"FAILED: {e}"

        # Test CSS loading
        try:
            css_objects = tool_instance._load_stylesheets(None)
            debug_info["css_loading"] = f"SUCCESS: {len(css_objects)} stylesheets"
        except Exception as e:
            debug_info["css_loading"] = f"FAILED: {e}"

        return debug_info

    def execute_sync(
        self,
        text: str,
        file_prefix: str = "document",
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
        stylesheets: Optional[List[str]] = None,
        auto_detect_markdown: bool = True
    ) -> Dict[str, Any]:
        """
        Execute PDF generation synchronously.

        Args:
            text: Text content to convert to PDF
            file_prefix: Prefix for output filename
            template_name: Optional HTML template name
            template_vars: Optional template variables
            stylesheets: Optional CSS stylesheets
            auto_detect_markdown: Whether to auto-detect Markdown

        Returns:
            Dictionary with PDF generation results
        """
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.execute(
                text=text,
                file_prefix=file_prefix,
                template_name=template_name,
                template_vars=template_vars,
                stylesheets=stylesheets,
                auto_detect_markdown=auto_detect_markdown
            ))
            return task
        except RuntimeError:
            return asyncio.run(self.execute(
                text=text,
                file_prefix=file_prefix,
                template_name=template_name,
                template_vars=template_vars,
                stylesheets=stylesheets,
                auto_detect_markdown=auto_detect_markdown
            ))

    def get_available_templates(self) -> List[str]:
        """Get list of available HTML templates."""
        try:
            template_files = []
            for file_path in self.templates_dir.glob("*.html"):
                template_files.append(file_path.name)
            return sorted(template_files)
        except Exception as e:
            self.logger.error(f"Error listing templates: {e}")
            return []

    def get_available_stylesheets(self) -> List[str]:
        """Get list of available CSS stylesheets."""
        try:
            css_files = []
            css_dir = self.templates_dir / "css"
            if css_dir.exists():
                for file_path in css_dir.glob("*.css"):
                    css_files.append(f"css/{file_path.name}")
            return sorted(css_files)
        except Exception as e:
            self.logger.error(f"Error listing stylesheets: {e}")
            return []

    def preview_markdown(self, text: str) -> str:
        """Convert Markdown to HTML for preview purposes."""
        try:
            if self._is_markdown(text):
                return markdown.markdown(
                    text,
                    extensions=['tables', 'fenced_code', 'toc', 'nl2br']
                )
            else:
                return f"<pre>{text}</pre>"
        except Exception as e:
            self.logger.error(f"Error previewing markdown: {e}")
            return f"<p>Error previewing content: {e}</p>"
