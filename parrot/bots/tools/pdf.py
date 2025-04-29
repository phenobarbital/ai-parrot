import os
from datetime import datetime
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration


def generate_pdf_from_html(html_content, report_dir):
    """Generate a PDF file from HTML content.

    Args:
        html_content (str): HTML content to be converted to PDF.

    """
    # Create a FontConfiguration object
    font_config = FontConfiguration()

    # Additional CSS specifically for PDF rendering
    pdf_css = CSS(string='''
        @page {
            size: letter;
            margin: 1cm;
            @top-center {
                content: "Payroll Attestation Report";
                font-size: 9pt;
                color: #666;
            }
            @bottom-right {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 9pt;
                color: #666;
            }
        }
        h1 { page-break-before: always; }
        table { page-break-inside: avoid; }
    ''', font_config=font_config)

    # Generate timestamp for the filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Create filename with timestamp
    output_filename = f"report_{timestamp}.html"
    output_path = os.path.join(report_dir, output_filename)

    # Convert HTML to PDF
    HTML(string=html_content).write_pdf(
        output_path,
        stylesheets=[pdf_css],
        font_config=font_config
    )

    return output_path
