---
type: Wiki Entity
title: OutputFormatter
id: class:parrot.outputs.formatter.OutputFormatter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Formatter for AI responses supporting multiple output modes.
---

# OutputFormatter

Defined in [`parrot.outputs.formatter`](../summaries/mod:parrot.outputs.formatter.md).

```python
class OutputFormatter
```

Formatter for AI responses supporting multiple output modes.

Supports LLM-based retry for fixing malformed outputs (e.g., invalid JSON).
When a rendering fails due to parsing errors, the formatter can use an LLM
client to attempt to fix the output automatically.

Example usage with retry:
    ```python
    from parrot.clients.claude import AnthropicClient
    from parrot.outputs.formatter import OutputFormatter, OutputRetryConfig

    # Create LLM client for retries
    client = AnthropicClient()

    # Configure retry behavior
    retry_config = OutputRetryConfig(
        max_retries=2,
        retry_temperature=0.1
    )

    # Create formatter with retry support
    formatter = OutputFormatter(
        llm_client=client,
        retry_config=retry_config
    )

    # Format with automatic retry on failure
    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=response,
        original_prompt="Create a bar chart showing sales data"
    )

    if result.success:
        print("Output formatted successfully")
    else:
        print(f"Failed after {result.retry_count} retries: {result.final_error}")
    ```

## Methods

- `def get_system_prompt(self, mode: OutputMode) -> Optional[str]` — Get the system prompt for a given output mode.
- `def has_system_prompt(self, mode: OutputMode) -> bool` — Check if an output mode has a registered system prompt.
- `async def format(self, mode: OutputMode, data: Any, **kwargs) -> Tuple[str, Optional[str]]` — Format output based on mode
- `def extract_data(self, data: Any) -> Optional[List[Dict[str, Any]]]` — Extract data from response using Table extraction logic.
- `def add_template(self, name: str, content: str) -> None` — Add an in-memory template for use with TEMPLATE_REPORT mode.
- `def set_llm_client(self, client: 'AbstractClient') -> None` — Set or update the LLM client used for retry operations.
- `def set_retry_config(self, config: OutputRetryConfig) -> None` — Set or update the retry configuration.
- `def llm_client(self) -> Optional['AbstractClient']` — Get the current LLM client.
- `def retry_config(self) -> OutputRetryConfig` — Get the current retry configuration.
- `async def format_with_retry(self, mode: OutputMode, data: Any, original_prompt: Optional[str]=None, llm_client: Optional['AbstractClient']=None, retry_config: Optional[OutputRetryConfig]=None, **kwargs) -> OutputRetryResult` — Format output with automatic LLM-based retry on parsing failures.
