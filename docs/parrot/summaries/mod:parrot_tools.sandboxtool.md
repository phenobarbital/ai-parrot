---
type: Wiki Summary
title: parrot_tools.sandboxtool
id: mod:parrot_tools.sandboxtool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AI-Parrot gVisor Sandbox Tool
relates_to:
- concept: class:parrot_tools.sandboxtool.ExecutionResult
  rel: defines
- concept: class:parrot_tools.sandboxtool.SandboxConfig
  rel: defines
- concept: class:parrot_tools.sandboxtool.SandboxPandasTool
  rel: defines
- concept: class:parrot_tools.sandboxtool.SandboxTool
  rel: defines
- concept: func:parrot_tools.sandboxtool.create_sandbox_tool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot_tools.sandboxtool`

AI-Parrot gVisor Sandbox Tool

Secure Python execution tool using gVisor (runsc) for complete kernel-level isolation.
This tool provides safe code execution for untrusted LLM-generated code.

## Classes

- **`SandboxConfig`** — Configuration for gVisor sandbox
- **`ExecutionResult`** — Result from sandbox execution
- **`SandboxTool(AbstractTool)`** — Secure Python execution using gVisor sandbox.
- **`SandboxPandasTool(SandboxTool)`** — Specialized version for Pandas operations with enhanced data handling.

## Functions

- `def create_sandbox_tool(tool_type: str='sandbox', **kwargs) -> Union[SandboxTool, SandboxPandasTool]` — Factory function to create gVisor tools.
