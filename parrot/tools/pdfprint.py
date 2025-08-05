"""
Enhanced PDF Print Tool with improved Markdown table support.
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
logging.getLogger("MARKDOWN").setLevel(logging.ERROR)
logging.getLogger("fontTools.ttLib.ttFont").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset.timer").setLevel(logging.ERROR)
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)


def count_tokens(text: str, model: str = "gpt-4") -> int:
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
    Enhanced PDF Print Tool with improved Markdown table support.

    This tool processes both plain text and Markdown content, with special
    attention to proper table rendering in PDF output.
    """

    name = "pdf_print"
    description = (
        "Generate PDF documents from text content. Supports both plain text and Markdown "
        "with enhanced table rendering. Can use custom HTML templates and CSS styling."
    )
    args_schema = PDFPrintArgs

    def __init__(
        self,
        templates_dir: Optional[Path] = None,
        default_template: str = "report.html",
        default_stylesheets: Optional[List[str]] = None,
        **kwargs
    ):
        """Initialize the PDF Print Tool with enhanced table support."""
        super().__init__(**kwargs)

        # Set up templates directory
        if templates_dir is None:
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
        """Create a default HTML template with enhanced table styling."""
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

            # Enhanced CSS with better table styling
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

h1 {
    color: #2c3e50;
    font-size: 2.5em;
    margin-bottom: 0.5em;
}

h2 {
    color: #34495e;
    font-size: 2em;
    margin-top: 1.5em;
    page-break-after: avoid;
}

h3 {
    color: #7f8c8d;
    font-size: 1.5em;
    margin-top: 1.2em;
    page-break-after: avoid;
}

.author, .date {
    font-style: italic;
    color: #7f8c8d;
    margin: 0.5em 0;
}

/* Enhanced table styling */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1.5em 0;
    background-color: white;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #ddd;
    padding: 12px 8px;
    text-align: left;
    vertical-align: top;
}

th {
    background-color: #f8f9fa;
    font-weight: bold;
    color: #2c3e50;
    border-bottom: 2px solid #34495e;
}

tbody tr:nth-child(even) {
    background-color: #f8f9fa;
}

tbody tr:hover {
    background-color: #e3f2fd;
}

/* Responsive table */
@media screen and (max-width: 768px) {
    table {
        font-size: 0.9em;
    }

    th, td {
        padding: 8px 4px;
    }
}

/* Number alignment */
td[align="right"],
th[align="right"],
.number {
    text-align: right;
}

/* Code styling */
code {
    background-color: #f4f4f4;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
    font-size: 0.9em;
}

pre {
    background-color: #f4f4f4;
    padding: 1em;
    border-radius: 5px;
    overflow-x: auto;
    border-left: 4px solid #3498db;
}

pre code {
    background-color: transparent;
    padding: 0;
}

blockquote {
    border-left: 4px solid #3498db;
    margin: 1em 0;
    padding-left: 1em;
    font-style: italic;
    background-color: #f8f9fa;
    padding: 1em 1em 1em 2em;
}

ul, ol {
    margin: 1em 0;
    padding-left: 2em;
}

li {
    margin: 0.5em 0;
}

footer {
    border-top: 1px solid #ddd;
    margin-top: 2em;
    padding-top: 1em;
    font-size: 0.9em;
    color: #7f8c8d;
}

/* Print specific styles */
@media print {
    body {
        margin: 1cm;
    }

    header {
        page-break-after: avoid;
    }

    h1, h2, h3 {
        page-break-after: avoid;
    }

    table {
        page-break-inside: avoid;
    }

    tr {
        page-break-inside: avoid;
    }

    th {
        background-color: #f0f0f0 !important;
        -webkit-print-color-adjust: exact;
        color-adjust: exact;
    }

    tbody tr:nth-child(even) {
        background-color: #f8f8f8 !important;
        -webkit-print-color-adjust: exact;
        color-adjust: exact;
    }
}
"""
            # Write files
            with open(templates_dir / "report.html", 'w', encoding='utf-8') as f:
                f.write(default_html)

            with open(templates_dir / "css" / "base.css", 'w', encoding='utf-8') as f:
                f.write(default_css)

            self.logger.info("Created default template files with enhanced table support")

        except Exception as e:
            self.logger.error(f"Error creating default template: {e}")

    def _is_markdown(self, text: str) -> bool:
        """Enhanced Markdown detection including table patterns."""
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

        # Enhanced Markdown patterns including tables
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
            r"^\s*\|.*\|.*$",               # Table rows
            r"^\s*\|[-\s:|]+\|.*$",         # Table separator rows
            r"^\s*\|[\-\s]+\|[\-\s\|]*$",   # ASCII-style table separators
        ]

        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE | re.DOTALL):
                return True

        return False

    def _preprocess_markdown_tables(self, text: str) -> str:
        """
        Preprocess Markdown tables to ensure proper formatting.

        This function fixes common table formatting issues and ensures
        tables are properly recognized by the Markdown parser.
        """
        lines = text.split('\n')
        processed_lines = []
        in_table = False
        table_buffer = []

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Detect potential table rows
            if stripped and '|' in stripped:
                # Check if this is an ASCII-style table separator with many dashes
                if re.match(r'^\s*\|[\-\s]+\|[\-\s\|]*$', stripped):
                    # Convert ASCII separator to Markdown format
                    # Count the number of columns from the previous line
                    if table_buffer:
                        prev_line = table_buffer[-1]
                        col_count = prev_line.count('|') - 1
                        markdown_separator = '|' + '---|' * col_count
                        table_buffer.append(markdown_separator)
                    else:
                        # Fallback separator
                        table_buffer.append('|---|---|---|')
                    in_table = True
                    continue

                # Check if this looks like a table row (starts and ends with |)
                if stripped.startswith('|') and stripped.endswith('|'):
                    # Clean up the row - remove extra spaces and normalize
                    cells = [cell.strip() for cell in stripped.split('|')[1:-1]]
                    cleaned_row = '| ' + ' | '.join(cells) + ' |'
                    table_buffer.append(cleaned_row)
                    in_table = True
                    continue

                # Check for table row without proper pipe formatting
                if stripped.count('|') >= 2:
                    # Ensure the line starts and ends with pipes
                    if not stripped.startswith('|'):
                        stripped = '| ' + stripped
                    if not stripped.endswith('|'):
                        stripped = stripped + ' |'

                    # Clean up the row
                    cells = [cell.strip() for cell in stripped.split('|')[1:-1]]
                    cleaned_row = '| ' + ' | '.join(cells) + ' |'
                    table_buffer.append(cleaned_row)
                    in_table = True
                    continue

            # If we were in a table and hit a non-table line
            if in_table and not stripped:
                # End of table - add the buffered table and empty line
                if table_buffer:
                    processed_lines.extend(table_buffer)
                    processed_lines.append('')  # Add empty line after table
                    table_buffer = []
                in_table = False
                processed_lines.append(line)
                continue
            elif in_table and stripped and '|' not in stripped:
                # End of table - add the buffered table
                if table_buffer:
                    processed_lines.extend(table_buffer)
                    processed_lines.append('')  # Add empty line after table
                    table_buffer = []
                in_table = False
                processed_lines.append(line)
                continue

            # Not a table line
            if not in_table:
                processed_lines.append(line)

        # Handle any remaining table buffer
        if table_buffer:
            processed_lines.extend(table_buffer)

        return '\n'.join(processed_lines)

    def _convert_ascii_tables_to_html(self, text: str) -> str:
        """
        Convert ASCII-style tables directly to HTML if Markdown conversion fails.
        """
        lines = text.split('\n')
        result_lines = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Look for potential table start (line with pipes)
            if line and '|' in line and line.count('|') >= 2:
                # Check if next line is a separator
                table_lines = [line]
                j = i + 1

                # Collect all consecutive lines that look like table rows
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line and '|' in next_line:
                        table_lines.append(next_line)
                        j += 1
                    elif not next_line:  # Empty line
                        j += 1
                        break
                    else:
                        break

                # If we have at least 2 lines, try to convert to HTML table
                if len(table_lines) >= 2:
                    html_table = self._ascii_to_html_table(table_lines)
                    if html_table:
                        result_lines.append(html_table)
                        i = j
                        continue

            # Not a table line, add as-is
            result_lines.append(lines[i])
            i += 1

        return '\n'.join(result_lines)

    def _ascii_to_html_table(self, table_lines: List[str]) -> str:
        """
        Convert ASCII table lines to HTML table.
        """
        try:
            # Remove empty lines and separator lines
            data_lines = []
            for line in table_lines:
                if line.strip() and not re.match(r'^\s*\|[\-\s]+\|[\-\s\|]*$', line.strip()):
                    data_lines.append(line.strip())

            if len(data_lines) < 1:
                return ""

            html_parts = ['<table class="ascii-table">']

            # Process each line
            for idx, line in enumerate(data_lines):
                # Split by pipe and clean up
                cells = [cell.strip() for cell in line.split('|')[1:-1]]  # Remove first/last empty parts

                if idx == 0:
                    # First row is header
                    html_parts.append('<thead><tr>')
                    for cell in cells:
                        html_parts.append(f'<th>{cell}</th>')
                    html_parts.append('</tr></thead><tbody>')
                else:
                    # Data row
                    html_parts.append('<tr>')
                    for cell in cells:
                        # Check if cell content is numeric for right alignment
                        if re.match(r'^\s*\d+(?:\.\d+)?\s*$', cell):
                            html_parts.append(f'<td align="right">{cell}</td>')
                        else:
                            html_parts.append(f'<td>{cell}</td>')
                    html_parts.append('</tr>')

            html_parts.append('</tbody></table>')
            return '\n'.join(html_parts)

        except Exception as e:
            self.logger.warning(f"Failed to convert ASCII table to HTML: {e}")
            return ""

    def _post_process_html_tables(self, html_content: str) -> str:
        """
        Post-process HTML to improve table formatting.
        """
        # Add CSS classes to tables for better styling
        html_content = re.sub(
            r'<table>',
            '<table class="markdown-table">',
            html_content,
            flags=re.IGNORECASE
        )

        # Ensure numeric columns are right-aligned
        def align_numeric_cells(match):
            cell_content = match.group(1)
            # Check if content looks like a number
            if re.match(r'^\s*\d+(?:\.\d+)?\s*$', cell_content.strip()):
                return f'<td align="right">{cell_content}</td>'
            return match.group(0)

        html_content = re.sub(
            r'<td>(.*?)</td>',
            align_numeric_cells,
            html_content,
            flags=re.IGNORECASE | re.DOTALL
        )

        return html_content

    def _process_content(
        self,
        text: str,
        auto_detect_markdown: bool,
        template_name: Optional[str],
        template_vars: Optional[Dict[str, Any]]
    ) -> str:
        """Enhanced content processing with better table handling."""
        content = text.strip()

        # Convert Markdown to HTML if needed
        if auto_detect_markdown and self._is_markdown(content):
            self.logger.info("Detected Markdown content, converting to HTML")
            try:
                # Preprocess tables for better recognition
                content = self._preprocess_markdown_tables(content)

                # Configure markdown with all necessary extensions
                md = markdown.Markdown(
                    extensions=[
                        'tables',           # Table support
                        'fenced_code',      # Code blocks
                        'nl2br',           # Newline to break
                        'attr_list',        # Attribute lists
                        'def_list',         # Definition lists
                        'footnotes',        # Footnotes
                        'toc',              # Table of contents
                        'codehilite',       # Code highlighting
                        'extra'             # Meta extension with many sub-extensions
                    ],
                    extension_configs={
                        'tables': {
                            'use_align_attribute': True
                        },
                        'codehilite': {
                            'css_class': 'highlight',
                            'use_pygments': False
                        }
                    },
                    output_format='html5'
                )

                content = md.convert(content)

                # If no tables were converted but we suspect there are ASCII tables, try fallback
                if '<table' not in content and '|' in text and text.count('|') > 4:
                    self.logger.info("Markdown didn't create tables, trying ASCII table conversion")
                    content = self._convert_ascii_tables_to_html(text)

                # Post-process HTML tables
                content = self._post_process_html_tables(content)

                self.logger.debug(f"Markdown converted with tables. Length: {len(content)}")

                # Log table detection
                table_count = content.count('<table')
                if table_count > 0:
                    self.logger.info(f"Successfully converted {table_count} table(s) to HTML")
                else:
                    self.logger.warning("No tables were detected in the conversion")

            except Exception as e:
                self.logger.warning(f"Markdown conversion failed: {e}, trying ASCII table conversion")
                # Try ASCII table conversion as fallback
                try:
                    content = self._convert_ascii_tables_to_html(content)
                    if '<table' not in content:
                        # Convert line breaks for plain text
                        content = content.replace('\n', '<br>')
                except Exception as ascii_error:
                    self.logger.warning(f"ASCII table conversion also failed: {ascii_error}")
                    content = content.replace('\n', '<br>')

        # Apply template if specified
        if template_name:
            try:
                template = self.env.get_template(template_name)

                # Prepare template context
                context = {
                    "body": content,
                    "content": content,
                    "generated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    **(template_vars or {})
                }

                content = template.render(**context)
                self.logger.info(f"Applied template: {template_name}")

            except Exception as e:
                self.logger.error(f"Error applying template {template_name}: {e}")

                # Create a simple HTML wrapper with table-friendly styling
                title = template_vars.get('title', 'Document') if template_vars else 'Document'
                author = template_vars.get('author', '') if template_vars else ''

                content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2cm; line-height: 1.6; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; font-weight: bold; }}
        h1, h2, h3 {{ color: #333; }}
    </style>
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
            # No template specified - ensure we have a complete HTML document with table styling
            if not content.strip().startswith('<!DOCTYPE') and not content.strip().startswith('<html'):
                content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Document</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2cm; line-height: 1.6; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; font-weight: bold; }}
        tbody tr:nth-child(even) {{ background-color: #f8f9fa; }}
        h1, h2, h3 {{ color: #333; }}
    </style>
</head>
<body>
    {content}
</body>
</html>"""
                self.logger.info("Added basic HTML wrapper with table styling to content")

        return content

    def _load_stylesheets(self, stylesheets: Optional[List[str]]) -> List[CSS]:
        """Load CSS stylesheets for PDF generation."""
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
        """Execute PDF generation with enhanced table support."""
        try:
            self.logger.debug(
                f"Starting PDF generation with {len(text)} characters of content"
            )

            # Process content with enhanced table handling
            processed_content = self._process_content(
                text, auto_detect_markdown, template_name, template_vars
            )

            # Log table information
            table_count = processed_content.count('<table')
            if table_count > 0:
                self.logger.info(f"Content contains {table_count} HTML table(s)")

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

            # Generate PDF with enhanced error handling
            try:
                html_obj = HTML(
                    string=processed_content,
                    base_url=str(self.templates_dir)
                )

                # Generate PDF with print-friendly settings
                html_obj.write_pdf(
                    str(output_path),
                    stylesheets=css_objects,
                    presentational_hints=True  # This helps with table rendering
                )

                # Verify file creation
                if not output_path.exists():
                    raise Exception("PDF file was not created")

                file_size = output_path.stat().st_size
                if file_size == 0:
                    raise Exception("PDF file is empty (0 bytes)")

                self.logger.info(f"PDF generated successfully: {output_path} ({file_size} bytes)")

            except Exception as pdf_error:
                self.logger.error(f"PDF generation failed: {pdf_error}")
                raise Exception(f"PDF generation failed: {pdf_error}")

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
                    "stylesheets_count": len(css_objects),
                    "tables_detected": processed_content.count('<table')
                },
                "generation_info": {
                    "timestamp": datetime.now().isoformat(),
                    "templates_dir": str(self.templates_dir),
                    "output_dir": str(self.output_dir),
                    "debug_html_path": str(debug_html_path) if 'debug_html_path' in locals() else None
                }
            }

            self.logger.info(f"PDF generation completed: {file_size} bytes, {token_count} tokens, {result['content_stats']['tables_detected']} tables")
            return result

        except Exception as e:
            self.logger.error(f"Error in PDF generation: {e}")
            self.logger.error(traceback.format_exc())
            raise

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
                # Use the same preprocessing for consistency
                text = self._preprocess_markdown_tables(text)

                html = markdown.markdown(
                    text,
                    extensions=['tables', 'fenced_code', 'toc', 'nl2br', 'extra'],
                    extension_configs={
                        'tables': {
                            'use_align_attribute': True
                        }
                    }
                )

                return self._post_process_html_tables(html)
            else:
                return f"<pre>{text}</pre>"
        except Exception as e:
            self.logger.error(f"Error previewing markdown: {e}")
            return f"<p>Error previewing content: {e}</p>"
