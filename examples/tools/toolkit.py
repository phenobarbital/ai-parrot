from typing import Any, Dict, List, Optional
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from parrot.tools import AbstractToolkit, tool_schema


# Example toolkits
class MathToolkit(AbstractToolkit):
    """Example toolkit for mathematical operations."""

    async def add(self, a: float, b: float) -> float:
        """Add two numbers together."""
        return a + b

    async def subtract(self, a: float, b: float) -> float:
        """Subtract the second number from the first."""
        return a - b

    async def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b

    async def divide(self, a: float, b: float) -> float:
        """Divide the first number by the second."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b

    async def power(self, base: float, exponent: float) -> float:
        """Raise base to the power of exponent."""
        return base ** exponent


# Custom schema example
class TextProcessingArgs(BaseModel):
    """Arguments for text processing tools."""
    text: str = Field(description="Text to process")
    operation: str = Field(description="Operation to perform", default="clean")


class TextToolkit(AbstractToolkit):
    """Example toolkit for text processing operations."""

    @tool_schema(TextProcessingArgs)
    async def clean_text(self, text: str, operation: str = "clean") -> str:
        """Clean and process text based on the specified operation."""
        if operation == "clean":
            return text.strip().lower()
        elif operation == "upper":
            return text.upper()
        elif operation == "title":
            return text.title()
        else:
            return text

    async def count_words(self, text: str) -> int:
        """Count the number of words in the text."""
        return len(text.split())

    async def reverse_text(self, text: str) -> str:
        """Reverse the input text."""
        return text[::-1]


# File operations toolkit example
class FileToolkitArgs(BaseModel):
    """Base arguments for file operations."""
    filename: str = Field(description="Name of the file")
    content: Optional[str] = Field(default=None, description="File content")


class FileToolkit(AbstractToolkit):
    """Toolkit for file operations."""

    input_class = FileToolkitArgs  # Default schema for all methods

    def __init__(self, base_dir: str = "/tmp", **kwargs):
        super().__init__(**kwargs)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    async def create_file(self, filename: str, content: str) -> Dict[str, Any]:
        """Create a new file with the specified content."""
        file_path = self.base_dir / filename

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            "filename": filename,
            "path": str(file_path),
            "size": len(content),
            "created": True
        }

    async def read_file(self, filename: str) -> Dict[str, Any]:
        """Read the contents of a file."""
        file_path = self.base_dir / filename

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return {
            "filename": filename,
            "content": content,
            "size": len(content)
        }

    async def list_files(self) -> List[str]:
        """List all files in the base directory."""
        return [f.name for f in self.base_dir.iterdir() if f.is_file()]


# Usage examples and testing
async def example_usage():
    """Example of how to use the AbstractToolkit system."""

    # Create toolkits
    math_toolkit = MathToolkit()
    text_toolkit = TextToolkit()
    file_toolkit = FileToolkit()

    # Get tools from each toolkit
    math_tools = math_toolkit.get_tools()
    text_tools = text_toolkit.get_tools()
    file_tools = file_toolkit.get_tools()

    print("Math Toolkit:")
    for tool in math_tools:
        print(f"  - {tool.name}: {tool.description}")
        schema = tool.get_tool_schema()
        print(f"    Schema: {schema['parameters']['properties'].keys()}")

    print("\nText Toolkit:")
    for tool in text_tools:
        print(f"  - {tool.name}: {tool.description}")

    print("\nFile Toolkit:")
    for tool in file_tools:
        print(f"  - {tool.name}: {tool.description}")

    # Test some tools
    print("\n--- Testing Tools ---")

    # Test math operations
    add_tool = math_toolkit.get_tool("add")
    result = await add_tool.execute(a=5, b=3)
    print(f"5 + 3 = {result.result}")

    # Test text processing
    clean_tool = text_toolkit.get_tool("clean_text")
    result = await clean_tool.execute(text="  HELLO WORLD  ", operation="clean")
    print(f"Cleaned text: '{result.result}'")

    # Test file operations
    create_tool = file_toolkit.get_tool("create_file")
    result = await create_tool.execute(filename="test.txt", content="Hello, World!")
    print(f"File created: {result.result}")

    read_tool = file_toolkit.get_tool("read_file")
    result = await read_tool.execute(filename="test.txt")
    print(f"File content: {result.result['content']}")


if __name__ == "__main__":
    asyncio.run(example_usage())
