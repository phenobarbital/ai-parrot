# PYTHON

- **Package Manager**: project use **`uv`** for package management. Commands like `uv pip`, `uv run`, and `uv add` are required.
- **Virtual Environment**: Work must always be performed within a `.venv` virtual environment.
  - **CRITICAL**: You MUST NEVER run `uv`, `python`, or `pip` commands WITHOUT first enabling the virtual environment.
  - **ALWAYS** run `source .venv/bin/activate` before any python-related command.
- **Concurrency**: Prefer non-blocking code using **`asyncio`** over blocking synchronous code.
- **Web Server**: Use **`aiohttp`** as the default web server/client library.
