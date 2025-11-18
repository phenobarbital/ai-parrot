import re
import sys
import asyncio
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union, Tuple
from functools import partial
import logging
import time
from pathlib import Path
import contextlib
import io
import uuid
import aiofiles
import aiohttp
from PIL import Image
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    ModelContent,
    UserContent,
)
from google.oauth2 import service_account
from google.genai import types
from navconfig import config, BASE_DIR
import pandas as pd
from sklearn.base import defaultdict
from .base import (
    AbstractClient,
    ToolDefinition,
    RetryConfig,
    TokenRetryMixin,
    StreamingRetryConfig
)
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat,
    CompletionUsage,
    ImageGenerationPrompt,
    SpeakerConfig,
    SpeechGenerationPrompt,
    VideoGenerationPrompt,
    ObjectDetectionResult,
    GoogleModel,
    TTSVoice
)
from ..tools.abstract import AbstractTool, ToolResult
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)
from ..models.google import (
    ALL_VOICE_PROFILES,
    VoiceRegistry,
    ConversationalScriptConfig,
    FictionalSpeaker
)
from ..exceptions import SpeechGenerationError  # pylint: disable=E0611
from ..models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
    IdentificationResponse
)

logging.getLogger(
    name='PIL.TiffImagePlugin'
).setLevel(logging.ERROR)  # Suppress TiffImagePlugin warnings
logging.getLogger(
    name='google_genai'
).setLevel(logging.ERROR)  # Suppress GenAI warnings


class GoogleGenAIClient(AbstractClient):
    """
    Client for interacting with Google's Generative AI, with support for parallel function calling.

    Only Gemini-2.5-pro works well with multi-turn function calling.
    Supports both API Key (Gemini Developer API) and Service Account (Vertex AI).
    """
    client_type: str = 'google'
    client_name: str = 'google'

    def __init__(self, vertexai: bool = False, **kwargs):
        self.vertexai: bool = vertexai
        self.vertex_location = kwargs.get('location', config.get('VERTEX_REGION'))
        self.vertex_project = kwargs.get('project', config.get('VERTEX_PROJECT_ID'))
        self._credentials_file = kwargs.get('credentials_file', config.get('VERTEX_CREDENTIALS_FILE'))
        if isinstance(self._credentials_file, str):
            self._credentials_file = Path(self._credentials_file).expanduser()
        self.api_key = kwargs.pop('api_key', config.get('GOOGLE_API_KEY'))
        super().__init__(**kwargs)
        self.client = None
        #  Create a single instance of the Voice registry
        self.voice_db = VoiceRegistry(profiles=ALL_VOICE_PROFILES)

    def get_client(self) -> genai.Client:
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

    async def __aenter__(self):
        """Initialize the client context."""
        # Google GenAI doesn't need explicit session management
        self.client = self.get_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the client context."""
        if self.client:
            with contextlib.suppress(Exception):
                await self.client._api_client._aiohttp_session.close()   # pylint: disable=E1101 # noqa
        self.client = None

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
                    break
             if 'type' not in cleaned:
                 cleaned['type'] = 'string'

        # Ensure object-like schemas always advertise an object type
        if 'properties' in cleaned and cleaned.get('type') != 'object':
            cleaned['type'] = 'object'

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

    def _build_tools(self, tool_type: str) -> Optional[List[types.Tool]]:
        """Build tools based on the specified type."""
        if tool_type == "custom_functions":
            # migrate to use abstractool + tool definition:
            # Group function declarations by their category
            declarations_by_category = defaultdict(list)
            for tool in self.tool_manager.all_tools():
                tool_name = tool.name
                category = getattr(tool, 'category', 'tools')
                if isinstance(tool, AbstractTool):
                    full_schema = tool.get_tool_schema()
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

    def _process_tool_result_for_api(self, result) -> dict:
        """Process tool result for Google Function Calling API compatibility."""

        if isinstance(result, Exception):
            return {"result": f"Error: {str(result)}", "error": True}

        if isinstance(result, ToolResult):
            content = result.result
            if result.metadata and 'stdout' in result.metadata:
                # Priorizar stdout si existe
                content = result.metadata['stdout']
            return {"result": str(content)}

        # Convert complex types to basic Python types
        if isinstance(result, pd.DataFrame):
            clean_result = result.to_dict(orient='records')
        elif hasattr(result, 'model_dump'):  # Pydantic v2
            clean_result = result.model_dump()
        elif hasattr(result, 'dict'):  # Pydantic v1
            clean_result = result.dict()
        elif isinstance(result, list):
            clean_result = [
                item.model_dump() if hasattr(item, 'model_dump')
                else item.dict() if hasattr(item, 'dict')
                else item
                for item in result
            ]
        if isinstance(result, str):
            if not result.strip():
                return {"result": "Code executed successfully (no output)"}
            return {"result": result}
        else:
            clean_result = result

        # Serialize with orjson to handle time/datetime objects
        serialized = self._json.dumps(clean_result)
        json_compatible_result = self._json.loads(serialized)

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
                summary = self._json.dumps(result.model_dump())
            elif isinstance(result, (dict, list)):
                summary = self._json.dumps(result)
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
        max_retries: int = 1,
    ) -> Any:
        """
        Simple multi-turn function calling - just keep going until no more function calls.
        """
        current_response = initial_response
        current_config = config
        iteration = 0

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
                # self.logger.notice(f"📤 Raw Result: {result}")

                try:
                    response_content = self._process_tool_result_for_api(result)
                    self.logger.info(f"📦 Processed for API: {response_content}")

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
                        self.logger.error(f"Error sending message: {e}")
                        retry_count += 1
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
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
                if hasattr(current_response, 'text'):
                    try:
                        preview = current_response.text[:100] if current_response.text else "No text"
                        self.logger.debug(f"Response preview: {preview}")
                    except:
                        self.logger.debug("Could not preview response text")

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

                    # Check for tool_code in text parts
                    elif hasattr(part, 'text') and part.text and '```tool_code' in part.text:
                        self.logger.info("Found tool_code block - converting to function call")
                        code_function_calls = self._parse_tool_code_blocks(part.text)
                        function_calls.extend(code_function_calls)

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

        # Method 1: Try response.text first (fastest path)
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
            if (hasattr(response, 'candidates') and
                response.candidates and
                len(response.candidates) > 0 and
                hasattr(response.candidates[0], 'content') and
                response.candidates[0].content and
                hasattr(response.candidates[0].content, 'parts') and
                response.candidates[0].content.parts):

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

    async def ask(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        stateless: bool = False,
        **kwargs
    ) -> AIMessage:
        """
        Ask a question to Google's Generative AI with support for parallel tool calls.

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
            force_tool_usage (Optional[str]): Force usage of specific tools, if needed.
                ("custom_functions", "builtin_tools", or None)
            stateless (bool): If True, don't use conversation memory (stateless mode).
        """
        max_retries = kwargs.pop('max_retries', 1)

        model = model.value if isinstance(model, GoogleModel) else model
        # If use_tools is None, use the instance default
        _use_tools = use_tools if use_tools is not None else self.enable_tools
        if not model:
            model = self.model or GoogleModel.GEMINI_2_5_FLASH.value
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
            for msg in messages[:-1]: # Exclude the current user message (last in list)
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


        default_tokens = max_tokens or self.max_tokens or 4096
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

        if _use_tools and tool_type == "custom_functions" and not tools:
            self.logger.info(
                "Tool usage requested but no tools are registered - disabling tools for this request."
            )
            _use_tools = False
            tool_type = None
            tools = []
            generation_config["temperature"] = base_temperature

        use_tools = _use_tools

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
            self.client = self.get_client()
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
                    if finish_reason and finish_reason.name == "MAX_TOKENS" and generation_config["max_output_tokens"] == 1024:
                        retry_count += 1
                        self.logger.warning(
                            f"Hit MAX_TOKENS limit on stateless response. Retrying {retry_count}/{max_retries} with increased token limit."
                        )
                        final_config.max_output_tokens = 8192
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
                    if finish_reason and finish_reason.name == "MAX_TOKENS" and generation_config["max_output_tokens"] == 1024:
                        retry_count += 1
                        self.logger.warning(
                            f"Hit MAX_TOKENS limit on initial response. Retrying {retry_count}/{max_retries} with increased token limit."
                        )
                        final_config.max_output_tokens = 8192
                        continue
                    break
                except Exception as e:
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
                max_retries=max_retries
            )

        # Extract assistant response text for conversation memory
        assistant_response_text = self._safe_extract_text(final_response)

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
                        final_output = self._json.loads(structured_text)
                else:
                    self.logger.warning("No structured text received, falling back to original response")
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
            text_response=assistant_response_text
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
        else:
            # Multiple calls - show the final result
            final_tc = all_tool_calls[-1]
            print('GOOGLE TYPE > ', type(final_tc.result))
            print('GOOGLE RAW ', final_tc)
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

        return "Calculation completed."

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",  # "retry", "notify", "ignore"
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """
        Stream Google Generative AI's response using AsyncIterator.
        Note: Tool calling is not supported in streaming mode with this implementation.

        Args:
            on_max_tokens: How to handle MAX_TOKENS finish reason:
                - "retry": Automatically retry with increased token limit
                - "notify": Yield a notification message and continue
                - "ignore": Silently continue (original behavior)
        """
        model = model.value if isinstance(model, GoogleModel) else model
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


        # Retry loop for MAX_TOKENS and other errors
        current_max_tokens = max_tokens or self.max_tokens
        retry_count = 0

        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
        # Convert to newer API format - create proper Tool objects
        function_declarations = []

        # Add custom function tools
        for tool in self.tool_manager.all_tools():
            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters=self._fix_tool_schema(tool.input_schema.copy())
                )
            )

        # Create a single Tool object with all function declarations plus built-in tools
        tools = [
            types.Tool(function_declarations=function_declarations),
        ]

        while retry_count <= retry_config.max_retries:
            try:
                generation_config = {
                    "max_output_tokens": current_max_tokens,
                    "temperature": temperature or self.temperature,
                }

                # Start the chat session
                chat = self.client.aio.chats.create(
                    model=model,
                    history=history,
                    config=GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=tools,
                        **generation_config
                    )
                )

                assistant_content = ""
                max_tokens_reached = False

                async for chunk in await chat.send_message_stream(prompt):
                    # Check for MAX_TOKENS finish reason
                    if (hasattr(chunk, 'candidates') and
                        chunk.candidates and
                        len(chunk.candidates) > 0):

                        candidate = chunk.candidates[0]
                        if (hasattr(candidate, 'finish_reason') and
                            str(candidate.finish_reason) == 'FinishReason.MAX_TOKENS'):
                            max_tokens_reached = True

                            # Handle MAX_TOKENS based on configuration
                            if on_max_tokens == "notify":
                                yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens). The response may be incomplete.**\n"
                            elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                                # We'll handle retry after the loop
                                break

                    # Yield the text content
                    if chunk.text:
                        assistant_content += chunk.text
                        yield chunk.text

                # If MAX_TOKENS reached and we should retry
                if max_tokens_reached and on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                    if retry_count < retry_config.max_retries:
                        # Increase token limit for retry
                        new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)

                        # Notify user about retry
                        yield f"\n\n🔄 **Response reached token limit ({current_max_tokens}). Retrying with increased limit ({new_max_tokens})...**\n\n"

                        current_max_tokens = new_max_tokens
                        retry_count += 1

                        # Wait before retry
                        await self._wait_with_backoff(retry_count, retry_config)
                        continue
                    else:
                        # Max retries reached
                        yield f"\n\n❌ **Maximum retries reached. Response may be incomplete due to token limits.**\n"

                # If we get here, streaming completed successfully (or we're not retrying)
                break

            except Exception as e:
                if retry_count < retry_config.max_retries:
                    error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                    yield error_msg

                    retry_count += 1
                    await self._wait_with_backoff(retry_count, retry_config)
                    continue
                else:
                    # Max retries reached, yield error and break
                    yield f"\n\n❌ **Streaming failed after {retry_config.max_retries} retries: {str(e)}**\n"
                    break

        # Update conversation memory
        if assistant_content:
            final_assistant_message = {
                "role": "assistant", "content": [
                    {"type": "text", "text": assistant_content}
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
                assistant_content,
                []
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
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
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
        final_config = GenerateContentConfig(**generation_config)

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

    async def generate_images(
        self,
        prompt_data: ImageGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.IMAGEN_3,
        reference_image: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        mime_format: str = "image/jpeg",
        number_of_images: int = 1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        add_watermark: bool = False
    ) -> AIMessage:
        """
        Generates images based on a text prompt using Imagen.
        """
        if prompt_data.model:
            model = GoogleModel.IMAGEN_3.value
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting image generation with model: {model}"
        )
        if model == GoogleModel.GEMINI_2_0_IMAGE_GENERATION.value:
            image_provider = "google_genai"
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )
        else:
            image_provider = "google_imagen"

        full_prompt = prompt_data.prompt
        if prompt_data.styles:
            full_prompt += ", " + ", ".join(prompt_data.styles)

        if reference_image:
            self.logger.info(
                f"Using reference image: {reference_image}"
            )
            if not reference_image.exists():
                raise FileNotFoundError(
                    f"Reference image not found: {reference_image}"
                )
            # Load the reference image
            ref_image = Image.open(reference_image)
            full_prompt = [full_prompt, ref_image]

        config = types.GenerateImagesConfig(
            number_of_images=number_of_images,
            output_mime_type=mime_format,
            safety_filter_level="BLOCK_LOW_AND_ABOVE",
            person_generation="ALLOW_ADULT", # Or ALLOW_ALL, etc.
            aspect_ratio=prompt_data.aspect_ratio,
        )

        try:
            start_time = time.time()
            # Use the asynchronous client for image generation
            image_response = await self.client.aio.models.generate_images(
                model=prompt_data.model,
                prompt=full_prompt,
                config=config
            )
            execution_time = time.time() - start_time

            pil_images = []
            saved_image_paths = []
            raw_response = {} # Initialize an empty dict for the raw response

            if image_response.generated_images:
                self.logger.info(
                    f"Successfully generated {len(image_response.generated_images)} image(s)."
                )
                raw_response['generated_images'] = []
                for i, generated_image in enumerate(image_response.generated_images):
                    pil_image = generated_image.image
                    pil_images.append(pil_image)

                    raw_response['generated_images'].append({
                        'uri': getattr(generated_image, 'uri', None),
                        'seed': getattr(generated_image, 'seed', None)
                    })

                    if output_directory:
                        file_path = self._save_image(pil_image, output_directory)
                        saved_image_paths.append(file_path)

            usage = CompletionUsage(execution_time=execution_time)
            # The primary 'output' is the list of raw PIL.Image objects
            # The new 'images' attribute holds the file paths
            ai_message = AIMessageFactory.from_imagen(
                output=pil_images,
                images=saved_image_paths,
                input=full_prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                provider=image_provider,
                usage=usage,
                raw_response=raw_response
            )
            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    def _find_voice_for_speaker(self, speaker: FictionalSpeaker) -> str:
        """
        Find the best voice for a speaker based on their characteristics and gender.

        Args:
            speaker: The fictional speaker configuration

        Returns:
            Voice name string
        """
        if not self.voice_db:
            self.logger.warning(
                "Voice database not available, using default voice"
            )
            return "erinome"  # Default fallback

        try:
            # First, try to find voices by characteristic
            characteristic_voices = self.voice_db.get_voices_by_characteristic(
                speaker.characteristic
            )

            if characteristic_voices:
                # Filter by gender if possible
                gender_filtered = [
                    v for v in characteristic_voices if v.gender == speaker.gender
                ]
                if gender_filtered:
                    return gender_filtered[0].voice_name.lower()
                else:
                    # Use first voice with matching characteristic regardless of gender
                    return characteristic_voices[0].voice_name.lower()

            # Fallback: find by gender only
            gender_voices = self.voice_db.get_voices_by_gender(speaker.gender)
            if gender_voices:
                self.logger.info(
                    f"Found voice by gender '{speaker.gender}': {gender_voices[0].voice_name}"
                )
                return gender_voices[0].voice_name.lower()

            # Ultimate fallback
            self.logger.warning(
                f"No voice found for speaker {speaker.name}, using default"
            )
            return "erinome"

        except Exception as e:
            self.logger.error(
                f"Error finding voice for speaker {speaker.name}: {e}"
            )
            return "erinome"

    async def create_conversation_script(
        self,
        report_data: ConversationalScriptConfig,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        use_structured_output: bool = False,
        max_lines: int = 20
    ) -> AIMessage:
        """
        Creates a conversation script using Google's Generative AI.
        Generates a fictional conversational script from a text report using a generative model.
        Generates a complete, TTS-ready prompt for a two-person conversation
        based on a source text report.

        This method is designed to create a script that can be used with Google's TTS system.

        Returns:
            A string formatted for Google's TTS `generate_content` method.
            Example:
            "Make Speaker1 sound tired and bored, and Speaker2 sound excited and happy:

            Speaker1: So... what's on the agenda today?
            Speaker2: You're never going to guess!"
        """
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting Conversation Script with model: {model}"
        )
        turn_id = str(uuid.uuid4())

        report_text = report_data.report_text
        if not report_text:
            raise ValueError(
                "Report text is required for generating a conversation script."
            )
        # Calculate conversation length
        conversation_length = min(report_data.length // 50, max_lines)
        if conversation_length < 4:
            conversation_length = max_lines
        system_prompt = report_data.system_prompt or "Create a natural and engaging conversation script based on the provided report."
        context = report_data.context or "This conversation is based on a report about a specific topic. The characters will discuss the key findings and insights from the report."
        interviewer = None
        interviewee = None
        for speaker in report_data.speakers:
            if not speaker.name or not speaker.role or not speaker.characteristic:
                raise ValueError(
                    "Each speaker must have a name, role, and characteristic."
                )
            # role (interviewer or interviewee) and characteristic (e.g., friendly, professional)
            if speaker.role == "interviewer":
                interviewer = speaker
            elif speaker.role == "interviewee":
                interviewee = speaker

        if not interviewer or not interviewee:
            raise ValueError("Must have exactly one interviewer and one interviewee.")
        system_instruction = report_data.system_instruction or f"""
You are a scriptwriter. Your task is {system_prompt} for a conversation between {interviewer.name} and {interviewee.name}. "

**Source Report:**"
---
{report_text}
---

**context:**
{context}


**Characters:**
1.  **{interviewer.name}**: The {interviewer.role}. Their personality is **{interviewer.characteristic}**.
2.  **{interviewee.name}**: The {interviewee.role}. Their personality is **{interviewee.characteristic}**.

**Conversation Length:** {conversation_length} lines.
**Instructions:**
- The conversation must be based on the key findings, data, and conclusions of the source report.
- The interviewer should ask insightful questions to guide the conversation.
- The interviewee should provide answers and explanations derived from the report.
- The dialogue should reflect the specified personalities of the characters.
- The conversation should be engaging, natural, and suitable for a TTS system.
- The script should be formatted for TTS, with clear speaker lines.

**Gender–Neutral Output (Strict)**
- Do NOT infer anyone's gender or use third-person gendered pronouns or titles: he, him, his, she, her, hers, Mr., Mrs., Ms., sir, ma’am, etc.
- If a third person must be referenced, use singular they/them/their or repeat the name/role (e.g., “the manager”, “Alex”).
- Do not include gendered stage directions (“in a feminine/masculine voice”).
- First/second person is fine inside dialogue (“I”, “you”), but NEVER use gendered third-person forms.

Before finalizing, scan and fix any gendered terms. If any banned term appears, rewrite that line to comply.

- **IMPORTANT**: Generate ONLY the dialogue script. Do not include headers, titles, or any text other than the speaker lines. The format must be exactly:
{interviewer.name}: [dialogue]
{interviewee.name}: [dialogue]
        """
        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": report_text}]
        }]

        final_config = GenerateContentConfig(
            system_instruction=system_instruction,
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
            tools=None,  # No tools needed for conversation script:
            **generation_config
        )

        # Make a stateless call to the model
        if not self.client:
            self.client = self.get_client()
        # response = await self.client.aio.models.generate_content(
        #     model=model,
        #     contents=contents,
        #     config=final_config
        # )
        sync_generate_content = partial(
            self.client.models.generate_content,
            model=model,
            contents=contents,
            config=final_config
        )
        # Run the synchronous function in a separate thread
        response = await asyncio.to_thread(sync_generate_content)
        # Extract the generated script text
        script_text = response.text if hasattr(response, 'text') else str(response)
        structured_output = script_text
        if use_structured_output:
            self.logger.info("Creating structured output for TTS system...")
            try:
                # Map speakers to voices
                speaker_configs = []
                for speaker in report_data.speakers:
                    voice = self._find_voice_for_speaker(speaker)
                    speaker_configs.append(
                        SpeakerConfig(name=speaker.name, voice=voice)
                    )
                    self.logger.notice(
                        f"Assigned voice '{voice}' to speaker '{speaker.name}'"
                    )
                structured_output = SpeechGenerationPrompt(
                    prompt=script_text,
                    speakers=speaker_configs
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to create structured output: {e}"
                )
                # Continue without structured output rather than failing

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=report_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def generate_speech(
        self,
        prompt_data: SpeechGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,
        output_directory: Optional[Path] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        mime_format: str = "audio/wav", # or "audio/mpeg", "audio/webm"
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> AIMessage:
        """
        Generates speech from text using either a single voice or multiple voices.
        """
        start_time = time.time()
        if prompt_data.model:
            model = prompt_data.model
        model = model.value if isinstance(model, GoogleModel) else model
        self.logger.info(
            f"Starting Speech generation with model: {model}"
        )

        # Validation of voices and fallback logic before creating the SpeechConfig:
        valid_voices = {v.value for v in TTSVoice}
        processed_speakers = []
        for speaker in prompt_data.speakers:
            final_voice = speaker.voice
            if speaker.voice not in valid_voices:
                self.logger.warning(
                    f"Invalid voice '{speaker.voice}' for speaker '{speaker.name}'. "
                    "Using default voice instead."
                )
                gender = speaker.gender.lower() if speaker.gender else 'female'
                final_voice = 'zephyr' if gender == 'female' else 'charon'
            processed_speakers.append(
                SpeakerConfig(name=speaker.name, voice=final_voice, gender=speaker.gender)
            )

        speech_config = None
        if len(processed_speakers) == 1:
            # Single-speaker configuration
            speaker = processed_speakers[0]
            gender = speaker.gender or 'female'
            default_voice = 'Charon' if gender == 'female' else 'Puck'
            voice = speaker.voice or default_voice
            self.logger.info(f"Using single voice: {voice}")
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                ),
                language_code=prompt_data.language or "en-US"  # Default to US English
            )
        else:
            # Multi-speaker configuration
            self.logger.info(
                f"Using multiple voices: {[s.voice for s in processed_speakers]}"
            )
            speaker_voice_configs = [
                types.SpeakerVoiceConfig(
                    speaker=s.name,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=s.voice
                        )
                    )
                ) for s in processed_speakers
            ]
            speech_config = types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=speaker_voice_configs
                ),
                language_code=prompt_data.language or "en-US"  # Default to US English
            )

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
            system_instruction=system_prompt,
            temperature=temperature
        )
        # Retry logic for network errors
        if not self.client:
            self.client = self.get_client()
        # chat = self.client.aio.chats.create(model=model, history=None, config=config)
        for attempt in range(max_retries + 1):

            try:
                if attempt > 0:
                    delay = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                    self.logger.info(
                        f"Retrying speech (attempt {attempt + 1}/{max_retries + 1}) after {delay}s delay..."
                    )
                    await asyncio.sleep(delay)
                # response = await self.client.aio.models.generate_content(
                #     model=model,
                #     contents=prompt_data.prompt,
                #     config=config,
                # )
                sync_generate_content = partial(
                    self.client.models.generate_content,
                    model=model,
                    contents=prompt_data.prompt,
                    config=config
                )
                # Run the synchronous function in a separate thread
                response = await asyncio.to_thread(sync_generate_content)
                # Robust audio data extraction with proper validation
                audio_data = self._extract_audio_data(response)
                if audio_data is None:
                    # Log the response structure for debugging
                    self.logger.error(f"Failed to extract audio data from response")
                    self.logger.debug(f"Response type: {type(response)}")
                    if hasattr(response, 'candidates'):
                        self.logger.debug(f"Candidates count: {len(response.candidates) if response.candidates else 0}")
                        if response.candidates and len(response.candidates) > 0:
                            candidate = response.candidates[0]
                            self.logger.debug(f"Candidate type: {type(candidate)}")
                            self.logger.debug(f"Candidate has content: {hasattr(candidate, 'content')}")
                            if hasattr(candidate, 'content'):
                                content = candidate.content
                                self.logger.debug(f"Content is None: {content is None}")
                                if content:
                                    self.logger.debug(f"Content has parts: {hasattr(content, 'parts')}")
                                    if hasattr(content, 'parts'):
                                        self.logger.debug(f"Parts count: {len(content.parts) if content.parts else 0}")

                    raise SpeechGenerationError(
                        "No audio data found in response. The speech generation may have failed or "
                        "the model may not support speech generation for this request."
                    )

                saved_file_paths = []

                if output_directory:
                    output_directory.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    file_path = output_directory / f"generated_speech_{timestamp}.wav"

                    self._save_audio_file(audio_data, file_path, mime_format)
                    saved_file_paths.append(file_path)
                    self.logger.info(
                        f"Saved speech to {file_path}"
                    )

                execution_time = time.time() - start_time
                usage = CompletionUsage(
                    execution_time=execution_time,
                    # Speech API does not return token counts
                    input_tokens=len(prompt_data.prompt), # Approximation
                )

                ai_message = AIMessageFactory.from_speech(
                    output=audio_data, # The raw PCM audio data
                    files=saved_file_paths,
                    input=prompt_data.prompt,
                    model=model,
                    provider="google_genai",
                    usage=usage,
                    user_id=user_id,
                    session_id=session_id,
                    raw_response=None # Response object isn't easily serializable
                )
                return ai_message

            except (
                aiohttp.ClientPayloadError,
                aiohttp.ClientConnectionError,
                aiohttp.ClientResponseError,
                aiohttp.ServerTimeoutError,
                ConnectionResetError,
                TimeoutError,
                asyncio.TimeoutError
            ) as network_error:
                error_msg = str(network_error)

                # Specific handling for different network errors
                if "TransferEncodingError" in error_msg:
                    self.logger.warning(
                        f"Transfer encoding error on attempt {attempt + 1}: {error_msg}")
                elif "Connection reset by peer" in error_msg:
                    self.logger.warning(
                        f"Connection reset on attempt {attempt + 1}: Server closed connection")
                elif "timeout" in error_msg.lower():
                    self.logger.warning(
                        f"Timeout error on attempt {attempt + 1}: {error_msg}")
                else:
                    self.logger.warning(
                        f"Network error on attempt {attempt + 1}: {error_msg}"
                    )

                if attempt < max_retries:
                    self.logger.debug(
                        f"Will retry in {retry_delay * (2 ** attempt)}s..."
                    )
                    continue
                else:
                    # Max retries exceeded
                    self.logger.error(
                        f"Speech generation failed after {max_retries + 1} attempts"
                    )
                    raise SpeechGenerationError(
                        f"Speech generation failed after {max_retries + 1} attempts. "
                        f"Last error: {error_msg}. This is typically a temporary network issue - please try again."
                    ) from network_error

            except Exception as e:
                # Non-network errors - don't retry
                error_msg = str(e)
                self.logger.error(
                    f"Speech generation failed with non-retryable error: {error_msg}"
                )

                # Provide helpful error messages based on error type
                if "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"API quota or rate limit exceeded: {error_msg}. Please try again later."
                    ) from e
                elif "permission" in error_msg.lower() or "unauthorized" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"Authorization error: {error_msg}. Please check your API credentials."
                    ) from e
                elif "model" in error_msg.lower():
                    raise SpeechGenerationError(
                        f"Model error: {error_msg}. The model '{model}' may not support speech generation."
                    ) from e
                else:
                    raise SpeechGenerationError(
                        f"Speech generation failed: {error_msg}"
                    ) from e

    def _extract_audio_data(self, response):
        """
        Robustly extract audio data from Google GenAI response.
        Similar to the text extraction pattern used elsewhere in the codebase.
        """
        try:
            # First attempt: Direct access to expected structure
            if (hasattr(response, 'candidates') and
                response.candidates and
                len(response.candidates) > 0 and
                hasattr(response.candidates[0], 'content') and
                response.candidates[0].content and
                hasattr(response.candidates[0].content, 'parts') and
                response.candidates[0].content.parts and
                len(response.candidates[0].content.parts) > 0):

                for part in response.candidates[0].content.parts:
                    # Check for inline_data with audio data
                    if (hasattr(part, 'inline_data') and
                        part.inline_data and
                        hasattr(part.inline_data, 'data') and
                        part.inline_data.data):
                        self.logger.debug("Found audio data in inline_data.data")
                        return part.inline_data.data

                    # Alternative: Check for direct data attribute
                    if hasattr(part, 'data') and part.data:
                        self.logger.debug("Found audio data in part.data")
                        return part.data

                    # Alternative: Check for binary data
                    if hasattr(part, 'binary') and part.binary:
                        self.logger.debug("Found audio data in part.binary")
                        return part.binary

            self.logger.warning("No audio data found in expected response structure")
            return None

        except Exception as e:
            self.logger.error(f"Audio data extraction failed: {e}")
            return None

    async def generate_videos(
        self,
        prompt: VideoGenerationPrompt,
        reference_image: Optional[Path] = None,
        output_directory: Optional[Path] = None,
        mime_format: str = "video/mp4",
        model: Union[str, GoogleModel] = GoogleModel.VEO_3_0,
    ) -> AIMessage:
        """
        Generate a video using the specified model and prompt.
        """
        if prompt.model:
            model = prompt.model
        model = model.value if isinstance(model, GoogleModel) else model
        if model not in [GoogleModel.VEO_2_0.value, GoogleModel.VEO_3_0.value]:
            raise ValueError(
                "Generate Videos are only supported with VEO 2.0 or VEO 3.0 models."
            )
        self.logger.info(
            f"Starting Video generation with model: {model}"
        )
        if output_directory:
            output_directory.mkdir(parents=True, exist_ok=True)
        else:
            output_directory = BASE_DIR.joinpath('static', 'generated_videos')
        args = {
            "prompt": prompt.prompt,
            "model": model,
        }

        if reference_image:
            # if a reference image is used, only Veo2 is supported:
            self.logger.info(
                f"Veo 3.0 does not support reference images, using VEO 2.0 instead."
            )
            model = GoogleModel.VEO_2_0.value
            self.logger.info(
                f"Using reference image: {reference_image}"
            )
            if not reference_image.exists():
                raise FileNotFoundError(
                    f"Reference image not found: {reference_image}"
                )
            # Load the reference image
            ref_image = Image.open(reference_image)
            args['image'] = types.Image(image_bytes=ref_image)

        start_time = time.time()
        operation = self.client.models.generate_videos(
            **args,
            config=types.GenerateVideosConfig(
                aspect_ratio=prompt.aspect_ratio or "16:9",  # Default to 16:9
                negative_prompt=prompt.negative_prompt,  # Optional negative prompt
                number_of_videos=prompt.number_of_videos,  # Number of videos to generate
            )
        )

        print("Video generation job started. Waiting for completion...", end="")
        spinner_chars = ['|', '/', '-', '\\']
        check_interval = 10  # Check status every 10 seconds
        spinner_index = 0

        # This loop checks the job status every 10 seconds
        while not operation.done:
            # This inner loop runs the spinner animation for the check_interval
            for _ in range(check_interval):
                # Write the spinner character to the console
                sys.stdout.write(
                    f"\rVideo generation job started. Waiting for completion... {spinner_chars[spinner_index]}"
                )
                sys.stdout.flush()
                spinner_index = (spinner_index + 1) % len(spinner_chars)
                time.sleep(1) # Animate every second

            # After 10 seconds, get the updated operation status
            operation = self.client.operations.get(operation)

        print("\rVideo generation job completed.          ", end="")

        for n, generated_video in enumerate(operation.result.generated_videos):
            # Download the generated videos
            # bytes of the original MP4
            mp4_bytes = self.client.files.download(file=generated_video.video)
            video_path = self._save_video_file(
                mp4_bytes,
                output_directory,
                video_number=n,
                mime_format=mime_format
            )
        execution_time = time.time() - start_time
        usage = CompletionUsage(
            execution_time=execution_time,
            # Video API does not return token counts
            input_tokens=len(prompt.prompt), # Approximation
        )

        ai_message = AIMessageFactory.from_video(
            output=operation, # The raw Video object
            files=[video_path],
            input=prompt.prompt,
            model=model,
            provider="google_genai",
            usage=usage,
            user_id=None,
            session_id=None,
            raw_response=None # Response object isn't easily serializable
        )
        return ai_message

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

    async def summarize_text(
        self,
        text: str,
        max_length: int = 500,
        min_length: int = 100,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Generates a summary for a given text in a stateless manner.

        Args:
            text (str): The text content to summarize.
            max_length (int): The maximum desired character length for the summary.
            min_length (int): The minimum desired character length for the summary.
            model (Union[str, GoogleModel]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        self.logger.info(
            f"Generating summary for text: '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        # Define the specific system prompt for summarization
        system_prompt = f"""
Your job is to produce a final summary from the following text and identify the main theme.
- The summary should be concise and to the point.
- The summary should be no longer than {max_length} characters and no less than {min_length} characters.
- The summary should be in a single paragraph.
"""

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless call. The 'prompt' is the text to be summarized.
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        final_config = GenerateContentConfig(
            system_instruction=system_prompt,
            tools=None,  # No tools needed for summarization
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.2,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Translates a given text from a source language to a target language.

        Args:
            text (str): The text content to translate.
            target_lang (str): The ISO code for the target language (e.g., 'es', 'fr').
            source_lang (Optional[str]): The ISO code for the source language.
                If None, the model will attempt to detect it.
            model (Union[str, GoogleModel]): The model to use. Defaults to GEMINI_2_5_FLASH,
                which is recommended for speed.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        self.logger.info(
            f"Translating text to '{target_lang}': '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        # Construct the system prompt for translation
        if source_lang:
            prompt_instruction = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                "Only return the translated text, without any additional comments or explanations."
            )
        else:
            prompt_instruction = (
                f"First, detect the source language of the following text. Then, translate it to {target_lang}. "
                "Only return the translated text, without any additional comments or explanations."
            )

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        final_config = GenerateContentConfig(
            system_instruction=prompt_instruction,
            tools=None,  # No tools needed for translation
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def extract_key_points(
        self,
        text: str,
        num_points: int = 5,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH, # Changed to GoogleModel
        temperature: Optional[float] = 0.3,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Extract *num_points* bullet-point key ideas from *text* (stateless).
        """
        self.logger.info(
            f"Extracting {num_points} key points from text: '{text[:50]}...'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        system_instruction = ( # Changed to system_instruction for Google GenAI
            f"Extract the {num_points} most important key points from the following text.\n"
            "- Present each point as a clear, concise bullet point (•).\n"
            "- Focus on the main ideas and significant information.\n"
            "- Each point should be self-contained and meaningful.\n"
            "- Order points by importance (most important first)."
        )

        # Build contents for the stateless API call
        contents = [{
            "role": "user",
            "parts": [{"text": text}]
        }]

        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }

        final_config = GenerateContentConfig(
            system_instruction=system_instruction,
            tools=None, # No tools needed for this task
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=None, # No structured output explicitly requested
            tool_calls=[] # No tool calls for this method
        )
        ai_message.provider = "google_genai" # Set provider

        return ai_message

    async def analyze_sentiment(
        self,
        text: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False,
    ) -> AIMessage:
        """
        Perform sentiment analysis on text and return a structured or unstructured response.

        Args:
            text (str): The text to analyze.
            model (Union[GoogleModel, str]): The model to use for the analysis.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
            use_structured (bool): If True, forces a structured JSON output matching
                the SentimentAnalysis model. Defaults to False.
        """
        self.logger.info(f"Analyzing sentiment for text: '{text[:50]}...'")

        model_name = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        system_instruction = ""
        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }
        structured_output_model = None

        if use_structured:
            # ✍️ Generate a prompt to force JSON output matching the Pydantic schema
            schema = SentimentAnalysis.model_json_schema()
            system_instruction = (
                "You are an expert in sentiment analysis. Analyze the following text and provide a structured JSON response. "
                "Your response MUST be a valid JSON object that conforms to the following JSON Schema. "
                "Do not include any other text, explanations, or markdown formatting like ```json ... ```.\n\n"
                f"JSON Schema:\n{self._json.dumps(schema, indent=2)}"
            )
            # Enable Gemini's JSON mode for reliable structured output
            generation_config["response_mime_type"] = "application/json"
            structured_output_model = SentimentAnalysis
        else:
            # The original prompt for a human-readable, unstructured response
            system_instruction = (
                "Analyze the sentiment of the following text and provide a structured response.\n"
                "Your response must include:\n"
                "1. Overall sentiment (Positive, Negative, Neutral, or Mixed)\n"
                "2. Confidence level (High, Medium, Low)\n"
                "3. Key emotional indicators found in the text\n"
                "4. Brief explanation of your analysis\n\n"
                "Format your answer clearly with numbered sections."
            )

        contents = [{"role": "user", "parts": [{"text": text}]}]

        final_config = GenerateContentConfig(
            system_instruction={"role": "system", "parts": [{"text": system_instruction}]},
            tools=None,
            **generation_config,
        )

        response = await self.client.aio.models.generate_content(
            model=model_name,
            contents=contents,
            config=final_config,
        )

        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model_name,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output_model,
            tool_calls=[],
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = True,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured or unstructured information.

        Args:
            review_text (str): The product review text to analyze.
            product_id (str): Unique identifier for the product.
            product_name (str): Name of the product being reviewed.
            model (Union[GoogleModel, str]): The model to use for the analysis.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
            use_structured (bool): If True, forces a structured JSON output matching
                the ProductReview model. Defaults to True.
        """
        self.logger.info(
            f"Analyzing product review for product_id: '{product_id}'"
        )

        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        system_instruction = ""
        generation_config = {
            "max_output_tokens": self.max_tokens,
            "temperature": temperature or self.temperature,
        }
        structured_output_model = None

        if use_structured:
            # Generate a prompt to force JSON output matching the Pydantic schema
            schema = ProductReview.model_json_schema()
            system_instruction = (
                "You are a product review analysis expert. Analyze the provided product review "
                "and extract the required information. Your response MUST be a valid JSON object "
                "that conforms to the following JSON Schema. Do not include any other text, "
                "explanations, or markdown formatting like ```json ... ``` around the JSON object.\n\n"
                f"JSON Schema:\n{self._json.dumps(schema)}"
            )
            # Enable Gemini's JSON mode for reliable structured output
            generation_config["response_mime_type"] = "application/json"
            structured_output_model = ProductReview
        else:
            # Generate a prompt for a more general, text-based analysis
            system_instruction = (
                "You are a product review analysis expert. Analyze the sentiment and key aspects "
                "of the following product review.\n"
                "Your response must include:\n"
                "1. Overall sentiment (Positive, Negative, or Neutral)\n"
                "2. Estimated Rating (on a scale of 1-5)\n"
                "3. Key Positive Points mentioned\n"
                "4. Key Negative Points mentioned\n"
                "5. A brief summary of the review's main points."
            )

        # Build the user content part of the request
        user_prompt = (
            f"Product ID: {product_id}\n"
            f"Product Name: {product_name}\n"
            f"Review Text: \"{review_text}\""
        )
        contents = [{
            "role": "user",
            "parts": [{"text": user_prompt}]
        }]

        # Finalize the generation configuration
        final_config = GenerateContentConfig(
            system_instruction={"role": "system", "parts": [{"text": system_instruction}]},
            tools=None,
            **generation_config
        )

        # Make a stateless call to the model
        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config
        )

        # Create the AIMessage response using the factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=user_prompt, # Use the full prompt as input text
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_output_model,
            tool_calls=[]
        )
        ai_message.provider = "google_genai"

        return ai_message

    async def image_generation(
        self,
        prompt_data: Union[str, ImageGenerationPrompt],
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW,
        temperature: Optional[float] = None,
        prompt_instruction: Optional[str] = None,
        reference_images: List[Optional[Path]] = None,
        output_directory: Optional[Path] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stateless: bool = True
    ) -> AIMessage:
        """
        Generates images based on a text prompt using Nano-Banana.
        """
        if isinstance(prompt_data, str):
            prompt_data = ImageGenerationPrompt(
                prompt=prompt_data,
                model=model,
            )
        if prompt_data.model:
            model = GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW.value
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())
        prompt_data.model = model

        self.logger.info(
            f"Starting image generation with model: {model}"
        )

        messages, conversation_session, _ = await self._prepare_conversation_context(
            prompt_data.prompt, None, user_id, session_id, None
        )

        full_prompt = prompt_data.prompt
        if prompt_data.styles:
            full_prompt += ", " + ", ".join(prompt_data.styles)

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

        ref_images = []
        if reference_images:
            self.logger.info(
                f"Using reference image: {reference_images}"
            )
            for img_path in reference_images:
                if not img_path.exists():
                    raise FileNotFoundError(
                        f"Reference image not found: {img_path}"
                    )
                # Load the reference image
                ref_images.append(Image.open(img_path))

        config=types.GenerateContentConfig(
            response_modalities=['Text', 'Image'],
            temperature=temperature or self.temperature,
            system_instruction=prompt_instruction
        )

        try:
            start_time = time.time()
            content = [full_prompt, *ref_images] if ref_images else [full_prompt]
            # Use the asynchronous client for image generation
            if stateless:
                response = await self.client.aio.models.generate_content(
                    model=prompt_data.model,
                    contents=content,
                    config=config
                )
            else:
                # Create the stateful chat session
                chat = self.client.aio.chats.create(model=model, history=history, config=config)
                response = await chat.send_message(
                    message=content,
                )
            execution_time = time.time() - start_time

            pil_images = []
            saved_image_paths = []
            raw_response = {} # Initialize an empty dict for the raw response

            raw_response['generated_images'] = []
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    raw_response['text'] = part.text
                elif part.inline_data is not None:
                    image = Image.open(io.BytesIO(part.inline_data.data))
                    pil_images.append(image)
                    if output_directory:
                        if isinstance(output_directory, str):
                            output_directory = Path(output_directory).resolve()
                        file_path = self._save_image(image, output_directory)
                        saved_image_paths.append(file_path)
                        raw_response['generated_images'].append({
                            'uri': file_path,
                            'seed': None
                        })

            usage = CompletionUsage(execution_time=execution_time)
            if not stateless:
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_session,
                    messages + [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[Image Analysis]: {full_prompt}"}
                            ]
                        },
                    ],
                    None,
                    turn_id,
                    prompt_data.prompt,
                    response.text,
                    []
                )
            ai_message = AIMessageFactory.from_imagen(
                output=pil_images,
                images=saved_image_paths,
                input=full_prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                provider='nano-banana',
                usage=usage,
                raw_response=raw_response
            )
            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    def _upload_video(self, video_path: Union[str, Path]) -> str:
        """
        Uploads a video file to Google GenAi Client.
        """
        if isinstance(video_path, str):
            video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(
                f"Video file not found: {video_path}"
            )
        video_file = self.client.files.upload(
            file=video_path
        )
        while video_file.state == "PROCESSING":
            time.sleep(10)
            video_file = self.client.files.get(name=video_file.name)

        if video_file.state == "FAILED":
            raise ValueError(video_file.state)

        self.logger.debug(
            f"Uploaded video file: {video_file.uri}"
        )

        return video_file

    async def video_understanding(
        self,
        prompt: str,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = None,
        prompt_instruction: Optional[str] = None,
        video: Optional[Union[str, Path]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stateless: bool = True,
        offsets: Optional[tuple[str, str]] = None,
    ) -> AIMessage:
        """
        Using a video (local or youtube) no analyze and extract information from videos.
        """
        model = model.value if isinstance(model, GoogleModel) else model
        turn_id = str(uuid.uuid4())

        self.logger.info(
            f"Starting video analysis with model: {model}"
        )

        if stateless:
            # For stateless mode, skip conversation memory
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            # Use the unified conversation context preparation from AbstractClient
            messages, conversation_history, prompt_instruction = await self._prepare_conversation_context(
                prompt, None, user_id, session_id, prompt_instruction, stateless=stateless
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

        config=types.GenerateContentConfig(
            response_modalities=['Text'],
            temperature=temperature or self.temperature,
            system_instruction=prompt_instruction
        )

        if isinstance(video, str) and video.startswith("http"):
            # youtube video link:
            data = types.FileData(
                file_uri=video
            )
            video_metadata = None
            if offsets:
                video_metadata=types.VideoMetadata(
                    start_offset=offsets[0],
                    end_offset=offsets[1]
                )
            video_info = types.Part(
                file_data=data,
                video_metadata=video_metadata
            )
        else:
            video_info = self._upload_video(video)

        try:
            start_time = time.time()
            content = [
                types.Part(
                    text=prompt
                ),
                video_info
            ]
            # Use the asynchronous client for image generation
            if stateless:
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=content,
                    config=config
                )
            else:
                # Create the stateful chat session
                chat = self.client.aio.chats.create(model=model, history=history, config=config)
                response = await chat.send_message(
                    message=content,
                )
            execution_time = time.time() - start_time

            final_response = response.text

            usage = CompletionUsage(execution_time=execution_time)

            if not stateless:
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_history,
                    messages + [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[Image Analysis]: {prompt}"}
                            ]
                        },
                    ],
                    None,
                    turn_id,
                    prompt,
                    final_response,
                    []
                )
            # Create AIMessage using factory
            ai_message = AIMessageFactory.from_gemini(
                response=response,
                input_text=prompt,
                model=model,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                structured_output=final_response,
                tool_calls=None,
                conversation_history=conversation_history,
                text_response=final_response
            )

            # Override provider to distinguish from Vertex AI
            ai_message.provider = "google_genai"

            return ai_message

        except Exception as e:
            self.logger.error(f"Image generation failed: {e}")
            raise

    def _get_image_from_input(self, image: Union[str, Path, Image.Image]) -> Image.Image:
        """Helper to consistently load an image into a PIL object."""
        if isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        elif isinstance(image, bytes):
            return Image.open(io.BytesIO(image)).convert("RGB")
        else:
            return image.convert("RGB")

    def _crop_box(self, pil_img: Image.Image, box: DetectionBox) -> Image.Image:
        """Crops a detection box from a PIL image with a small padding."""
        # A small padding can provide more context to the model
        pad = 8
        x1 = max(0, box.x1 - pad)
        y1 = max(0, box.y1 - pad)
        x2 = min(pil_img.width, box.x2 + pad)
        y2 = min(pil_img.height, box.y2 + pad)
        return pil_img.crop((x1, y1, x2, y2))

    def _shelf_and_position(self, box: DetectionBox, regions: List[ShelfRegion]) -> Tuple[str, str]:
        """
        Determines the shelf and position for a given detection box using a robust
        centroid-based assignment logic.
        """
        if not regions:
            return "unknown", "center"

        # --- NEW LOGIC: Use the object's center point for assignment ---
        center_y = box.y1 + (box.y2 - box.y1) / 2
        best_region = None

        # 1. Primary Method: Find which shelf region CONTAINS the center point.
        for region in regions:
            if region.bbox.y1 <= center_y < region.bbox.y2:
                best_region = region
                break # Found the correct shelf

        # 2. Fallback Method: If no shelf contains the center (edge case), find the closest one.
        if not best_region:
            min_distance = float('inf')
            for region in regions:
                shelf_center_y = region.bbox.y1 + (region.bbox.y2 - region.bbox.y1) / 2
                distance = abs(center_y - shelf_center_y)
                if distance < min_distance:
                    min_distance = distance
                    best_region = region

        shelf = best_region.level if best_region else "unknown"

        # --- Position logic remains the same, it's correct ---
        if best_region:
            box_center_x = (box.x1 + box.x2) / 2.0
            shelf_width = best_region.bbox.x2 - best_region.bbox.x1
            third_width = shelf_width / 3.0
            left_boundary = best_region.bbox.x1 + third_width
            right_boundary = best_region.bbox.x1 + 2 * third_width

            if box_center_x < left_boundary:
                position = "left"
            elif box_center_x > right_boundary:
                position = "right"
            else:
                position = "center"
        else:
            position = "center"

        return shelf, position

    async def image_identification(
        self,
        prompt: str,
        image: Union[Path, bytes, Image.Image],
        detections: List[DetectionBox],
        shelf_regions: List[ShelfRegion],
        reference_images: Optional[Dict[str, Union[Path, bytes, Image.Image]]] = None,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_PRO,
        temperature: float = 0.0,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[IdentifiedProduct]:
        """
        Identify products using detected boxes, reference images, and Gemini Vision.

        This method sends the full image, reference images, and individual crops of each
        detection to Gemini for precise identification, returning a structured list of
        IdentifiedProduct objects.

        Args:
            image: The main image of the retail display.
            detections: A list of `DetectionBox` objects from the initial detection step.
            shelf_regions: A list of `ShelfRegion` objects defining shelf boundaries.
            reference_images: Optional list of images showing ideal products.
            model: The Gemini model to use, defaulting to Gemini 2.5 Pro for its advanced vision capabilities.
            temperature: The sampling temperature for the model's response.

        Returns:
            A list of `IdentifiedProduct` objects with detailed identification info.
        """
        self.logger.info(f"Starting Gemini identification for {len(detections)} detections.")
        model_name = model.value if isinstance(model, GoogleModel) else model

        # --- 1. Prepare Images and Metadata ---
        main_image_pil = self._get_image_from_input(image)
        detection_details = []
        id_to_details = {}
        for i, det in enumerate(detections, start=1):
            shelf, pos = self._shelf_and_position(det, shelf_regions)
            detection_details.append({
                "id": i,
                "detection": det,
                "shelf": shelf,
                "position": pos,
                "crop": self._crop_box(main_image_pil, det),
            })
            id_to_details[i] = {"shelf": shelf, "position": pos, "detection": det}

        # --- 2. Construct the Multi-Modal Prompt for Gemini ---
        # The prompt is a list of parts: text instructions, reference images,
        # the main image, and finally the individual crops.
        contents = [Part(text=prompt)] # Start with the user-provided prompt

        # --- Create a lookup map from ID to pre-calculated details ---
        id_to_details = {}
        for i, det in enumerate(detections, 1):
            shelf, pos = self._shelf_and_position(det, shelf_regions)
            id_to_details[i] = {"shelf": shelf, "position": pos, "detection": det}

        if reference_images:
            # Add a text part to introduce the references
            contents.append(Part(text="\n\n--- REFERENCE IMAGE GUIDE ---"))
            for label, ref_img_input in reference_images.items():
                # Add the label text, then the image
                contents.append(Part(text=f"Reference for '{label}':"))
                contents.append(self._get_image_from_input(ref_img_input))
            contents.append(Part(text="--- END REFERENCE GUIDE ---"))

        # Add the main image for overall context
        contents.append(main_image_pil)

        # Add each cropped detection image
        for item in detection_details:
            contents.append(item['crop'])

        for i, det in enumerate(detections, 1):
            contents.append(self._crop_box(main_image_pil, det))

        # Manually generate the JSON schema from the Pydantic model
        raw_schema = IdentificationResponse.model_json_schema()
        # Clean the schema to remove unsupported properties like 'additionalProperties'
        _schema = self.clean_google_schema(raw_schema)

        # --- 3. Configure the API Call for Structured Output ---
        generation_config = GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=8192, # Generous limit for JSON with many items
            response_mime_type="application/json",
            response_schema=_schema,
        )

        # --- 4. Call Gemini and Process the Response ---
        try:
            response = await self.client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=generation_config,
            )
        except Exception as e:
            # if is 503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.', 'status': 'UNAVAILABLE'}}
            # then, retry with a short delay but chaing to use gemini-2,5-flash instead pro.
            await asyncio.sleep(1.5)
            response = await self.client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=generation_config,
            )

        try:
            response_text = self._safe_extract_text(response)
            if not response_text:
                raise ValueError(
                    "Received an empty response from the model."
                )

            print('RAW RESPONSE:', response_text)
            # The model output should conform to the Pydantic model directly
            parsed_data = IdentificationResponse.model_validate_json(response_text)
            identified_items = parsed_data.identified_products

            # --- 5. Link LLM results back to original detections ---
            final_products = []
            for item in identified_items:
                # Case 1: Item was pre-detected (has a positive ID)
                if item.detection_id is not None and item.detection_id > 0 and item.detection_id in id_to_details:
                    details = id_to_details[item.detection_id]
                    item.detection_box = details["detection"]

                    # Only use geometric fallback if LLM didn't provide shelf_location
                    if not item.shelf_location:
                        self.logger.warning(
                            f"LLM did not provide shelf_location for ID {item.detection_id}. Using geometric fallback."
                        )
                        item.shelf_location = details["shelf"]
                    if not item.position_on_shelf:
                        item.position_on_shelf = details["position"]
                    final_products.append(item)

                # Case 2: Item was newly found by the LLM
                elif item.detection_id is None:
                    if item.detection_box:
                        # TRUST the LLM's assignment, only use geometric fallback if missing
                        if not item.shelf_location:
                            self.logger.info(f"LLM didn't provide shelf_location, calculating geometrically")
                            shelf, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                            item.shelf_location = shelf
                            item.position_on_shelf = pos
                        else:
                            # LLM provided shelf_location, trust it but calculate position if missing
                            self.logger.info(f"Using LLM-assigned shelf_location: {item.shelf_location}")
                            if not item.position_on_shelf:
                                _, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                                item.position_on_shelf = pos

                        self.logger.info(
                            f"Adding new object found by LLM: {item.product_type} on shelf '{item.shelf_location}'"
                        )
                        final_products.append(item)

                # Case 3: Item was newly found by the LLM (has a negative ID from our validator)
                elif item.detection_id < 0:
                    if item.detection_box:
                        # TRUST the LLM's assignment, only use geometric fallback if missing
                        if not item.shelf_location:
                            self.logger.info(f"LLM didn't provide shelf_location, calculating geometrically")
                            shelf, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                            item.shelf_location = shelf
                            item.position_on_shelf = pos
                        else:
                            # LLM provided shelf_location, trust it but calculate position if missing
                            self.logger.info(f"Using LLM-assigned shelf_location: {item.shelf_location}")
                            if not item.position_on_shelf:
                                _, pos = self._shelf_and_position(item.detection_box, shelf_regions)
                                item.position_on_shelf = pos

                        self.logger.info(f"Adding new object found by LLM: {item.product_type} on shelf '{item.shelf_location}'")
                        final_products.append(item)
                    else:
                        self.logger.warning(
                            f"LLM-found item with ID '{item.detection_id}' is missing a detection_box, skipping."
                        )

            self.logger.info(
                f"Successfully identified {len(final_products)} products."
            )
            return final_products

        except Exception as e:
            self.logger.error(
                f"Gemini image identification failed: {e}"
            )
            # Fallback to creating simple products from initial detections
            fallback_products = []
            for item in detection_details:
                shelf, pos = item["shelf"], item["position"]
                det = item["detection"]
                fallback_products.append(IdentifiedProduct(
                    detection_box=det,
                    detection_id=item['id'],
                    product_type=det.class_name,
                    product_model=None,
                    confidence=det.confidence * 0.5, # Lower confidence for fallback
                    visual_features=["fallback_identification"],
                    reference_match="none",
                    shelf_location=shelf,
                    position_on_shelf=pos
                ))
            return fallback_products

    async def create_speech(
        self,
        content: str,
        voice_name: Optional[str] = 'charon',
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH,
        output_directory: Optional[Path] = None,
        only_script: bool = False,
        script_file: str = "narration_script.txt",
        podcast_file: str= "generated_podcast.wav",
        mime_format: str = "audio/wav",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        language: str = "en-US"
    ) -> AIMessage:
        """
        Generates a simple narrative script from text and then converts it to speech.
        This is a simpler, two-step process for text-to-speech generation.

        Args:
            content (str): The text content to generate speech from.
            voice_name (Optional[str]): The name of the voice to use. Defaults to 'charon'.
            model (Union[str, GoogleModel]): The model for the text-to-text step.
            output_directory (Optional[Path]): Directory to save the audio file.
            mime_format (str): The audio format, e.g., 'audio/wav'.
            user_id (Optional[str]): Optional user identifier.
            session_id (Optional[str]): Optional session identifier.
            max_retries (int): Maximum network retries.
            retry_delay (float): Delay for retries.

        Returns:
            An AIMessage object containing the generated audio, the text script, and metadata.
        """
        self.logger.info(
            "Starting a two-step text-to-speech process."
        )
        # Step 1: Generate a simple, narrated script from the provided text.
        system_prompt = f"""
You are a professional scriptwriter. Given the input text, generate a clear, narrative style, suitable for a voiceover.

**Instructions:**
- The conversation should be engaging, natural, and suitable for a TTS system.
- The script should be formatted for TTS, with clear speaker lines.
"""
        script_prompt = f"""
Read the following text in a clear, narrative style, suitable for a voiceover.
Ensure the tone is neutral and professional. Do not add any conversational
elements. Just read the text.

Text:
---
{content}
---
"""
        script_text = ''
        script_response = None
        try:
            script_response = await self.ask(
                prompt=script_prompt,
                model=model,
                system_prompt=system_prompt,
                temperature=0.0,
                stateless=True,
                use_tools=False,
            )
            script_text = script_response.output
        except Exception as e:
            self.logger.error(f"Script generation failed: {e}")
            raise SpeechGenerationError(
                f"Script generation failed: {str(e)}"
            ) from e

        if not script_text:
            raise SpeechGenerationError(
                "Script generation failed, could not proceed with speech generation."
            )

        self.logger.info(f"Generated script text successfully.")
        saved_file_paths = []
        if only_script:
            # If only the script is needed, save it and return it in an AIMessage
            output_directory.mkdir(parents=True, exist_ok=True)
            script_path = output_directory / script_file
            try:
                async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
                    await f.write(script_text)
                self.logger.info(
                    f"Saved narration script to {script_path}"
                )
                saved_file_paths.append(script_path)
            except Exception as e:
                self.logger.error(f"Failed to save script file: {e}")
            ai_message = AIMessageFactory.from_gemini(
                response=script_response,
                text_response=script_text,
                input_text=content,
                model=model if isinstance(model, str) else model.value,
                user_id=user_id,
                session_id=session_id,
                files=saved_file_paths
            )
            return ai_message

        # Step 2: Generate speech from the generated script.
        speech_config_data = SpeechGenerationPrompt(
            prompt=script_text,
            speakers=[
                SpeakerConfig(
                    name="narrator",
                    voice=voice_name,
                )
            ],
            language=language
        )

        # Use the existing core logic to generate the audio
        model = GoogleModel.GEMINI_2_5_FLASH_TTS.value

        speaker = speech_config_data.speakers[0]
        final_voice = speaker.voice

        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=final_voice
                )
            ),
            language_code=speech_config_data.language or "en-US"
        )

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
            temperature=0.7
        )

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    delay = retry_delay * (2 ** (attempt - 1))
                    self.logger.info(
                        f"Retrying speech (attempt {attempt + 1}/{max_retries + 1}) after {delay}s delay..."
                    )
                    await asyncio.sleep(delay)
                start_time = time.time()
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=speech_config_data.prompt,
                    config=config,
                )
                execution_time = time.time() - start_time
                audio_data = self._extract_audio_data(response)
                if audio_data is None:
                    raise SpeechGenerationError(
                        "No audio data found in response. The speech generation may have failed."
                    )

                saved_file_paths = []
                if output_directory:
                    output_directory.mkdir(parents=True, exist_ok=True)
                    podcast_path = output_directory / podcast_file
                    script_path = output_directory / script_file
                    self._save_audio_file(audio_data, podcast_path, mime_format)
                    saved_file_paths.append(podcast_path)
                    try:
                        async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
                            await f.write(script_text)
                        self.logger.info(f"Saved narration script to {script_path}")
                        saved_file_paths.append(script_path)
                    except Exception as e:
                        self.logger.error(f"Failed to save script file: {e}")

                usage = CompletionUsage(
                    execution_time=execution_time,
                    input_tokens=len(script_text),
                )

                ai_message = AIMessageFactory.from_speech(
                    output=audio_data,
                    files=saved_file_paths,
                    input=script_text,
                    model=model,
                    provider="google_genai",
                    documents=[script_path],
                    usage=usage,
                    user_id=user_id,
                    session_id=session_id,
                    raw_response=None
                )
                return ai_message

            except (
                aiohttp.ClientPayloadError,
                aiohttp.ClientConnectionError,
                aiohttp.ClientResponseError,
                aiohttp.ServerTimeoutError,
                ConnectionResetError,
                TimeoutError,
                asyncio.TimeoutError
            ) as network_error:
                if attempt < max_retries:
                    self.logger.warning(
                        f"Network error on attempt {attempt + 1}: {str(network_error)}. Retrying..."
                    )
                    continue
                else:
                    self.logger.error(
                        f"Speech generation failed after {max_retries + 1} attempts"
                    )
                    raise SpeechGenerationError(
                        f"Speech generation failed after {max_retries + 1} attempts. "
                        f"Last error: {str(network_error)}."
                    ) from network_error

            except Exception as e:
                self.logger.error(
                    f"Speech generation failed with non-retryable error: {str(e)}"
                )
                raise SpeechGenerationError(
                    f"Speech generation failed: {str(e)}"
                ) from e

    async def video_generation(
        self,
        prompt_data: Union[str, VideoGenerationPrompt],
        model: Union[str, GoogleModel] = GoogleModel.VEO_3_0,
        reference_image: Optional[Path] = None,
        generate_image_first: bool = False,
        image_prompt: Optional[str] = None,
        image_generation_model: str = "imagen-4.0-generate-001",
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        output_directory: Optional[Path] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stateless: bool = True,
        poll_interval: int = 10
    ) -> AIMessage:
        """
        Generates videos based on a text prompt using Veo models.

        Args:
            prompt_data: Text prompt or VideoGenerationPrompt object
            model: Video generation model (VEO_2_0 or VEO_3_0)
            reference_image: Optional path to reference image. If provided, this takes precedence.
            generate_image_first: If True and no reference_image, generates an image with Imagen first
            image_generation_model: Model to use for image generation (default: imagen-4.0-generate-001)
            aspect_ratio: Video aspect ratio (e.g., "16:9", "9:16"). Overrides prompt_data setting.
            resolution: Video resolution (e.g., "720p", "1080p"). Overrides prompt_data setting.
            negative_prompt: What to avoid in the video. Overrides prompt_data setting.
            output_directory: Directory to save generated videos
            user_id: User ID for conversation tracking
            session_id: Session ID for conversation tracking
            stateless: If True, no conversation memory is saved
            poll_interval: Seconds between polling checks (default: 10)

        Returns:
            AIMessage containing the generated video
        """
        # Parse prompt data
        if isinstance(prompt_data, str):
            prompt_data = VideoGenerationPrompt(
                prompt=prompt_data,
                model=model.value if isinstance(model, GoogleModel) else model,
            )

        # Validate and set model
        if prompt_data.model:
            model = prompt_data.model
        model = model.value if isinstance(model, GoogleModel) else model

        if model not in [GoogleModel.VEO_2_0.value, GoogleModel.VEO_3_0.value, GoogleModel.VEO_3_0_FAST.value]:
            raise ValueError(
                f"Video generation only supported with VEO 2.0 or VEO 3.0 models. Got: {model}"
            )

        # Setup output directory
        if output_directory:
            if isinstance(output_directory, str):
                output_directory = Path(output_directory).resolve()
            output_directory.mkdir(parents=True, exist_ok=True)
        else:
            output_directory = BASE_DIR.joinpath('static', 'generated_videos')
            output_directory.mkdir(parents=True, exist_ok=True)

        turn_id = str(uuid.uuid4())

        self.logger.info(
            f"Starting video generation with model: {model}"
        )

        # Prepare conversation context if not stateless
        if not stateless:
            messages, conversation_session, _ = await self._prepare_conversation_context(
                prompt_data.prompt, None, user_id, session_id, None
            )
        else:
            messages = None
            conversation_session = None

        # Override prompt settings with explicit parameters
        final_aspect_ratio = aspect_ratio or prompt_data.aspect_ratio or "16:9"
        final_resolution = resolution or getattr(prompt_data, 'resolution', None) or "720p"
        final_negative_prompt = negative_prompt or prompt_data.negative_prompt or ""

        # Step 1: Handle image input (reference or generate)
        generated_image = None
        image_for_video = None

        if reference_image:
            self.logger.info(
                f"Using reference image: {reference_image}"
            )
            if not reference_image.exists():
                raise FileNotFoundError(f"Reference image not found: {reference_image}")

            # VEO 3.0 doesn't support reference images, fall back to VEO 2.0
            # if model == GoogleModel.VEO_3_0.value:
            #     self.logger.warning(
            #         "VEO 3.0 does not support reference images. Switching to VEO 2.0."
            #     )
            #     model = GoogleModel.VEO_3_0_FAST

            # Load reference image
            ref_image_pil = Image.open(reference_image)
            # Convert PIL Image to bytes for Google GenAI API
            img_byte_arr = io.BytesIO()
            ref_image_pil.save(img_byte_arr, format=ref_image_pil.format or 'JPEG')
            img_byte_arr.seek(0)
            image_bytes = img_byte_arr.getvalue()

            image_for_video = types.Image(
                image_bytes=image_bytes,
                mime_type=f"image/{(ref_image_pil.format or 'jpeg').lower()}"
            )

        elif generate_image_first:
            self.logger.info(
                f"Generating image first with {image_generation_model} before video generation"
            )

            try:
                # Generate image using Imagen
                image_config = types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/jpeg",
                    aspect_ratio=final_aspect_ratio
                )

                gen_prompt = image_prompt or prompt_data.prompt

                image_response = await self.client.aio.models.generate_images(
                    model=image_generation_model,
                    prompt=gen_prompt,
                    config=image_config
                )

                if image_response.generated_images:
                    generated_image = image_response.generated_images[0]
                    self.logger.info(
                        "Successfully generated reference image for video"
                    )

                    # Convert generated image to format needed for video generation
                    pil_image = generated_image.image
                    # can we use directly because is a google.genai.types.Image
                    image_for_video = pil_image
                    # Also, save the generated image to output directory:
                    gen_image_path = output_directory / f"generated_image_{turn_id}.jpg"
                    pil_image.save(gen_image_path)
                    self.logger.info(
                        f"Saved generated reference image to: {gen_image_path}"
                    )

                    # VEO 3.0 doesn't support reference images
                    if model == GoogleModel.VEO_3_0.value:
                        self.logger.warning(
                            "VEO 3.0 does not support reference images. Switching to VEO 3.0 FAST"
                        )
                        model = GoogleModel.VEO_3_0_FAST
                else:
                    raise Exception("Image generation returned no images")

            except Exception as e:
                self.logger.error(f"Image generation failed: {e}")
                raise Exception(f"Failed to generate reference image: {e}")

        # Step 2: Generate video
        self.logger.info(f"Generating video with prompt: '{prompt_data.prompt[:100]}...'")

        try:
            start_time = time.time()

            # Prepare video generation arguments
            video_args = {
                "model": model,
                "prompt": prompt_data.prompt,
            }

            if image_for_video:
                video_args["image"] = image_for_video

            # Create config with all parameters
            video_config = types.GenerateVideosConfig(
                aspect_ratio=final_aspect_ratio,
                number_of_videos=prompt_data.number_of_videos or 1,
            )

            # Add resolution if supported (check model capabilities)
            if final_resolution:
                video_config.resolution = final_resolution

            # Add negative prompt if provided
            if final_negative_prompt:
                video_config.negative_prompt = final_negative_prompt

            video_args["config"] = video_config

            # Start async video generation operation
            self.logger.info("Starting async video generation operation...")
            operation = await self.client.aio.models.generate_videos(**video_args)

            # Step 3: Poll operation status asynchronously
            self.logger.info(
                f"Polling video generation status every {poll_interval} seconds..."
            )
            spinner_chars = ['|', '/', '-', '\\']
            spinner_index = 0
            poll_count = 0

            # This loop checks the job status every poll_interval seconds
            while not operation.done:
                poll_count += 1
                # This inner loop runs the spinner animation for the poll_interval
                for _ in range(poll_interval):
                    # Write the spinner character to the console
                    sys.stdout.write(
                        f"\rVideo generation job started. Waiting for completion... {spinner_chars[spinner_index]}"
                    )
                    sys.stdout.flush()
                    spinner_index = (spinner_index + 1) % len(spinner_chars)
                    await asyncio.sleep(1)  # Animate every second (async version)

                # After poll_interval seconds, get the updated operation status
                operation = await self.client.aio.operations.get(operation)

            print("\rVideo generation job completed.          ", end="")
            sys.stdout.flush()

            execution_time = time.time() - start_time
            self.logger.info(
                f"Video generation completed in {execution_time:.2f}s after {poll_count} polls"
            )

            # Step 4: Download and save videos using bytes download
            generated_videos = operation.response.generated_videos

            if not generated_videos:
                raise Exception("Video generation completed but no videos were returned")

            saved_video_paths = []
            raw_response = {'generated_videos': []}

            for n, generated_video in enumerate(generated_videos):
                # Download the video bytes (MP4)
                # NOTE: Use sync client for file download as aio may not support it
                mp4_bytes = self.client.files.download(file=generated_video.video)

                # Save video to file using helper method
                video_path = self._save_video_file(
                    mp4_bytes,
                    output_directory,
                    video_number=n,
                    mime_format='video/mp4'
                )
                saved_video_paths.append(str(video_path))

                self.logger.info(f"Saved video to: {video_path}")

                # Collect metadata
                raw_response['generated_videos'].append({
                    'path': str(video_path),
                    'duration': getattr(generated_video, 'duration', None),
                    'uri': getattr(generated_video, 'uri', None),
                })

            # Step 5: Update conversation memory if not stateless
            usage = CompletionUsage(
                execution_time=execution_time,
                # Video API does not return token counts, use approximation
                input_tokens=len(prompt_data.prompt),
            )

            if not stateless and conversation_session:
                await self._update_conversation_memory(
                    user_id,
                    session_id,
                    conversation_session,
                    messages + [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"[Video Generation]: {prompt_data.prompt}"}
                            ]
                        },
                    ],
                    None,
                    turn_id,
                    prompt_data.prompt,
                    f"Generated {len(saved_video_paths)} video(s)",
                    []
                )

            # Step 6: Create and return AIMessage using the factory
            ai_message = AIMessageFactory.from_video(
                output=operation,  # The raw operation response object
                files=saved_video_paths,  # List of saved video file paths
                input=prompt_data.prompt,
                model=model,
                provider="google_genai",
                usage=usage,
                user_id=user_id,
                session_id=session_id,
                raw_response=None  # Response object isn't easily serializable
            )

            # Add metadata about the generation
            ai_message.metadata = {
                'aspect_ratio': final_aspect_ratio,
                'resolution': final_resolution,
                'negative_prompt': final_negative_prompt,
                'reference_image_used': reference_image is not None or generate_image_first,
                'image_generation_used': generate_image_first,
                'poll_count': poll_count,
                'execution_time': execution_time
            }

            self.logger.info(
                f"Video generation successful: {len(saved_video_paths)} video(s) created"
            )

            return ai_message

        except Exception as e:
            self.logger.error(f"Video generation failed: {e}", exc_info=True)
            raise

    def _save_video_file(
        self,
        video_bytes: bytes,
        output_directory: Path,
        video_number: int = 0,
        mime_format: str = "video/mp4"
    ) -> Path:
        """
        Helper method to save video bytes to disk.

        Args:
            video_bytes: Raw video bytes from the API
            output_directory: Directory to save the video
            video_number: Index number for the video filename
            mime_format: MIME type of the video (default: video/mp4)

        Returns:
            Path to saved video file
        """
        # Generate filename based on timestamp and video number
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"video_{timestamp}_{video_number}.mp4"

        video_path = output_directory / filename

        # Write bytes to file
        with open(video_path, 'wb') as f:
            f.write(video_bytes)

        self.logger.info(f"Saved {len(video_bytes)} bytes to {video_path}")

        return video_path


GoogleClient = GoogleGenAIClient  # Alias for easier imports
