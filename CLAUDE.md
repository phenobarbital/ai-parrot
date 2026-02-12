# AI-Parrot Development Guide for Claude

## Project Overview

AI-Parrot is an async-first Python framework for building, extending, and orchestrating AI Agents and Chatbots. Built on top of `navigator-api`, it provides a unified interface for interacting with LLM providers, managing tools, conducting agent-to-agent (A2A) communication, and serving agents via Model Context Protocol (MCP).

**Current Branch**: `finance-agents`
**Main Branch**: `main`

---

## Core Philosophy: "Think-Act-Reflect"

As an AI assistant working on this project, you must follow the mandatory Think-Act-Reflect loop:

### 1. 🧠 Think (Plan)
Before any complex coding task, you MUST:
- Generate a plan in `artifacts/plan_[task_id].md`
- Read relevant source code to understand the architecture
- Discuss and confirm the complete plan with the user before proceeding
- Use `<thought>` blocks to reason through edge cases, security, and scalability

### 2. ⚡ Act (Execute)
- Write clean, modular, and well-documented code following project standards
- Optimize code for AI readability (context window efficiency)
- Follow the Agentic Design principles
- All code changes should be incremental and purposeful

### 3. ✅ Reflect (Verify)
You are responsible for verifying your work:
- **ALWAYS** run `pytest` after making changes
- Save all evidence (logs, test results) to `artifacts/logs/`
- For UI/Frontend modifications, generate screenshots
- Confirm that changes align with the original plan

---

## Development Environment

### Package Management & Virtual Environment

**CRITICAL RULES:**
1. **Package Manager**: Use **`uv`** exclusively for package management
   ```bash
   uv pip install <package>
   uv pip list
   uv add <package>
   ```

2. **Virtual Environment**: ALWAYS activate before Python operations
   ```bash
   source .venv/bin/activate
   ```
   **NEVER** run `uv`, `python`, or `pip` commands without activating first.

3. **Dependencies**: Manage all dependencies via `pyproject.toml`

---

## Python Coding Standards

### Type Safety & Documentation
All Python code MUST include:

```python
from typing import Optional, List, Dict
from pydantic import BaseModel

class ExampleModel(BaseModel):
    """Google-style docstring describing the model.

    Attributes:
        name: Description of the name field.
        value: Description of the value field.
    """
    name: str
    value: int

def example_function(param: str, optional: Optional[int] = None) -> Dict[str, str]:
    """Brief description of what the function does.

    Args:
        param: Description of the param.
        optional: Description of the optional parameter.

    Returns:
        Dictionary containing the result.

    Raises:
        ValueError: When param is invalid.
    """
    pass
```

**Requirements:**
- ✅ ALL functions and classes MUST have Google-style docstrings
- ✅ ALL code MUST use strict Type Hints (from `typing` module)
- ✅ Use `pydantic` models for all data structures and schemas
- ✅ Follow PEP 8 style guidelines
- ✅ Use snake_case for functions/variables

### Code Quality
- Write modular and reusable code
- Implement proper error handling and logging
- Use context managers (`with` statement)
- Use list comprehensions and generator expressions where appropriate
- Profile code to identify bottlenecks for performance-critical sections

---

## Tool-Centric Architecture

AI-Parrot's agents interact with the world through tools. When creating tools:

1. **Location**: Place all external API/service wrappers in `parrot/tools/`
2. **Decorator Pattern**: Use `@tool` for simple functions
   ```python
   from parrot.tools import tool

   @tool
   def get_weather(location: str) -> str:
       """Get the current weather for a location."""
       return f"Weather in {location}: Sunny, 25°C"
   ```

3. **Toolkit Pattern**: Use `AbstractToolkit` for complex tool collections
4. **Documentation**: Every tool MUST have clear docstrings explaining purpose, parameters, and return values

---

## Testing Requirements

### Running Tests
After ANY logic modification:
```bash
source .venv/bin/activate
pytest
```

### Writing Tests
- Use `pytest` and `pytest-asyncio` for all tests
- Create fixtures for test data
- Test data pipelines, model predictions, and API integrations
- Place tests in the `tests/` directory
- Write both unit tests and integration tests

Example:
```python
import pytest
from parrot.bots import Chatbot

@pytest.mark.asyncio
async def test_chatbot_initialization():
    """Test that Chatbot initializes correctly."""
    bot = Chatbot(name="TestBot", llm="openai:gpt-4o")
    await bot.configure()
    assert bot.name == "TestBot"
```

---

## Async-First Development

AI-Parrot is built on async/await patterns:

```python
import asyncio
from parrot.bots import Chatbot

async def main():
    bot = Chatbot(name="MyBot", llm="openai:gpt-4o")
    await bot.configure()
    response = await bot.ask("Hello!")
    return response

# Always use asyncio.run() for entry points
if __name__ == "__main__":
    asyncio.run(main())
```

**Best Practices:**
- Use `async/await` for I/O-bound tasks
- Use multiprocessing for CPU-bound tasks
- Avoid blocking operations in async contexts
- Handle async context managers properly

---

## Project Structure

```
ai-parrot/
├── .agent/              # AI rules, skills, and workflows
│   ├── rules.md         # Core agent directives
│   ├── CONTEXT.md       # Project context
│   ├── skills/          # Reusable agent skills
│   ├── workflows/       # Development workflows
│   └── rules/           # Specific development rules
├── artifacts/           # AI-generated outputs
│   ├── plan_*.md        # Task plans
│   └── logs/            # Test results and evidence
├── parrot/              # Main package
│   ├── bots/            # Agent implementations
│   ├── tools/           # Tool definitions
│   ├── crews/           # Multi-agent orchestration
│   └── integrations/    # Telegram, MS Teams, etc.
├── tests/               # pytest test suite
├── examples/            # Example implementations
└── pyproject.toml       # Dependencies and config
```

---

## Common Workflows

### Starting a New Feature
1. Read `artifacts/plan_[feature].md` or create one if complex
2. Activate virtual environment: `source .venv/bin/activate`
3. Create feature branch following git-flow
4. Implement changes with proper type hints and docstrings
5. Run tests: `pytest`
6. Commit with descriptive message
7. Save artifacts/logs for documentation

### Debugging
1. Check `artifacts/logs/` for previous test results
2. Use proper logging instead of print statements
3. Run specific test: `pytest tests/test_specific.py -v`
4. Save debug output to `artifacts/logs/debug_[timestamp].log`

### Adding Dependencies
```bash
source .venv/bin/activate
uv add <package-name>
# Dependencies automatically added to pyproject.toml
```

---

## Machine Learning & AI Best Practices

When working with ML/AI components:

- **Traditional ML**: Use scikit-learn
- **Deep Learning**: Use PyTorch or TensorFlow/Keras
- **Data Processing**: Use pandas, numpy
- **Visualization**: Use matplotlib/seaborn
- **Experiment Tracking**: Use MLflow or Weights & Biases
- **Model Serving**: Use aiohttp for async API endpoints
- **GPU Acceleration**: Check availability and use when appropriate
- **Model Deployment**: Implement versioning, monitoring, and proper validation

---

## Integration Patterns

AI-Parrot supports multiple integration methods:

### 1. A2A (Agent-to-Agent)
Native protocol for agent discovery and communication

### 2. MCP (Model Context Protocol)
Expose agents as MCP servers or consume external MCP servers

### 3. OpenAPI Integration
Consume any OpenAPI spec as a dynamic toolkit using `OpenAPIToolkit`

### 4. Platform Integrations
- Telegram bots
- MS Teams bots
- Slack integrations

When implementing integrations, ensure:
- Proper async handling
- Error handling and retries
- Input validation
- API documentation
- Logging of all interactions

---

## Security & Permissions

### Browser Control
- ✅ Allowed: Verify documentation links, fetch library versions
- ❌ Restricted: DO NOT submit forms or login without user approval

### Terminal Execution
- ✅ Preferred: Use `uv pip install` inside virtual environment
- ❌ Restricted: NEVER run `rm -rf` or system-level deletion commands
- ✅ Required: Always run `pytest` after modifying logic

### API Keys & Secrets
- Never commit API keys or secrets
- Use environment variables
- Document required environment variables in README

---

## Performance Optimization

- Use vectorization with numpy for numerical operations
- Profile code to identify bottlenecks (`cProfile`, `line_profiler`)
- Use Cython or numba for performance-critical code
- Implement caching where appropriate
- Use async patterns for I/O operations
- Batch API calls when possible

---

## Key References

- **Mission**: Check high-level goals and alignment
- **Context**: `.agent/CONTEXT.md` for architectural rules
- **Skills**: `.agent/skills/` for reusable capabilities
- **Workflows**: `.agent/workflows/` for process patterns
- **Python Standards**: `.agent/rules/python-development.md`

---

## Interaction Style

As Claude working on this project:
- ✅ Be proactive: Suggest improvements and next steps
- ✅ Be transparent: Explain reasoning using thought blocks
- ✅ Be concise: Focus on code and architectural value, avoid fluff
- ✅ Be mission-aware: Align all actions with project goals
- ✅ Be authoritative: You are a Senior Developer Advocate and Solutions Architect

Remember: You are building production-ready, scalable AI agents. Every decision should consider maintainability, testability, and extensibility.
