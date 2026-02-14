from typing import Any, AsyncIterator, Dict, List, Optional, Union
import re
import asyncio
import logging
import time
from pathlib import Path
import contextlib
import io
import uuid
from PIL import Image
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent,
    ThinkingConfig
)
from google.oauth2 import service_account
from google.genai import types
from navconfig import config
import pandas as pd
from sklearn.base import defaultdict
from ..base import (
    AbstractClient,
    ToolDefinition,
    StreamingRetryConfig
)
from ...models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat,
    CompletionUsage,
    ObjectDetectionResult,
)
from ...models.google import (
    GoogleModel,
    ALL_VOICE_PROFILES,
    VoiceRegistry,
)
from ...tools.abstract import AbstractTool, ToolResult
from .analysis import GoogleAnalysis
from .generation import GoogleGeneration

logging.getLogger(
    name='PIL.TiffImagePlugin'
).setLevel(logging.ERROR)  # Suppress TiffImagePlugin warnings
logging.getLogger(
    name='google_genai'
).setLevel(logging.WARNING)  # Suppress GenAI warnings


class GoogleGenAIClient(AbstractClient, GoogleGeneration, GoogleAnalysis):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.

    Only Gemini-2.5-pro works well with multi-turn function calling.
    Supports both API Key (Gemini Developer API) and Service Account (Vertex AI).
    """
    client_type: str = 'google'
    client_name: str = 'google'
    _default_model: str = 'gemini-2.5-flash'
    _model_garden: bool = False

    def __init__(self, vertexai: bool = False, model_garden: bool = False, **kwargs):
        self.model_garden = model_garden
        self.vertexai: bool = True if model_garden else vertexai
        self.vertex_location = kwargs.get('location', config.get('VERTEX_REGION'))
        self.vertex_project = kwargs.get('project', config.get('VERTEX_PROJECT_ID'))
        self._credentials_file = kwargs.get('credentials_file', config.get('VERTEX_CREDENTIALS_FILE'))
        if isinstance(self._credentials_file, str):
            self._credentials_file = Path(self._credentials_file).expanduser()
        self.api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))

        # Suppress httpcore logs as requested
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
        logging.getLogger("httpcore.http11").setLevel(logging.WARNING)

        super().__init__(**kwargs)
        self.max_tokens = kwargs.get('max_tokens', 8192)
        self.client = None
        #  Create a single instance of the Voice registry
        self.voice_db = VoiceRegistry(profiles=ALL_VOICE_PROFILES)

    async def get_client(self) -> genai.Client:
        """Get the underlying Google GenAI client."""
        if self.vertexai:
            self.logger.info(
                f"Initializing Vertex AI for project {self.vertex_project} in {self.vertex_location}"
            )
            try:
                if self._credentials_file and self._credentials_file.exists():
                    credentials = service_account.Credentials.from_service_account_file(
                        str(self._credentials_file)
                    )
                else:
                    credentials = None  # Use default credentials

                return genai.Client(
                    vertexai=True,
                    project=self.vertex_project,
                    location=self.vertex_location,
                    credentials=credentials
                )
            except Exception as exc:
                self.logger.error(f"Failed to initialize Vertex AI client: {exc}")
                raise
        return genai.Client(
            api_key=self.api_key
        )

    async def close(self):
        if self.client:
            with contextlib.suppress(Exception):
                await self.client._api_client._aiohttp_session.close()   # pylint: disable=E1101 # noqa
        self.client = None

    def _fix_tool_schema(self, schema: dict):
        """Recursively converts schema type values to uppercase for GenAI compatibility."""
        if isinstance(schema, dict):
            for key, value in schema.items():
                if key == 'type' and isinstance(value, str):
                    schema[key] = value.upper()
                else:
                    self._fix_tool_schema(value)
        elif isinstance(schema, list):
            for item in schema:
                self._fix_tool_schema(item)
        return schema

    def _analyze_prompt_for_tools(self, prompt: str) -> List[str]:
        """
        Analyze the prompt to determine which tools might be needed.
        This is a placeholder for more complex logic that could analyze the prompt.
        """
        prompt_lower = prompt.lower()
        # Keywords that suggest need for built-in tools
        search_keywords = [
            'search',
            'find',
            'google',
            'web',
            'internet',
            'latest',
            'news',
            'weather'
        ]
        has_search_intent = any(keyword in prompt_lower for keyword in search_keywords)
        if has_search_intent:
            return "builtin_tools"
        else:
            # Mixed intent - prefer custom functions if available, otherwise builtin
            return "custom_functions"

    def _resolve_schema_refs(self, schema: dict, defs: dict = None) -> dict:
        """
        Recursively resolves $ref in JSON schema by inlining definitions.
        This is crucial for Pydantic v2 schemas used with Gemini.
        """
        if defs is None:
            defs = schema.get('$defs', schema.get('definitions', {}))

        if not isinstance(schema, dict):
            return schema

        # Handle $ref
        if '$ref' in schema:
            ref_path = schema['$ref']
            # Extract definition name (e.g., "#/$defs/MyModel" -> "MyModel")
            def_name = ref_path.split('/')[-1]
            if def_name in defs:
                # Get the definition
                resolved = self._resolve_schema_refs(defs[def_name], defs)
                # Merge with any other properties in the current schema (rare but possible)
                merged = {k: v for k, v in schema.items() if k != '$ref'}
                merged.update(resolved)
                return merged

        # Process children
        new_schema = {}
        for key, value in schema.items():
            if key == 'properties' and isinstance(value, dict):
                new_schema[key] = {
                    k: self._resolve_schema_refs(v, defs)
                    for k, v in value.items()
                }
            elif key == 'items' and isinstance(value, dict):
                new_schema[key] = self._resolve_schema_refs(value, defs)
            elif key in ('anyOf', 'allOf', 'oneOf') and isinstance(value, list):
                new_schema[key] = [self._resolve_schema_refs(item, defs) for item in value]
            else:
                new_schema[key] = value

        return new_schema

    def clean_google_schema(self, schema: dict) -> dict:
        """
        Clean a Pydantic-generated schema for Google Function Calling compatibility.
        NOW INCLUDES: Reference resolution.
        """
        if not isinstance(schema, dict):
            return schema

        # 1. Resolve References FIRST
        # Pydantic v2 uses $defs, v1 uses definitions
        if '$defs' in schema or 'definitions' in schema:
            schema = self._resolve_schema_refs(schema)

        cleaned = {}

        # Fields that Google Function Calling supports
        supported_fields = {
            'type', 'description', 'enum', 'default', 'properties',
            'required', 'items'
        }

        # Copy supported fields
        for key, value in schema.items():
            if key in supported_fields:
                if key == 'properties':
                    cleaned[key] = {k: self.clean_google_schema(v) for k, v in value.items()}
                elif key == 'items':
                    cleaned[key] = self.clean_google_schema(value)
                else:
                    cleaned[key] = value

        # ... [Rest of your existing type conversion logic stays the same] ...
        if 'type' in cleaned:
            if cleaned['type'] == 'integer':
                cleaned['type'] = 'number'  # Google prefers 'number' over 'integer'
            elif cleaned['type'] == 'object' and 'properties' not in cleaned:
                # Ensure objects have properties field, even if empty, to prevent confusion
                cleaned['properties'] = {}
            elif isinstance(cleaned['type'], list):
                non_null_types = [t for t in cleaned['type'] if t != 'null']
                cleaned['type'] = non_null_types[0] if non_null_types else 'string'

        # Handle anyOf (union types) - Simplified for Gemini
        if 'anyOf' in schema:
             # Pick the first non-null type, effectively flattening the union
             found_valid_option = False
             for option in schema['anyOf']:
                if not isinstance(option, dict): continue
                option_type = option.get('type')
                if option_type and option_type != 'null':
                    cleaned['type'] = option_type
                    if option_type == 'array' and 'items' in option:
                        cleaned['items'] = self.clean_google_schema(option['items'])
                    if option_type == 'object' and 'properties' in option:
                        cleaned['properties'] = {k: self.clean_google_schema(v) for k, v in option['properties'].items()}
                        if 'required' in option:
                            cleaned['required'] = option['required']
                    found_valid_option = True
                    break

             if not found_valid_option:
                 # If no valid option found (e.g. only nulls?), default to string
                 cleaned['type'] = 'string'

             # IMPORTANT: Remove anyOf after processing to avoid confusion
             cleaned.pop('anyOf', None)

        # Ensure type is present
        if 'type' not in cleaned:
             # Heuristic: if properties exist, it's an object
             if 'properties' in cleaned:
                 cleaned['type'] = 'object'
             elif 'items' in cleaned:
                 cleaned['type'] = 'array'
             else:
                 cleaned['type'] = 'string'

        # Ensure object-like schemas always advertise an object type
        if 'properties' in cleaned and cleaned.get('type') != 'object':
            cleaned['type'] = 'object'

        # Google rejects OBJECT schemas with empty properties; coerce to string.
        if cleaned.get('type') == 'object' and cleaned.get('properties') == {}:
            cleaned.pop('properties', None)
            cleaned['type'] = 'string'

        # Remove problematic fields
        problematic_fields = {
            'prefixItems', 'additionalItems', 'minItems', 'maxItems',
            'minLength', 'maxLength', 'pattern', 'format', 'minimum',
            'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
            'allOf', 'anyOf', 'oneOf', 'not', 'const', 'examples',
            '$defs', 'definitions', '$ref', 'title', 'additionalProperties'
        }

        for field in problematic_fields:
            cleaned.pop(field, None)

        return cleaned

    def _recursive_json_repair(self, data: Any) -> Any:
        """
        Traverses a dictionary/list and attempts to parse string values
        that look like JSON objects/lists.
        """
        if isinstance(data, dict):
            return {k: self._recursive_json_repair(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._recursive_json_repair(item) for item in data]
        elif isinstance(data, str):
            data = data.strip()
            # fast check if it looks like json
            if (data.startswith('{') and data.endswith('}')) or \
               (data.startswith('[') and data.endswith(']')):
                try:
                    import json
                    parsed = json.loads(data)
                    # Recurse into the parsed object in case it has nested strings
                    return self._recursive_json_repair(parsed)
                except (json.JSONDecodeError, TypeError):
                    return data
        return data

    def _coerce_json_keys_to_str(self, data: Any) -> Any:
        """Recursively coerce mapping keys to strings for JSON compatibility."""
        if isinstance(data, dict):
            return {
                str(k): self._coerce_json_keys_to_str(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self._coerce_json_keys_to_str(item) for item in data]
        if isinstance(data, tuple):
            return [self._coerce_json_keys_to_str(item) for item in data]
        if isinstance(data, set):
            return [self._coerce_json_keys_to_str(item) for item in data]
        return data

    def _apply_structured_output_schema(
        self,
        generation_config: Dict[str, Any],
        output_config: Optional[StructuredOutputConfig]
    ) -> Optional[Dict[str, Any]]:
        """Apply a cleaned structured output schema to the generationho config."""
        if not output_config or output_config.format != OutputFormat.JSON:
            return None

        try:
            raw_schema = output_config.get_schema()
            cleaned_schema = self.clean_google_schema(raw_schema)
            fixed_schema = self._fix_tool_schema(cleaned_schema)
        except Exception as exc:
            self.logger.error(
                f"Failed to generate structured output schema for Gemini: {exc}"
            )
            return None

        generation_config["response_mime_type"] = "application/json"
        generation_config["response_schema"] = fixed_schema
        return fixed_schema

    def _build_tools(self, tool_type: str, filter_names: Optional[List[str]] = None) -> Optional[List[types.Tool]]:
        """Build tools based on the specified type."""
        if tool_type == "custom_functions":
            # migrate to use abstractool + tool definition:
            # Group function declarations by their category
            declarations_by_category = defaultdict(list)
            for tool in self.tool_manager.all_tools():
                tool_name = tool.name
                if filter_names is not None and tool_name not in filter_names:
                    continue

                tool_name = tool.name
                category = getattr(tool, 'category', 'tools')
                if isinstance(tool, AbstractTool):
                    full_schema = tool.get_schema()
                    tool_description = full_schema.get("description", tool.description)
                    # Extract ONLY the parameters part
                    schema = full_schema.get("parameters", {}).copy()
                    # Clean the schema for Google compatibility
                    schema = self.clean_google_schema(schema)
                elif isinstance(tool, ToolDefinition):
                    tool_description = tool.description
                    schema = self.clean_google_schema(tool.input_schema.copy())
                else:
                    # Fallback for other tool types
                    tool_description = getattr(tool, 'description', f"Tool: {tool_name}")
                    schema = getattr(tool, 'input_schema', {})
                    schema = self.clean_google_schema(schema)

                # Ensure we have a valid parameters schema
                if not schema:
                    schema = {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                try:
                    declaration = types.FunctionDeclaration(
                        name=tool_name,
                        description=tool_description,
                        parameters=self._fix_tool_schema(schema)
                    )
                    declarations_by_category[category].append(declaration)
                except Exception as e:
                    self.logger.error(f"Error creating function declaration for {tool_name}: {e}")
                    # Skip this tool if it can't be created
                    continue

            tool_list = []
            for category, declarations in declarations_by_category.items():
                if declarations:
                    tool_list.append(
                        types.Tool(
                            function_declarations=declarations
                        )
                    )
            return tool_list
        elif tool_type == "builtin_tools":
            return [
                types.Tool(
                    google_search=types.GoogleSearch()
                ),
            ]

        return None

    def _extract_function_calls(self, response) -> List:
        """Extract function calls from response - handles both proper function calls AND code blocks."""
        function_calls = []

        try:
            if (response.candidates and
                len(response.candidates) > 0 and
                response.candidates[0].content and
                response.candidates[0].content.parts):

                for part in response.candidates[0].content.parts:
                    # First, check for proper function calls
                    if hasattr(part, 'function_call') and part.function_call:
                        function_calls.append(part.function_call)
                        self.logger.debug(f"Found proper function call: {part.function_call.name}")

                    # Second, check for text that contains tool code blocks
                    elif hasattr(part, 'text') and part.text and '```tool_code' in part.text:
                        self.logger.info("Found tool code block - parsing as function call")
                        code_block_calls = self._parse_tool_code_blocks(part.text)
                        function_calls.extend(code_block_calls)

        except (AttributeError, IndexError) as e:
            self.logger.debug(f"Error extracting function calls: {e}")

        self.logger.debug(f"Total function calls extracted: {len(function_calls)}")
        return function_calls

    async def _handle_stateless_function_calls(
        self,
        response,
        model: str,
        contents: List,
        config,
        all_tool_calls: List[ToolCall],
        original_prompt: Optional[str] = None
    ) -> Any:
        """Handle function calls in stateless mode (single request-response)."""
        function_calls = self._extract_function_calls(response)

        if not function_calls:
            return response

        # Execute function calls
        tool_call_objects = []
        for fc in function_calls:
            tc = ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=fc.name,
                arguments=dict(fc.args)
            )
            tool_call_objects.append(tc)

        start_time = time.time()
        tool_execution_tasks = [
            self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls
        ]
        tool_results = await asyncio.gather(
            *tool_execution_tasks,
            return_exceptions=True
        )
        execution_time = time.time() - start_time

        for tc, result in zip(tool_call_objects, tool_results):
            tc.execution_time = execution_time / len(tool_call_objects)
            if isinstance(result, Exception):
                tc.error = str(result)
            else:
                tc.result = result

        all_tool_calls.extend(tool_call_objects)

        # Prepare function responses
        function_response_parts = []
        for fc, result in zip(function_calls, tool_results):
            if isinstance(result, Exception):
                response_content = f"Error: {str(result)}"
            else:
                response_content = str(result.get('result', result) if isinstance(result, dict) else result)

            function_response_parts.append(
                Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": response_content}
                    )
                )
            )

        if summary_part := self._create_tool_summary_part(
            function_calls,
            tool_results,
            original_prompt
        ):
            function_response_parts.append(summary_part)

        # Add function call and responses to conversation
        contents.append({
            "role": "model",
            "parts": [{"function_call": fc} for fc in function_calls]
        })
        contents.append({
            "role": "user",
            "parts": function_response_parts
        })

        # Generate final response
        final_response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        return final_response

    # Maximum characters per tool result sent back to the model.
    # ~200K chars ≈ 50K tokens; keeps aggregate well under the 1M limit.
    MAX_TOOL_RESULT_CHARS: int = 200_000

    def _process_tool_result_for_api(self, result) -> dict:
        """Process tool result for Google Function Calling API compatibility.

        Serializes various Python objects into a JSON-compatible dict
        for the Google GenAI API. Results exceeding MAX_TOOL_RESULT_CHARS
        are truncated to prevent context-window overflow.
        """
        # 1. Handle exceptions and special wrapper types first
        if isinstance(result, Exception):
            return {"result": f"Tool execution failed: {str(result)}", "error": True}

        # Handle ToolResult wrapper
        if isinstance(result, ToolResult):
            content = result.result
            if result.metadata and 'stdout' in result.metadata:
                # Prioritize stdout if exists
                content = result.metadata['stdout']
            result = content # The actual result to process is the content

        # Handle string results early (no conversion needed)
        if isinstance(result, str):
            if not result.strip():
                return {"result": "Code executed successfully (no output)"}
            if len(result) > self.MAX_TOOL_RESULT_CHARS:
                result = result[:self.MAX_TOOL_RESULT_CHARS] + "\n...[TRUNCATED]"
            return {"result": result}

        # Convert complex types to basic Python types
        clean_result = result

        if isinstance(result, pd.DataFrame):
            # For large DataFrames, limit rows to prevent context overflow
            if len(result) > 500:
                self.logger.warning(
                    f"DataFrame has {len(result)} rows, truncating to 500 "
                    f"for API response"
                )
                result = result.head(500)
            # Convert DataFrame to records and ensure all keys are strings
            records = result.to_dict(orient='records')
            clean_result = [
                {str(k): v for k, v in record.items()}
                for record in records
            ]
        elif isinstance(result, list):
            # Handle lists (including lists of Pydantic models)
            clean_result = []
            for item in result:
                if hasattr(item, 'model_dump'):  # Pydantic v2
                    clean_result.append(item.model_dump())
                elif hasattr(item, 'dict'):  # Pydantic v1
                    clean_result.append(item.dict())
                else:
                    clean_result.append(item)
        elif hasattr(result, 'model_dump'):  # Pydantic v2 single model
            clean_result = result.model_dump()
        elif hasattr(result, 'dict'):  # Pydantic v1 single model
            clean_result = result.dict()

        clean_result = self._coerce_json_keys_to_str(clean_result)

        # 4. Attempt to serialize the processed result
        try:
            serialized = self._json.dumps(clean_result)
            # --- truncation gate ---
            if len(serialized) > self.MAX_TOOL_RESULT_CHARS:
                self.logger.warning(
                    f"Tool result too large ({len(serialized)} chars), "
                    f"truncating to {self.MAX_TOOL_RESULT_CHARS}"
                )
                # Truncated JSON is not valid — return as plain string
                return {
                    "result": serialized[:self.MAX_TOOL_RESULT_CHARS]
                    + "\n...[TRUNCATED]"
                }
            json_compatible_result = self._json.loads(serialized)
        except Exception as e:
            # This is the fallback for non-serializable objects (like PriceOutput)
            self.logger.warning(
                f"Could not serialize result of type {type(clean_result)} to JSON: {e}. "
                "Falling back to string representation."
            )
            fallback = str(clean_result)
            if len(fallback) > self.MAX_TOOL_RESULT_CHARS:
                fallback = fallback[:self.MAX_TOOL_RESULT_CHARS] + "\n...[TRUNCATED]"
            json_compatible_result = fallback

        # Wrap for Google Function Calling format
        if isinstance(json_compatible_result, dict) and 'result' in json_compatible_result:
            return json_compatible_result
        else:
            return {"result": json_compatible_result}

    def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str:
        """Create a short, human-readable summary of a tool result."""

        try:
            if isinstance(result, Exception):
                summary = f"Error: {result}"
            elif isinstance(result, pd.DataFrame):
                preview = result.head(5)
                summary = preview.to_string(index=True)
            elif hasattr(result, 'model_dump'):
                summary = self._json.dumps(
                    self._coerce_json_keys_to_str(result.model_dump())
                )
            elif isinstance(result, (dict, list)):
                summary = self._json.dumps(
                    self._coerce_json_keys_to_str(result)
                )
            else:
                summary = str(result)
        except Exception as exc:  # pylint: disable=broad-except
            summary = f"Unable to summarize result: {exc}"

        summary = summary.strip() or "[empty result]"
        if len(summary) > max_length:
            summary = summary[:max_length].rstrip() + "…"
        return summary

    def _create_tool_summary_part(
        self,
        function_calls,
        tool_results,
        original_prompt: Optional[str] = None
    ) -> Optional[Part]:
        """Build a textual summary of tool outputs for the model to read easily."""

        if not function_calls or not tool_results:
            return None

        summary_lines = ["Tool execution summaries:"]
        for fc, result in zip(function_calls, tool_results):
            summary_lines.append(
                f"- {fc.name}: {self._summarize_tool_result(result)}"
            )

        if original_prompt:
            summary_lines.append(f"Original Request: {original_prompt}")

        summary_lines.append(
            "Use the information above to craft the final response without running redundant tool calls."
        )

        summary_text = "\n".join(summary_lines)
        return Part(text=summary_text)

    async def _handle_multiturn_function_calls(
        self,
        chat,
        initial_response,
        all_tool_calls: List[ToolCall],
        original_prompt: Optional[str] = None,
        model: str = None,
        max_iterations: int = 10,
        config: GenerateContentConfig = None,
        max_retries: int = 3,
        lazy_loading: bool = False,
        active_tool_names: Optional[set] = None,
    ) -> Any:
        """
        Simple multi-turn function calling - just keep going until no more function calls.
        """
        current_response = initial_response
        current_config = config
        iteration = 0

        if active_tool_names is None:
            active_tool_names = set()

        model = model or self.model
        self.logger.info("Starting simple multi-turn function calling loop")

        while iteration < max_iterations:
            iteration += 1

            # Get function calls (including converted from tool_code)
            function_calls = self._get_function_calls_from_response(current_response)
            if not function_calls:
                # Check if we have any text content in the response
                final_text = self._safe_extract_text(current_response)
                self.logger.notice(f"🎯 Final Response from Gemini: {final_text[:200]}...")
                if not final_text and all_tool_calls:
                    self.logger.warning(
                        "Final response is empty after tool execution, generating summary..."
                    )
                    try:
                        synthesis_prompt = """
Please now generate the complete response based on all the information gathered from the tools.
Provide a comprehensive answer to the original request.
Synthesize the data and provide insights, analysis, and conclusions as appropriate.
                        """
                        current_response = await chat.send_message(
                            synthesis_prompt,
                            config=current_config
                        )
                        # Check if this worked
                        synthesis_text = self._safe_extract_text(current_response)
                        if synthesis_text:
                            self.logger.info("Successfully generated synthesis response")
                        else:
                            self.logger.warning("Synthesis attempt also returned empty response")
                    except Exception as e:
                        self.logger.error(f"Synthesis attempt failed: {e}")

                self.logger.info(
                    f"No function calls found - completed after {iteration-1} iterations"
                )
                break

            self.logger.info(
                f"Iteration {iteration}: Processing {len(function_calls)} function calls"
            )

            # Execute function calls
            tool_call_objects = []
            for fc in function_calls:
                tc = ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=fc.name,
                    arguments=dict(fc.args) if hasattr(fc.args, 'items') else fc.args
                )
                tool_call_objects.append(tc)

            # Execute tools
            start_time = time.time()
            tool_execution_tasks = [
                self._execute_tool(fc.name, dict(fc.args) if hasattr(fc.args, 'items') else fc.args)
                for fc in function_calls
            ]
            tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)
            execution_time = time.time() - start_time

            # Lazy Loading Check
            if lazy_loading:
                found_new = False
                for fc, result in zip(function_calls, tool_results):
                    if fc.name == "search_tools" and isinstance(result, str):
                        new_tools = self._check_new_tools(fc.name, result)
                        for nt in new_tools:
                            if nt not in active_tool_names:
                                active_tool_names.add(nt)
                                found_new = True

                if found_new:
                    # Rebuild tools with expanded set
                    new_tools_list = self._build_tools("custom_functions", filter_names=list(active_tool_names))
                    current_config.tools = new_tools_list
                    self.logger.info(f"Updated tools for next turn. Count: {len(active_tool_names)}")

            # Update tool call objects
            for tc, result in zip(tool_call_objects, tool_results):
                tc.execution_time = execution_time / len(tool_call_objects)
                if isinstance(result, Exception):
                    tc.error = str(result)
                    self.logger.error(f"Tool {tc.name} failed: {result}")
                else:
                    tc.result = result
                    # self.logger.info(f"Tool {tc.name} result: {result}")

            all_tool_calls.extend(tool_call_objects)
            function_response_parts = []
            for fc, result in zip(function_calls, tool_results):
                tool_id = fc.id or f"call_{uuid.uuid4().hex[:8]}"
                self.logger.notice(f"🔍 Tool: {fc.name}")
                self.logger.notice(f"📤 Raw Result Type: {type(result)}")

                try:
                    # Debug log first 20 cahrs of result
                    result_preview = str(result)[:20]
                    self.logger.notice(f"Tool {fc.name} output preview: {result_preview}...")

                    response_content = self._process_tool_result_for_api(result)
                    # self.logger.info(
                    #     f"📦 Processed for API: {response_content}"
                    # )

                    function_response_parts.append(
                        Part(
                            function_response=types.FunctionResponse(
                                id=tool_id,
                                name=fc.name,
                                response=response_content
                            )
                        )
                    )

                except Exception as e:
                    self.logger.error(f"Error processing result for tool {fc.name}: {e}")
                    function_response_parts.append(
                        Part(
                            function_response=types.FunctionResponse(
                                id=tool_id,
                                name=fc.name,
                                response={"result": f"Tool error: {str(e)}", "error": True}
                            )
                        )
                    )

            summary_part = self._create_tool_summary_part(
                function_calls,
                tool_results,
                original_prompt
            )
            # Combine the tool results with the textual summary prompt
            next_prompt_parts = function_response_parts.copy()
            if summary_part:
                next_prompt_parts.append(summary_part)

            # Send responses back
            retry_count = 0
            try:
                self.logger.debug(
                    f"Sending {len(next_prompt_parts)} responses back to model"
                )
                while retry_count < max_retries:
                    try:
                        current_response = await chat.send_message(
                            next_prompt_parts,
                            config=current_config
                        )
                        finish_reason = getattr(current_response.candidates[0], 'finish_reason', None)
                        if finish_reason:
                            if finish_reason.name == "MAX_TOKENS" and current_config.max_output_tokens < 8192:
                                self.logger.warning(
                                    f"Hit MAX_TOKENS limit. Retrying with increased token limit."
                                )
                                retry_count += 1
                                current_config.max_output_tokens = 8192
                                continue
                            elif finish_reason.name == "MALFORMED_FUNCTION_CALL":
                                self.logger.warning(
                                    f"Malformed function call detected. Retrying..."
                                )
                                retry_count += 1
                                await asyncio.sleep(2 ** retry_count)
                                continue
                        break
                    except Exception as e:
                        error_str = str(e)
                        retry_count += 1
                        # Parse retryDelay from 429 RESOURCE_EXHAUSTED
                        delay = 2 ** retry_count
                        if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str:
                            import re as _re
                            m = _re.search(r'retryDelay.*?(\d+)s', error_str)
                            if m:
                                delay = int(m.group(1)) + 1
                            self.logger.warning(
                                f"Rate limited (429). Waiting {delay}s before retry {retry_count}/{max_retries}"
                            )
                        else:
                            self.logger.error(f"Error sending message: {e}")
                        await asyncio.sleep(delay)
                        if (retry_count + 1) >= max_retries:
                            self.logger.error("Max retries reached, aborting")
                            raise e

                # Check for UNEXPECTED_TOOL_CALL error
                if (hasattr(current_response, 'candidates') and
                    current_response.candidates and
                    hasattr(current_response.candidates[0], 'finish_reason')):

                    finish_reason = current_response.candidates[0].finish_reason

                    if str(finish_reason) == 'FinishReason.UNEXPECTED_TOOL_CALL':
                        self.logger.warning("Received UNEXPECTED_TOOL_CALL")

                # Debug what we got back
                try:
                    # Use _safe_extract_text to avoid triggering warnings on function calls
                    preview_text = self._safe_extract_text(current_response)
                    preview = preview_text[:100] if preview_text else "No text (or Function Call)"
                    self.logger.debug(f"Response preview: {preview}")
                except Exception as e:
                    self.logger.debug(f"Could not preview response text: {e}")

            except Exception as e:
                self.logger.error(f"Failed to send responses back: {e}")
                break

        self.logger.info(f"Completed with {len(all_tool_calls)} total tool calls")
        return current_response

    def _parse_tool_code_blocks(self, text: str) -> List:
        """Convert tool_code blocks to function call objects."""
        function_calls = []

        if '```tool_code' not in text:
            return function_calls

        # Simple regex to extract tool calls
        pattern = r'```tool_code\s*\n\s*print\(default_api\.(\w+)\((.*?)\)\)\s*\n\s*```'
        matches = re.findall(pattern, text, re.DOTALL)

        for tool_name, args_str in matches:
            self.logger.debug(f"Converting tool_code to function call: {tool_name}")
            try:
                # Parse arguments like: a = 9310, b = 3, operation = "divide"
                args = {}
                for arg_part in args_str.split(','):
                    if '=' in arg_part:
                        key, value = arg_part.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"\'')  # Remove quotes

                        # Try to convert to number
                        try:
                            if '.' in value:
                                args[key] = float(value)
                            else:
                                args[key] = int(value)
                        except ValueError:
                            args[key] = value  # Keep as string
                # extract tool from Tool Manager
                tool = self.tool_manager.get_tool(tool_name)
                if tool:
                    # Create function call
                    fc = types.FunctionCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=tool_name,
                        args=args
                    )
                    function_calls.append(fc)
                    self.logger.info(f"Created function call: {tool_name}({args})")

            except Exception as e:
                self.logger.error(f"Failed to parse tool_code: {e}")

        return function_calls

    def _get_function_calls_from_response(self, response) -> List:
        """Get function calls from response - handles both proper calls and tool_code blocks."""
        function_calls = []

        try:
            if (response.candidates and
                response.candidates[0].content and
                response.candidates[0].content.parts):

                for part in response.candidates[0].content.parts:
                    # Check for proper function calls first
                    if hasattr(part, 'function_call') and part.function_call:
                        function_calls.append(part.function_call)
                        self.logger.debug(
                            f"Found proper function call: {part.function_call.name}"
                        )

                    # Handle reasoning content types (ignore for function calling)
                    elif hasattr(part, 'thought_signature') or hasattr(part, 'thought'):
                        self.logger.debug("Skipping reasoning/thought part during function extraction")

                    # Check for tool_code in text parts
                    elif hasattr(part, 'text') and part.text and '```tool_code' in part.text:
                        self.logger.info("Found tool_code block - converting to function call")
                        code_function_calls = self._parse_tool_code_blocks(part.text)
                        function_calls.extend(code_function_calls)
            else:
                self.logger.warning("Response has no candidates or content parts")

        except Exception as e:
            self.logger.error(f"Error getting function calls: {e}")

        self.logger.info(f"Total function calls found: {len(function_calls)}")
        return function_calls

    def _safe_extract_text(self, response) -> str:
        """
        Enhanced text extraction that handles reasoning models and mixed content warnings.

        This method tries multiple approaches to extract text from Google GenAI responses,
        handling special cases like thought_signature parts from reasoning models.
        """

        # Pre-check for function calls to avoid library warnings when accessing .text
        has_function_call = False
        try:
            if (hasattr(response, 'candidates') and response.candidates and
                len(response.candidates) > 0 and hasattr(response.candidates[0], 'content') and
                response.candidates[0].content and hasattr(response.candidates[0].content, 'parts') and
                response.candidates[0].content.parts):
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        has_function_call = True
                        break
        except Exception:
            pass

        # Method 1: Try response.text first (fastest path)
        # Skip if we found a function call, as accessing .text triggers a warning in the library
        if not has_function_call:
            try:
                if hasattr(response, 'text') and response.text:
                    if (text := response.text.strip()):
                        self.logger.debug(
                            f"Extracted text via response.text: '{text[:100]}...'"
                        )
                        return text
            except Exception as e:
                # This is expected with reasoning models that have mixed content
                self.logger.debug(
                    f"response.text failed (normal for reasoning models): {e}"
                )

        # Method 2: Manual extraction from parts (more robust)
        try:
            if (hasattr(response, 'candidates') and response.candidates and len(response.candidates) > 0 and
                hasattr(response.candidates[0], 'content') and response.candidates[0].content and
                hasattr(response.candidates[0].content, 'parts') and response.candidates[0].content.parts):

                text_parts = []
                thought_parts_found = 0

                # Extract text from each part, handling special cases
                for part in response.candidates[0].content.parts:
                    # Check for regular text content
                    if hasattr(part, 'text') and part.text:
                        if (clean_text := part.text.strip()):
                            text_parts.append(clean_text)
                            self.logger.debug(
                                f"Found text part: '{clean_text[:50]}...'"
                            )

                    # Skip thought_signature parts
                    if hasattr(part, 'thought_signature'):
                        self.logger.debug("Skipping thought_signature part")
                        continue

                    # Check for code execution result (contains output from executed code)
                    elif hasattr(part, 'code_execution_result') and part.code_execution_result:
                        result = part.code_execution_result
                        outcome = getattr(result, 'outcome', None)
                        output = getattr(result, 'output', None)
                        self.logger.debug(
                            f"Found code_execution_result: outcome={outcome}"
                        )
                        if output and isinstance(output, str) and output.strip():
                            text_parts.append(output.strip())
                            self.logger.debug(
                                f"Extracted code execution output: '{output[:50]}...'"
                            )

                    # Check for executable code (the code that was executed)
                    elif hasattr(part, 'executable_code') and part.executable_code:
                        exec_code = part.executable_code
                        code_text = getattr(exec_code, 'code', None)
                        language = getattr(exec_code, 'language', 'PYTHON')
                        self.logger.debug(
                            f"Found executable_code part: language={language}, code_len={len(code_text) if code_text else 0}"
                        )
                        # We don't add executable_code to text output by default,
                        # but log it for debugging purposes

                    # Log non-text parts but don't extract them
                    elif hasattr(part, 'thought_signature'):
                        thought_parts_found += 1
                        self.logger.debug(
                            "Found thought_signature part (reasoning model internal thought)"
                        )

                # Log reasoning model detection
                if thought_parts_found > 0:
                    self.logger.debug(
                        f"Detected reasoning model with {thought_parts_found} thought parts"
                    )

                # Combine text parts
                if text_parts:
                    if (combined_text := "".join(text_parts).strip()):
                        self.logger.debug(
                            f"Successfully extracted text from {len(text_parts)} parts"
                        )
                        return combined_text
                else:
                    self.logger.debug("No text parts found in response parts")

        except Exception as e:
            self.logger.error(f"Manual text extraction failed: {e}")

        # Method 3: Deep inspection for debugging (fallback)
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0] if len(response.candidates) > 0 else None
                if candidate:
                    if hasattr(candidate, 'finish_reason'):
                        finish_reason = str(candidate.finish_reason)
                        self.logger.debug(f"Response finish reason: {finish_reason}")
                        if 'MAX_TOKENS' in finish_reason:
                            self.logger.warning("Response truncated due to token limit")
                        elif 'SAFETY' in finish_reason:
                            self.logger.warning("Response blocked by safety filters")
                        elif 'STOP' in finish_reason:
                            self.logger.debug("Response completed normally but no text found")

                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts'):
                            parts_count = len(candidate.content.parts) if candidate.content.parts else 0
                            self.logger.debug(f"Response has {parts_count} parts but no extractable text")
                            if candidate.content.parts:
                                part_types = []
                                for part in candidate.content.parts:
                                    part_attrs = [attr for attr in dir(part)
                                                    if not attr.startswith('_') and hasattr(part, attr) and getattr(part, attr)]
                                    part_types.append(part_attrs)
                                self.logger.debug(f"Part attribute types found: {part_types}")

        except Exception as e:
            self.logger.error(f"Deep inspection failed: {e}")

        # Method 4: Final fallback - return empty string with clear logging
        self.logger.warning(
            "Could not extract any text from response using any method"
        )
        return ""

    def _extract_code_execution_content(
        self,
        response,
        output_directory: Optional[Union[str, Path]] = None
    ) -> Dict[str, Any]:
        """
        Extract code execution content from response including code, results, and images.

        This method handles responses from Google's code execution feature which can
        include executed Python code, execution results, and generated images (e.g., matplotlib charts).

        Args:
            response: The Google GenAI response object
            output_directory: Optional directory to save extracted images

        Returns:
            Dict containing:
                - 'code': List of executed code strings
                - 'output': Combined text output from code execution
                - 'images': List of PIL Image objects or saved file paths
                - 'has_content': Boolean indicating if any content was extracted
        """
        result = {
            'code': [],
            'output': [],
            'images': [],
            'has_content': False
        }

        try:
            if not (hasattr(response, 'candidates') and response.candidates and
                    len(response.candidates) > 0 and
                    hasattr(response.candidates[0], 'content') and
                    response.candidates[0].content and
                    hasattr(response.candidates[0].content, 'parts') and
                    response.candidates[0].content.parts):
                return result

            for part in response.candidates[0].content.parts:
                # Extract executable code
                if hasattr(part, 'executable_code') and part.executable_code:
                    exec_code = part.executable_code
                    code_text = getattr(exec_code, 'code', None)
                    if code_text:
                        result['code'].append(code_text)
                        result['has_content'] = True
                        self.logger.debug(
                            f"Extracted executable code: {len(code_text)} chars"
                        )

                # Extract code execution result
                elif hasattr(part, 'code_execution_result') and part.code_execution_result:
                    exec_result = part.code_execution_result
                    outcome = getattr(exec_result, 'outcome', None)
                    output_text = getattr(exec_result, 'output', None)

                    self.logger.debug(
                        f"Code execution result: outcome={outcome}"
                    )

                    if output_text and isinstance(output_text, str) and output_text.strip():
                        result['output'].append(output_text.strip())
                        result['has_content'] = True

                # Extract images from inline_data (matplotlib charts, generated images)
                elif hasattr(part, 'inline_data') and part.inline_data:
                    try:
                        inline_data = part.inline_data
                        mime_type = getattr(inline_data, 'mime_type', '')

                        # Check if it's an image
                        if mime_type and mime_type.startswith('image/'):
                            image_data = getattr(inline_data, 'data', None)
                            if image_data:
                                # Convert to PIL Image
                                image = Image.open(io.BytesIO(image_data))
                                self.logger.debug(
                                    f"Extracted image from inline_data: {mime_type}, size={image.size}"
                                )

                                # Save to file if output_directory is provided
                                if output_directory:
                                    output_dir = Path(output_directory)
                                    output_dir.mkdir(parents=True, exist_ok=True)
                                    # Generate unique filename
                                    ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
                                    filename = f"chart_{uuid.uuid4().hex[:8]}.{ext}"
                                    file_path = output_dir / filename
                                    image.save(file_path)
                                    result['images'].append(file_path)
                                    self.logger.debug(f"Saved image to: {file_path}")
                                else:
                                    result['images'].append(image)

                                result['has_content'] = True
                    except Exception as e:
                        self.logger.warning(f"Failed to extract image from inline_data: {e}")

                # Try as_image() method for parts that support it
                elif hasattr(part, 'as_image') and callable(getattr(part, 'as_image')):
                    try:
                        # Check if this part can be converted to an image
                        # The as_image() method is available on parts with image content
                        image = part.as_image()
                        if image:
                            self.logger.debug(
                                f"Extracted image via as_image(): size={image.size if hasattr(image, 'size') else 'unknown'}"
                            )

                            if output_directory:
                                output_dir = Path(output_directory)
                                output_dir.mkdir(parents=True, exist_ok=True)
                                filename = f"chart_{uuid.uuid4().hex[:8]}.png"
                                file_path = output_dir / filename
                                image.save(file_path)
                                result['images'].append(file_path)
                                self.logger.debug(f"Saved image to: {file_path}")
                            else:
                                result['images'].append(image)

                            result['has_content'] = True
                    except Exception as e:
                        # as_image() may fail if the part doesn't actually contain image data
                        self.logger.debug(f"as_image() not applicable for this part: {e}")

            # Log summary
            if result['has_content']:
                self.logger.info(
                    f"Extracted code execution content: "
                    f"{len(result['code'])} code blocks, "
                    f"{len(result['output'])} outputs, "
                    f"{len(result['images'])} images"
                )

        except Exception as e:
            self.logger.error(f"Error extracting code execution content: {e}")

        return result

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        use_thinking: Optional[bool] = None,
        stateless: bool = False,
        deep_research: bool = False,
        file_search_store_names: Optional[List[str]] = None,
        lazy_loading: bool = False,
        **kwargs
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.

        Args:
            prompt (str): The input prompt for the model.
            model (Union[str, GoogleModel]): The model to use. If None, uses the client's configured model
                or defaults to GEMINI_2_5_FLASH.
            max_tokens (int): Maximum number of tokens in the response.
            temperature (float): Sampling temperature for response generation.
            files (Optional[List[Union[str, Path]]]): Optional files to include in the request.
            system_prompt (Optional[str]): Optional system prompt to guide the model.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output configuration.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id: Optional session identifier for tracking.
            force_tool_usage (Optional[str]): Force usage of specific tools, if needed.
                ("custom_functions", "builtin_tools", or None)
            stateless (bool): If True, don't use conversation memory (stateless mode).
            deep_research (bool): If True, use Google's deep research agent.
            file_search_store_names (Optional[List[str]]): Names of file search stores for deep research.
        """
        max_retries = kwargs.pop('max_retries', 2)
        retry_on_fail = kwargs.pop('retry_on_fail', True)

        if not retry_on_fail:
            max_retries = 1

        # Route to deep research if requested
        if deep_research:
            self.logger.info("Using Google Deep Research mode via interactions.create()")
            return await self._deep_research_ask(
                prompt=prompt,
                file_search_store_names=file_search_store_names,
                user_id=user_id,
                session_id=session_id,
                files=files
            )

        model = model.value if isinstance(model, GoogleModel) else model
        # If use_tools is None, use the instance default
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        if not model:
            model = self.model or GoogleModel.GEMINI_2_5_FLASH.value

        # Handle case where model is passed as a tuple or list
        if isinstance(model, (list, tuple)):
            model = model[0]

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Prepare conversation context using unified memory system
        conversation_history = None
        messages = []

        # Use the abstract method to prepare conversation context
        if stateless:
            # For stateless mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            # Use the unified conversation context preparation from AbstractClient
            messages, conversation_history, system_prompt = await self._prepare_conversation_context(
                prompt, files, user_id, session_id, system_prompt, stateless=stateless
            )

        # Prepare conversation history for Google GenAI format
        history = []
        # Construct history directly from the 'messages' array, which should be in the correct format
        if messages:
            for msg in messages[:-1]:  # Exclude the current user message (last in list)
                role = msg['role'].lower()
                # Assuming content is already in the format [{"type": "text", "text": "..."}]
                # or other GenAI Part types if files were involved.
                # Here, we only expect text content for history, as images/files are for the current turn.
                if role == 'user':
                    # Content can be a list of dicts (for text/parts) or a single string.
                    # Standardize to list of Parts.
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                        # Add other part types if necessary for history (e.g., function responses)
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        default_tokens = max_tokens or self.max_tokens or 16000
        generation_config = {
            "max_output_tokens": default_tokens,
            "temperature": temperature or self.temperature
        }
        base_temperature = generation_config["temperature"]

        # Prepare structured output configuration
        output_config = self._get_structured_config(structured_output)

        # Tool selection
        requested_tools = tools

        if _use_tools:
            if requested_tools and isinstance(requested_tools, list):
                for tool in requested_tools:
                    self.register_tool(tool)
            tool_type = "custom_functions"
            # if Tools, reduce temperature to avoid hallucinations.
            generation_config["temperature"] = 0
        elif _use_tools is None:
            # If not explicitly set, analyze the prompt to decide
            tool_type = self._analyze_prompt_for_tools(prompt)
        else:
            tool_type = 'builtin_tools' if _use_tools else None

        tools = self._build_tools(tool_type) if tool_type else []

        # Debug: List tool names
        if tools:
            tool_names = []
            for tool in tools:
                if hasattr(tool, 'function_declarations'):
                    tool_names.extend([fd.name for fd in tool.function_declarations])
            print(f'TOOLS ({len(tool_names)}): {tool_names}')
            print(f'request_form in tools: {"request_form" in tool_names}')

        if _use_tools and tool_type == "custom_functions" and not tools:
            self.logger.info(
                "Tool usage requested but no tools are registered - disabling tools for this request."
            )
            _use_tools = False
            tool_type = None
            tools = []
            generation_config["temperature"] = base_temperature

        use_tools = _use_tools

        # LAZY LOADING LOGIC
        active_tool_names = set()
        if use_tools and lazy_loading:
            # Override initial tool selection to just search_tools
            active_tool_names.add("search_tools")
            tools = self._build_tools("custom_functions", filter_names=["search_tools"])
            # Add system prompt instruction
            search_prompt = "You have access to a library of tools. Use the 'search_tools' function to find relevant tools."
            system_prompt = f"{system_prompt}\n\n{search_prompt}" if system_prompt else search_prompt
            # Update final_config later with this new system prompt if needed,
            # but system_prompt is passed to GenerateContentConfig below.


        self.logger.debug(
            f"Using model: {model}, max_tokens: {default_tokens}, temperature: {temperature}, "
            f"structured_output: {structured_output}, "
            f"use_tools: {_use_tools}, tool_type: {tool_type}, toolbox: {len(tools)}, "
        )

        use_structured_output = bool(output_config)
        # Google limitation: Cannot combine tools with structured output
        # Strategy: If both are requested, use tools first, then apply structured output to final result
        if _use_tools and use_structured_output:
            self.logger.info(
                "Google Gemini doesn't support tools + structured output simultaneously. "
                "Using tools first, then applying structured output to the final result."
            )
            structured_output_for_later = output_config
            # Don't set structured output in initial config
            output_config = None
        else:
            structured_output_for_later = None
            # Set structured output in generation config if no tools conflict
            if output_config:
                self._apply_structured_output_schema(generation_config, output_config)

        # Track tool calls for the response
        all_tool_calls = []
        # Build contents for conversation
        contents = []

        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            if role in ["user", "model"]:
                text_parts = [part["text"] for part in msg["content"] if "text" in part]
                if text_parts:
                    contents.append({
                        "role": role,
                        "parts": [{"text": " ".join(text_parts)}]
                    })

        # Add the current prompt
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        chat = None
        if not self.client:
            self.client = await self.get_client()
        # configure thinking config for gemini:
        thinking_config = None
        if use_thinking:
            thinking_config = ThinkingConfig(
                max_thinking_steps=1,
                max_thinking_tokens=100,
                max_thinking_time=10,
            )
        elif 'flash' in model.lower():
            # Flash puede deshabilitarse con budget=0
            thinking_config = ThinkingConfig(
                thinking_budget=0,
                include_thoughts=False
            )
        else:
            thinking_config = ThinkingConfig(
                thinking_budget=1024,  # Reasonable minimum for complex tasks
                include_thoughts=False  # Critical: no thoughts in response
            )
        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
            tools=tools,
            thinking_config=thinking_config,
            **generation_config
        )
        if stateless:
            # For stateless mode, handle in a single call (existing behavior)
            contents = []

            for msg in messages:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                if role in ["user", "model"]:
                    text_parts = [part["text"] for part in msg["content"] if "text" in part]
                    if text_parts:
                        contents.append({
                            "role": role,
                            "parts": [{"text": " ".join(text_parts)}]
                        })
            try:
                retry_count = 0
                while retry_count < max_retries:
                    response = await self.client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                        config=final_config
                    )
                    finish_reason = getattr(response.candidates[0], 'finish_reason', None)
                    if finish_reason:
                        if finish_reason.name == "MAX_TOKENS" and generation_config["max_output_tokens"] == 1024:
                            retry_count += 1
                            self.logger.warning(
                                f"Hit MAX_TOKENS limit on stateless response. Retrying {retry_count}/{max_retries} with increased token limit."
                            )
                            final_config.max_output_tokens = 8192
                            continue
                        elif finish_reason.name == "MALFORMED_FUNCTION_CALL":
                            self.logger.warning(
                                f"Malformed function call detected (stateless). Retrying {retry_count + 1}/{max_retries}..."
                            )
                            retry_count += 1
                            await asyncio.sleep(2 ** retry_count)
                            continue
                    break
            except Exception as e:
                self.logger.error(
                    f"Error during generate_content: {e}"
                )
                if (retry_count + 1) >= max_retries:
                    raise e
                retry_count += 1

            # Handle function calls in stateless mode
            final_response = await self._handle_stateless_function_calls(
                response,
                model,
                contents,
                final_config,
                all_tool_calls,
                original_prompt=prompt
            )
        else:
            # MULTI-TURN CONVERSATION MODE
            chat = self.client.aio.chats.create(
                model=model,
                history=history
            )
            retry_count = 0
            # Send initial message
            while retry_count < max_retries:
                try:
                    response = await chat.send_message(
                        message=prompt,
                        config=final_config
                    )
                    finish_reason = getattr(response.candidates[0], 'finish_reason', None)
                    if finish_reason:
                        if finish_reason.name == "MAX_TOKENS" and generation_config["max_output_tokens"] <= 1024:
                            retry_count += 1
                            self.logger.warning(
                                f"Hit MAX_TOKENS limit on initial response. Retrying {retry_count}/{max_retries} with increased token limit."
                            )
                            final_config.max_output_tokens = 8192
                            continue
                        elif finish_reason.name == "MALFORMED_FUNCTION_CALL":
                            self.logger.warning(
                                f"Malformed function call detected (stateful). Retrying {retry_count + 1}/{max_retries}..."
                            )
                            # Exponential backoff
                            await asyncio.sleep(2 ** retry_count)

                            # On the last retry, try forcing simpler tool use or dropping tools?
                            # For now, just continue, but maybe we can clear history if it fails repeatedly?
                            # No, standard retry is best for now.
                            retry_count += 1
                            continue
                    break
                except Exception as e:
                    # Handle specific network client error (socket/aiohttp issue)
                    if "'NoneType' object has no attribute 'getaddrinfo'" in str(e):
                        self.logger.warning(
                            f"Encountered network client error: {e}. Resetting client and retrying."
                        )
                        # Reset the client
                        self.client = None
                        if not self.client:
                            self.client = await self.get_client()
                        # Recreate the chat session
                        chat = self.client.aio.chats.create(
                            model=model,
                            history=history
                        )
                        retry_count += 1
                        continue

                    self.logger.error(
                        f"Error during initial chat.send_message: {e}"
                    )
                    if (retry_count + 1) >= max_retries:
                        raise e
                    retry_count += 1

            has_function_calls = False
            if response and getattr(response, "candidates", None):
                candidate = response.candidates[0] if response.candidates else None
                content = getattr(candidate, "content", None) if candidate else None
                parts = getattr(content, "parts", None) if content else None
                has_function_calls = bool(parts)

            self.logger.debug(
                f"Initial response has function calls: {has_function_calls}"
            )

            # Multi-turn function calling loop
            final_response = await self._handle_multiturn_function_calls(
                chat,
                response,
                all_tool_calls,
                original_prompt=original_prompt,
                model=model,
                max_iterations=10,
                config=final_config,
                max_retries=max_retries,
                lazy_loading=lazy_loading,
                active_tool_names=active_tool_names
            )

        # Extract assistant response text for conversation memory
        assistant_response_text = self._safe_extract_text(final_response)

        # Extract code execution content (code, results, images) from the response
        code_execution_content = self._extract_code_execution_content(final_response)

        # If code execution produced output but we don't have text, use the code execution output
        if not assistant_response_text and code_execution_content['output']:
            assistant_response_text = "\n".join(code_execution_content['output'])
            self.logger.info(
                f"Using code execution output as response text: {len(assistant_response_text)} chars"
            )

        # If we still don't have text but have tool calls, generate a summary
        if not assistant_response_text and all_tool_calls:
            assistant_response_text = self._create_simple_summary(
                all_tool_calls
            )

        # Handle structured output
        final_output = None
        if structured_output_for_later and use_tools and assistant_response_text:
            try:
                # Create a new generation config for structured output only
                structured_config = {
                    "max_output_tokens": max_tokens or self.max_tokens,
                    "temperature": temperature or self.temperature,
                    "response_mime_type": "application/json"
                }

                # OPTIMIZATION: Try to parse immediately to avoid 2nd LLM call
                # If the model already returned valid valid JSON, we can skip the slow reformatting call
                try:
                    self.logger.debug("Attempting fast-path check for structured output...")

                    # Check if text looks like JSON before trying to parse (avoids warnings)
                    text_to_check = assistant_response_text.strip()
                    is_json_candidate = (
                        text_to_check.startswith('{') or
                        text_to_check.startswith('[') or
                        '```json' in text_to_check
                    )

                    if is_json_candidate:
                        # We accept the result if it is NOT just the original string (which implies parsing failure return)
                        fast_parsed = await self._parse_structured_output(
                            assistant_response_text,
                            structured_output_for_later
                        )

                        # _parse_structured_output returns the original text if it fails
                        # So if we get something that isn't the original text, we succeeded
                        if fast_parsed != assistant_response_text:
                            self.logger.info("Fast-path structured parsing successful. Skipping reformatting step.")
                            final_output = fast_parsed
                    else:
                        self.logger.debug("Response does not look like JSON, skipping fast-path parsing.")
                except Exception as e:
                    self.logger.debug(f"Fast-path parsing failed: {e}")

                if final_output is None:
                    # Set the schema based on the type of structured output
                    schema_config = (
                        structured_output_for_later
                        if isinstance(structured_output_for_later, StructuredOutputConfig)
                        else self._get_structured_config(structured_output_for_later)
                    )
                    if schema_config:
                        self._apply_structured_output_schema(structured_config, schema_config)
                    # Create a new client call without tools for structured output
                    format_prompt = (
                        f"Please format the following information according to the requested JSON structure. "
                        f"Return only the JSON object with the requested fields:\n\n{assistant_response_text}"
                    )
                    structured_response = await self.client.aio.models.generate_content(
                        model=model,
                        contents=[{"role": "user", "parts": [{"text": format_prompt}]}],
                        config=GenerateContentConfig(**structured_config)
                    )
                    # Extract structured text
                    if structured_text := self._safe_extract_text(structured_response):
                        # Parse the structured output
                        if isinstance(structured_output_for_later, StructuredOutputConfig):
                            final_output = await self._parse_structured_output(
                                structured_text,
                                structured_output_for_later
                            )
                        elif isinstance(structured_output_for_later, type):
                            if hasattr(structured_output_for_later, 'model_validate_json'):
                                final_output = structured_output_for_later.model_validate_json(structured_text)
                            elif hasattr(structured_output_for_later, 'model_validate'):
                                parsed_json = self._json.loads(structured_text)
                                final_output = structured_output_for_later.model_validate(parsed_json)
                        else:
                            final_output = self._json.loads(structured_text)
                    else:
                        self.logger.warning(
                            "No structured text received, falling back to original response"
                        )
                        final_output = assistant_response_text
            except Exception as e:
                self.logger.error(f"Error parsing structured output: {e}")
                # Fallback to original text if structured output fails
                final_output = assistant_response_text
        elif output_config and not use_tools:
            try:
                final_output = await self._parse_structured_output(
                    assistant_response_text,
                    output_config
                )
            except Exception:
                final_output = assistant_response_text
        else:
            final_output = assistant_response_text

        # Update conversation memory with the final response
        final_assistant_message = {
            "role": "model",
            "content": [
                {
                    "type": "text",
                    "text": str(final_output) if final_output != assistant_response_text else assistant_response_text
                }
            ]
        }

        # Update conversation memory with unified system
        if not stateless and conversation_history:
            tools_used = [tc.name for tc in all_tool_calls]
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [final_assistant_message],
                system_prompt,
                turn_id,
                original_prompt,
                assistant_response_text,
                tools_used
            )
        # Prepare code execution content for AIMessage
        extracted_images = code_execution_content.get('images', []) if code_execution_content else []
        extracted_code = (
            "\n\n".join(code_execution_content['code'])
            if code_execution_content and code_execution_content.get('code')
            else None
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output,
            tool_calls=all_tool_calls,
            conversation_history=conversation_history,
            text_response=assistant_response_text,
            files=extracted_images,
            images=extracted_images,
            code=extracted_code
        )

        # Override provider to distinguish from Vertex AI
        ai_message.provider = "google_genai"

        return ai_message

    def _create_simple_summary(self, all_tool_calls: List[ToolCall]) -> str:
        """Create a simple summary from tool calls."""
        if not all_tool_calls:
            return "Task completed."

        if len(all_tool_calls) == 1:
            tc = all_tool_calls[0]
            if isinstance(tc.result, Exception):
                return f"Tool {tc.name} failed with error: {tc.result}"
            elif isinstance(tc.result, pd.DataFrame):
                if not tc.result.empty:
                    return f"Tool {tc.name} returned a DataFrame with {len(tc.result)} rows."
                else:
                    return f"Tool {tc.name} returned an empty DataFrame."
            elif tc.result and isinstance(tc.result, dict) and 'expression' in tc.result:
                return tc.result['expression']
            elif tc.result and isinstance(tc.result, dict) and 'result' in tc.result:
                return f"Result: {tc.result['result']}"
        if len(all_tool_calls) >= 1:
            # Multiple calls - show the final result
            final_tc = all_tool_calls[-1]
            if isinstance(final_tc.result, pd.DataFrame):
                if not final_tc.result.empty:
                    return f"Data: {final_tc.result.to_string()}"
                else:
                    return f"Final tool {final_tc.name} returned an empty DataFrame."
            if final_tc.result and isinstance(final_tc.result, dict):
                if 'result' in final_tc.result:
                    return f"Final result: {final_tc.result['result']}"
                elif 'expression' in final_tc.result:
                    return final_tc.result['expression']
            # Return string representation of result if available
            elif final_tc.result:
                return str(final_tc.result)[:2000]

        # Last resort: show what tools were called
        tool_names = [tc.name for tc in all_tool_calls]
        return f"Completed {len(all_tool_calls)} tool calls: {', '.join(tool_names)}"

    def _build_function_declarations(self) -> List[types.FunctionDeclaration]:
        """Build function declarations for Google GenAI tools."""
        function_declarations = []

        for tool in self.tool_manager.all_tools():
            tool_name = tool.name

            if isinstance(tool, AbstractTool):
                full_schema = tool.get_tool_schema()
                tool_description = full_schema.get("description", tool.description)
                schema = full_schema.get("parameters", {}).copy()
                schema = self.clean_google_schema(schema)
            elif isinstance(tool, ToolDefinition):
                tool_description = tool.description
                schema = self.clean_google_schema(tool.input_schema.copy())
            else:
                tool_description = getattr(tool, 'description', f"Tool: {tool_name}")
                schema = getattr(tool, 'input_schema', {})
                schema = self.clean_google_schema(schema)

            if not schema:
                schema = {"type": "object", "properties": {}, "required": []}

            try:
                declaration = types.FunctionDeclaration(
                    name=tool_name,
                    description=tool_description,
                    parameters=self._fix_tool_schema(schema)
                )
                function_declarations.append(declaration)
            except Exception as e:
                self.logger.error(f"Error creating {tool_name}: {e}")
                continue

        return function_declarations

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",  # "retry", "notify", "ignore"
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
    ) -> AsyncIterator[str]:
        """
        Stream Google Generative AI's response using AsyncIterator with support for Tool Calling.

        Args:
            on_max_tokens: How to handle MAX_TOKENS finish reason:
                - "retry": Automatically retry with increased token limit
                - "notify": Yield a notification message and continue
                - "ignore": Silently continue (original behavior)
            deep_research: If True, use Google's deep research agent (stream mode)
            agent_config: Optional configuration for deep research (e.g., thinking_summaries)
        """
        model = (
            model.value if isinstance(model, GoogleModel) else model
        ) or (self.model or GoogleModel.GEMINI_2_5_FLASH.value)

        # Handle case where model is passed as a tuple or list
        if isinstance(model, (list, tuple)):
            model = model[0]

        # Stub for deep research streaming
        if deep_research:
            self.logger.warning(
                "Google Deep Research streaming is not yet fully implemented. "
                "Falling back to standard ask_stream() behavior."
            )
            # TODO: Implement interactions.create(stream=True) when SDK supports it
            # For now, just use regular streaming

        turn_id = str(uuid.uuid4())
        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        # Use the unified conversation context preparation from AbstractClient
        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Prepare conversation history for Google GenAI format
        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude the current user message (last in list)
                role = msg['role'].lower()
                if role == 'user':
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        # --- Tool Configuration (Mirrored from ask method) ---
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        # Register requested tools if any
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        # Determine tool strategy
        if _use_tools:
            # If explicit tools passed or just enabled, force low temp
            temperature = 0 if temperature is None else temperature
            tool_type = "custom_functions"
        elif _use_tools is None:
            # Analyze prompt
            tool_type = self._analyze_prompt_for_tools(prompt)
        else:
            tool_type = 'builtin_tools' if _use_tools else None

        # Build the actual tool objects for Gemini
        gemini_tools = self._build_tools(tool_type) if tool_type else []

        if _use_tools and tool_type == "custom_functions" and not gemini_tools:
            # Fallback if no tools registered
            gemini_tools = None

        # --- Execution Loop ---

        # Retry loop variables
        current_max_tokens = max_tokens or self.max_tokens
        retry_count = 0

        # Variables for multi-turn tool loop
        current_message_content = prompt # Start with the user prompt
        keep_looping = True

        # Start the chat session once
        chat = self.client.aio.chats.create(
            model=model,
            history=history,
            config=GenerateContentConfig(
                system_instruction=system_prompt,
                tools=gemini_tools,
                temperature=temperature or self.temperature,
                max_output_tokens=current_max_tokens
            )
        )

        all_assistant_text = [] # Keep track of full text for memory update

        while keep_looping and retry_count <= retry_config.max_retries:
            # By default, we stop after one turn unless a tool is called
            keep_looping = False

            try:
                # If we are retrying due to max tokens, update config
                chat._config.max_output_tokens = current_max_tokens

                assistant_content_chunk = ""
                max_tokens_reached = False

                # We need to capture function calls from the chunks as they arrive
                collected_function_calls = []

                async for chunk in await chat.send_message_stream(current_message_content):
                    # Check for MAX_TOKENS finish reason
                    if (hasattr(chunk, 'candidates') and chunk.candidates and len(chunk.candidates) > 0):
                        candidate = chunk.candidates[0]
                        if (hasattr(candidate, 'finish_reason') and
                            str(candidate.finish_reason) == 'FinishReason.MAX_TOKENS'):
                            max_tokens_reached = True

                            if on_max_tokens == "notify":
                                yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens).**\n"
                            elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                                # Break inner loop to handle retry in outer loop
                                break

                    # Capture function calls from the chunk
                    if (hasattr(chunk, 'candidates') and chunk.candidates):
                         for candidate in chunk.candidates:
                            if hasattr(candidate, 'content') and candidate.content and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'function_call') and part.function_call:
                                        collected_function_calls.append(part.function_call)

                    # Yield text content if present
                    if chunk.text:
                        assistant_content_chunk += chunk.text
                        all_assistant_text.append(chunk.text)
                        yield chunk.text

                # --- Handle Max Tokens Retry ---
                if max_tokens_reached and on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                    if retry_count < retry_config.max_retries:
                        new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)
                        yield f"\n\n🔄 **Retrying with increased limit ({new_max_tokens})...**\n\n"
                        current_max_tokens = new_max_tokens
                        retry_count += 1
                        await self._wait_with_backoff(retry_count, retry_config)
                        keep_looping = True # Force loop to continue
                        continue
                    else:
                        yield f"\n\n❌ **Maximum retries reached.**\n"

                # --- Handle Function Calls ---
                if collected_function_calls:
                    # We have tool calls to execute!
                    self.logger.info(f"Streaming detected {len(collected_function_calls)} tool calls.")

                    # Execute tools (parallel)
                    tool_execution_tasks = [
                        self._execute_tool(fc.name, dict(fc.args))
                        for fc in collected_function_calls
                    ]
                    tool_results = await asyncio.gather(*tool_execution_tasks, return_exceptions=True)

                    # Build the response parts containing tool outputs
                    function_response_parts = []
                    for fc, result in zip(collected_function_calls, tool_results):
                        response_content = self._process_tool_result_for_api(result)
                        function_response_parts.append(
                            Part(
                                function_response=types.FunctionResponse(
                                    name=fc.name,
                                    response=response_content
                                )
                            )
                        )

                    # Set the next message to be these tool outputs
                    current_message_content = function_response_parts

                    # Force the loop to run again to stream the answer based on these tools
                    keep_looping = True

            except Exception as e:
                # Handle specific network client error
                if "'NoneType' object has no attribute 'getaddrinfo'" in str(e):
                    if retry_count < retry_config.max_retries:
                        self.logger.warning(
                            f"Encountered network client error during stream: {e}. Resetting client..."
                        )
                        self.client = None
                        if not self.client:
                            self.client = await self.get_client()

                        # Recreate chat session
                        # Note: We rely on history variable being the initial history.
                        # Intermediate turn state might be lost if this happens mid-conversation,
                        # but this error usually happens at connection start.
                        chat = self.client.aio.chats.create(
                            model=model,
                            history=history,
                            config=GenerateContentConfig(
                                system_instruction=system_prompt,
                                tools=gemini_tools,
                                temperature=temperature or self.temperature,
                                max_output_tokens=current_max_tokens
                            )
                        )
                        retry_count += 1
                        await self._wait_with_backoff(retry_count, retry_config)
                        keep_looping = True
                        continue

                if retry_count < retry_config.max_retries:
                    error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                    yield error_msg
                    retry_count += 1
                    await self._wait_with_backoff(retry_count, retry_config)
                    keep_looping = True
                    continue
                else:
                    yield f"\n\n❌ **Streaming failed: {str(e)}**\n"
                    break

        # Update conversation memory
        final_text = "".join(all_assistant_text)
        if final_text:
            final_assistant_message = {
                "role": "assistant", "content": [
                    {"type": "text", "text": final_text}
                ]
            }
            # Extract assistant response text for conversation memory
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_history,
                messages + [final_assistant_message],
                system_prompt,
                turn_id,
                prompt,
                final_text,
                [] # We don't easily track tool usage in stream return yet, or we could track in loop
            )

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # Google GenAI doesn't have a native batch API, so we process sequentially
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes],
        reference_images: Optional[Union[List[Path], List[bytes]]] = None,
        model: Union[str, GoogleModel] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        no_memory: bool = False,
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI using a stateful chat session.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        if not model:
            model = self.model or GoogleModel.GEMINI_2_5_FLASH.value
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        if no_memory:
            # For no_memory mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_session = None
        else:
            messages, conversation_session, _ = await self._prepare_conversation_context(
                prompt, None, user_id, session_id, None
            )

        # Prepare conversation history for Google GenAI format
        history = []
        if messages:
            for msg in messages[:-1]: # Exclude the current user message (last in list)
                role = msg['role'].lower()
                if role == 'user':
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(UserContent(parts=parts))
                elif role in ['assistant', 'model']:
                    parts = []
                    for part_content in msg.get('content', []):
                        if isinstance(part_content, dict) and part_content.get('type') == 'text':
                            parts.append(Part(text=part_content.get('text', '')))
                    if parts:
                        history.append(ModelContent(parts=parts))

        # --- Multi-Modal Content Preparation ---
        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(
                    f"Image file not found: {image}"
                )
            # Load the primary image
            primary_image = Image.open(image)
        elif isinstance(image, bytes):
            primary_image = Image.open(io.BytesIO(image))
        elif isinstance(image, Image.Image):
            primary_image = image
        else:
            raise ValueError(
                "Image must be a Path, bytes, or PIL.Image object."
            )

        # The content for the API call is a list containing images and the final prompt
        contents = [primary_image]
        if reference_images:
            for ref_path in reference_images:
                self.logger.debug(
                    f"Loading reference image from: {ref_path}"
                )
                if isinstance(ref_path, Path):
                    if not ref_path.exists():
                        raise FileNotFoundError(
                            f"Reference image file not found: {ref_path}"
                        )
                    contents.append(Image.open(ref_path))
                elif isinstance(ref_path, bytes):
                    contents.append(Image.open(io.BytesIO(ref_path)))
                elif isinstance(ref_path, Image.Image):
                    # is already a PIL.Image Object
                    contents.append(ref_path)
                else:
                    raise ValueError(
                        "Reference Image must be a Path, bytes, or PIL.Image object."
                    )

        contents.append(prompt) # The text prompt always comes last
        generation_config = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
        }
        output_config = self._get_structured_config(structured_output)
        structured_output_config = output_config
        # Vision models generally don't support tools, so we focus on structured output
        if structured_output_config:
            self.logger.debug("Structured output requested for vision task.")
            self._apply_structured_output_schema(generation_config, structured_output_config)
        elif count_objects:
            # Default to JSON for structured output if not specified
            structured_output_config = StructuredOutputConfig(output_type=ObjectDetectionResult)
            self._apply_structured_output_schema(generation_config, structured_output_config)

        # Create the stateful chat session
        chat = self.client.aio.chats.create(model=model, history=history)
        # Disable thinking for image tasks as recommended by Google (reduces latency)
        final_config = GenerateContentConfig(
            **generation_config,
            thinking_config=ThinkingConfig(thinking_budget=0)
        )

        # Make the primary multi-modal call
        self.logger.debug(f"Sending {len(contents)} parts to the model.")
        response = await chat.send_message(
            message=contents,
            config=final_config
        )

        # --- Response Handling ---
        final_output = None
        if structured_output_config:
            try:
                final_output = await self._parse_structured_output(
                    response.text,
                    structured_output_config
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to parse structured output from vision model: {e}"
                )
                final_output = response.text
        elif '```json' in response.text:
            # Attempt to extract JSON from markdown code block
            try:
                final_output = self._parse_json_from_text(response.text)
            except Exception as e:
                self.logger.error(
                    f"Failed to parse JSON from markdown in vision model response: {e}"
                )
                final_output = response.text
        else:
            final_output = response.text

        final_assistant_message = {
            "role": "model", "content": [
                {"type": "text", "text": final_output}
            ]
        }
        if no_memory is False:
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages + [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"[Image Analysis]: {prompt}"}
                        ]
                    },
                    final_assistant_message
                ],
                None,
                turn_id,
                original_prompt,
                response.text,
                []
            )
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"
        return ai_message

    async def _deep_research_ask(
        self,
        prompt: str,
        file_search_store_names: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[str]] = None
    ) -> AIMessage:
        """
        Perform deep research using Google's interactions.create() API.
        """
        model = "deep-research-pro-preview-12-2025"

        agent_config = {
            "type": "deep-research",
            "thinking_summaries": "auto"
        }

        tools = []
        if file_search_store_names:
            tools.append({
                "type": "file_search",
                "file_search_store_names": file_search_store_names
            })

        try:
            self.logger.info(f"Starting Deep Research Interaction: {prompt}")

            # Check if interactions API is supported
            if not hasattr(self.client, 'interactions'):
                raise NotImplementedError(
                    "The installed google-genai SDK does not support 'interactions' API. "
                    "Deep Research feature is unavailable."
                )

            # Create interaction stream
            stream = self.client.interactions.create(
                input=prompt,
                agent=model,
                background=True,
                stream=True,
                tools=tools,
                agent_config=agent_config
            )

            interaction_id = None
            last_event_id = None
            full_text = ""
            thought_process = []

            # Iterate through the stream (synchronous iterator in current SDK)
            # We wrap it in to_thread if it blocks, but let's assume standard iteration for now
            # loops over the stream
            for chunk in stream:
                if hasattr(chunk, 'event_type'):
                    if chunk.event_type == "interaction.start":
                        interaction_id = chunk.interaction.id
                        self.logger.info(f"Interaction started: {interaction_id}")

                    if chunk.event_id:
                        last_event_id = chunk.event_id

                    if chunk.event_type == "content.delta":
                        if chunk.delta.type == "text":
                            print(chunk.delta.text, end="", flush=True) # Keep console output for debugging
                            full_text += chunk.delta.text
                        elif chunk.delta.type == "thought_summary":
                            thought = chunk.delta.content.text
                            print(f"Thought: {thought}", flush=True)
                            thought_process.append(thought)

                    elif chunk.event_type == "interaction.complete":
                        self.logger.info("Research Complete")

            # Construct response
            response = AIMessage(
                input=prompt,
                output=full_text,
                response=full_text,
                is_structured=False,
                model=model,
                provider="google",
                usage=CompletionUsage(
                    total_tokens=0,
                    prompt_tokens=0,
                    completion_tokens=0
                ),
                finish_reason="stop"
            )

            # Attach metadata
            response.user_id = user_id
            response.session_id = session_id
            if thought_process:
                response.prediction = "\n".join(thought_process)

            return response

        except Exception as e:
            self.logger.error(f"Deep Research failed: {e}")
            raise

    async def deep_research(
        self,
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        files: Optional[List[Union[str, Path]]] = None
    ) -> AIMessage:
        """
        Execute a Deep Research task, optionally uploading files first.

        Args:
            query: The research query
            user_id: Optional user ID
            session_id: Optional session ID
            files: List of file paths to upload and include in research

        Returns:
            AIMessage containing the research results
        """
        file_search_store_names = []

        if not self.client:
            self.client = await self.get_client()

        # Handle file uploads if provided
        if files:
            try:
                self.logger.info(f"Uploading {len(files)} files for deep research...")
                uploaded_files = []
                for file_path in files:
                    file_path = Path(file_path).expanduser().resolve()
                    if not file_path.exists():
                        self.logger.warning(f"File not found: {file_path}")
                        continue

                    uploaded_file = self.client.files.upload(file=file_path)
                    uploaded_files.append(uploaded_file)
                    self.logger.info(f"Uploaded {file_path.name} as {uploaded_file.name}")

                # Wait for files to be processed
                self.logger.info("Waiting for files to process...")
                active_files = []
                for f in uploaded_files:
                    while f.state.name == "PROCESSING":
                        time.sleep(1)
                        f = self.client.files.get(name=f.name)

                    if f.state.name == "ACTIVE":
                        active_files.append(f)
                    else:
                        self.logger.error(f"File {f.name} failed processing with state: {f.state.name}")

                if active_files:
                     # Create a temporary store or just use the files directly if supported
                     # The SDK example uses 'file_search_store_names' which implies we need a store
                     # For now, let's assume we pass a store name if we had one, or maybe just the file names
                     # The example code showed: "file_search_store_names": ['fileSearchStores/my-store-name']
                     # We might need to creates a store. But for this preview, let's see if we can just skip store
                     # creation if not strictly required or if we can infer it.
                     pass

            except Exception as e:
                self.logger.error(f"Error handling files for deep research: {e}")
                # Proceed without files if upload fails? Or raise?
                # Raising seems safer for "deep research on files"
                raise

        return await self._deep_research_ask(
            prompt=query,
            user_id=user_id,
            session_id=session_id,
            file_search_store_names=file_search_store_names
        )

    async def question(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        use_internal_tools: bool = False, # New parameter to control internal tools
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI in a stateless manner,
        without conversation history and with optional internal tools.

        Args:
            prompt (str): The input prompt for the model.
            model (Union[str, GoogleModel]): The model to use, defaults to GEMINI_2_5_FLASH.
            max_tokens (int): Maximum number of tokens in the response.
            temperature (float): Sampling temperature for response generation.
            files (Optional[List[Union[str, Path]]]): Optional files to include in the request.
            system_prompt (Optional[str]): Optional system prompt to guide the model.
            structured_output (Union[type, StructuredOutputConfig]): Optional structured output configuration.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
            use_internal_tools (bool): If True, Gemini's built-in tools (e.g., Google Search)
                will be made available to the model. Defaults to False.
        """
        self.logger.info(
            f"Initiating RAG pipeline for prompt: '{prompt[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        output_config = self._get_structured_config(structured_output)

        generation_config = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        if output_config:
            self._apply_structured_output_schema(generation_config, output_config)

        tools = None
        if use_internal_tools:
            tools = self._build_tools("builtin_tools") # Only built-in tools
            self.logger.debug(
                f"Enabled internal tool usage."
            )

        # Build contents for the stateless call
        contents = []
        if files:
            for file_path in files:
                # In a real scenario, you'd handle file uploads to Gemini properly
                # This is a placeholder for file content
                contents.append(
                    {
                        "part": {
                            "inline_data": {
                                "mime_type": "application/octet-stream",
                                "data": "BASE64_ENCODED_FILE_CONTENT"
                            }
                        }
                    }
                )

        # Add the user prompt as the first part
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        all_tool_calls = [] # To capture any tool calls made by internal tools

        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            **generation_config
        )

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Handle potential internal tool calls if they are part of the direct generate_content response
        # Gemini can sometimes decide to use internal tools even without explicit function calling setup
        # if the tools are broadly enabled (e.g., through a general 'tool' parameter).
        # This part assumes Gemini's 'generate_content' directly returns tool calls if it uses them.
        if use_internal_tools and response.candidates and response.candidates[0].content.parts:
            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, 'function_call') and part.function_call
            ]
            if function_calls:
                tool_call_objects = []
                for fc in function_calls:
                    tc = ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        arguments=dict(fc.args)
                    )
                    tool_call_objects.append(tc)

                start_time = time.time()
                tool_execution_tasks = [
                    self._execute_tool(fc.name, dict(fc.args)) for fc in function_calls
                ]
                tool_results = await asyncio.gather(
                    *tool_execution_tasks,
                    return_exceptions=True
                )
                execution_time = time.time() - start_time

                for tc, result in zip(tool_call_objects, tool_results):
                    tc.execution_time = execution_time / len(tool_call_objects)
                    if isinstance(result, Exception):
                        tc.error = str(result)
                    else:
                        tc.result = result

                all_tool_calls.extend(tool_call_objects)
                pass # We're not doing a multi-turn here for stateless

        final_output = None
        if output_config:
            try:
                final_output = await self._parse_structured_output(
                    response.text,
                    output_config
                )
            except Exception:
                final_output = response.text

        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=all_tool_calls
        )
        ai_message.provider = "google_genai"

        return ai_message
