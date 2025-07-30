import asyncio
from pathlib import Path
from parrot.tools.ppt import PowerPointTool


async def example_usage():
    # Initialize the tool
    tool = PowerPointTool(
        templates_dir=Path("./templates"),
        output_dir="./presentations"
    )

    # Example markdown content
    markdown_content = """
# Company Overview
Welcome to our quarterly presentation.

## Financial Performance
Our revenue has increased by **25%** this quarter.

Key metrics:
- Revenue: $2.5M
- Profit: $500K
- Growth: 25%

## Market Analysis
The market shows positive trends:

1. Increased demand
2. New opportunities
3. Competitive advantages

## Future Plans
Our roadmap for the next quarter includes:

- Product launches
- Market expansion
- Team growth

### Development Goals
Focus areas for development:
- Innovation
- Quality
- Customer satisfaction

## Conclusion
Thank you for your attention.
    """

    # Generate PowerPoint presentation
    result = await tool.execute(
        content=markdown_content,
        output_filename="quarterly_presentation.pptx",
        title_styles={
            'font_name': 'Arial',
            'font_size': 24,
            'bold': True,
            'font_color': '1F4E79'
        },
        content_styles={
            'font_name': 'Arial',
            'font_size': 14,
            'alignment': 'left'
        },
        overwrite_existing=True,
    )

    print(result)

    # Example 2: Technical Presentation with Code and Tables
    print("\n=== Example 2: Technical Presentation ===")

    technical_markdown = """
# API Documentation Review
Overview of our new REST API endpoints.

## Authentication
All requests require API key authentication.

Security features:
- JWT tokens
- Rate limiting
- SSL encryption

## Endpoints Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/users | Get all users |
| POST | /api/users | Create user |
| PUT | /api/users/{id} | Update user |
| DELETE | /api/users/{id} | Delete user |

## Code Examples
Basic usage patterns and examples.

### GET Request
Simple data retrieval.

### POST Request
Creating new resources.

## Performance Metrics
Current system performance:

- Response time: 200ms average
- Uptime: 99.9%
- Concurrent users: 10,000

## Implementation Status
Development progress update.

### Completed Features
- User management
- Authentication
- Basic CRUD operations

### Upcoming Features
- Advanced filtering
- Bulk operations
- Real-time notifications

## Questions & Next Steps
Review and feedback session.
    """

    tech_styles = {
        'title_styles': {
            'font_name': 'Segoe UI',
            'font_size': 24,
            'bold': True,
            'font_color': '2E7D32'
        },
        'content_styles': {
            'font_name': 'Consolas',
            'font_size': 12,
            'font_color': '424242'
        }
    }

    result4 = await tool.execute(
        content=technical_markdown,
        output_filename="api_documentation.pptx",
        overwrite_existing=True,
        **tech_styles
    )
    print(result4)

    # BACKWARD COMPATIBLE - Your existing usage pattern works:
    tool = PowerPointTool(
        templates_dir=Path("./templates"),
        output_dir="./presentations"
    )

    # Basic presentation generation
    result = await tool.execute(
        content='''# My Presentation

## Introduction
Welcome to our quarterly review.

## Key Metrics
- Revenue: Up 15%
- Users: 10,000+ new signups
- Satisfaction: 4.8/5 stars

## Next Steps
- Expand to new markets
- Improve customer support
- Launch mobile app
    ''',
        file_prefix="quarterly_review"
    )

    print(result)

    # Advanced presentation with templates and styling
    advanced_result = await tool.execute(
        content=markdown_content,
        template_name="business_presentation.html",
        template_vars={
            "company": "ACME Corp",
            "quarter": "Q4 2024",
            "presenter": "John Smith"
        },
        pptx_template="corporate_template.potx",
        slide_layout=1,
        title_styles={
            "font_name": "Arial",
            "font_size": 28,
            "bold": True,
            "font_color": "#1f497d"
        },
        content_styles={
            "font_name": "Arial",
            "font_size": 18,
            "alignment": "left"
        },
        max_slides=20,
        output_filename="quarterly_presentation",
        overwrite_existing=True
    )

    print(advanced_result)

    # Single slide presentation (no heading splitting)
    single_slide = await tool.execute(
        content="All content on one slide without heading-based splitting.",
        split_by_headings=False,
        slide_layout=0,  # Title slide
        file_prefix="single_slide"
    )

    print(single_slide)

if __name__ == "__main__":
    # Run the example usage function
    asyncio.run(example_usage())
    # Note: Ensure that the templates and static directories are correctly set up.
    # The PowerPoint generation will depend on the templates available in the specified directory.
