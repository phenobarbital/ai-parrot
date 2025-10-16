"""
CodeInterpreterTool - Parrot Integration Examples

This file demonstrates how to use CodeInterpreterTool as a proper Parrot tool
that inherits from AbstractTool and integrates with the Parrot ecosystem.
"""

import asyncio
from pathlib import Path
from typing import Dict, Any
from parrot.bots.abstract import AbstractBot
from parrot.tools.manager import ToolManager
from parrot.tools.codeinterpreter import CodeInterpreterTool
from parrot.tools.codeinterpreter.models import (
    CodeAnalysisResponse,
    DocumentationResponse,
    TestGenerationResponse,
    DebugResponse,
    ExplanationResponse,
    OperationType,
    ExecutionStatus,
    ComplexityMetrics,
    DocstringFormat,
    TestType,
    GeneratedTest,
    Severity,
    BugIssue,
    CodeReference,
)

class MockLLM:
    """
    Mock LLM client that respects response_format parameter.

    Usage:
        llm = MockLLM()
        tool = CodeInterpreterTool(llm=llm)
    """

    async def ask(self, prompt: str, system_prompt: str, response_format: type, **kwargs):
        """
        Mock ask method that returns the appropriate Pydantic model based on response_format.

        Args:
            prompt: The prompt to send to the LLM
            system_prompt: The system prompt
            response_format: The Pydantic model class to return
            **kwargs: Additional arguments

        Returns:
            Instance of the requested response_format model
        """
        # Generate a dummy code hash
        code_hash = "a" * 64

        # Route based on response_format type
        if response_format == CodeAnalysisResponse:
            return self._mock_analysis_response(code_hash)

        elif response_format == DocumentationResponse:
            return self._mock_documentation_response(code_hash)

        elif response_format == TestGenerationResponse:
            return self._mock_test_response(code_hash)

        elif response_format == DebugResponse:
            return self._mock_debug_response(code_hash)

        elif response_format == ExplanationResponse:
            return self._mock_explanation_response(code_hash)

        else:
            raise ValueError(f"Unknown response format: {response_format}")

    def _mock_analysis_response(self, code_hash: str) -> CodeAnalysisResponse:
        """Create mock analysis response."""
        return CodeAnalysisResponse(
            operation_type=OperationType.ANALYZE,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1500,
            code_hash=code_hash,
            executive_summary="This code implements a data processing function with input validation and error handling.",
            detailed_purpose="The code provides a function that processes input data, validates the format, handles edge cases, and returns processed results. It includes proper error handling for common failure scenarios.",
            complexity_metrics=ComplexityMetrics(
                cyclomatic_complexity=5,
                lines_of_code=45,
                cognitive_complexity=7,
                maintainability_index=78.5
            )
        )

    def _mock_documentation_response(self, code_hash: str) -> DocumentationResponse:
        """Create mock documentation response."""
        documented_code = '''def process_data(data: list) -> dict:
    """Process input data and return results.

    This function takes a list of data items, validates each item,
    processes them according to business rules, and returns a summary.

    Args:
        data: List of data items to process. Each item should be a dict
              with 'id' and 'value' keys.

    Returns:
        Dictionary containing processing results with keys:
        - 'processed': Number of items processed successfully
        - 'failed': Number of items that failed processing
        - 'results': List of processed items

    Raises:
        ValueError: If data is None or empty
        TypeError: If data is not a list

    Examples:
        >>> data = [{'id': 1, 'value': 10}, {'id': 2, 'value': 20}]
        >>> result = process_data(data)
        >>> result['processed']
        2
    """
    if not data:
        raise ValueError("Data cannot be empty")

    # Processing logic here
    results = []
    for item in data:
        # Process each item
        results.append(item)

    return {
        'processed': len(results),
        'failed': 0,
        'results': results
    }
'''

        return DocumentationResponse(
            operation_type=OperationType.DOCUMENT,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=2000,
            code_hash=code_hash,
            docstring_format=DocstringFormat.GOOGLE,
            modified_code=documented_code,
            documentation_coverage=100.0
        )

    def _mock_test_response(self, code_hash: str) -> TestGenerationResponse:
        """Create mock test response."""
        test_code = '''def test_process_data_valid_input():
    """Test processing with valid input data."""
    data = [{'id': 1, 'value': 10}, {'id': 2, 'value': 20}]
    result = process_data(data)

    assert result['processed'] == 2
    assert result['failed'] == 0
    assert len(result['results']) == 2


def test_process_data_empty_input():
    """Test that empty input raises ValueError."""
    with pytest.raises(ValueError, match="Data cannot be empty"):
        process_data([])


def test_process_data_none_input():
    """Test that None input raises ValueError."""
    with pytest.raises(ValueError, match="Data cannot be empty"):
        process_data(None)


def test_process_data_invalid_type():
    """Test that invalid input type raises TypeError."""
    with pytest.raises(TypeError):
        process_data("not a list")
'''

        return TestGenerationResponse(
            operation_type=OperationType.TEST,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=2500,
            code_hash=code_hash,
            test_framework="pytest",
            generated_tests=[
                GeneratedTest(
                    name="test_process_data_valid_input",
                    test_type=TestType.UNIT,
                    test_code=test_code,
                    estimated_coverage=85.0,
                    covers_lines=[1, 2, 3, 4, 5],
                    is_edge_case=False
                )
            ],
            overall_coverage=85.0
        )

    def _mock_debug_response(self, code_hash: str) -> DebugResponse:
        """Create mock debug response."""
        return DebugResponse(
            operation_type=OperationType.DEBUG,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=1800,
            code_hash=code_hash,
            issues_found=[
                BugIssue(
                    severity=Severity.HIGH,
                    category="error_handling",
                    title="Missing type checking for input parameter",
                    location=CodeReference(
                        start_line=1,
                        end_line=3,
                        code_snippet="def process_data(data):\n    if not data:"
                    ),
                    description="The function does not check if 'data' is the correct type before processing. This could lead to unexpected behavior if a non-list is passed.",
                    trigger_scenario="When a string or other non-list type is passed as the 'data' parameter, the function may fail with unclear error messages.",
                    expected_behavior="Function should validate that 'data' is a list before attempting to process it.",
                    actual_behavior="Function assumes 'data' is a list without validation.",
                    suggested_fix="Add type checking at the start of the function:\n\nif not isinstance(data, list):\n    raise TypeError('data must be a list')"
                )
            ],
            critical_count=0,
            high_count=1,
            medium_count=0,
            low_count=0
        )

    def _mock_explanation_response(self, code_hash: str) -> ExplanationResponse:
        """Create mock explanation response."""
        return ExplanationResponse(
            operation_type=OperationType.EXPLAIN,
            status=ExecutionStatus.SUCCESS,
            execution_time_ms=2200,
            code_hash=code_hash,
            analogy="This code works like a quality control checkpoint in a factory - items come in, get inspected, and only valid ones pass through.",
            high_level_summary="This function processes a list of data items, validates each one, and returns a summary of the processing results.",
            user_expertise_level="intermediate"
        )




# ============================================================================
# Example 1: Basic Usage as Parrot Tool
# ============================================================================

async def example_basic_usage():
    """Basic usage of CodeInterpreterTool as a Parrot tool."""

    # Mock LLM client that simulates structured output support
    class MockClient:
        async def ask(self, prompt, system_prompt, response_format):
            # In real usage, this would call the actual LLM API
            # and return a validated Pydantic model instance
            from parrot.tools.codeinterpreter.models import CodeAnalysisResponse, OperationType, ExecutionStatus, ComplexityMetrics

            return CodeAnalysisResponse(
                operation_type=OperationType.ANALYZE,
                status=ExecutionStatus.SUCCESS,
                execution_time_ms=1500,
                code_hash="a" * 64,
                executive_summary="This code implements a simple calculator.",
                detailed_purpose="Provides basic arithmetic operations.",
                complexity_metrics=ComplexityMetrics(
                    cyclomatic_complexity=3,
                    lines_of_code=45
                )
            )

    # Initialize the tool (Parrot way)
    tool = CodeInterpreterTool(
        llm=MockClient(),  # Note: llm parameter, not llm_client
        use_docker=False  # For demo, use subprocess
    )

    sample_code = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
"""

    # Method 1: Use _execute() (AbstractTool interface)
    result = await tool._execute(
        code=sample_code,
        operation="analyze"
    )

    print("Analysis Result:", result)

    # Method 2: Use convenience methods (returns Pydantic models)
    analysis = await tool.analyze_code(sample_code)
    print(f"\nExecutive Summary: {analysis.executive_summary}")
    print(f"Complexity: {analysis.complexity_metrics.cyclomatic_complexity}")

    return tool


# ============================================================================
# Example 2: Integration with ToolManager
# ============================================================================

async def example_tool_manager():
    """Using CodeInterpreterTool with Parrot's ToolManager."""
    # Create tool manager
    tool_manager = ToolManager()

    # Create and register CodeInterpreterTool
    class MockMini:
        async def ask(self, *args, **kwargs):
            pass

    code_tool = CodeInterpreterTool(llm=MockMini())
    tool_manager.register_tool(code_tool)

    # Verify registration
    print(f"Registered tools: {tool_manager.list_tools()}")

    # Access the tool
    tool = tool_manager.get_tool("code_interpreter")
    print(f"Tool name: {tool.name}")
    print(f"Tool description: {tool.description}")

    return tool_manager


# ============================================================================
# Example 3: Using as Agent Tool (Agent-as-Tool Pattern)
# ============================================================================

async def example_agent_as_tool():
    """
    Demonstrate CodeInterpreterTool as an Agent-as-Tool.

    The tool wraps an LLM agent with specialized capabilities,
    similar to how AgentTool wraps a Bot.
    """

    # Simulate an agent that uses CodeInterpreterTool
    class CodeReviewAgent:
        """Agent that performs code reviews using CodeInterpreterTool."""

        def __init__(self, llm):
            self.name = "Code Review Agent"
            self.code_tool = CodeInterpreterTool(llm=llm)

        async def review_code(self, code: str) -> Dict[str, Any]:
            """Perform comprehensive code review."""

            # Run multiple operations
            print("🔍 Running code analysis...")
            analysis = await self.code_tool.analyze_code(code)

            print("🐛 Detecting bugs...")
            bugs = await self.code_tool.detect_bugs(code)

            print("📊 Generating test suggestions...")
            tests = await self.code_tool.generate_tests(code)

            # Compile review report
            return {
                "summary": analysis.executive_summary,
                "complexity": analysis.complexity_metrics.cyclomatic_complexity,
                "quality_score": analysis.complexity_metrics.maintainability_index,
                "bugs_found": len(bugs.issues_found),
                "critical_bugs": bugs.critical_count,
                "test_coverage": tests.overall_coverage,
                "recommendations": [
                    obs.actionable_suggestion
                    for obs in analysis.quality_observations
                    if obs.actionable_suggestion
                ]
            }

    agent = CodeReviewAgent(llm=MockLLM())

    sample_code = """
def process_data(data):
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result
"""

    review = await agent.review_code(sample_code)

    print("\n📋 Code Review Report:")
    print(f"Summary: {review['summary']}")
    print(f"Complexity: {review['complexity']}")
    print(f"Quality Score: {review['quality_score']}")
    print(f"Bugs Found: {review['bugs_found']} (Critical: {review['critical_bugs']})")
    print(f"Test Coverage: {review['test_coverage']}%")

    return agent


# ============================================================================
# Example 4: Multi-Operation Workflow
# ============================================================================

async def example_multi_operation_workflow():
    """Demonstrate using multiple operations in a workflow."""

    tool = CodeInterpreterTool(llm=MockLLM())

    code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
"""

    # Workflow: Document → Test → Analyze
    print("📝 Step 1: Generating documentation...")
    docs = await tool.generate_documentation(code)
    print(f"Documentation coverage: {docs.documentation_coverage}%")
    print(f"Files saved: {len(docs.saved_files)}")

    print("\n🧪 Step 2: Generating tests...")
    tests = await tool.generate_tests(code, coverage_target=85.0)
    print(f"Tests generated: {len(tests.generated_tests)}")
    print(f"Estimated coverage: {tests.overall_coverage}%")

    print("\n✅ Workflow complete!")

    return {
        "documentation": docs,
        "tests": tests
    }


# ============================================================================
# Example 5: Using Tool Schema for LLM Function Calling
# ============================================================================

def example_tool_schema():
    """
    Demonstrate how to use the tool schema for LLM function calling.

    The tool schema is automatically generated from the args_schema
    and can be used with LLMs that support function calling.
    """
    tool = CodeInterpreterTool(llm=MockLLM())

    # Get the tool schema (compatible with OpenAI, Claude, etc.)
    schema = tool.get_tool_schema()

    print("Tool Schema:")
    print(f"Name: {schema['name']}")
    print(f"Description: {schema['description']}")
    print("\nParameters:")

    for param_name, param_info in schema.get('parameters', {}).get('properties', {}).items():
        print(f"  - {param_name}: {param_info.get('description', 'No description')}")
        print(f"    Type: {param_info.get('type', 'unknown')}")
        if 'enum' in param_info:
            print(f"    Valid values: {param_info['enum']}")

    print(f"\nRequired parameters: {schema.get('parameters', {}).get('required', [])}")

    return schema


# ============================================================================
# Example 6: Error Handling and Validation
# ============================================================================

async def example_error_handling():
    """Demonstrate error handling and input validation."""
    tool = CodeInterpreterTool(llm=MockLLM())

    # Test with invalid code
    invalid_code = "def broken_function(\n    # Missing closing parenthesis"

    try:
        result = await tool._execute(
            code=invalid_code,
            operation="analyze"
        )

        print("Result:", result)

        if result.get("status") == "failed":
            print(f"⚠️ Operation failed: {result.get('error_message')}")

    except Exception as e:
        print(f"❌ Exception caught: {e}")

    # Test with valid code but simulated LLM error
    valid_code = "def hello(): return 'world'"

    analysis = await tool.analyze_code(valid_code)

    if analysis.status == ExecutionStatus.FAILED:
        print(f"⚠️ Analysis failed: {analysis.error_message}")
    else:
        print("✅ Analysis succeeded")

    return tool


# ============================================================================
# Example 7: Cleanup and Resource Management
# ============================================================================

async def example_cleanup():
    """Demonstrate proper cleanup of resources."""
    # Create tool with Docker (if available)
    tool = CodeInterpreterTool(
        llm=MockLLM(),
        use_docker=True  # Will fallback to subprocess if Docker unavailable
    )

    try:
        # Use the tool
        code = "print('Hello, World!')"
        result = tool.execute_code_safely(code)
        print(f"Execution result: {result}")

    finally:
        # Always cleanup resources
        tool.cleanup()
        print("✅ Resources cleaned up")

    return tool


# ============================================================================
# Main Demo Runner
# ============================================================================

async def main():
    """Run all examples."""
    print("=" * 80)
    print("CodeInterpreterTool - Parrot Integration Examples")
    print("=" * 80)

    print("\n1. Basic Usage")
    print("-" * 80)
    await example_basic_usage()

    print("\n2. Tool Manager Integration")
    print("-" * 80)
    await example_tool_manager()

    print("\n3. Agent-as-Tool Pattern")
    print("-" * 80)
    await example_agent_as_tool()

    print("\n4. Multi-Operation Workflow")
    print("-" * 80)
    await example_multi_operation_workflow()

    print("\n5. Tool Schema for Function Calling")
    print("-" * 80)
    example_tool_schema()

    print("\n6. Error Handling")
    print("-" * 80)
    await example_error_handling()

    print("\n7. Resource Cleanup")
    print("-" * 80)
    await example_cleanup()

    print("\n" + "=" * 80)
    print("All examples complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
