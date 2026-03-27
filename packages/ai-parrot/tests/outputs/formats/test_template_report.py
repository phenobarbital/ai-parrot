import pytest
from dataclasses import dataclass
from pydantic import BaseModel
from parrot.outputs.formatter import OutputFormatter
from parrot.models.outputs import OutputMode


class UserModel(BaseModel):
    """Test Pydantic model"""
    name: str
    age: int
    role: str = "user"


@dataclass
class ReportData:
    """Test dataclass"""
    title: str
    items: list
    count: int


@pytest.mark.asyncio
async def test_template_report_with_dict():
    """Test template_report with dictionary data"""
    formatter = OutputFormatter()

    # Add an in-memory template
    formatter.add_template(
        "simple.html",
        "<h1>{{ title }}</h1><p>{{ description }}</p>"
    )

    data = {
        "title": "Test Report",
        "description": "This is a test report"
    }

    # Render the template
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        data,
        template="simple.html"
    )

    assert "<h1>Test Report</h1>" in result
    assert "<p>This is a test report</p>" in result


@pytest.mark.asyncio
async def test_template_report_with_pydantic():
    """Test template_report with Pydantic model"""
    formatter = OutputFormatter()

    # Add an in-memory template
    formatter.add_template(
        "user.html",
        "<div><h2>{{ name }}</h2><p>Age: {{ age }}</p><p>Role: {{ role }}</p></div>"
    )

    user = UserModel(name="Alice", age=30, role="admin")

    # Render the template
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        user,
        template="user.html"
    )

    assert "<h2>Alice</h2>" in result
    assert "Age: 30" in result
    assert "Role: admin" in result


@pytest.mark.asyncio
async def test_template_report_with_dataclass():
    """Test template_report with dataclass"""
    formatter = OutputFormatter()

    # Add an in-memory template
    formatter.add_template(
        "report.html",
        """
        <div>
            <h1>{{ title }}</h1>
            <p>Total items: {{ count }}</p>
            <ul>
            {% for item in items %}
                <li>{{ item }}</li>
            {% endfor %}
            </ul>
        </div>
        """
    )

    report = ReportData(
        title="Monthly Report",
        items=["Item 1", "Item 2", "Item 3"],
        count=3
    )

    # Render the template
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        report,
        template="report.html"
    )

    assert "<h1>Monthly Report</h1>" in result
    assert "Total items: 3" in result
    assert "<li>Item 1</li>" in result
    assert "<li>Item 2</li>" in result
    assert "<li>Item 3</li>" in result


@pytest.mark.asyncio
async def test_template_report_with_extra_context():
    """Test template_report with extra context variables"""
    formatter = OutputFormatter()

    # Add an in-memory template
    formatter.add_template(
        "context.html",
        "<div><h1>{{ title }}</h1><p>{{ extra_info }}</p></div>"
    )

    data = {"title": "Report"}

    # Render with extra context
    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        data,
        template="context.html",
        extra_info="Additional information"
    )

    assert "<h1>Report</h1>" in result
    assert "<p>Additional information</p>" in result


@pytest.mark.asyncio
async def test_template_report_missing_template():
    """Test that missing template raises appropriate error"""
    formatter = OutputFormatter()

    data = {"title": "Test"}

    with pytest.raises(ValueError) as exc_info:
        await formatter.format_async(
            OutputMode.TEMPLATE_REPORT,
            data,
            template="nonexistent.html"
        )

    assert "not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_template_report_no_template_name():
    """Test that missing template name raises appropriate error"""
    formatter = OutputFormatter()

    data = {"title": "Test"}

    with pytest.raises(ValueError) as exc_info:
        await formatter.format_async(
            OutputMode.TEMPLATE_REPORT,
            data
        )

    assert "Template name must be provided" in str(exc_info.value)


@pytest.mark.asyncio
async def test_template_report_with_markdown():
    """Test template_report with markdown template"""
    formatter = OutputFormatter()

    # Add a markdown template
    formatter.add_template(
        "report.md",
        """
# {{ title }}

## Summary

{{ summary }}

## Details

{% for item in items %}
- {{ item }}
{% endfor %}
        """
    )

    data = {
        "title": "Analysis Report",
        "summary": "This is a summary of the analysis",
        "items": ["Finding 1", "Finding 2", "Finding 3"]
    }

    result = await formatter.format_async(
        OutputMode.TEMPLATE_REPORT,
        data,
        template="report.md"
    )

    assert "# Analysis Report" in result
    assert "## Summary" in result
    assert "This is a summary of the analysis" in result
    assert "- Finding 1" in result
    assert "- Finding 2" in result
    assert "- Finding 3" in result
