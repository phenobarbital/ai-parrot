---
trigger: glob
globs: "**/*.py"
description: when we are creating python (.py, .pyx) files
---

You are an expert in Python asynchronous programming with asyncio.

**CRITICAL ENVIRONMENT RULES:**
1. **Package Manager**: You MUST use **`uv`** for all package management (e.g., `uv pip install`, `uv run`, `uv add`).
2. **Virtual Environment**: You MUST always act within the virtual environment.
   - **CRITICAL**: NEVER run `uv`, `python`, or `pip` commands without first activating the environment.
   - **ALWAYS** run `source .venv/bin/activate` before any python-related command.
3. **Web Server/Client**: You MUST use **`aiohttp`**.
4. **Runtime**: You MUST use **`asyncio`**.

Key Principles:
- Use async/await for I/O-bound operations
- Understand event loop mechanics
- Avoid blocking the event loop
- Handle cancellation and timeouts properly
- Use appropriate concurrency primitives
- if possible, use asyncio semaphores on async loops

Async Fundamentals:
- Use async def to define coroutines
- Use await to call async functions
- Never use time.sleep() in async code (use asyncio.sleep())
- Understand the difference between concurrency and parallelism
- Use asyncio.run() as the entry point for async programs

Async I/O Operations:
- Use aiohttp for async HTTP requests
- Use aiofiles for async file operations
- Use asyncpg for async PostgreSQL
- For other databases use AsyncDB (https://github.com/phenobarbital/asyncdb)

Concurrency Patterns:
- Use asyncio.gather() for concurrent execution
- Use asyncio.create_task() for background tasks
- Use asyncio.wait() with return_when parameter
- Use asyncio.as_completed() for processing results as they arrive
- Use asyncio.Queue for producer-consumer patterns

Synchronization Primitives:
- Use asyncio.Lock for mutual exclusion
- Use asyncio.Semaphore for limiting concurrency
- Use asyncio.Event for signaling between tasks
- Use asyncio.Condition for complex coordination
- Avoid deadlocks with proper lock ordering

Error Handling:
- Wrap async operations in try/except blocks
- Handle asyncio.CancelledError for task cancellation
- Use asyncio.shield() to protect critical operations
- Implement proper cleanup in finally blocks
- Use asyncio.wait_for() for timeouts

Performance Optimization:
- Use connection pooling for databases
- Implement rate limiting with asyncio.Semaphore
- Batch operations when possible
- Use asyncio.gather() with return_exceptions=True
- Profile async code with aiomonitor or aiodebug

Testing Async Code:
- Use pytest-asyncio for testing
- Use asynctest for mocking async functions
- Test cancellation scenarios
- Test timeout handling
- Use asyncio.run() in test fixtures

Common Pitfalls:
- Don't mix blocking and async code
- Don't create too many concurrent tasks
- Always await coroutines
- Don't use global event loops
- Handle task exceptions properly

Best Practices:
- Use type hints with Coroutine, Awaitable types
- Document async functions clearly
- Use context managers (async with) for resources
- Implement graceful shutdown
- Monitor event loop lag in production