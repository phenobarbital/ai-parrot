"""
Example demonstrating the TEMPLATE_REPORT OutputMode.

This example shows how to use Jinja2 templates to render AI outputs
using the TemplateEngine and TemplateReportRenderer.
"""
import asyncio
from dataclasses import dataclass
from pydantic import BaseModel
from parrot.outputs.formatter import OutputFormatter
from parrot.models.outputs import OutputMode


class AnalysisResult(BaseModel):
    """Example Pydantic model for analysis results"""
    title: str
    summary: str
    findings: list[str]
    confidence: float
    recommendations: list[str]


@dataclass
class ReportMetadata:
    """Example dataclass for report metadata"""
    author: str
    date: str
    version: str


async def example_basic_template():
    """Example 1: Basic template rendering with dictionary data"""
    print("\n=== Example 1: Basic Template Rendering ===\n")

    # Create formatter
    formatter = OutputFormatter()

    # Add an HTML template
    formatter.add_template(
        "simple_report.html",
        """
        <!DOCTYPE html>
        <html>
        <head>
            <title>{{ title }}</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                .summary { background: #f0f0f0; padding: 15px; border-radius: 5px; }
            </style>
        </head>
        <body>
            <h1>{{ title }}</h1>
            <div class="summary">
                <p>{{ description }}</p>
            </div>
        </body>
        </html>
        """
    )

    # Data to render
    data = {
        "title": "Simple Report",
        "description": "This is a simple example of template-based rendering."
    }

    # Render the template
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        data,
        template="simple_report.html"
    )

    print(result)


async def example_pydantic_model():
    """Example 2: Rendering with Pydantic model"""
    print("\n=== Example 2: Pydantic Model Rendering ===\n")

    formatter = OutputFormatter()

    # Add a detailed analysis template
    formatter.add_template(
        "analysis.html",
        """
        <!DOCTYPE html>
        <html>
        <head>
            <title>{{ title }}</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                          color: white; padding: 20px; border-radius: 8px; }
                .summary { background: #f8f9fa; padding: 20px; margin: 20px 0; border-left: 4px solid #667eea; }
                .findings { margin: 20px 0; }
                .finding { background: #fff; padding: 10px; margin: 10px 0;
                          border: 1px solid #ddd; border-radius: 4px; }
                .confidence { font-size: 24px; font-weight: bold; color: #667eea; }
                .recommendations { background: #e8f5e9; padding: 15px; border-radius: 8px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{{ title }}</h1>
                <p class="confidence">Confidence: {{ confidence * 100 }}%</p>
            </div>

            <div class="summary">
                <h2>Summary</h2>
                <p>{{ summary }}</p>
            </div>

            <div class="findings">
                <h2>Key Findings</h2>
                {% for finding in findings %}
                <div class="finding">{{ loop.index }}. {{ finding }}</div>
                {% endfor %}
            </div>

            <div class="recommendations">
                <h2>Recommendations</h2>
                <ul>
                {% for rec in recommendations %}
                    <li>{{ rec }}</li>
                {% endfor %}
                </ul>
            </div>
        </body>
        </html>
        """
    )

    # Create analysis result
    analysis = AnalysisResult(
        title="Market Analysis Report",
        summary="Comprehensive analysis of market trends and opportunities",
        findings=[
            "Strong growth trend in technology sector",
            "Emerging opportunities in renewable energy",
            "Increasing consumer demand for sustainable products"
        ],
        confidence=0.87,
        recommendations=[
            "Increase investment in tech companies",
            "Explore partnerships in green energy sector",
            "Develop eco-friendly product lines"
        ]
    )

    # Render the template
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        analysis,
        template="analysis.html"
    )

    print(result)


async def example_markdown_template():
    """Example 3: Markdown template for reports"""
    print("\n=== Example 3: Markdown Template ===\n")

    formatter = OutputFormatter()

    # Add a markdown template
    formatter.add_template(
        "report.md",
        """
# {{ title }}

**Author:** {{ author }}
**Date:** {{ date }}
**Version:** {{ version }}

---

## Executive Summary

{{ summary }}

## Detailed Analysis

{% for section, content in analysis.items() %}
### {{ section }}

{{ content }}

{% endfor %}

## Conclusion

{{ conclusion }}

---
*Generated using AI-Parrot Template Report*
        """
    )

    # Combine data from multiple sources
    metadata = ReportMetadata(
        author="AI Assistant",
        date="2025-11-04",
        version="1.0"
    )

    # Mix dataclass and dict data
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        {
            "title": "Quarterly Business Review",
            "author": metadata.author,
            "date": metadata.date,
            "version": metadata.version,
            "summary": "This quarter showed strong performance across all metrics.",
            "analysis": {
                "Revenue": "Revenue increased by 25% compared to last quarter.",
                "Customer Growth": "Acquired 1,000 new customers, a 15% increase.",
                "Product Development": "Launched 3 new features with positive feedback."
            },
            "conclusion": "The quarter exceeded expectations with strong growth indicators."
        },
        template="report.md"
    )

    print(result)


async def example_with_extra_context():
    """Example 4: Adding extra context variables"""
    print("\n=== Example 4: Extra Context Variables ===\n")

    formatter = OutputFormatter()

    formatter.add_template(
        "email.html",
        """
        <!DOCTYPE html>
        <html>
        <body>
            <h2>Hello {{ recipient_name }},</h2>
            <p>{{ message }}</p>
            <p><strong>From:</strong> {{ sender_name }}</p>
            <p><strong>Department:</strong> {{ department }}</p>
        </body>
        </html>
        """
    )

    # Base data
    data = {
        "message": "Your report has been generated successfully."
    }

    # Render with extra context
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        data,
        template="email.html",
        recipient_name="John Doe",
        sender_name="AI Assistant",
        department="Analytics"
    )

    print(result)


async def main():
    """Run all examples"""
    await example_basic_template()
    await example_pydantic_model()
    await example_markdown_template()
    await example_with_extra_context()


if __name__ == "__main__":
    asyncio.run(main())
