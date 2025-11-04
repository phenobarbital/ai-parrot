import pytest
from jinja2 import Environment, FileSystemLoader
from parrot.outputs.formatter import OutputFormatter
from parrot.models.outputs import OutputMode


@pytest.fixture
def jinja2_env():
    # Create a Jinja2 environment with an async-enabled loader
    return Environment(loader=FileSystemLoader("templates/"), enable_async=True)


@pytest.mark.asyncio
async def test_jinja2_output_formatter(jinja2_env):
    """
    Tests the Jinja2OutputFormatter for async rendering and content type validation.
    """
    formatter = OutputFormatter()
    data = {"name": "World"}

    # Define the template name
    template_name = "test.html"

    # Render the content asynchronously
    rendered_content, content_type = await formatter.format_async(
        OutputMode.JINJA2, data, env=jinja2_env, template=template_name
    )

    # Validate the rendered content and content type
    assert "Hello, World!" in rendered_content
    assert content_type == "text/html"
