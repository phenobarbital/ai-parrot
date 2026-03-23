"""
CodeInterpreterTool - Agent-as-Tool for comprehensive code analysis.

This package provides a Parrot Tool for analyzing, documenting,
testing, debugging, and explaining Python code.

Main components:
- CodeInterpreterTool: Main Parrot tool class (inherits from AbstractTool)
- Response models: Pydantic models for structured outputs
- Isolated execution: Docker-based code execution environment
- Internal tools: Static analysis, execution, and file operations

Quick start:
    >>> from parrot.tools.code_interpreter import CodeInterpreterTool
    >>> from your_llm_client import LLMClient
    >>>
    >>> client = LLMClient(api_key="your-key")
    >>> tool = CodeInterpreterTool(llm=client)
    >>>
    >>> # Use as async tool
    >>> result = await tool._execute(
    ...     code=source_code,
    ...     operation="analyze"
    ... )
    >>> print(result)

    >>> # Or use convenience methods
    >>> analysis = await tool.analyze_code(source_code)
    >>> print(analysis.executive_summary)
"""
from .tool import CodeInterpreterTool, CodeInterpreterArgs
# Import response models
from .models import (
    # Enums
    OperationType,
    ExecutionStatus,
    Severity,
    DocstringFormat,
    TestType,

    # Base models
    BaseCodeResponse,
    CodeReference,

    # Response models
    CodeAnalysisResponse,
    DocumentationResponse,
    TestGenerationResponse,
    DebugResponse,
    ExplanationResponse,

    # Component models
    ComplexityMetrics,
    FunctionComponent,
    ClassComponent,
    Dependency,
    QualityObservation,
    DocumentedElement,
    GeneratedTest,
    CoverageGap,
    BugIssue,
    CodeFlowStep,
    ConceptExplanation,
)

# Import executors
from .executor import (
    IsolatedExecutor,
    SubprocessExecutor,
    ExecutionResult,
    create_executor,
)

# Import internal tools
from .internals import (
    StaticAnalysisTool,
    PythonExecutionTool,
    FileOperationsTool,
    calculate_code_hash,
)

__all__ = [
    # Main Parrot tool
    "CodeInterpreterTool",
    "CodeInterpreterArgs",

    # Enums
    "OperationType",
    "ExecutionStatus",
    "Severity",
    "DocstringFormat",
    "TestType",

    # Response models
    "CodeAnalysisResponse",
    "DocumentationResponse",
    "TestGenerationResponse",
    "DebugResponse",
    "ExplanationResponse",

    # Component models
    "BaseCodeResponse",
    "CodeReference",
    "ComplexityMetrics",
    "FunctionComponent",
    "ClassComponent",
    "Dependency",
    "QualityObservation",
    "DocumentedElement",
    "GeneratedTest",
    "CoverageGap",
    "BugIssue",
    "CodeFlowStep",
    "ConceptExplanation",

    # Executors
    "IsolatedExecutor",
    "SubprocessExecutor",
    "ExecutionResult",
    "create_executor",

    # Internal tools
    "StaticAnalysisTool",
    "PythonExecutionTool",
    "FileOperationsTool",
    "calculate_code_hash",
]
