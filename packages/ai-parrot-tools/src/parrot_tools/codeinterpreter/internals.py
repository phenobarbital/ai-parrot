"""
Internal tools for the CodeInterpreterTool agent.
These tools provide the agent with capabilities for static analysis,
code execution, and file operations.
"""

import ast
import hashlib
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class FunctionInfo:
    """Information about a function"""
    name: str
    lineno: int
    args: List[str]
    returns: Optional[str]
    docstring: Optional[str]
    decorators: List[str]
    is_async: bool


@dataclass
class ClassInfo:
    """Information about a class"""
    name: str
    lineno: int
    bases: List[str]
    methods: List[str]
    docstring: Optional[str]
    decorators: List[str]


@dataclass
class ImportInfo:
    """Information about an import"""
    module: str
    names: List[str]
    is_from_import: bool


class StaticAnalysisTool:
    """
    Tool for performing static analysis on Python code.
    Uses AST parsing and radon for complexity metrics.
    """

    def analyze_code_structure(self, code: str) -> Dict[str, Any]:
        """
        Analyze code structure using AST.

        Args:
            code: Python source code

        Returns:
            Dictionary with functions, classes, imports, and basic metrics
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "error": f"Syntax error at line {e.lineno}: {e.msg}",
                "success": False
            }

        functions = []
        classes = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_info = self._extract_function_info(node)
                functions.append(asdict(func_info))

            elif isinstance(node, ast.ClassDef):
                class_info = self._extract_class_info(node)
                classes.append(asdict(class_info))

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                import_info = self._extract_import_info(node)
                imports.append(asdict(import_info))

        # Calculate basic metrics
        lines = code.split('\n')
        total_lines = len(lines)
        code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
        comment_lines = len([l for l in lines if l.strip().startswith('#')])

        return {
            "success": True,
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "metrics": {
                "total_lines": total_lines,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "blank_lines": total_lines - code_lines - comment_lines
            }
        }

    def _extract_function_info(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
        """Extract information from a function node"""
        args = [arg.arg for arg in node.args.args]

        returns = None
        if node.returns:
            returns = ast.unparse(node.returns)

        docstring = ast.get_docstring(node)

        decorators = [ast.unparse(dec) for dec in node.decorator_list]

        return FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            args=args,
            returns=returns,
            docstring=docstring,
            decorators=decorators,
            is_async=isinstance(node, ast.AsyncFunctionDef)
        )

    def _extract_class_info(self, node: ast.ClassDef) -> ClassInfo:
        """Extract information from a class node"""
        bases = [ast.unparse(base) for base in node.bases]

        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)

        docstring = ast.get_docstring(node)
        decorators = [ast.unparse(dec) for dec in node.decorator_list]

        return ClassInfo(
            name=node.name,
            lineno=node.lineno,
            bases=bases,
            methods=methods,
            docstring=docstring,
            decorators=decorators
        )

    def _extract_import_info(self, node: ast.Import | ast.ImportFrom) -> ImportInfo:
        """Extract information from an import node"""
        if isinstance(node, ast.Import):
            return ImportInfo(
                module=node.names[0].name if node.names else "",
                names=[alias.name for alias in node.names],
                is_from_import=False
            )
        else:  # ImportFrom
            return ImportInfo(
                module=node.module or "",
                names=[alias.name for alias in node.names],
                is_from_import=True
            )

    def calculate_complexity(self, code: str) -> Dict[str, Any]:
        """
        Calculate code complexity metrics using radon.

        Args:
            code: Python source code

        Returns:
            Dictionary with complexity metrics
        """
        try:
            # Try to import radon
            from radon.complexity import cc_visit
            from radon.metrics import mi_visit, h_visit

            # Cyclomatic Complexity
            cc_results = cc_visit(code)
            complexity_data = []

            for item in cc_results:
                complexity_data.append({
                    "name": item.name,
                    "complexity": item.complexity,
                    "lineno": item.lineno,
                    "type": item.classname or "function"
                })

            # Calculate average complexity
            avg_complexity = sum(item.complexity for item in cc_results) / len(cc_results) if cc_results else 0

            # Maintainability Index
            mi_score = mi_visit(code, multi=True)

            # Halstead metrics
            h_metrics = h_visit(code)

            return {
                "success": True,
                "cyclomatic_complexity": {
                    "average": round(avg_complexity, 2),
                    "total": sum(item.complexity for item in cc_results),
                    "details": complexity_data
                },
                "maintainability_index": round(mi_score, 2) if mi_score else None,
                "halstead": {
                    "difficulty": round(h_metrics.difficulty, 2) if h_metrics else None,
                    "volume": round(h_metrics.volume, 2) if h_metrics else None,
                    "effort": round(h_metrics.effort, 2) if h_metrics else None,
                } if h_metrics else None
            }

        except ImportError:
            # Radon not available, calculate basic cyclomatic complexity manually
            return self._basic_complexity(code)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to calculate complexity: {str(e)}"
            }

    def _basic_complexity(self, code: str) -> Dict[str, Any]:
        """Calculate basic cyclomatic complexity without radon"""
        try:
            tree = ast.parse(code)

            complexity_data = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    complexity = self._calculate_function_complexity(node)
                    complexity_data.append({
                        "name": node.name,
                        "complexity": complexity,
                        "lineno": node.lineno,
                        "type": "function"
                    })

            avg_complexity = sum(item["complexity"] for item in complexity_data) / len(complexity_data) if complexity_data else 0

            return {
                "success": True,
                "cyclomatic_complexity": {
                    "average": round(avg_complexity, 2),
                    "total": sum(item["complexity"] for item in complexity_data),
                    "details": complexity_data
                },
                "note": "Basic complexity calculation (radon not available)"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_function_complexity(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Calculate cyclomatic complexity of a function"""
        complexity = 1  # Base complexity

        for child in ast.walk(node):
            # Count decision points
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        return complexity


class PythonExecutionTool:
    """
    Tool for executing Python code in isolated environment.
    This wraps the IsolatedExecutor for use by the agent.
    """

    def __init__(self, executor):
        """
        Initialize with an executor instance.

        Args:
            executor: IsolatedExecutor or SubprocessExecutor instance
        """
        self.executor = executor

    def execute(
        self,
        code: str,
        description: str = "Execute Python code"
    ) -> Dict[str, Any]:
        """
        Execute Python code and return results.

        Args:
            code: Python code to execute
            description: Description of what's being executed

        Returns:
            Dictionary with execution results
        """
        # Validate syntax first
        is_valid, error = self.executor.validate_syntax(code)
        if not is_valid:
            return {
                "success": False,
                "error": error,
                "description": description
            }

        # Execute code
        result = self.executor.execute_code(code)

        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "execution_time_ms": result.execution_time_ms,
            "error": result.error_message,
            "description": description
        }

    def execute_tests(
        self,
        test_code: str,
        source_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute pytest tests.

        Args:
            test_code: Test code using pytest
            source_code: Optional source code being tested

        Returns:
            Dictionary with test execution results
        """
        result = self.executor.execute_tests(test_code, source_code)

        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "execution_time_ms": result.execution_time_ms,
            "error": result.error_message
        }


class FileOperationsTool:
    """
    Tool for file operations (reading, writing, organizing outputs).
    """

    def __init__(self, base_output_dir: Path):
        """
        Initialize with base output directory.

        Args:
            base_output_dir: Base directory for saving outputs
        """
        self.base_output_dir = Path(base_output_dir)
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

    def save_file(
        self,
        content: str,
        filename: str,
        subdirectory: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Save content to a file.

        Args:
            content: Content to save
            filename: Name of the file
            subdirectory: Optional subdirectory within base_output_dir

        Returns:
            Dictionary with file path and success status
        """
        try:
            if subdirectory:
                output_dir = self.base_output_dir / subdirectory
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_dir = self.base_output_dir

            file_path = output_dir / filename
            file_path.write_text(content)

            return {
                "success": True,
                "file_path": str(file_path),
                "absolute_path": str(file_path.absolute()),
                "size_bytes": len(content.encode('utf-8'))
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to save file: {str(e)}"
            }

    def read_file(self, file_path: str) -> Dict[str, Any]:
        """
        Read content from a file.

        Args:
            file_path: Path to the file

        Returns:
            Dictionary with file content and metadata
        """
        try:
            path = Path(file_path)
            content = path.read_text()

            return {
                "success": True,
                "content": content,
                "size_bytes": len(content.encode('utf-8')),
                "absolute_path": str(path.absolute())
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read file: {str(e)}"
            }

    def save_multiple(
        self,
        files: Dict[str, str],
        subdirectory: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Save multiple files.

        Args:
            files: Dictionary of filename -> content
            subdirectory: Optional subdirectory within base_output_dir

        Returns:
            Dictionary with results for each file
        """
        results = {}

        for filename, content in files.items():
            result = self.save_file(content, filename, subdirectory)
            results[filename] = result

        success_count = sum(1 for r in results.values() if r.get("success"))

        return {
            "success": success_count == len(files),
            "files": results,
            "success_count": success_count,
            "total_count": len(files)
        }


def calculate_code_hash(code: str) -> str:
    """
    Calculate SHA-256 hash of code.

    Args:
        code: Source code

    Returns:
        Hexadecimal hash string
    """
    return hashlib.sha256(code.encode('utf-8')).hexdigest()
