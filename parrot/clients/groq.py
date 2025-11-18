import traceback
from typing import AsyncIterator, List, Optional, Union, Any
from pathlib import Path
from logging import getLogger
import uuid
import time
import json
from dataclasses import is_dataclass
from pydantic import BaseModel, TypeAdapter
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig import config
from groq import AsyncGroq
from .base import AbstractClient
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    StructuredOutputConfig,
    OutputFormat,
)
from ..models.groq import GroqModel
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)


getLogger('httpx').setLevel('WARNING')
getLogger('httpcore').setLevel('WARNING')
getLogger('groq').setLevel('INFO')


STRUCTURED_OUTPUT_COMPATIBLE_MODELS = {
    GroqModel.LLAMA_4_SCOUT_17B.value,
    GroqModel.LLAMA_4_MAVERICK_17B.value,
    GroqModel.KIMI_K2_INSTRUCT.value,
    GroqModel.OPENAI_GPT_OSS_SAFEGUARD_20B.value,
    GroqModel.OPENAI_GPT_OSS_20B.value,
    GroqModel.OPENAI_GPT_OSS_120B.value,
}


class GroqClient(AbstractClient):
    """Client for interacting with Groq's API.

    Note: Groq has a limitation where structured output (JSON mode) cannot be
    combined with tool calling in the same request. When both are requested,
    this client handles tools first, then makes a separate request for
    structured output formatting.

    """

    client_type: str = "groq"
    client_name: str = "groq"
    model: str = GroqModel.LLAMA_3_3_70B_VERSATILE

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://api.groq.com/openai/v1",
        **kwargs
    ):
        self.api_key = api_key or config.get('GROQ_API_KEY')
        self.base_url = base_url
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        super().__init__(**kwargs)
        self.client = AsyncGroq(api_key=self.api_key)

    def _fix_schema_for_groq(self, schema: dict) -> dict:
        """
        Fix JSON schema to comply with Groq's structured-output validator.

        - Start from the OpenAI-normalized schema (handles additionalProperties, required, etc.).
        - Collapse Optional[T] patterns:
            anyOf: [T, {"type": "null"}]  ->  T (keeping default/title/description).
        - Resolve Groq's ambiguity with integer vs number:
            anyOf: [{"type": "integer"}, {"type": "number"}, ...] -> drop "integer".
        - Drop some scalar constraints Groq doesn't care about.
        """
        # First apply your generic OpenAI-style normalization
        schema = self._oai_normalize_schema(schema)

        unsupported_constraints = [
            "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
            "minLength", "maxLength", "pattern", "format",
            "minItems", "maxItems", "uniqueItems",
            "minProperties", "maxProperties",
        ]

        def visit(node):
            if isinstance(node, dict):
                # Drop constraints Groq doesn't care about
                for c in unsupported_constraints:
                    node.pop(c, None)

                # --- Handle anyOf ---
                if "anyOf" in node and isinstance(node["anyOf"], list):
                    variants = node["anyOf"]

                    # 1) Fix integer/number overlap for Groq
                    type_variants = [
                        v.get("type") for v in variants
                        if isinstance(v, dict) and "type" in v
                    ]
                    if "number" in type_variants and "integer" in type_variants:
                        new_variants = []
                        for v in variants:
                            if isinstance(v, dict) and v.get("type") == "integer":
                                # drop integer variant when number is also present
                                continue
                            new_variants.append(v)
                        variants = new_variants
                        node["anyOf"] = variants

                    # 2) Collapse Optional[T] pattern: anyOf: [T, {"type": "null"}]
                    non_null = [
                        v for v in variants
                        if not (isinstance(v, dict) and v.get("type") == "null")
                    ]
                    nulls = [
                        v for v in variants
                        if isinstance(v, dict) and v.get("type") == "null"
                    ]

                    if len(non_null) == 1 and len(nulls) >= 1:
                        base = visit(non_null[0])  # recurse into T

                        # Preserve metadata from wrapper (title, default, description...)
                        for k, v in list(node.items()):
                            if k == "anyOf":
                                continue
                            base.setdefault(k, v)

                        node.clear()
                        node.update(base)
                    else:
                        # Just recurse into each variant
                        node["anyOf"] = [visit(v) for v in variants]

                # Recurse into object properties / patternProperties
                for key in ("properties", "patternProperties"):
                    if key in node and isinstance(node[key], dict):
                        for k, v in list(node[key].items()):
                            node[key][k] = visit(v)

                # Recurse into items (array element schemas)
                if "items" in node and isinstance(node["items"], (dict, list)):
                    node["items"] = visit(node["items"])

                # Recurse into combinators other than anyOf
                for key in ("allOf", "oneOf"):
                    if key in node and isinstance(node[key], list):
                        node[key] = [visit(v) for v in node[key]]

                # 🔴 IMPORTANT: recurse into $defs / definitions (this is what was missing)
                for key in ("$defs", "definitions"):
                    if key in node and isinstance(node[key], dict):
                        for k, v in list(node[key].items()):
                            node[key][k] = visit(v)

            elif isinstance(node, list):
                return [visit(v) for v in node]

            return node

        return visit(dict(schema))

    def _prepare_groq_tools(self) -> List[dict]:
        """Convert registered tools to Groq format."""
        groq_tools = []
        for tool in self.tool_manager.all_tools():
            tool_name = tool.name if hasattr(tool, 'name') else tool.__class__.__name__
            print(f":::: Preparing tool: {tool_name}")
            # Fix the tool schema for Groq
            if hasattr(tool, 'input_schema'):
                # Convert dict schema to Groq-compliant schema
                fixed_schema = self._fix_schema_for_groq(tool.input_schema)
            elif hasattr(tool, 'get_tool_schema'):
                # Handle Pydantic model schemas
                fixed_schema = self._fix_schema_for_groq(
                    tool.get_tool_schema()
                )
            else:
                fixed_schema = {}

            groq_tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool.description,
                    "parameters": fixed_schema
                }
            })
        return groq_tools

    def _prepare_structured_output_format(self, structured_output: type) -> dict:
        if not structured_output:
            return {}

        # Normalize instance → class
        if isinstance(structured_output, BaseModel):
            structured_output = structured_output.__class__
        if is_dataclass(structured_output) and not isinstance(structured_output, type):
            structured_output = structured_output.__class__

        # Pydantic models
        if isinstance(structured_output, type) and hasattr(structured_output, 'model_json_schema'):
            schema = structured_output.model_json_schema()
            fixed_schema = self._fix_schema_for_groq(schema)
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": fixed_schema,
                        "strict": True
                    }
                }
            }

        # Dataclasses
        if is_dataclass(structured_output):
            schema = TypeAdapter(structured_output).json_schema()
            fixed_schema = self._fix_schema_for_groq(schema)
            return {
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": structured_output.__name__.lower(),
                        "schema": fixed_schema,
                        "strict": True
                    }
                }
            }

        # Fallback
        return {"response_format": {"type": "json_object"}}

    async def ask(
        self,
        prompt: str,
        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        use_tools: Optional[bool] = None,
        use_code_interpreter: Optional[bool] = None
    ) -> AIMessage:
        """Ask Groq a question with optional conversation memory."""
        model = model.value if isinstance(model, GroqModel) else model
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = prompt
        _use_tools = use_tools if use_tools is not None else self.enable_tools

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare tools
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
        if _use_tools:
            tools = self._prepare_groq_tools()
        else:
            tools = None

        # Groq doesn't support combining structured output with tools
        # Priority: tools first, then structured output in separate request if needed
        output_config = self._get_structured_config(
            structured_output
        )
        use_tools = _use_tools
        use_structured_output = bool(output_config)

        if use_structured_output and model not in STRUCTURED_OUTPUT_COMPATIBLE_MODELS:
            self.logger.error(
                f"The model '{model}' does not support structured output. "
                "Please choose a compatible model."
            )
            model = GroqModel.LLAMA_4_SCOUT_17B.value

        structured_output_for_later: Optional[StructuredOutputConfig] = None
        request_output_config: Optional[StructuredOutputConfig] = output_config

        if use_tools and use_structured_output:
            # Handle tools first, structured output later
            structured_output_for_later = output_config
            request_output_config = None

        # Track tool calls for the response
        all_tool_calls = []

        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False
        }

        if use_tools and not use_structured_output:
            request_args["tool_choice"] = "auto"
            request_args["tools"] = tools or []
            # Enable parallel tool calls for supported models
            if model != getattr(GroqModel, "GEMMA2_9B_IT", None) and \
               model != getattr(GroqModel, "GEMMA2_9B_IT", "google/gemma-2-9b-it"):
                request_args["parallel_tool_calls"] = True
        elif use_code_interpreter:
            if model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b"):
                request_args["tool_choice"] = "required"
                request_args["tools"] = [
                    {
                        "type": "browser_search"
                    },
                    {
                        "type": "code_interpreter"
                    }
                ]

        # Add structured output format if no tools
        if request_output_config and not use_tools:
            self._ensure_json_instruction(
                messages,
                "Please respond with a valid JSON object that matches the requested schema."
            )
            if request_output_config.format == OutputFormat.JSON:
                if output_type := request_output_config.output_type:
                    request_args.update(
                        self._prepare_structured_output_format(output_type)
                    )
                else:
                    request_args["response_format"] = {"type": "json_object"}

        # Make initial request
        response = await self.client.chat.completions.create(**request_args)
        result = response.choices[0].message

        # Handle tool calls in a loop (only if tools were enabled)
        if use_tools:
            # Keep track of conversation turns
            conversation_turns = 0
            max_turns = 10  # Prevent infinite loops

            while result.tool_calls and conversation_turns < max_turns:
                conversation_turns += 1

                # Add the assistant's message with tool calls to conversation
                messages.append({
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in result.tool_calls
                    ]
                })

                # Execute each tool call
                for tool_call in result.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = self._json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = json_decoder(tool_call.function.arguments)

                    # Create ToolCall object and execute
                    tc = ToolCall(
                        id=tool_call.id,
                        name=tool_name,
                        arguments=tool_args
                    )

                    try:
                        start_time = time.time()
                        tool_result = await self._execute_tool(tool_name, tool_args)
                        execution_time = time.time() - start_time
                        tc.result = tool_result
                        tc.execution_time = execution_time

                        # Add tool result to conversation
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": str(tool_result)
                        })
                    except Exception as e:
                        tc.error = str(e)
                        trace = traceback.format_exc()
                        # Add error to conversation
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": f"Error: {str(e)}",
                            "traceback": trace
                        })

                    all_tool_calls.append(tc)

                # Continue conversation with tool results to get final response
                continue_args = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": top_p,
                    "stream": False,
                }

                # Only add tools if we want to allow further tool calls
                # For final response, we might want to remove tools to force a text response
                if conversation_turns < max_turns - 1:  # Allow more tool calls if not at limit
                    continue_args["tools"] = tools
                    continue_args["tool_choice"] = "auto"
                    if model != GroqModel.GEMMA2_9B_IT:
                        continue_args["parallel_tool_calls"] = True
                else:
                    # Force final response without more tool calls
                    continue_args["tool_choice"] = "none"

                response = await self.client.chat.completions.create(**continue_args)
                result = response.choices[0].message

        # Handle structured output after tools if needed
        final_output = None
        parsed_config: Optional[StructuredOutputConfig] = None
        if structured_output_for_later and use_tools:
            # Add the final tool response to messages
            if result.content:
                messages.append({
                    "role": "assistant",
                    "content": result.content
                })

            # Make a new request for structured output
            json_followup_instruction = (
                "Please format the above response as valid JSON that matches the requested structure."
            )
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": json_followup_instruction}]
            })

            self._ensure_json_instruction(messages, json_followup_instruction)

            structured_args = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": False
            }

            if structured_output_for_later.format == OutputFormat.JSON:
                output_type = structured_output_for_later.output_type
                if output_type:
                    structured_args.update(
                        self._prepare_structured_output_format(output_type)
                    )
                else:
                    structured_args["response_format"] = {"type": "json_object"}

            structured_response = await self.client.chat.completions.create(**structured_args)
            result = structured_response.message if hasattr(
                structured_response,
                'message'
            ) else structured_response.choices[0].message

            parsed_config = structured_output_for_later
        else:
            parsed_config = request_output_config

        response_text = result.content if isinstance(result.content, str) else self._json.dumps(result.content)
        if parsed_config:
            try:
                final_output = await self._parse_structured_output(
                    response_text,
                    parsed_config
                )
            except Exception:  # pylint: disable=broad-except
                final_output = response_text
        else:
            final_output = result.content

        # Add final assistant message to conversation (if not already added)
        if not (use_tools and result.content):  # Only add if we haven't already added it in tool handling
            messages.append({
                "role": "assistant",
                "content": result.content or ""
            })

        # Update conversation memory
        tools_used = [tc.name for tc in all_tool_calls]
        assistant_response_text = result.content if isinstance(
            result.content, str) else self._json.dumps(result.content)
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            assistant_response_text,
            tools_used
        )

        # Create AIMessage using factory
        structured_payload = None
        if parsed_config and final_output is not None and not (
            isinstance(final_output, str) and final_output == response_text
        ):
            structured_payload = final_output

        ai_message = AIMessageFactory.from_groq(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=structured_payload
        )

        # Add tool calls to the response
        ai_message.tool_calls = all_tool_calls

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        top_p: float = 0.9,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[dict]] = None
    ) -> AsyncIterator[str]:
        """Stream Groq's response with optional conversation memory."""

        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        model = model.value if isinstance(model, GroqModel) else model

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True
        }

        # Note: For streaming, we don't handle tools in this version
        # You might want to implement a more sophisticated streaming + tools handler
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)
        # Prepare tools for the request
        tools = self._prepare_groq_tools()
        if tools:
            request_args["tools"] = tools
            request_args["tool_choice"] = "auto"

        response_stream = await self.client.chat.completions.create(**request_args)

        assistant_content = ""
        async for chunk in response_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                text_chunk = chunk.choices[0].delta.content
                assistant_content += text_chunk
                yield text_chunk

        # Update conversation memory if content was generated
        if assistant_content:
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })
            # Update conversation memory
            tools_used = []
            await self._update_conversation_memory(
                user_id,
                session_id,
                conversation_session,
                messages,
                system_prompt,
                turn_id,
                prompt,
                assistant_content,
                tools_used
            )

    async def batch_ask(self, requests):
        """Process multiple requests in batch."""
        return await super().batch_ask(requests)

    async def summarize_text(
        self,
        text: str,
        model: str = GroqModel.LLAMA_3_3_70B_VERSATILE,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
        top_p: float = 0.9,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> AIMessage:
        """Summarize the given text using Groq API.

        Args:
            text (str): The text to be summarized.
            model (str): The Groq model to use.
            max_tokens (int): Maximum tokens for the response.
            temperature (float): Sampling temperature.
            top_p (float): Top-p sampling.

        Returns:
            str: The summarized text.
        """
        # Generate unique turn ID for tracking
        turn_id = str(uuid.uuid4())
        original_prompt = text
        model = model.value if isinstance(model, GroqModel) else model

        system_prompt = system_prompt or "Summarize the following text:"

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            original_prompt, None, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }

        # Make request to Groq API
        response = await self.client.chat.completions.create(**request_args)
        result = response.choices[0].message

        # Extract summarized text
        summarized_text = result.content

        # Add final assistant message to conversation
        messages.append({
            "role": "assistant",
            "content": result.content
        })

        # Update conversation memory
        tools_used = []
        # return only 100 characters of the summarized text
        assistant_content = summarized_text[:100] if summarized_text else ""
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            'summarization',
            assistant_content,
            tools_used
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_groq(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=summarized_text
        )

        return ai_message

    async def analyze_sentiment(
        self,
        text: str,
        model: Union[GroqModel, str] = GroqModel.KIMI_K2_INSTRUCT,
        temperature: Optional[float] = 0.1,
        max_tokens: int = 1024,
        top_p: float = 0.9,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False
    ) -> AIMessage:
        """
        Analyze the sentiment of a given text.

        Args:
            text (str): The text content to analyze.
            model (Union[GroqModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        model = model.value if isinstance(model, GroqModel) else model

        turn_id = str(uuid.uuid4())
        original_prompt = text

        if use_structured:
            system_prompt = (
                "You are a sentiment analysis expert. Analyze the sentiment of the given text "
                "and respond with structured data including sentiment classification, "
                "confidence level, emotional indicators, and reasoning."
            )
        else:
            system_prompt = """
Analyze the sentiment of the following text and provide a structured response.
Your response should include:
1. Overall sentiment (Positive, Negative, Neutral, or Mixed)
2. Confidence level (High, Medium, Low)
3. Key emotional indicators found in the text
4. Brief explanation of your analysis
Format your response clearly with these sections.
            """

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            original_prompt, None, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare request arguments
        request_args = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }

        # Add structured output if requested
        structured_output = None
        if use_structured:
            request_args.update(
                self._prepare_structured_output_format(SentimentAnalysis)
            )
            structured_output = SentimentAnalysis

        # Make request to Groq API
        response = await self.client.chat.completions.create(**request_args)
        result = response.choices[0].message

        # Extract sentiment analysis result
        sentiment_result = result.content

        # Add final assistant message to conversation
        messages.append({
            "role": "assistant",
            "content": result.content
        })


        # Handle structured output
        final_output = None
        if structured_output:
            # Prepare structured output configuration
            output_config = self._get_structured_config(structured_output)
            try:
                final_output = await self._parse_structured_output(
                    result.content,
                    output_config
                )
            except Exception:
                final_output = result.content

        # Update conversation memory
        tools_used = []
        # return only 100 characters of the sentiment analysis result
        assistant_content = sentiment_result[:100] if sentiment_result else ""
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            'sentiment_analysis',
            assistant_content,
            tools_used
        )

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_groq(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output is not None else sentiment_result,
        )

        return ai_message

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[GroqModel, str] = GroqModel.KIMI_K2_INSTRUCT,
        temperature: Optional[float] = 0.1,
        max_tokens: int = 1024,
        top_p: float = 0.9,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured information.

        Args:
            review_text (str): The product review text to analyze.
            product_id (str): Unique identifier for the product.
            product_name (str): Name of the product being reviewed.
            model (Union[GroqModel, str]): The model to use.
            temperature (float): Sampling temperature for response generation.
            max_tokens (int): Maximum tokens in response.
            top_p (float): Top-p sampling parameter.
            user_id (Optional[str]): Optional user identifier for tracking.
            session_id (Optional[str]): Optional session identifier for tracking.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")

        turn_id = str(uuid.uuid4())
        original_prompt = review_text
        model = model.value if isinstance(model, GroqModel) else model

        system_prompt = (
            f"You are a product review analysis expert. Analyze the given product review "
            f"for '{product_name}' (ID: {product_id}) and extract structured information "
            f"including sentiment, rating, and key features mentioned in the review."
        )

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            original_prompt, None, user_id, session_id, system_prompt
        )

        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        # Prepare request arguments with structured output
        request_args = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}"},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }

        # Add structured output format
        request_args.update(self._prepare_structured_output_format(ProductReview))

        # Make request to Groq API
        response = await self.client.chat.completions.create(**request_args)
        result = response.choices[0].message

        # Add final assistant message to conversation
        messages.append({
            "role": "assistant",
            "content": result.content
        })

        # Update conversation memory
        tools_used = []
        assistant_content = result.content[:100] if result.content else ""
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            'product_review_analysis',
            assistant_content,
            tools_used
        )
        # Handle structured output
        final_output = None
        # Prepare structured output configuration
        output_config = self._get_structured_config(ProductReview)
        try:
            final_output = await self._parse_structured_output(
                result.content,
                output_config
            )
        except Exception:
            final_output = result.content

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_groq(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output is not None else result.content,
        )

        return ai_message
