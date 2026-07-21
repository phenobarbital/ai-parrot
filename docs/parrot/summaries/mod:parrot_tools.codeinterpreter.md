---
type: Wiki Summary
title: parrot_tools.codeinterpreter
id: mod:parrot_tools.codeinterpreter
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CodeInterpreterTool - Agent-as-Tool for comprehensive code analysis.
relates_to:
- concept: mod:parrot_tools
  rel: references
---

# `parrot_tools.codeinterpreter`

CodeInterpreterTool - Agent-as-Tool for comprehensive code analysis.

This package provides a Parrot Tool for analyzing, documenting,
testing, debugging, and explaining Python code.

Main components:
- CodeInterpreterTool: Main Parrot tool class (inherits from AbstractTool)
- Response models: Pydantic models for structured outputs
- Isolated execution: Docker-based code execution environment
- Internal tools: Static analysis, execution, and file operations

Quick start:
    >>> from parrot_tools.code_interpreter import CodeInterpreterTool
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
