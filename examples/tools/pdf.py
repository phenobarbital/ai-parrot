from navconfig import BASE_DIR
from parrot.tools.pdfprint import PDFPrintTool

async def example_usage():
    # Initialize the tool
    pdf_tool = PDFPrintTool(
        templates_dir=BASE_DIR / 'templates',
        # base_url="/static"  # Configure your static URL base
    )
    # Get available resources
    templates = pdf_tool.get_available_templates()
    stylesheets = pdf_tool.get_available_stylesheets()

    text_content = "# Sample Document\n\nThis is a **sample** document with *Markdown* formatting."
    # Generate a PDF
    result = await pdf_tool._execute(
        text=text_content,
        file_prefix="sample_document"
    )
    print("PDF generated:", result)


    # Generate PDF from Markdown
    result = await pdf_tool.execute(
        text="""# My Report
This is **bold** text with a [link](http://example.com).
""",
        file_prefix="my_report",
        template_vars={"title": "My Report", "author": "John Doe"}
    )
    print("PDF generated from Markdown:", result)

    # Generate PDF with custom template
    result = await pdf_tool.execute(
        text="Some content here",
        template_name="report_template.html",
        stylesheets=["css/custom.css", "css/print.css"],
        template_vars={
            "title": "Custom Document",
            "author": "Jane Smith",
            "date": "2024-12-19"
        }
    )
    print("PDF generated with custom template:", result)
    result = result.result
    print(f"PDF generated: {result['file_url']}")
    print(f"File size: {result['file_size_mb']} MB")
    print(f"Content had {result['content_stats']['tokens']} tokens")

if __name__ == "__main__":
    import asyncio
    # Run the test function
    asyncio.run(example_usage())
    # Note: Ensure that the templates and static directories are correctly set up.
    # The PDF generation will depend on the templates available in the specified directory.
