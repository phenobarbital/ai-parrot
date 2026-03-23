"""
CodeInterpreterTool - Parrot Tool for comprehensive code analysis.

Agent-as-Tool that wraps an LLM agent with specialized capabilities for:
- Code analysis with complexity metrics
- Documentation generation
- Test generation
- Bug detection
- Code explanation
"""
import time
from typing import Optional, Dict, Any, Literal
from pathlib import Path
from pydantic import BaseModel, Field
import hashlib
from parrot.tools.abstract import AbstractTool

# Import response models
from .models import (
    CodeAnalysisResponse,
    DocumentationResponse,
    TestGenerationResponse,
    DebugResponse,
    ExplanationResponse,
    OperationType,
    ExecutionStatus,
)

# Import system prompt
from .prompts import CODE_INTERPRETER_SYSTEM_PROMPT

# Import internal tools
from .internals import (
    StaticAnalysisTool,
    PythonExecutionTool,
    FileOperationsTool,
    calculate_code_hash,
)

# Import isolated executor
from .executor import create_executor


class CodeInterpreterArgs(BaseModel):
    """Input schema for CodeInterpreterTool."""
    code: str = Field(
        ...,
        description="Python source code to analyze"
    )
    operation: Literal["analyze", "document", "test", "debug", "explain"] = Field(
        default="analyze",
        description="Type of operation to perform on the code"
    )

    # Operation-specific parameters
    focus_areas: Optional[str] = Field(
        None,
        description="Comma-separated list of areas to focus on for analysis (e.g., 'complexity,error handling')"
    )
    docstring_format: str = Field(
        default="google",
        description="Format for docstrings: 'google', 'numpy', or 'sphinx'"
    )
    include_module_docs: bool = Field(
        default=True,
        description="Whether to generate module-level documentation"
    )
    test_framework: str = Field(
        default="pytest",
        description="Testing framework to use for test generation"
    )
    coverage_target: float = Field(
        default=80.0,
        description="Target code coverage percentage for tests"
    )
    include_edge_cases: bool = Field(
        default=True,
        description="Whether to include edge case tests"
    )
    severity_threshold: str = Field(
        default="low",
        description="Minimum severity for bug detection: 'critical', 'high', 'medium', or 'low'"
    )
    include_style_issues: bool = Field(
        default=False,
        description="Whether to include style/formatting issues in bug detection"
    )
    expertise_level: str = Field(
        default="intermediate",
        description="User expertise level for explanations: 'beginner', 'intermediate', or 'advanced'"
    )
    include_visualization: bool = Field(
        default=True,
        description="Whether to include ASCII visualizations in explanations"
    )


class CodeInterpreterTool(AbstractTool):
    """
    Agent-as-Tool for comprehensive Python code analysis.

    Features:
    - Code analysis with complexity metrics
    - Automatic documentation generation
    - Test generation with pytest
    - Bug detection with severity classification
    - Code explanation at various expertise levels
    - Isolated code execution for verification

    This tool wraps an LLM agent with specialized capabilities and internal tools
    for static analysis, code execution, and file operations.
    """

    name = "code_interpreter"
    description = (
        "Analyze, document, test, debug, and explain Python code. "
        "Provides comprehensive code analysis with complexity metrics, "
        "generates documentation and tests, detects bugs, and explains code functionality."
    )
    args_schema = CodeInterpreterArgs

    def __init__(
        self,
        llm,
        use_docker: bool = True,
        docker_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        Initialize the CodeInterpreterTool.

        Args:
            llm: LLM client instance (must support structured outputs via ask() method)
            use_docker: Whether to use Docker for code execution
            docker_config: Optional Docker configuration parameters
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(**kwargs)

        # Store LLM client with Parrot convention
        self._llm = llm

        # Initialize internal tools
        docker_config = docker_config or {}
        self.executor = create_executor(use_docker=use_docker, **docker_config)
        self.static_analyzer = StaticAnalysisTool()
        self.python_tool = PythonExecutionTool(self.executor)
        self.file_ops = FileOperationsTool(self.output_dir)

        # System prompt for the agent
        self.system_prompt = CODE_INTERPRETER_SYSTEM_PROMPT

        self.logger.info(f"CodeInterpreterTool initialized. Output dir: {self.output_dir}")

    def _default_output_dir(self) -> Path:
        """Get the default output directory for code interpreter outputs."""
        return self.static_dir / "reports" / "code_interpreter"

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

    async def _make_agent_request(
        self,
        operation_type: OperationType,
        code: str,
        user_request: str,
        response_model: type,
        additional_context: Optional[str] = None,
    ) -> Any:
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
            # Assuming the LLM client has an ask() method that accepts response_format
            response = await self._llm.ask(
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

            self.logger.error(f"Agent request failed: {e}")

            # Create minimal error response
            return response_model(
                operation_type=operation_type,
                status=ExecutionStatus.FAILED,
                execution_time_ms=execution_time,
                code_hash=calculate_code_hash(code),
                error_message=f"Agent request failed: {str(e)}",
            )

    async def _execute_analyze(
        self,
        code: str,
        focus_areas: Optional[str] = None,
    ) -> CodeAnalysisResponse:
        """Perform code analysis operation."""
        user_request = "Perform a comprehensive analysis of this code."

        if focus_areas:
            areas = [area.strip() for area in focus_areas.split(',')]
            user_request += f"\n\nFocus particularly on: {', '.join(areas)}"

        user_request += """

        Provide:
        1. Executive summary of the code's purpose
        2. Detailed analysis of all functions and classes
        3. Dependencies and their usage
        4. Complexity metrics interpretation
        5. Quality observations (strengths and improvements)
        """

        return await self._make_agent_request(
            operation_type=OperationType.ANALYZE,
            code=code,
            user_request=user_request,
            response_model=CodeAnalysisResponse,
        )

    async def _execute_document(
        self,
        code: str,
        docstring_format: str = "google",
        include_module_docs: bool = True,
    ) -> DocumentationResponse:
        """Generate documentation operation."""
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

        response = await self._make_agent_request(
            operation_type=OperationType.DOCUMENT,
            code=code,
            user_request=user_request,
            response_model=DocumentationResponse,
        )

        # Save generated documentation to files
        if response.status == ExecutionStatus.SUCCESS:
            files_to_save = {}

            # Save modified code with docstrings
            filename = self.generate_filename("documented_code", ".py")
            files_to_save[filename] = response.modified_code

            # Save module documentation if available
            if response.module_documentation:
                doc_filename = self.generate_filename("module_documentation", ".md")
                files_to_save[doc_filename] = response.module_documentation

            # Save files using file_ops
            for filename, content in files_to_save.items():
                result = self.file_ops.save_file(
                    content=content,
                    filename=filename,
                    subdirectory=f"documentation_{response.operation_id}"
                )

                if result.get("success"):
                    response.saved_files.append(result["absolute_path"])

        return response

    async def _execute_test(
        self,
        code: str,
        test_framework: str = "pytest",
        coverage_target: float = 80.0,
        include_edge_cases: bool = True,
    ) -> TestGenerationResponse:
        """Generate tests operation."""
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

        response = await self._make_agent_request(
            operation_type=OperationType.TEST,
            code=code,
            user_request=user_request,
            response_model=TestGenerationResponse,
        )

        # Save generated tests to file
        if response.status == ExecutionStatus.SUCCESS and response.generated_tests:
            # Combine all test code
            all_tests = [
                "import pytest",
                "import sys",
                "from pathlib import Path",
                "",
                "# Add source code directory to path if needed",
                "# sys.path.insert(0, str(Path(__file__).parent))",
                "",
            ]

            for test in response.generated_tests:
                all_tests.extend(
                    (
                        f"# Test: {test.name}",
                        f"# Type: {test.test_type.value}",
                        test.test_code,
                        "",
                    )
                )

            test_content = "\n".join(all_tests)

            # Also save the original source code
            test_filename = self.generate_filename("test_generated", ".py")
            source_filename = self.generate_filename("source_code", ".py")

            subdirectory = f"tests_{response.operation_id}"

            # Save test file
            test_result = self.file_ops.save_file(
                content=test_content,
                filename=test_filename,
                subdirectory=subdirectory
            )

            # Save source file
            source_result = self.file_ops.save_file(
                content=code,
                filename=source_filename,
                subdirectory=subdirectory
            )

            if test_result.get("success"):
                response.saved_files.append(test_result["absolute_path"])
                response.test_file_path = test_result["absolute_path"]

            if source_result.get("success"):
                response.saved_files.append(source_result["absolute_path"])

            # Save setup instructions if provided
            if response.setup_instructions:
                readme_filename = self.generate_filename("README", ".md")
                readme_content = f"# Test Setup Instructions\n\n{response.setup_instructions}"
                readme_result = self.file_ops.save_file(
                    content=readme_content,
                    filename=readme_filename,
                    subdirectory=subdirectory
                )
                if readme_result.get("success"):
                    response.saved_files.append(readme_result["absolute_path"])

        return response

    async def _execute_debug(
        self,
        code: str,
        severity_threshold: str = "low",
        include_style_issues: bool = False,
    ) -> DebugResponse:
        """Detect bugs operation."""
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

        return await self._make_agent_request(
            operation_type=OperationType.DEBUG,
            code=code,
            user_request=user_request,
            response_model=DebugResponse,
        )

    async def _execute_explain(
        self,
        code: str,
        expertise_level: str = "intermediate",
        include_visualization: bool = True,
    ) -> ExplanationResponse:
        """Explain code operation."""
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

        return await self._make_agent_request(
            operation_type=OperationType.EXPLAIN,
            code=code,
            user_request=user_request,
            response_model=ExplanationResponse,
            additional_context=f"User expertise level: {expertise_level}",
        )

    async def _execute(
        self,
        code: str,
        operation: str = "analyze",
        focus_areas: Optional[str] = None,
        docstring_format: str = "google",
        include_module_docs: bool = True,
        test_framework: str = "pytest",
        coverage_target: float = 80.0,
        include_edge_cases: bool = True,
        severity_threshold: str = "low",
        include_style_issues: bool = False,
        expertise_level: str = "intermediate",
        include_visualization: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the code interpreter tool (AbstractTool interface).

        Args:
            code: Python source code to analyze
            operation: Type of operation ('analyze', 'document', 'test', 'debug', 'explain')
            focus_areas: Areas to focus on for analysis
            docstring_format: Format for docstrings
            include_module_docs: Whether to generate module docs
            test_framework: Testing framework to use
            coverage_target: Target coverage percentage
            include_edge_cases: Whether to include edge case tests
            severity_threshold: Minimum severity for bug detection
            include_style_issues: Whether to include style issues
            expertise_level: User expertise level for explanations
            include_visualization: Whether to include visualizations
            **kwargs: Additional arguments

        Returns:
            Dictionary with operation results
        """
        self.logger.info(f"Executing CodeInterpreterTool operation: {operation}")

        try:
            # Route to appropriate operation
            if operation == "analyze":
                response = await self._execute_analyze(code, focus_areas)
            elif operation == "document":
                response = await self._execute_document(
                    code, docstring_format, include_module_docs
                )
            elif operation == "test":
                response = await self._execute_test(
                    code, test_framework, coverage_target, include_edge_cases
                )
            elif operation == "debug":
                response = await self._execute_debug(
                    code, severity_threshold, include_style_issues
                )
            elif operation == "explain":
                response = await self._execute_explain(
                    code, expertise_level, include_visualization
                )
            else:
                return {
                    "error": f"Unknown operation: {operation}",
                    "valid_operations": ["analyze", "document", "test", "debug", "explain"]
                }

            # Convert Pydantic model to dict for return
            return response.model_dump()

        except Exception as e:
            self.logger.error(f"Error in CodeInterpreterTool: {e}", exc_info=True)
            return {
                "error": str(e),
                "operation": operation,
                "code_preview": f"{code[:100]}..." if len(code) > 100 else code,
            }

    # Convenience methods for direct access (optional, for backward compatibility)

    async def analyze_code(
        self,
        code: str,
        focus_areas: Optional[list[str]] = None,
    ) -> CodeAnalysisResponse:
        """Convenience method for code analysis."""
        focus_str = ','.join(focus_areas) if focus_areas else None
        return await self._execute_analyze(code, focus_str)

    async def generate_documentation(
        self,
        code: str,
        docstring_format: str = "google",
        include_module_docs: bool = True,
    ) -> DocumentationResponse:
        """Convenience method for documentation generation."""
        return await self._execute_document(code, docstring_format, include_module_docs)

    async def generate_tests(
        self,
        code: str,
        test_framework: str = "pytest",
        coverage_target: float = 80.0,
        include_edge_cases: bool = True,
    ) -> TestGenerationResponse:
        """Convenience method for test generation."""
        return await self._execute_test(
            code, test_framework, coverage_target, include_edge_cases
        )

    async def detect_bugs(
        self,
        code: str,
        severity_threshold: str = "low",
        include_style_issues: bool = False,
    ) -> DebugResponse:
        """Convenience method for bug detection."""
        return await self._execute_debug(code, severity_threshold, include_style_issues)

    async def explain_code(
        self,
        code: str,
        expertise_level: str = "intermediate",
        include_visualization: bool = True,
    ) -> ExplanationResponse:
        """Convenience method for code explanation."""
        return await self._execute_explain(code, expertise_level, include_visualization)

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
