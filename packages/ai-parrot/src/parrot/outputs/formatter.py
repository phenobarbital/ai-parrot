from __future__ import annotations
import sys
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple, Callable, TYPE_CHECKING, List
from .formats import get_renderer, get_output_prompt, has_system_prompt
from ..models.outputs import OutputMode
from ..template.engine import TemplateEngine
import os
import uuid

if TYPE_CHECKING:
    from ..clients.base import AbstractClient


logger = logging.getLogger(__name__)


@dataclass
class OutputRetryConfig:
    """Configuration for LLM-based output retry on parsing failures.

    When output parsing fails (e.g., malformed JSON for ECharts), this config
    controls how the system will use an LLM to attempt to fix the output.

    Attributes:
        max_retries: Maximum number of retry attempts (default: 2)
        retry_on_parse_error: Whether to retry on parsing/validation errors
        retry_model: Optional specific model to use for retries (uses client default if None)
        retry_temperature: Temperature for retry requests (lower = more deterministic)
        retry_max_tokens: Max tokens for retry response
        include_original_prompt: Whether to include the original user prompt in retry
        custom_retry_prompts: Optional dict mapping OutputMode to custom retry prompts
    """
    max_retries: int = 2
    retry_on_parse_error: bool = True
    retry_model: Optional[str] = None
    retry_temperature: float = 0.1
    retry_max_tokens: int = 4096
    include_original_prompt: bool = True
    custom_retry_prompts: dict = field(default_factory=dict)

    def get_retry_prompt(self, mode: OutputMode) -> Optional[str]:
        """Get custom retry prompt for a specific output mode."""
        return self.custom_retry_prompts.get(mode)


# Default retry prompts for different output modes
DEFAULT_RETRY_PROMPTS = {
    OutputMode.ECHARTS: """You are a JSON repair assistant. The previous LLM response attempted to generate an ECharts configuration but produced invalid output.

**Your task:** Fix the malformed JSON and return ONLY a valid ECharts JSON configuration.

**Original Output (with error):**
```
{original_output}
```

**Error encountered:**
{error_message}

**Requirements:**
1. Return ONLY valid JSON inside a ```json code block
2. The JSON must be a valid ECharts option object
3. Must include at least 'series', 'dataset', or 'options' key
4. Fix any syntax errors (missing commas, quotes, brackets)
5. Do NOT add explanations - just the fixed JSON

**Fixed JSON:**""",

    OutputMode.JSON: """You are a JSON repair assistant. The previous response contained malformed JSON.

**Original Output:**
```
{original_output}
```

**Error:**
{error_message}

**Task:** Return ONLY the corrected, valid JSON inside a ```json code block. No explanations.""",

    OutputMode.PLOTLY: """You are a Python code repair assistant. The previous response attempted to generate Plotly visualization code but it failed.

**Original Code:**
```python
{original_output}
```

**Error:**
{error_message}

**Task:** Fix the Python code to create a valid Plotly figure. Return ONLY the corrected code inside a ```python code block.""",

    OutputMode.YAML: """You are a YAML repair assistant. The previous response contained malformed YAML.

**Original Output:**
```yaml
{original_output}
```

**Error:**
{error_message}

**Task:** Return ONLY the corrected, valid YAML. No explanations.""",
}


@dataclass
class OutputRetryResult:
    """Result from an output retry attempt.

    Attributes:
        success: Whether the retry produced valid output
        content: The formatted content (original or fixed)
        wrapped_content: Optional wrapped version (e.g., HTML)
        retry_count: Number of retry attempts made
        original_error: The original error that triggered retry
        final_error: The final error if all retries failed (None if success)
    """
    success: bool
    content: Any
    wrapped_content: Optional[Any]
    retry_count: int = 0
    original_error: Optional[str] = None
    final_error: Optional[str] = None


class OutputFormatter:
    """
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
    """

    def __init__(
        self,
        template_engine: Optional[TemplateEngine] = None,
        llm_client: Optional["AbstractClient"] = None,
        retry_config: Optional[OutputRetryConfig] = None,
    ):
        """
        Initialize the OutputFormatter.

        Args:
            template_engine: Optional TemplateEngine instance for template-based rendering.
                If not provided, a new one will be created when needed.
            llm_client: Optional LLM client instance for retry functionality.
                Required for format_with_retry() to work.
            retry_config: Optional retry configuration. If not provided,
                defaults will be used when retry is attempted.
        """
        self._is_ipython = self._detect_ipython()
        self._is_notebook = self._detect_notebook()
        self._environment = self._detect_environment()
        self._renderers = {}
        self._template_engine = template_engine
        self._llm_client = llm_client
        self._retry_config = retry_config or OutputRetryConfig()

    def _detect_environment(self) -> str:
        if self._is_ipython:
            return "jupyter" if self._is_notebook else "ipython"
        return "terminal"

    def _detect_ipython(self) -> bool:
        try:
            if "IPython" not in sys.modules:
                return False
            from IPython import get_ipython
            return get_ipython() is not None
        except (ImportError, NameError):
            return False

    def _detect_notebook(self) -> bool:
        try:
            from IPython import get_ipython
            ipython = get_ipython()
            return ipython is not None and "IPKernelApp" in ipython.config
        except Exception:
            return False

    def _get_renderer(self, mode: OutputMode):
        """
        Get or create a renderer instance for the specified output mode.

        Args:
            mode: OutputMode enum value

        Returns:
            Renderer instance for the given mode
        """
        if mode not in self._renderers:
            renderer_cls = get_renderer(mode)
            # Special handling for TEMPLATE_REPORT renderer to pass TemplateEngine
            if mode == OutputMode.TEMPLATE_REPORT:
                # Lazy initialize TemplateEngine if not provided
                if self._template_engine is None:
                    self._template_engine = TemplateEngine()
                self._renderers[mode] = renderer_cls(
                    template_engine=self._template_engine
                )
            else:
                self._renderers[mode] = renderer_cls()
        return self._renderers[mode]

    def get_system_prompt(self, mode: OutputMode) -> Optional[str]:
        """
        Get the system prompt for a given output mode.

        Args:
            mode: OutputMode enum value

        Returns:
            System prompt string or None if mode has no specific prompt
        """
        print(f"Getting system prompt for mode: {mode}")
        return get_output_prompt(mode)

    def has_system_prompt(self, mode: OutputMode) -> bool:
        """
        Check if an output mode has a registered system prompt.

        Args:
            mode: OutputMode enum value

        Returns:
            True if mode has a system prompt
        """
        return has_system_prompt(mode)

    async def format(
        self,
        mode: OutputMode,
        data: Any,
        **kwargs
    ) -> Tuple[str, Optional[str]]:
        """
        Format output based on mode

        Returns:
            Tuple[str, Optional[str]]: (content, wrapped_content)
            - content: main formatted output
            - wrapped_content: optional wrapped version (e.g., HTML)
        """
        if mode == OutputMode.DEFAULT:
            return data, None

        renderer = self._get_renderer(mode)
        render_method = getattr(renderer, "render_async", renderer.render)

        # Call renderer and get tuple response
        content, wrapped = await render_method(
            data,
            environment=self._environment,
            is_ipython=self._is_ipython,
            is_notebook=self._is_notebook,
            **kwargs,
        )

        # Debug: Save complete HTML to file for inspection
        if mode == OutputMode.HTML and kwargs.get("type") == "complete":
            try:
                # Create debug directory if it doesn't exist
                debug_dir = "static/html/tests"
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir, exist_ok=True)
                
                # Generate unique filename
                file_id = str(uuid.uuid4())
                filename = f"debug_{file_id}.html"
                file_path = os.path.join(debug_dir, filename)
                
                # Write content to file
                content_to_save = wrapped if wrapped else content
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(str(content_to_save))
                
                logger.info(f"Saved debug HTML output to: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to save debug HTML output: {e}")
        
        # Debug: Save complete HTML to file for inspection in Table, Chart, and Plot modes
        if mode in (OutputMode.TABLE, OutputMode.ECHARTS, OutputMode.PLOTLY, OutputMode.MATPLOTLIB, OutputMode.SEABORN, OutputMode.HOLOVIEWS, OutputMode.D3, OutputMode.BOKEH, OutputMode.ALTAIR) and kwargs.get("output_format") == "html" and kwargs.get("html_mode") == "complete":
             try:
                 # Create debug directory if it doesn't exist
                 debug_dir = "static/html/tests"
                 if not os.path.exists(debug_dir):
                     os.makedirs(debug_dir, exist_ok=True)
                 
                 filename = "debug.html"
                 file_path = os.path.join(debug_dir, filename)
                 
                 # Write content to file
                 content_to_save = wrapped if wrapped else content
                 with open(file_path, "w", encoding="utf-8") as f:
                     f.write(str(content_to_save))
                 
                 logger.info(f"Saved debug HTML output to: {file_path}")
             except Exception as e:
                 logger.warning(f"Failed to save debug HTML output for Table: {e}")

        return content, wrapped

    def extract_data(self, data: Any) -> Optional[List[Dict[str, Any]]]:
        """
        Extract data from response using Table extraction logic.
        
        Args:
            data: The response data to extract from
            
        Returns:
            List of dictionaries representing the data, or None if extraction failed/empty
        """
        try:
            renderer = self._get_renderer(OutputMode.TABLE)
            if hasattr(renderer, '_extract_data'):
                df = renderer._extract_data(data)
                # Check if it's a pandas DataFrame (has empty property)
                if hasattr(df, 'empty') and not df.empty:
                    return df.to_dict(orient='records')
        except Exception as e:
            logger.warning(f"Failed to extract data: {e}")
        return None

    def add_template(self, name: str, content: str) -> None:
        """
        Add an in-memory template for use with TEMPLATE_REPORT mode.

        Args:
            name: Template name (e.g., 'report.html', 'summary.md')
            content: Jinja2 template content

        Example:
            formatter = OutputFormatter()
            formatter.add_template('report.html', '<h1>{{ title }}</h1>')
            result = await formatter.format_async(
                OutputMode.TEMPLATE_REPORT,
                {"title": "My Report"},
                template="report.html"
            )
        """
        # Ensure TemplateEngine is initialized
        if self._template_engine is None:
            self._template_engine = TemplateEngine()

        # Get or create the TEMPLATE_REPORT renderer to add the template
        renderer = self._get_renderer(OutputMode.TEMPLATE_REPORT)
        if hasattr(renderer, 'add_template'):
            renderer.add_template(name, content)

    # =========================================================================
    # LLM Retry Functionality
    # =========================================================================

    def set_llm_client(self, client: "AbstractClient") -> None:
        """
        Set or update the LLM client used for retry operations.

        Args:
            client: An AbstractClient instance (Claude, GPT, etc.)
        """
        self._llm_client = client

    def set_retry_config(self, config: OutputRetryConfig) -> None:
        """
        Set or update the retry configuration.

        Args:
            config: OutputRetryConfig instance
        """
        self._retry_config = config

    @property
    def llm_client(self) -> Optional["AbstractClient"]:
        """Get the current LLM client."""
        return self._llm_client

    @property
    def retry_config(self) -> OutputRetryConfig:
        """Get the current retry configuration."""
        return self._retry_config

    def _get_retry_prompt(
        self,
        mode: OutputMode,
        original_output: str,
        error_message: str,
        original_prompt: Optional[str] = None
    ) -> str:
        """
        Build the retry prompt for fixing malformed output.

        Args:
            mode: The OutputMode that failed
            original_output: The raw output that failed to parse
            error_message: The error message from the parser
            original_prompt: Optional original user prompt for context

        Returns:
            Formatted retry prompt string
        """
        # Check for custom prompt in config first
        custom_prompt = self._retry_config.get_retry_prompt(mode)
        if custom_prompt:
            template = custom_prompt
        else:
            # Use default or generic prompt
            template = DEFAULT_RETRY_PROMPTS.get(mode)

        if template:
            prompt = template.format(
                original_output=original_output,
                error_message=error_message
            )
        else:
            # Generic fallback for modes without specific prompts
            prompt = f"""The previous output was malformed and could not be parsed.

**Original Output:**
```
{original_output}
```

**Error:**
{error_message}

**Task:** Fix the output to be valid for {mode.value} format. Return ONLY the corrected output."""

        # Optionally include original prompt for context
        if original_prompt and self._retry_config.include_original_prompt:
            prompt = f"""**Original User Request:**
{original_prompt}

{prompt}"""

        return prompt

    def _extract_raw_output(self, data: Any) -> str:
        """
        Extract raw output string from response data for retry.

        Args:
            data: Response data (AIMessage, string, dict, etc.)

        Returns:
            Raw output string
        """
        # Handle AIMessage-like objects
        if hasattr(data, 'response') and data.response:
            return str(data.response)
        if hasattr(data, 'content') and data.content:
            return str(data.content)
        if hasattr(data, 'output') and data.output:
            return str(data.output)
        if hasattr(data, 'to_text'):
            return str(data.to_text)

        # Handle dict responses
        if isinstance(data, dict):
            if 'response' in data:
                return str(data['response'])
            if 'content' in data:
                return str(data['content'])
            if 'output' in data:
                return str(data['output'])

        # Fallback to string conversion
        return str(data)

    def _is_parse_error_result(
        self,
        content: Any,
        wrapped: Optional[Any],
        mode: OutputMode
    ) -> Tuple[bool, Optional[str]]:
        """
        Detect if the format result indicates a parsing error.

        Different renderers signal errors differently:
        - ECharts: Returns error HTML in wrapped content
        - JSON: May return error message as content
        - Others: May return None or error strings

        Args:
            content: The content returned from format()
            wrapped: The wrapped content returned from format()
            mode: The output mode used

        Returns:
            Tuple of (is_error, error_message)
        """
        # Check for explicit error indicators in content
        if content is None:
            return True, "Renderer returned None content"

        content_str = str(content) if content else ""
        wrapped_str = str(wrapped) if wrapped else ""

        # Check for common error patterns
        error_patterns = [
            "Error parsing",
            "Invalid JSON",
            "Validation error",
            "JSONDecodeError",
            "SyntaxError",
            "ParseError",
            "class='error'",
            "class=\"error\"",
            "No ECharts configuration found",
            "must include 'series'",
        ]

        for pattern in error_patterns:
            if pattern in content_str or pattern in wrapped_str:
                # Extract error message
                error_msg = content_str if "Error" in content_str else wrapped_str
                return True, error_msg[:500]  # Truncate long errors

        return False, None

    async def _request_output_fix(
        self,
        mode: OutputMode,
        original_output: str,
        error_message: str,
        original_prompt: Optional[str] = None
    ) -> Optional[Any]:
        """
        Request the LLM to fix malformed output.

        Args:
            mode: The OutputMode that failed
            original_output: The raw output that failed to parse
            error_message: The error message from the parser
            original_prompt: Optional original user prompt for context

        Returns:
            Fixed response from LLM, or None if request fails
        """
        if not self._llm_client:
            logger.warning(
                "Cannot retry output fix: no LLM client configured"
            )
            return None

        retry_prompt = self._get_retry_prompt(
            mode=mode,
            original_output=original_output,
            error_message=error_message,
            original_prompt=original_prompt
        )

        # Get system prompt for the output mode (helps LLM understand the format)
        system_prompt = self.get_system_prompt(mode)
        if not system_prompt:
            system_prompt = f"You are a helpful assistant that fixes malformed {mode.value} output."

        try:
            # Make LLM request with retry-specific parameters
            response = await self._llm_client.ask(
                prompt=retry_prompt,
                system_prompt=system_prompt,
                max_tokens=self._retry_config.retry_max_tokens,
                temperature=self._retry_config.retry_temperature,
                model=self._retry_config.retry_model,
            )
            return response
        except Exception as e:
            logger.error(f"LLM retry request failed: {e}")
            return None

    async def format_with_retry(
        self,
        mode: OutputMode,
        data: Any,
        original_prompt: Optional[str] = None,
        llm_client: Optional["AbstractClient"] = None,
        retry_config: Optional[OutputRetryConfig] = None,
        **kwargs
    ) -> OutputRetryResult:
        """
        Format output with automatic LLM-based retry on parsing failures.

        This method attempts to format the output normally. If parsing fails,
        it uses the configured LLM client to request a fix for the malformed
        output, then retries formatting.

        Args:
            mode: OutputMode enum value
            data: The data to format (typically an AIMessage response)
            original_prompt: Optional original user prompt that generated the data.
                This provides context to the LLM for better fixes.
            llm_client: Optional LLM client to use for this call (overrides default)
            retry_config: Optional retry config for this call (overrides default)
            **kwargs: Additional arguments passed to the renderer

        Returns:
            OutputRetryResult with success status, content, and retry information

        Example:
            ```python
            result = await formatter.format_with_retry(
                mode=OutputMode.ECHARTS,
                data=response,
                original_prompt="Create a pie chart of quarterly sales"
            )

            if result.success:
                # Use result.content and result.wrapped_content
                display_chart(result.wrapped_content)
            else:
                # Handle failure
                logger.error(f"Format failed: {result.final_error}")
                show_raw_output(result.content)
            ```
        """
        # Use provided overrides or defaults
        client = llm_client or self._llm_client
        config = retry_config or self._retry_config

        # Track retry attempts
        retry_count = 0
        original_error: Optional[str] = None
        current_data = data

        while True:
            # Attempt to format
            try:
                content, wrapped = await self.format(mode, current_data, **kwargs)

                # Check if result indicates a parse error
                is_error, error_msg = self._is_parse_error_result(
                    content, wrapped, mode
                )

                if not is_error:
                    # Success!
                    return OutputRetryResult(
                        success=True,
                        content=content,
                        wrapped_content=wrapped,
                        retry_count=retry_count,
                        original_error=original_error
                    )

                # We have a parse error
                if original_error is None:
                    original_error = error_msg

                # Check if we should retry
                if not config.retry_on_parse_error:
                    logger.debug("Retry disabled, returning error result")
                    return OutputRetryResult(
                        success=False,
                        content=content,
                        wrapped_content=wrapped,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error=error_msg
                    )

                if retry_count >= config.max_retries:
                    logger.warning(
                        f"Max retries ({config.max_retries}) exceeded for {mode}"
                    )
                    return OutputRetryResult(
                        success=False,
                        content=content,
                        wrapped_content=wrapped,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error=error_msg
                    )

                if not client:
                    logger.warning(
                        "Cannot retry: no LLM client available"
                    )
                    return OutputRetryResult(
                        success=False,
                        content=content,
                        wrapped_content=wrapped,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error="No LLM client available for retry"
                    )

                # Attempt retry with LLM fix
                retry_count += 1
                logger.info(
                    f"Attempting retry {retry_count}/{config.max_retries} "
                    f"for {mode} output"
                )

                # Extract raw output for retry
                raw_output = self._extract_raw_output(current_data)

                # Request fix from LLM
                fixed_response = await self._request_output_fix(
                    mode=mode,
                    original_output=raw_output,
                    error_message=error_msg or "Unknown parsing error",
                    original_prompt=original_prompt
                )

                if fixed_response is None:
                    logger.warning("LLM fix request failed")
                    return OutputRetryResult(
                        success=False,
                        content=content,
                        wrapped_content=wrapped,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error="LLM fix request failed"
                    )

                # Use fixed response for next iteration
                current_data = fixed_response
                logger.debug(f"Retry {retry_count}: Got fixed response from LLM")

            except Exception as e:
                error_msg = str(e)
                if original_error is None:
                    original_error = error_msg

                logger.error(f"Format raised exception: {e}")

                # If we can't retry, return failure
                if retry_count >= config.max_retries or not client:
                    return OutputRetryResult(
                        success=False,
                        content=self._extract_raw_output(data),
                        wrapped_content=None,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error=error_msg
                    )

                # Attempt retry
                retry_count += 1
                raw_output = self._extract_raw_output(current_data)

                fixed_response = await self._request_output_fix(
                    mode=mode,
                    original_output=raw_output,
                    error_message=error_msg,
                    original_prompt=original_prompt
                )

                if fixed_response is None:
                    return OutputRetryResult(
                        success=False,
                        content=raw_output,
                        wrapped_content=None,
                        retry_count=retry_count,
                        original_error=original_error,
                        final_error="LLM fix request failed"
                    )

                current_data = fixed_response
