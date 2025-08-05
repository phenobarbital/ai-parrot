from typing import AsyncIterator, Dict, List, Optional, Union, Any
import time
import asyncio
from pathlib import Path
import uuid
import io
from PIL import Image
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import (
    GenerativeModel,
    Part,
    Tool,
    FunctionDeclaration,
    Content,
    GenerationConfig
)
from navconfig import config, BASE_DIR
from .base import AbstractClient, ToolDefinition, StreamingRetryConfig
from ..models import (
    AIMessage,
    AIMessageFactory,
    ToolCall,
    CompletionUsage,
    StructuredOutputConfig,
    OutputFormat,
    ObjectDetectionResult
)
from ..models.google import VertexAIModel
from ..tools.abstract import AbstractTool
from ..models.outputs import (
    SentimentAnalysis,
    ProductReview
)


class VertexAIClient(AbstractClient):
    """
    Client for interacting with Google's Vertex AI with full feature parity.
    """
    client_type: str = "vertexai"

    def __init__(self, **kwargs):
        project_id = kwargs.pop('project_id', config.get("VERTEX_PROJECT_ID"))
        region = kwargs.pop('region', config.get("VERTEX_REGION"))
        config_file = kwargs.pop(
            'config_file',
            config.get('GOOGLE_CREDENTIALS_FILE', 'env/google/vertexai.json')
        )

        config_dir = BASE_DIR.joinpath(config_file)
        self.vertex_credentials = service_account.Credentials.from_service_account_file(
            str(config_dir)
        )
        vertexai.init(
            project=project_id,
            location=region,
            credentials=self.vertex_credentials
        )
        super().__init__(**kwargs)

    async def __aenter__(self):
        """Initialize the client context."""
        # Vertex AI doesn't need explicit session management
        return self

    def _extract_usage_from_response(self, response) -> Dict[str, Any]:
        """Extract usage metadata from Vertex AI response."""
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            return {
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count
            }
        return {}

    def _build_tools(self) -> Optional[List[Tool]]:
        """Build tools for Vertex AI format."""
        if not self.tools:
            return None

        function_declarations = []
        for tool_name, tool in self.tools.items():
            if isinstance(tool, AbstractTool):
                full_schema = tool.get_tool_schema()
                tool_description = full_schema.get("description", tool.description)
                # Extract ONLY the parameters part
                schema = full_schema.get("parameters", {}).copy()
                try:
                    del schema['additionalProperties']
                except KeyError:
                    pass
            elif isinstance(tool, ToolDefinition):
                tool_description = tool.description
                schema = tool.input_schema
            else:
                # Fallback for other tool types
                tool_description = getattr(tool, 'description', f"Tool: {tool_name}")
                schema = getattr(tool, 'input_schema', {})

            # Ensure we have a valid parameters schema
            if not schema:
                schema = {
                    "type": "object",
                    "properties": {},
                    "required": []
                }

            function_declarations.append(
                FunctionDeclaration(
                    name=tool_name,
                    description=tool_description,
                    parameters=schema
                )
            )

        return [Tool.from_function_declarations(function_declarations)]

    async def ask(
        self,
        prompt: str,
        model: Union[VertexAIModel, str] = VertexAIModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        stateless: bool = False
    ) -> AIMessage:
        """
        Ask a question to Vertex AI with full conversation memory and tool support.
        """
        model = model.value if isinstance(model, VertexAIModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        # Prepare conversation context using unified memory system
        conversation_history = None
        messages = []

        # Use the abstract method to prepare conversation context
        if stateless:
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
            conversation_history = None
        else:
            messages, conversation_history, system_prompt = await self._prepare_conversation_context(
                prompt, files, user_id, session_id, system_prompt, stateless=stateless
            )

        # Register additional tools if provided
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        # Convert messages to Vertex AI format (excluding current message)
        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude the current user message
                if msg["content"] and isinstance(msg["content"], list) and msg["content"]:
                    content_text = msg["content"][0].get("text", "")
                    role = "model" if msg["role"] == "assistant" else msg["role"]
                    history.append(
                        Content(
                            role=role,
                            parts=[Part.from_text(content_text)]
                        )
                    )

        # Prepare structured output configuration
        output_config = self._get_structured_config(structured_output)

        generation_config = GenerationConfig(
            max_output_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
        )

        # Handle structured output for Vertex AI
        if structured_output:
            schema_for_prompt = None
            if isinstance(structured_output, type):
                generation_config.response_mime_type = "application/json"
                generation_config.response_schema = structured_output.model_json_schema()
                schema_for_prompt = structured_output.model_json_schema()

            elif isinstance(structured_output, StructuredOutputConfig):
                if structured_output.format == OutputFormat.JSON:
                    generation_config.response_mime_type = "application/json"
                    generation_config.response_schema = structured_output.output_type.model_json_schema()
                    schema_for_prompt = structured_output.output_type.model_json_schema()

            # If a structured output is requested, add a strong system prompt to enforce clean JSON output
            # This is crucial for the Vertex AI client.
            if schema_for_prompt and not system_prompt:
                system_prompt = (
                    "Your response must be a valid JSON object that strictly adheres to the provided schema. "
                    "Do not include any text, explanations, or markdown formatting (like ```json) outside of the JSON object itself. "
                    f"JSON Schema:\n{schema_for_prompt}"
                )

        # Build tools
        vertex_tools = self._build_tools()
        all_tool_calls = []


        print('TOOLS > ', vertex_tools)
        print('SYSTEM PROMPT > ', system_prompt)
        # Create the model
        multimodal_model = GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
            tools=vertex_tools
        )

        # Start chat with history
        chat = multimodal_model.start_chat(history=history)

        # Make the primary call
        response = await chat.send_message_async(
            prompt,
            generation_config=generation_config
        )

        # Handle function calls with parallel execution
        if response.candidates and response.candidates[0].content.parts:
            function_calls = [
                part.function_call
                for part in response.candidates[0].content.parts
                if hasattr(part, 'function_call') and part.function_call
            ]

            if function_calls:
                tool_call_objects = []
                # Execute all tool calls concurrently
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

                # Update ToolCall objects with results
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
                        response_content = str(result)

                    function_response_parts.append(
                        Part.from_function_response(
                            name=fc.name,
                            response={"result": response_content}
                        )
                    )

                # Send tool results back to model
                response = await chat.send_message_async(function_response_parts)
        # Handle structured output
        final_output = None
        if structured_output:
            try:
                final_output = await self._parse_structured_output(
                    response.text,
                    output_config
                )
            except Exception:
                final_output = response.text

        # Extract assistant response text
        assistant_response_text = response.text

        # Update conversation memory
        final_assistant_message = {
            "role": "model",
            "content": [{"type": "text", "text": response.text}]
        }

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

        # Extract usage information
        usage_data = self._extract_usage_from_response(response)

        # Create AIMessage using factory
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=original_prompt,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=all_tool_calls,
            conversation_history=conversation_history
        )

        # Override usage with proper Vertex AI usage data
        if usage_data:
            ai_message.usage = CompletionUsage(
                prompt_tokens=usage_data.get("prompt_token_count", 0),
                completion_tokens=usage_data.get("candidates_token_count", 0),
                total_tokens=usage_data.get("total_token_count", 0),
                extra_usage=usage_data
            )

        # Update provider
        ai_message.provider = "vertexai"
        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Union[VertexAIModel, str] = VertexAIModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        retry_config: Optional[StreamingRetryConfig] = None,
        on_max_tokens: Optional[str] = "retry",
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """
        Stream Vertex AI's response with retry and error handling.
        """
        model = model.value if isinstance(model, VertexAIModel) else model
        turn_id = str(uuid.uuid4())

        # Default retry configuration
        if retry_config is None:
            retry_config = StreamingRetryConfig()

        # Register additional tools if provided
        if tools and isinstance(tools, list):
            for tool in tools:
                self.register_tool(tool)

        messages, conversation_history, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        # Convert messages to Vertex AI format
        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude current message
                if msg["content"] and isinstance(msg["content"], list) and msg["content"]:
                    content_text = msg["content"][0].get("text", "")
                    role = "model" if msg["role"] == "assistant" else msg["role"]
                    history.append(
                        Content(
                            role=role,
                            parts=[Part.from_text(content_text)]
                        )
                    )

        # Build tools
        vertex_tools = self._build_tools()

        # Retry loop for MAX_TOKENS and other errors
        current_max_tokens = max_tokens or self.max_tokens
        retry_count = 0

        while retry_count <= retry_config.max_retries:
            try:
                generation_config = GenerationConfig(
                    max_output_tokens=current_max_tokens,
                    temperature=temperature or self.temperature,
                )

                multimodal_model = GenerativeModel(
                    model_name=model,
                    system_instruction=system_prompt,
                    tools=vertex_tools
                )

                chat = multimodal_model.start_chat(history=history)

                response = await chat.send_message_async(
                    prompt,
                    generation_config=generation_config,
                    stream=True
                )

                assistant_content = ""
                max_tokens_reached = False

                async for chunk in response:
                    # Check for MAX_TOKENS finish reason
                    if (hasattr(chunk, 'candidates') and
                        chunk.candidates and
                        len(chunk.candidates) > 0):

                        candidate = chunk.candidates[0]
                        if (hasattr(candidate, 'finish_reason') and
                            str(candidate.finish_reason) == 'FINISH_REASON_MAX_TOKENS'):
                            max_tokens_reached = True

                            # Handle MAX_TOKENS based on configuration
                            if on_max_tokens == "notify":
                                yield f"\n\n⚠️ **Response truncated due to token limit ({current_max_tokens} tokens). The response may be incomplete.**\n"
                            elif on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                                break

                    # Yield the text content
                    if chunk.text:
                        assistant_content += chunk.text
                        yield chunk.text

                # Handle retry logic
                if max_tokens_reached and on_max_tokens == "retry" and retry_config.auto_retry_on_max_tokens:
                    if retry_count < retry_config.max_retries:
                        new_max_tokens = int(current_max_tokens * retry_config.token_increase_factor)
                        yield f"\n\n🔄 **Response reached token limit ({current_max_tokens}). Retrying with increased limit ({new_max_tokens})...**\n\n"
                        current_max_tokens = new_max_tokens
                        retry_count += 1
                        await self._wait_with_backoff(retry_count, retry_config)
                        continue
                    else:
                        yield f"\n\n❌ **Maximum retries reached. Response may be incomplete due to token limits.**\n"

                # Update conversation memory
                if assistant_content:
                    final_assistant_message = {
                        "role": "assistant",
                        "content": [{"type": "text", "text": assistant_content}]
                    }
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
                break

            except Exception as e:
                if retry_count < retry_config.max_retries:
                    error_msg = f"\n\n⚠️ **Streaming error (attempt {retry_count + 1}): {str(e)}. Retrying...**\n\n"
                    yield error_msg
                    retry_count += 1
                    await self._wait_with_backoff(retry_count, retry_config)
                    continue
                else:
                    yield f"\n\n❌ **Streaming failed after {retry_config.max_retries} retries: {str(e)}**\n"
                    break

    async def ask_to_image(
        self,
        prompt: str,
        image: Union[Path, bytes],
        reference_images: Optional[Union[List[Path], List[bytes]]] = None,
        model: Union[str, VertexAIModel] = VertexAIModel.GEMINI_2_5_FLASH,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        structured_output: Union[type, StructuredOutputConfig] = None,
        count_objects: bool = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Ask a question to Vertex AI using images with conversation memory.
        """
        model = model.value if isinstance(model, VertexAIModel) else model
        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, _ = await self._prepare_conversation_context(
            prompt, None, user_id, session_id, None
        )

        # Convert messages to Vertex AI format
        history = []
        if messages:
            for msg in messages[:-1]:  # Exclude current message
                if msg["content"] and isinstance(msg["content"], list) and msg["content"]:
                    content_text = msg["content"][0].get("text", "")
                    role = "model" if msg["role"] == "assistant" else msg["role"]
                    history.append(
                        Content(
                            role=role,
                            parts=[Part.from_text(content_text)]
                        )
                    )

        # --- Multi-Modal Content Preparation ---
        if isinstance(image, Path):
            if not image.exists():
                raise FileNotFoundError(f"Image file not found: {image}")
            primary_image = Image.open(image)
        elif isinstance(image, bytes):
            primary_image = Image.open(io.BytesIO(image))
        elif isinstance(image, Image.Image):
            primary_image = image
        else:
            raise ValueError("Image must be a Path, bytes, or PIL.Image object.")

        # Prepare content parts
        content_parts = [Part.from_image(primary_image)]

        if reference_images:
            for ref_path in reference_images:
                self.logger.debug(f"Loading reference image from: {ref_path}")
                if isinstance(ref_path, Path):
                    if not ref_path.exists():
                        raise FileNotFoundError(f"Reference image file not found: {ref_path}")
                    content_parts.append(Part.from_image(Image.open(ref_path)))
                elif isinstance(ref_path, bytes):
                    content_parts.append(Part.from_image(Image.open(io.BytesIO(ref_path))))
                elif isinstance(ref_path, Image.Image):
                    content_parts.append(Part.from_image(ref_path))
                else:
                    raise ValueError("Reference Image must be a Path, bytes, or PIL.Image object.")

        content_parts.append(Part.from_text(prompt))  # Text prompt comes last

        # Prepare structured output configuration
        output_config = self._get_structured_config(structured_output)

        generation_config = GenerationConfig(
            max_output_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature,
        )

        # Handle structured output
        if structured_output:
            if isinstance(structured_output, type):
                generation_config.response_mime_type = "application/json"
                generation_config.response_schema = structured_output.model_json_schema()
            elif isinstance(structured_output, StructuredOutputConfig):
                if structured_output.format == OutputFormat.JSON:
                    generation_config.response_mime_type = "application/json"
                    generation_config.response_schema = structured_output.output_type.model_json_schema()
        elif count_objects:
            generation_config.response_mime_type = "application/json"
            generation_config.response_schema = ObjectDetectionResult.model_json_schema()
            structured_output = ObjectDetectionResult

        # Create the model and chat
        multimodal_model = GenerativeModel(model_name=model)
        chat = multimodal_model.start_chat(history=history)

        # Make the multi-modal call
        self.logger.debug(f"Sending {len(content_parts)} parts to the model.")
        response = await chat.send_message_async(
            content_parts,
            generation_config=generation_config
        )

        # Handle structured output
        final_output = None
        if structured_output:
            try:
                if not isinstance(structured_output, StructuredOutputConfig):
                    structured_output = StructuredOutputConfig(
                        output_type=structured_output,
                        format=OutputFormat.JSON
                    )
                final_output = await self._parse_structured_output(
                    response.text,
                    structured_output
                )
            except Exception as e:
                self.logger.error(f"Failed to parse structured output from vision model: {e}")
                final_output = response.text

        # Update conversation memory
        final_assistant_message = {
            "role": "model",
            "content": [{"type": "text", "text": response.text}]
        }

        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages + [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": f"[Image Analysis]: {prompt}"}]
                },
                final_assistant_message
            ],
            None,
            turn_id,
            original_prompt,
            response.text,
            []
        )

        # Extract usage information
        usage_data = self._extract_usage_from_response(response)

        # Create AIMessage
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

        # Override usage with proper Vertex AI usage data
        if usage_data:
            ai_message.usage = CompletionUsage(
                prompt_tokens=usage_data.get("prompt_token_count", 0),
                completion_tokens=usage_data.get("candidates_token_count", 0),
                total_tokens=usage_data.get("total_token_count", 0),
                extra_usage=usage_data
            )

        ai_message.provider = "vertexai"
        return ai_message

    async def batch_ask(self, requests) -> List[AIMessage]:
        """Process multiple requests in batch."""
        # Vertex AI doesn't have a native batch API, so we process sequentially
        results = []
        for request in requests:
            result = await self.ask(**request)
            results.append(result)
        return results

    async def analyze_sentiment(
        self,
        text: str,
        model: Union[str, VertexAIModel] = VertexAIModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        use_structured: bool = False,
    ) -> AIMessage:
        """
        Analyze the sentiment of a given text (stateless).
        """
        model = model.value if isinstance(model, VertexAIModel) else model
        turn_id = str(uuid.uuid4())

        if use_structured:
            system_prompt = """
You are a sentiment analysis expert.
Analyze the sentiment of the given text and respond with valid JSON matching this exact schema:
{
  "sentiment": "positive" | "negative" | "neutral" | "mixed",
  "confidence_level": 0.0-1.0,
  "emotional_indicators": ["word1", "phrase2", ...],
  "reason": "explanation of analysis"
}
Respond only with valid JSON, no additional text."""

            generation_config = GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=SentimentAnalysis.model_json_schema()
            )
        else:
            system_prompt = (
                "Analyze the sentiment of the following text and provide a structured response.\n"
                "Your response must include:\n"
                "1. Overall sentiment (Positive, Negative, Neutral, or Mixed)\n"
                "2. Confidence level (High, Medium, Low)\n"
                "3. Key emotional indicators found in the text\n"
                "4. Brief explanation of your analysis\n\n"
                "Format your answer clearly with numbered sections."
            )
            generation_config = GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=temperature,
            )
            structured_output = None

        # Create the model
        multimodal_model = GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )

        # Make the stateless call
        response = await multimodal_model.generate_content_async(
            text,
            generation_config=generation_config
        )

        # Handle structured output parsing
        final_output = None
        if use_structured:
            try:
                output_config = StructuredOutputConfig(
                    output_type=SentimentAnalysis,
                    format=OutputFormat.JSON
                )
                final_output = await self._parse_structured_output(
                    response.text,
                    output_config
                )
            except Exception as e:
                self.logger.error(f"Failed to parse structured output: {e}")
                final_output = response.text

        # Extract usage information
        usage_data = self._extract_usage_from_response(response)

        # Create AIMessage
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=[]
        )

        # Override usage with proper Vertex AI usage data
        if usage_data:
            ai_message.usage = CompletionUsage(
                prompt_tokens=usage_data.get("prompt_token_count", 0),
                completion_tokens=usage_data.get("candidates_token_count", 0),
                total_tokens=usage_data.get("total_token_count", 0),
                extra_usage=usage_data
            )

        ai_message.provider = "vertexai"
        return ai_message

    async def analyze_product_review(
        self,
        review_text: str,
        product_id: str,
        product_name: str,
        model: Union[str, VertexAIModel] = VertexAIModel.GEMINI_2_5_FLASH,
        temperature: Optional[float] = 0.1,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AIMessage:
        """
        Analyze a product review and extract structured information (stateless).
        """
        model = model.value if isinstance(model, VertexAIModel) else model
        turn_id = str(uuid.uuid4())

        system_prompt = f"""
You are a product review analysis expert.
Analyze the given product review and respond with valid JSON matching this exact schema:
{{
  "product_id": "{product_id}",
  "product_name": "{product_name}",
  "review_text": "original review text",
  "rating": 0.0-5.0,
  "sentiment": "positive" | "negative" | "neutral",
  "key_features": ["feature1", "feature2", ...]
}}
Extract the rating based on the review content (estimate if not explicitly stated), determine sentiment, and identify key product features mentioned. Respond only with valid JSON, no additional text.
        """

        generation_config = GenerationConfig(
            max_output_tokens=self.max_tokens,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=ProductReview.model_json_schema()
        )

        # Create the model
        multimodal_model = GenerativeModel(
            model_name=model,
            system_instruction=system_prompt
        )

        # Prepare the input text
        input_text = f"Product ID: {product_id}\nProduct Name: {product_name}\nReview: {review_text}"

        # Make the stateless call
        response = await multimodal_model.generate_content_async(
            input_text,
            generation_config=generation_config
        )

        # Handle structured output parsing
        final_output = None
        try:
            output_config = StructuredOutputConfig(
                output_type=ProductReview,
                format=OutputFormat.JSON
            )
            final_output = await self._parse_structured_output(
                response.text,
                output_config
            )
        except Exception as e:
            self.logger.error(f"Failed to parse structured output: {e}")
            final_output = response.text

        # Extract usage information
        usage_data = self._extract_usage_from_response(response)

        # Create AIMessage
        ai_message = AIMessageFactory.from_gemini(
            response=response,
            input_text=review_text,
            model=model,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            structured_output=final_output if final_output != response.text else None,
            tool_calls=[]
        )

        # Override usage with proper Vertex AI usage data
        if usage_data:
            ai_message.usage = CompletionUsage(
                prompt_tokens=usage_data.get("prompt_token_count", 0),
                completion_tokens=usage_data.get("candidates_token_count", 0),
                total_tokens=usage_data.get("total_token_count", 0),
                extra_usage=usage_data
            )

        ai_message.provider = "vertexai"
        return ai_message
