"""
CodeInterpreterTool: Agent-as-Tool for code analysis, documentation, testing, and debugging.

This tool wraps an LLM agent with specialized capabilities for understanding and improving code.
"""

from typing import Optional, Dict, Any, Union
from pathlib import Path
import time
from datetime import datetime

# Import the response models
from .models import (
    CodeAnalysisResponse,
    DocumentationResponse,
    TestGenerationResponse,
    DebugResponse,
    ExplanationResponse,
    OperationType,
    ExecutionStatus,
    BaseCodeResponse
)

# Import the system prompt
from .prompts import CODE_INTERPRETER_SYSTEM_PROMPT

# Import internal tools
from .internals import (
    StaticAnalysisTool,
    PythonExecutionTool,
    FileOperationsTool,
    calculate_code_hash
)

# Import isolated executor
from .executor import create_executor


class CodeInterpreterTool:
    """
    Agent-as-Tool for comprehensive code analysis.

    This tool uses an LLM agent with specialized tools to analyze, document,
    test, debug, and explain Python code.

    Features:
    - Code analysis with complexity metrics
    - Automatic documentation generation
    - Test generation with pytest
    - Bug detection and suggestions
    - Code explanation at various expertise levels
    - Isolated code execution for verification
    """

    def __init__(
        self,
        llm_client,
        output_dir: str = "./code_interpreter_outputs",
        use_docker: bool = True,
        docker_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the CodeInterpreterTool.

        Args:
            llm_client: LLM client instance (OpenAI, Claude, Google GenAI, Groq)
                       Must support structured outputs via ask() method
            output_dir: Directory for saving generated outputs
            use_docker: Whether to use Docker for code execution
            docker_config: Optional Docker configuration parameters
        """
        self.llm_client = llm_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize internal tools
        docker_config = docker_config or {}
        self.executor = create_executor(use_docker=use_docker, **docker_config)
        self.static_analyzer = StaticAnalysisTool()
        self.python_tool = PythonExecutionTool(self.executor)
        self.file_ops = FileOperationsTool(self.output_dir)

        # System prompt
        self.system_prompt = CODE_INTERPRETER_SYSTEM_PROMPT

    def _build_tool_context(self, code: str) -> str:
        """
        Build context with static analysis results for the agent.

        Args:
            code: Source code to analyze

        Returns:
            Formatted context string
        """
        # Perform static analysis
        structure = self.static_analyzer.analyze_code_structure(code)
        complexity = self.static_analyzer.calculate_complexity(code)

        context = "## Static Analysis Results\n\n"

        if structure.get("success"):
            context += "### Code Structure\n"
            context += f"- Functions: {len(structure.get('functions', []))}\n"
            context += f"- Classes: {len(structure.get('classes', []))}\n"
            context += f"- Imports: {len(structure.get('imports', []))}\n"

            metrics = structure.get('metrics', {})
            context += f"\n### Basic Metrics\n"
            context += f"- Total lines: {metrics.get('total_lines', 0)}\n"
            context += f"- Code lines: {metrics.get('code_lines', 0)}\n"
            context += f"- Comment lines: {metrics.get('comment_lines', 0)}\n"

        if complexity.get("success"):
            cc = complexity.get("cyclomatic_complexity", {})
            context += f"\n### Complexity Metrics\n"
            context += f"- Average cyclomatic complexity: {cc.get('average', 0)}\n"
            context += f"- Total cyclomatic complexity: {cc.get('total', 0)}\n"

            if complexity.get("maintainability_index"):
                context += f"- Maintainability index: {complexity['maintainability_index']}\n"

        context += f"\n## Source Code\n```python\n{code}\n```\n"

        return context

    def _make_agent_request(
        self,
        operation_type: OperationType,
        code: str,
        user_request: str,
        response_model: type[BaseCodeResponse],
        additional_context: Optional[str] = None,
    ) -> BaseCodeResponse:
        """
        Make a request to the LLM agent with structured output.

        Args:
            operation_type: Type of operation to perform
            code: Source code to analyze
            user_request: User's specific request
            response_model: Pydantic model for structured response
            additional_context: Optional additional context

        Returns:
            Structured response from the agent
        """
        start_time = time.time()

        # Build the context
        tool_context = self._build_tool_context(code)

        # Build the full prompt
        prompt = f"{tool_context}\n\n## User Request\n{user_request}"

        if additional_context:
            prompt += f"\n\n## Additional Context\n{additional_context}"

        try:
            # Make the request with structured output
            # Assuming the llm_client has an ask() method that accepts response_format
            response = self.llm_client.ask(
                prompt=prompt,
                system_prompt=self.system_prompt,
                response_format=response_model,
            )

            # Calculate execution time
            execution_time = int((time.time() - start_time) * 1000)

            # Update execution time in response
            if hasattr(response, 'execution_time_ms'):
                response.execution_time_ms = execution_time

            # Update code hash
            if hasattr(response, 'code_hash'):
                response.code_hash = calculate_code_hash(code)

            return response

        except Exception as e:
            # Return error response
            execution_time = int((time.time() - start_time) * 1000)

            # Create minimal error response
            error_response = response_model(
                operation_type=operation_type,
                status=ExecutionStatus.FAILED,
                execution_time_ms=execution_time,
                code_hash=calculate_code_hash(code),
                error_message=f"Agent request failed: {str(e)}",
            )

            return error_response

    def analyze_code(
        self,
        code: str,
        focus_areas: Optional[list[str]] = None,
    ) -> CodeAnalysisResponse:
        """
        Perform comprehensive code analysis.

        Args:
            code: Python source code to analyze
            focus_areas: Optional list of specific areas to focus on

        Returns:
            CodeAnalysisResponse with detailed analysis
        """
        user_request = "Perform a comprehensive analysis of this code."

        if focus_areas:
            user_request += f"\n\nFocus particularly on: {', '.join(focus_areas)}"

        user_request += """

        Provide:
        1. Executive summary of the code's purpose
        2. Detailed analysis of all functions and classes
        3. Dependencies and their usage
        4. Complexity metrics interpretation
        5. Quality observations (strengths and improvements)
        """

        return self._make_agent_request(
            operation_type=OperationType.ANALYZE,
            code=code,
            user_request=user_request,
            response_model=CodeAnalysisResponse,
        )

    def generate_documentation(
        self,
        code: str,
        docstring_format: str = "google",
        include_module_docs: bool = True,
    ) -> DocumentationResponse:
        """
        Generate documentation for code.

        Args:
            code: Python source code to document
            docstring_format: Format for docstrings (google, numpy, sphinx)
            include_module_docs: Whether to generate module-level documentation

        Returns:
            DocumentationResponse with generated documentation
        """
        user_request = f"""Generate comprehensive documentation for this code.

Requirements:
- Use {docstring_format}-style docstrings
- Document all functions, classes, and methods
- Include parameter types and descriptions
- Include return value descriptions
- Include exception documentation
- Add usage examples where helpful
"""

        if include_module_docs:
            user_request += "- Generate module-level documentation in markdown format\n"

        response = self._make_agent_request(
            operation_type=OperationType.DOCUMENT,
            code=code,
            user_request=user_request,
            response_model=DocumentationResponse,
        )

        # Save generated documentation to files
        if response.status == ExecutionStatus.SUCCESS:
            files_to_save = {}

            # Save modified code with docstrings
            files_to_save["documented_code.py"] = response.modified_code

            # Save module documentation if available
            if response.module_documentation:
                files_to_save["module_documentation.md"] = response.module_documentation

            # Save files
            save_result = self.file_ops.save_multiple(
                files_to_save,
                subdirectory=f"documentation_{response.operation_id}"
            )

            if save_result["success"]:
                response.saved_files = [
                    info["absolute_path"]
                    for info in save_result["files"].values()
                    if info.get("success")
                ]

        return response

    def generate_tests(
        self,
        code: str,
        test_framework: str = "pytest",
        coverage_target: float = 80.0,
        include_edge_cases: bool = True,
    ) -> TestGenerationResponse:
        """
        Generate tests for code.

        Args:
            code: Python source code to test
            test_framework: Testing framework to use (default: pytest)
            coverage_target: Target coverage percentage
            include_edge_cases: Whether to include edge case tests

        Returns:
            TestGenerationResponse with generated tests
        """
        user_request = f"""Generate comprehensive tests for this code.

Requirements:
- Use {test_framework} as the testing framework
- Target {coverage_target}% code coverage
- Include both happy path and error cases
"""

        if include_edge_cases:
            user_request += "- Generate specific tests for edge cases\n"

        user_request += """
- Use descriptive test names
- Include fixtures where appropriate
- Add docstrings to explain what each test validates
- Organize tests logically
"""

        response = self._make_agent_request(
            operation_type=OperationType.TEST,
            code=code,
            user_request=user_request,
            response_model=TestGenerationResponse,
        )

        # Save generated tests to file
        if response.status == ExecutionStatus.SUCCESS and response.generated_tests:
            # Combine all test code
            all_tests = []
            all_tests.append("import pytest")
            all_tests.append("import sys")
            all_tests.append("from pathlib import Path")
            all_tests.append("")
            all_tests.append("# Add source code directory to path if needed")
            all_tests.append("# sys.path.insert(0, str(Path(__file__).parent))")
            all_tests.append("")

            for test in response.generated_tests:
                all_tests.append(f"# Test: {test.name}")
                all_tests.append(f"# Type: {test.test_type.value}")
                all_tests.append(test.test_code)
                all_tests.append("")

            test_content = "\n".join(all_tests)

            # Also save the original source code
            files_to_save = {
                "test_generated.py": test_content,
                "source_code.py": code,
            }

            # Save setup instructions if provided
            if response.setup_instructions:
                files_to_save["README.md"] = f"# Test Setup Instructions\n\n{response.setup_instructions}"

            save_result = self.file_ops.save_multiple(
                files_to_save,
                subdirectory=f"tests_{response.operation_id}"
            )

            if save_result["success"]:
                response.saved_files = [
                    info["absolute_path"]
                    for info in save_result["files"].values()
                    if info.get("success")
                ]

                # Update test_file_path
                test_file = save_result["files"].get("test_generated.py")
                if test_file and test_file.get("success"):
                    response.test_file_path = test_file["absolute_path"]

        return response

    def detect_bugs(
        self,
        code: str,
        severity_threshold: str = "low",
        include_style_issues: bool = False,
    ) -> DebugResponse:
        """
        Detect potential bugs and issues in code.

        Args:
            code: Python source code to analyze
            severity_threshold: Minimum severity to report (critical, high, medium, low)
            include_style_issues: Whether to include style/formatting issues

        Returns:
            DebugResponse with identified issues
        """
        user_request = f"""Analyze this code for potential bugs and issues.

Requirements:
- Report issues with severity {severity_threshold} and above
- Check for logic errors, exception handling, resource management
- Look for security vulnerabilities
- Identify potential performance issues
- Check for type inconsistencies
"""

        if not include_style_issues:
            user_request += "- Focus on functional issues, not style/formatting\n"

        user_request += """
For each issue found:
- Provide specific location in code
- Explain the problem clearly
- Describe the trigger scenario
- Suggest a specific fix with code diff if possible
- Provide impact analysis
"""

        return self._make_agent_request(
            operation_type=OperationType.DEBUG,
            code=code,
            user_request=user_request,
            response_model=DebugResponse,
        )

    def explain_code(
        self,
        code: str,
        expertise_level: str = "intermediate",
        include_visualization: bool = True,
    ) -> ExplanationResponse:
        """
        Explain how code works.

        Args:
            code: Python source code to explain
            expertise_level: User's expertise level (beginner, intermediate, advanced)
            include_visualization: Whether to include ASCII visualizations

        Returns:
            ExplanationResponse with detailed explanation
        """
        user_request = f"""Explain how this code works.

Target audience expertise level: {expertise_level}

Requirements:
- Start with a high-level summary
- Explain the execution flow step by step
- Define any technical concepts that may not be familiar
- Describe data structures used
"""

        if include_visualization:
            user_request += "- Include ASCII diagrams or visualizations where helpful\n"

        if expertise_level == "beginner":
            user_request += "- Use simple analogies and avoid jargon\n"
            user_request += "- Explain basic programming concepts as needed\n"
        elif expertise_level == "advanced":
            user_request += "- Include complexity analysis\n"
            user_request += "- Discuss algorithmic trade-offs\n"

        return self._make_agent_request(
            operation_type=OperationType.EXPLAIN,
            code=code,
            user_request=user_request,
            response_model=ExplanationResponse,
            additional_context=f"User expertise level: {expertise_level}",
        )

    def execute_code_safely(self, code: str) -> Dict[str, Any]:
        """
        Execute code in isolated environment (direct tool access).

        Args:
            code: Python code to execute

        Returns:
            Execution results dictionary
        """
        return self.python_tool.execute(code, "Direct code execution")

    def cleanup(self):
        """Clean up resources (Docker containers, temp files, etc.)"""
        if hasattr(self.executor, 'cleanup'):
            self.executor.cleanup()
