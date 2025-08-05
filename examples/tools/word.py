# Usage Examples for DOCX Generator Tool
import asyncio
from pathlib import Path
from parrot.tools.msword import MSWordTool, WordToMarkdownTool


async def example_usage():

    # Create MS Word tool
    word_tool = MSWordTool(
        templates_dir=Path("templates"),
        overwrite_existing=True
    )

    # Basic markdown to Word conversion
    result = await word_tool.execute(
        content="# My Report\n\nThis is **bold** text with a [link](http://example.com).",
        file_prefix="my_report",
        overwrite_existing=True
    )

    markdown_content = """
# Project Report

## Executive Summary
This is a **comprehensive** report about our project.

### Key Findings
- Finding 1: *Important discovery*
- Finding 2: Another key point
- Finding 3: Final insight

## Conclusion
The project was successful.
    """

    # Advanced Word document with template and custom margins
    advanced_result = await word_tool.execute(
        content=markdown_content,
        template_name="business_report.html",
        template_vars={
            "title": "Quarterly Report",
            "author": "Analytics Team",
            "company": "ACME Corp"
        },
        docx_template="corporate_template.dotx",
        page_margins={
            "top": 1.0,
            "bottom": 1.0,
            "left": 1.25,
            "right": 1.25
        },
        file_prefix="quarterly_report"
    )

    result = advanced_result.result
    print(f"Word document created: {result['file_url']}")
    print(f"File size: {result['file_size_mb']} MB")



    # Convert Word document from URL to Markdown
    word_to_md_tool = WordToMarkdownTool()
    conversion_result = await word_to_md_tool.convert_from_url(
        url="https://calibre-ebook.com/downloads/demos/demo.docx",
        save_markdown=True,
        file_prefix="converted_document"
    )

    print(conversion_result)
    print(f"Markdown content: {conversion_result['markdown_content'][:100]}...")

    # Initialize the tool
    tool = MSWordTool(
        templates_dir=Path("./templates"),
        output_dir="./documents",
        overwrite_existing=True,
    )

    # Example 1: Basic Markdown to DOCX
    result1 = await tool.execute(
        text="""
# Project Report

## Executive Summary
This is a **comprehensive** report about our project.

### Key Findings
- Finding 1: *Important discovery*
- Finding 2: Another key point
- Finding 3: Final insight

## Conclusion
The project was successful.
    """,
        output_filename="project_report.docx"
    )

    print("Basic DOCX generated:", result1)

    # # Example 2: Using Jinja2 Template
    # # First create a template file: templates/report_template.html
    # template_content = """
    # <!DOCTYPE html>
    # <html>
    # <head>
    #     <title>{{ title }}</title>
    # </head>
    # <body>
    #     <h1>{{ title }}</h1>
    #     <p><strong>Author:</strong> {{ author }}</p>
    #     <p><strong>Date:</strong> {{ date }}</p>

    #     <div class="content">
    #         {{ content | safe }}
    #     </div>

    #     <footer>
    #         <p>Generated on {{ timestamp }}</p>
    #     </footer>
    # </body>
    # </html>
    # """

    result2 = await tool.execute(
        content="## Summary\nThis is the main content of the report.",
        template_name="report_template.html",
        template_vars={
            "title": "Monthly Report",
            "author": "Jane Smith",
            "date": "2025-06-17"
        },
        output_filename="monthly_report.docx"
    )

    print("DOCX generated with template:", result2)

    # Example 3: HTML Input
    html_content = """
<h1>Technical Documentation</h1>
<h2>Overview</h2>
<p>This document contains <strong>important</strong> technical information.</p>
<ul>
    <li>Feature A</li>
    <li>Feature B</li>
    <li>Feature C</li>
</ul>
<h2>Code Examples</h2>
<p>Here's some code: <code>print("Hello, World!")</code></p>
    """

    result3 = await tool.execute(
        content=html_content,
        output_filename="tech_docs.docx"
    )

    print("DOCX generated from HTML:", result3)

    # Example 4: Custom Output Directory
    result4 = await tool.execute(
        content="# Meeting Notes\n\n## Attendees\n- John\n- Mary\n- Bob",
        output_dir="./meetings/2025-06",
        output_filename="team_meeting_notes.docx"
    )

    print("DOCX generated in custom directory:", result4)


if __name__ == "__main__":
    # Run the example usage function
    asyncio.run(example_usage())
    # Note: Ensure that the templates directory is correctly set up.
    # The Word document generation will depend on the templates available in the specified directory.
