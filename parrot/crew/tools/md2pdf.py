from navconfig import BASE_DIR
from crewai_tools import BaseTool
import markdown2
from weasyprint import HTML


class MarkdownToPDFTool(BaseTool):
    """Markdown to PDF Tool."""
    name: str = "MarkdownToPDFTool"
    description: str = "Converts markdown documents to PDF format."

    def _run(self, markdown_content: str) -> str:
        # Convert Markdown to HTML
        html_content = markdown2.markdown(markdown_content)
        # Convert HTML to PDF (assuming it's a simple conversion without advanced styling)
        pdf = HTML(string=html_content).write_pdf()

        # Save PDF to a temporary file and return file path
        pdf_file_path = BASE_DIR.joinpath('docs', 'report.pdf')
        with open(str(pdf_file_path), 'wb') as f:
            f.write(pdf)
        return pdf_file_path

    def __call__(self, markdown_content: str) -> str:
        return self._run(markdown_content)
