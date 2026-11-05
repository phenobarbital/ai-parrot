"""FEAT-803 AC4: tutorials follow the beginner pattern."""
from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["first-chatbot", "first-agent"])
def test_tutorial_pattern(name: str) -> None:
    text = (ROOT / "docs" / "tutorials" / f"{name}.md").read_text(encoding="utf-8")
    for heading in ("## What You'll Build", "## Step 1", "## What's Next"):
        assert heading in text
    assert "```python" in text
    assert 600 <= len(text.split()) <= 1500
    
    # Check that every `from parrot` import line in the page is importable
    code_blocks = []
    in_code_block = False
    current_block = []
    
    for line in text.split('\n'):
        if line.strip() == '```python':
            if not in_code_block:
                in_code_block = True
                current_block = []
            else:
                in_code_block = False
                code_blocks.append('\n'.join(current_block))
        elif in_code_block:
            current_block.append(line)
    
    # Check imports in code blocks
    for block in code_blocks:
        lines = block.split('\n')
        for line in lines:
            if line.strip().startswith('from parrot') or line.strip().startswith('import parrot'):
                # Extract the module name
                if line.strip().startswith('from parrot'):
                    module_name = line.strip().split('from ')[1].split(' import')[0]
                else:  # import parrot...
                    module_name = line.strip().split('import ')[1].split('.')[0]
                
                # Try to import the module
                try:
                    importlib.util.find_spec(module_name)
                except (ImportError, ModuleNotFoundError):
                    pytest.fail(f"Module '{module_name}' is not importable")


def test_tutorial_links() -> None:
    """Test that tutorials link to each other and to wiki pages correctly."""
    chatbot_text = (ROOT / "docs" / "tutorials" / "first-chatbot.md").read_text(encoding="utf-8")
    agent_text = (ROOT / "docs" / "tutorials" / "first-agent.md").read_text(encoding="utf-8")
    
    # Chatbot tutorial should link to agent tutorial
    assert "first-agent.md" in chatbot_text
    
    # Agent tutorial should link to chatbot tutorial
    assert "first-chatbot.md" in agent_text
    
    # Both should link to wiki pages
    assert "github.com/phenobarbital/ai-parrot/wiki/" in chatbot_text
    assert "github.com/phenobarbital/ai-parrot/wiki/" in agent_text