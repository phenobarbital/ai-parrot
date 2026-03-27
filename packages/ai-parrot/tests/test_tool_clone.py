"""
Test the clone() method of AbstractTool.
"""
import sys
from pathlib import Path

# Ensure we import from source, not installed package
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from typing import Any, Dict
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema


class SimpleTestTool(AbstractTool):
    """A simple test tool for testing clone functionality."""
    
    name = "SimpleTestTool"
    description = "A tool for testing clone method"
    
    def __init__(self, custom_param=None, **kwargs):
        super().__init__(custom_param=custom_param, **kwargs)
        self.custom_param = custom_param
    
    async def _execute(self, **kwargs) -> Any:
        return {"result": "test"}


class CustomCloneTool(AbstractTool):
    """A tool that customizes the clone behavior."""
    
    name = "CustomCloneTool"
    description = "A tool with custom clone behavior"
    
    def __init__(self, public_param=None, private_param=None, **kwargs):
        super().__init__(public_param=public_param, private_param=private_param, **kwargs)
        self.public_param = public_param
        self.private_param = private_param
    
    def _get_clone_kwargs(self) -> Dict[str, Any]:
        """Override to exclude private_param from cloning."""
        kwargs = super()._get_clone_kwargs()
        # Remove private_param from clone
        kwargs.pop('private_param', None)
        return kwargs
    
    async def _execute(self, **kwargs) -> Any:
        return {"result": "custom"}



def test_basic_clone():
    """Test basic clone functionality."""
    original = SimpleTestTool(
        name="TestTool",
        description="Test description",
        custom_param="test_value"
    )
    
    # Clone the tool
    cloned = original.clone()
    
    # Verify it's a different instance
    assert cloned is not original
    assert id(cloned) != id(original)
    
    # Verify it's the same class
    assert type(cloned) == type(original)
    assert isinstance(cloned, SimpleTestTool)
    
    # Verify configuration is the same
    assert cloned.name == original.name
    assert cloned.description == original.description
    assert cloned.custom_param == original.custom_param


def test_clone_with_paths():
    """Test cloning with path parameters."""
    output_dir = Path("/tmp/test_output")
    static_dir = Path("/tmp/test_static")
    
    original = SimpleTestTool(
        output_dir=output_dir,
        static_dir=static_dir,
        custom_param="with_paths"
    )
    
    cloned = original.clone()
    
    # Verify paths are preserved
    assert cloned.output_dir == original.output_dir
    assert cloned.static_dir == original.static_dir
    assert cloned.custom_param == original.custom_param


def test_custom_clone_kwargs():
    """Test that subclasses can override _get_clone_kwargs()."""
    original = CustomCloneTool(
        public_param="public_value",
        private_param="private_value"
    )
    
    # Verify original has both parameters
    assert original.public_param == "public_value"
    assert original.private_param == "private_value"
    
    # Clone the tool
    cloned = original.clone()
    
    # Verify cloned has public_param but not private_param
    assert cloned.public_param == "public_value"
    assert cloned.private_param is None  # Should be None since not passed


def test_clone_preserves_base_url():
    """Test that clone preserves base_url configuration."""
    original = SimpleTestTool(
        base_url="https://example.com/static",
        custom_param="url_test"
    )
    
    cloned = original.clone()
    
    assert cloned.base_url == original.base_url
    assert cloned.static_url == original.static_url


def test_multiple_clones():
    """Test creating multiple clones."""
    original = SimpleTestTool(custom_param="original")
    
    clone1 = original.clone()
    clone2 = original.clone()
    
    # All should be different instances
    assert clone1 is not original
    assert clone2 is not original
    assert clone1 is not clone2
    
    # All should have the same configuration
    assert clone1.custom_param == original.custom_param == clone2.custom_param


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
