"""FEAT-803 AC4: tutorials follow the beginner pattern."""

from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["first-tool", "deployment"])
def test_tutorial_pattern(name: str) -> None:
    """Test that each tutorial follows the required structure."""
    text = (ROOT / "docs" / "tutorials" / f"{name}.md").read_text(encoding="utf-8")

    # Check required headings
    for heading in ("## What You'll Build", "## Step 1", "## What's Next"):
        assert heading in text, f"Missing heading '{heading}' in {name}.md"

    # Check for code blocks
    assert "```python" in text, f"Missing Python code block in {name}.md"

    # Check word count (600-1500 words)
    word_count = len(text.split())
    assert 600 <= word_count <= 1500, f"{name}.md has {word_count} words (expected 600-1500)"


def test_first_tool_imports() -> None:
    """Test that all parrot imports in first-tool.md are importable."""
    text = (ROOT / "docs" / "tutorials" / "first-tool.md").read_text(encoding="utf-8")

    # Extract code blocks
    code_blocks = []
    in_code_block = False
    current_block = []

    for line in text.split("\n"):
        if line.strip() == "```python":
            if not in_code_block:
                in_code_block = True
                current_block = []
            else:
                in_code_block = False
                code_blocks.append("\n".join(current_block))
        elif in_code_block:
            current_block.append(line)

    # Check imports in code blocks
    for block in code_blocks:
        lines = block.split("\n")
        for line in lines:
            if line.strip().startswith("from parrot") or line.strip().startswith("import parrot"):
                # Extract the module name
                if line.strip().startswith("from parrot"):
                    module_name = line.strip().split("from ")[1].split(" import")[0]
                else:  # import parrot...
                    module_name = line.strip().split("import ")[1].split(".")[0]

                # Try to import the module
                try:
                    importlib.util.find_spec(module_name)
                except (ImportError, ModuleNotFoundError):
                    pytest.fail(f"Module '{module_name}' is not importable in first-tool.md")


def test_deployment_imports() -> None:
    """Test that all parrot imports in deployment.md are importable."""
    text = (ROOT / "docs" / "tutorials" / "deployment.md").read_text(encoding="utf-8")

    # Extract code blocks
    code_blocks = []
    in_code_block = False
    current_block = []

    for line in text.split("\n"):
        if line.strip() == "```python":
            if not in_code_block:
                in_code_block = True
                current_block = []
            else:
                in_code_block = False
                code_blocks.append("\n".join(current_block))
        elif in_code_block:
            current_block.append(line)

    # Check imports in code blocks
    for block in code_blocks:
        lines = block.split("\n")
        for line in lines:
            if line.strip().startswith("from parrot") or line.strip().startswith("import parrot"):
                # Extract the module name
                if line.strip().startswith("from parrot"):
                    module_name = line.strip().split("from ")[1].split(" import")[0]
                else:  # import parrot...
                    module_name = line.strip().split("import ")[1].split(".")[0]

                # Try to import the module
                try:
                    importlib.util.find_spec(module_name)
                except (ImportError, ModuleNotFoundError):
                    pytest.fail(f"Module '{module_name}' is not importable in deployment.md")


def test_tutorial_links() -> None:
    """Test that tutorials link to each other and to wiki pages correctly."""
    first_tool_text = (ROOT / "docs" / "tutorials" / "first-tool.md").read_text(encoding="utf-8")
    deployment_text = (ROOT / "docs" / "tutorials" / "deployment.md").read_text(encoding="utf-8")

    # first-tool should link to deployment
    assert "deployment.md" in first_tool_text

    # deployment should link to first-chatbot
    assert "first-chatbot.md" in deployment_text

    # Both should link to wiki pages
    assert "github.com/phenobarbital/ai-parrot/wiki/" in first_tool_text
    assert "github.com/phenobarbital/ai-parrot/wiki/" in deployment_text
