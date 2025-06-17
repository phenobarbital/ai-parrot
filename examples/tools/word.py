# Usage Examples for DOCX Generator Tool

from pathlib import Path
from parrot.tools.msword import DocxGeneratorTool

# Initialize the tool
tool = DocxGeneratorTool(
    templates_dir=Path("./templates"),
    output_dir="./documents"
)

# Example 1: Basic Markdown to DOCX
result1 = tool._run(
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

# Example 2: Using Jinja2 Template
# First create a template file: templates/report_template.html
template_content = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
</head>
<body>
    <h1>{{ title }}</h1>
    <p><strong>Author:</strong> {{ author }}</p>
    <p><strong>Date:</strong> {{ date }}</p>

    <div class="content">
        {{ content | safe }}
    </div>

    <footer>
        <p>Generated on {{ timestamp }}</p>
    </footer>
</body>
</html>
"""

result2 = tool._run(
    text="## Summary\nThis is the main content of the report.",
    template_name="report_template.html",
    template_vars={
        "title": "Monthly Report",
        "author": "Jane Smith",
        "date": "2025-06-17"
    },
    output_filename="monthly_report.docx"
)

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

result3 = tool._run(
    text=html_content,
    output_filename="tech_docs.docx"
)

# Example 4: Using DOCX Template
result4 = tool._run(
    text="# New Content\nThis will be added to the existing template.",
    docx_template="./templates/company_template.docx",
    output_filename="branded_document.docx"
)

# Example 5: Custom Output Directory
result5 = tool._run(
    text="# Meeting Notes\n\n## Attendees\n- John\n- Mary\n- Bob",
    output_dir="./meetings/2025-06",
    output_filename="team_meeting_notes.docx"
)

print("All examples completed!")
for i, result in enumerate([result1, result2, result3, result4, result5], 1):
    print(f"Example {i}: {result}")
