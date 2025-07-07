from navconfig import BASE_DIR
from parrot.tools.pdf import PDFPrintTool


# Initialize the tool
pdf_tool = PDFPrintTool(
    templates_dir=BASE_DIR / 'templates',
    # base_url="/static"  # Configure your static URL base
)

async def test_pdf_tool():
    """Test the PDF tool with a simple example."""
    # Create sample text content
    text_content = "# Sample Document\n\nThis is a **sample** document with *Markdown* formatting."

    # Generate a PDF
    result = await pdf_tool._arun(
        text=text_content,
        file_prefix="sample_document"
    )

    print("PDF generated:", result)

if __name__ == "__main__":
    import asyncio
    # Run the test function
    asyncio.run(test_pdf_tool())
    # Note: Ensure that the templates and static directories are correctly set up.
    # The PDF generation will depend on the templates available in the specified directory.
