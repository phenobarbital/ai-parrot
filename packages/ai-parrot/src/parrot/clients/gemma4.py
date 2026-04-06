"""
Gemma4Client for ai-parrot framework.

Dedicated client for Google Gemma 4 multimodal models that use
AutoProcessor + AutoModelForMultimodalLM (processor-based architecture).

Supported models:
  - google/gemma-4-E2B-it   (2B parameters)
  - google/gemma-4-E4B-it   (4B parameters)
  - google/gemma-4-26B-A4B-it (26B MoE, 4B active)
"""
import asyncio
import json
import logging
import uuid
import time
import mimetypes
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from pathlib import Path
from enum import Enum

## transformers and torch are imported lazily to avoid pulling in heavy
## dependencies when Gemma4Client is not actually used.

from .base import AbstractClient, MessageResponse
from ..models import (
    AIMessage,
    AIMessageFactory,
    CompletionUsage,
    StructuredOutputConfig
)
from ..models.basic import ToolCall
from ..models.responses import InvokeResult
from ..exceptions import InvokeError
from ..tools.manager import ToolFormat


class Gemma4Model(Enum):
    """Supported Gemma 4 model variants."""
    GEMMA_4_E2B = "google/gemma-4-E2B-it"
    GEMMA_4_E4B = "google/gemma-4-E4B-it"
    GEMMA_4_26B_A4B = "google/gemma-4-26B-A4B-it"


# Maximum tool-call loop iterations to prevent infinite loops.
MAX_TOOL_ROUNDS = 10


class Gemma4Client(AbstractClient):
    """Client for Google Gemma 4 multimodal instruction-tuned models.

    Gemma 4 models use AutoProcessor (not AutoTokenizer) and
    AutoModelForMultimodalLM (not AutoModelForCausalLM). They support:
      - Text-only and multimodal (image/audio/video) input
      - Optional thinking/chain-of-thought mode via ``enable_thinking``
      - Function calling / tool use via ``tools`` parameter
      - Structured response parsing via ``processor.parse_response()``
    """

    client_type: str = "gemma4"
    client_name: str = "gemma4"

    def __init__(
        self,
        model: Union[str, Gemma4Model] = Gemma4Model.GEMMA_4_E2B,
        device: Optional[str] = None,
        dtype: Optional[Any] = None,
        trust_remote_code: bool = False,
        enable_thinking: bool = False,
        **kwargs
    ):
        """Initialize the Gemma4Client.

        Args:
            model: Model name or Gemma4Model enum.
            device: Device to run on ('cpu', 'cuda', 'auto').
            dtype: PyTorch dtype for weights. Defaults to float16 on
                CUDA, float32 on CPU.
            trust_remote_code: Trust remote code from HuggingFace Hub.
            enable_thinking: Enable chain-of-thought thinking mode.
            **kwargs: Additional arguments for AbstractClient.
        """
        super().__init__(**kwargs)

        self.model_name = model.value if isinstance(model, Gemma4Model) else model
        self.client_name = self.model_name.split("/")[-1]

        self._device_arg = device
        self._dtype_arg = dtype
        self.device: Optional[str] = None
        self.dtype: Optional[Any] = None
        self.trust_remote_code = trust_remote_code
        self.enable_thinking = enable_thinking

        # Loaded lazily
        self.model = None
        self.processor = None
        self.generation_config = None

        self.logger = logging.getLogger(
            f"parrot.Gemma4Client.{self.model_name}"
        )

        # Reduce noise from HTTP libraries used by HuggingFace Hub
        logging.getLogger("httpcore").setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def get_client(self) -> Any:
        """Initialize the client context and load the model."""
        await self._load_model()
        return self.model

    async def close(self):
        """Clean up resources."""
        await self.clear_model()
        await super().close()

    async def _load_model(self):
        """Load the processor and model."""
        if self.model is not None and self.processor is not None:
            return

        import torch
        from transformers import (
            AutoModelForMultimodalLM,
            AutoProcessor,
            GenerationConfig,
        )

        # Resolve device/dtype on first load
        if self.device is None:
            self.device = self._device_arg or (
                "cuda" if torch.cuda.is_available() else "cpu"
            )
        if self.dtype is None:
            self.dtype = self._dtype_arg or (
                torch.float16 if torch.cuda.is_available() else torch.float32
            )

        if self.generation_config is None:
            self.generation_config = GenerationConfig(
                max_new_tokens=1024,
                temperature=1.0,
                top_p=0.95,
                top_k=64,
                do_sample=True,
                pad_token_id=None,
                eos_token_id=None,
            )

        self.logger.info(f"Loading model: {self.model_name}")

        self.processor = AutoProcessor.from_pretrained(
            self.model_name,
            trust_remote_code=self.trust_remote_code,
        )

        device_map = self.device if self.device != "cpu" else None

        # Suppress the harmless "offloaded layers buffer" warning that fires
        # during device-map inference (transformers doesn't forward
        # offload_buffers to infer_auto_device_map).
        _accel_logger = logging.getLogger("transformers.integrations.accelerate")
        _prev_level = _accel_logger.level
        _accel_logger.setLevel(logging.ERROR)
        try:
            self.model = AutoModelForMultimodalLM.from_pretrained(
                self.model_name,
                dtype=self.dtype,
                device_map=device_map,
                trust_remote_code=self.trust_remote_code,
                offload_buffers=True if device_map else None,
            )
        finally:
            _accel_logger.setLevel(_prev_level)

        if self.device == "cpu":
            self.model = self.model.to(self.device)

        # Resolve token IDs from the inner tokenizer
        inner_tok = getattr(self.processor, "tokenizer", None)
        if inner_tok:
            self.generation_config.pad_token_id = inner_tok.pad_token_id
            self.generation_config.eos_token_id = inner_tok.eos_token_id

        self.logger.info(f"Model loaded successfully on {self.device}")

    # ------------------------------------------------------------------
    # Tool preparation
    # ------------------------------------------------------------------

    def _prepare_gemma4_tools(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert ai-parrot tool definitions to Gemma 4 format.

        Gemma 4 uses the OpenAI function-calling schema::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { JSON Schema }
                }
            }

        This method merges:
          1. Tools registered in the ToolManager (via ``use_tools``).
          2. Ad-hoc tool dicts passed via the ``tools`` parameter.

        Args:
            tools: Optional extra tool definitions (already in dict form).

        Returns:
            List of Gemma 4-compatible tool schemas, or None if empty.
        """
        gemma_tools: List[Dict[str, Any]] = []
        processed_names: set = set()

        # 1. Registered tools from ToolManager
        if self.tool_manager and self.enable_tools:
            manager_schemas = self.tool_manager.get_tool_schemas(
                provider_format=ToolFormat.OPENAI
            )
            for schema in manager_schemas:
                name = schema.get("name")
                if name and name not in processed_names:
                    gemma_tools.append({
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": schema.get("description", ""),
                            "parameters": schema.get("parameters", {}),
                        },
                    })
                    processed_names.add(name)

        # 2. Ad-hoc tool dicts
        if tools:
            for tool in tools:
                # Already in Gemma 4 / OpenAI format
                if "type" in tool and "function" in tool:
                    name = tool["function"].get("name")
                    if name and name not in processed_names:
                        gemma_tools.append(tool)
                        processed_names.add(name)
                # Anthropic / ai-parrot internal format
                elif "name" in tool:
                    name = tool["name"]
                    if name not in processed_names:
                        gemma_tools.append({
                            "type": "function",
                            "function": {
                                "name": name,
                                "description": tool.get("description", ""),
                                "parameters": tool.get(
                                    "parameters",
                                    tool.get("input_schema", {}),
                                ),
                            },
                        })
                        processed_names.add(name)

        return gemma_tools or None

    def _parse_tool_calls(
        self, parsed: Dict[str, Any]
    ) -> List[ToolCall]:
        """Extract ToolCall objects from a parsed model response.

        ``parse_response()`` returns a dict with an optional
        ``tool_calls`` key whose items look like::

            {
                "type": "function",
                "function": {"name": "...", "arguments": "{...}"}
            }

        Args:
            parsed: Dict returned by ``processor.parse_response()``.

        Returns:
            List of ToolCall instances (may be empty).
        """
        raw_calls = parsed.get("tool_calls") or []
        tool_calls: List[ToolCall] = []
        for call in raw_calls:
            func = call.get("function", {})
            name = func.get("name", "").strip()
            if not name:
                continue
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {"raw": raw_args}
            else:
                arguments = raw_args
            tool_calls.append(ToolCall(
                id=str(uuid.uuid4()),
                name=name,
                arguments=arguments,
            ))
        return tool_calls

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def _format_huggingface_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Format abstract messages into Hugging Face Gemma 4 format.

        Translates file attachments to multimodal image/audio/video content 
        blocks and ensures they precede text in the content list.
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", [])
            
            if isinstance(content, str):
                formatted.append({"role": role, "content": [{"type": "text", "text": content}]})
                continue
                
            formatted_content = []
            text_blocks = []
            for block in content:
                if block.get("type") == "text":
                    text_blocks.append(block)
                elif block.get("type") == "file":
                    file_path = block.get("file_path")
                    mime, _ = mimetypes.guess_type(file_path)
                    if mime:
                        if mime.startswith("image/"):
                            formatted_content.append({"type": "image", "image": file_path})
                        elif mime.startswith("video/"):
                            formatted_content.append({"type": "video", "video": file_path})
                        elif mime.startswith("audio/"):
                            formatted_content.append({"type": "audio", "audio": file_path})
                        else:
                            self.logger.warning(f"Unsupported file type {mime} for {file_path}")
                else:
                    # In case of existing multimodal pieces or tools
                    formatted_content.append(block)
            
            # Text MUST come after images/audio/video for Gemma 4 optimal performance
            formatted_content.extend(text_blocks)
            
            formatted_msg = msg.copy()
            formatted_msg["content"] = formatted_content
            formatted.append(formatted_msg)
            
        return formatted

    def _apply_chat_template(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """Apply the processor's chat template to messages.

        Args:
            messages: Chat message list.
            tools: Optional Gemma 4-formatted tool definitions.

        Returns:
            BatchEncoding inputs.
        """
        kwargs: Dict[str, Any] = {
            "tokenize": True,
            "add_generation_prompt": True,
            "return_dict": True,
            "return_tensors": "pt",
            "enable_thinking": self.enable_thinking,
        }
        if tools:
            kwargs["tools"] = tools
        return self.processor.apply_chat_template(messages, **kwargs).to(self.model.device)

    # ------------------------------------------------------------------
    # Generation helper
    # ------------------------------------------------------------------

    def _generate(
        self,
        inputs: Any,
        max_tokens: int,
        temperature: float,
        **kwargs,
    ) -> tuple:
        """Tokenise, generate, decode. Returns (parsed_dict, usage, time).

        The ``parsed_dict`` always has at least ``content``; it may also
        contain ``thinking`` and ``tool_calls``.
        """
        from transformers import GenerationConfig

        input_length = inputs["input_ids"].shape[-1]

        gen_config = GenerationConfig(
            max_new_tokens=max_tokens,
            temperature=temperature,
            top_p=kwargs.get("top_p", 0.95),
            top_k=kwargs.get("top_k", 64),
            do_sample=temperature > 0,
            pad_token_id=self.generation_config.pad_token_id,
            eos_token_id=self.generation_config.eos_token_id,
            repetition_penalty=kwargs.get("repetition_penalty", 1.1),
        )

        start_time = time.time()
        import torch
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs, generation_config=gen_config
            )
        generation_time = time.time() - start_time

        generated_ids = outputs[0][input_length:]

        # Parse structured response (thinking, content, tool_calls)
        raw_response = self.processor.decode(
            generated_ids, skip_special_tokens=False
        )
        if hasattr(self.processor, "parse_response"):
            parsed = self.processor.parse_response(raw_response)
            if not isinstance(parsed, dict):
                parsed = {"content": str(parsed)}
        else:
            parsed = {
                "content": self.processor.decode(
                    generated_ids, skip_special_tokens=True
                )
            }

        usage = CompletionUsage(
            prompt_tokens=input_length,
            completion_tokens=len(generated_ids),
            total_tokens=input_length + len(generated_ids),
        )
        return parsed, usage, generation_time

    # ------------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------------

    async def ask(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 1.0,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        structured_output: Optional[Union[type, StructuredOutputConfig]] = None,
        **kwargs
    ) -> AIMessage:
        """Send a prompt and return the response.

        When tools are provided (or registered via ``use_tools``), the
        method enters a tool-calling loop:

        1. The model generates a response that may include ``tool_calls``.
        2. Each tool call is executed via ``_execute_tool()``.
        3. Tool results are appended and the model is re-prompted.
        4. The loop repeats until the model returns plain content or
           ``MAX_TOOL_ROUNDS`` is reached.

        Args:
            prompt: The user prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            files: File attachments (images, audio, video).
            system_prompt: System prompt.
            user_id: User ID for conversation memory.
            session_id: Session ID for conversation memory.
            tools: Ad-hoc tool definitions (Gemma 4 or ai-parrot format).
            structured_output: Structured output configuration.
            **kwargs: Extra generation parameters.

        Returns:
            AIMessage with the model response.
        """
        if not self.model or not self.processor:
            await self._load_model()

        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = (
            await self._prepare_conversation_context(
                prompt, files, user_id, session_id, system_prompt
            )
        )

        # Prepare tools
        gemma_tools = self._prepare_gemma4_tools(tools)

        # Format chat messages using conversation context
        chat_messages = self._format_huggingface_messages(messages)

        all_tool_calls: List[ToolCall] = []
        total_generation_time = 0.0
        total_usage = CompletionUsage(
            prompt_tokens=0, completion_tokens=0, total_tokens=0
        )

        # ------ Tool-calling loop ------
        for _round in range(MAX_TOOL_ROUNDS):
            inputs = self._apply_chat_template(
                chat_messages, tools=gemma_tools
            )
            parsed, usage, gen_time = self._generate(
                inputs, max_tokens, temperature, **kwargs
            )

            total_generation_time += gen_time
            total_usage = CompletionUsage(
                prompt_tokens=total_usage.prompt_tokens + usage.prompt_tokens,
                completion_tokens=total_usage.completion_tokens + usage.completion_tokens,
                total_tokens=total_usage.total_tokens + usage.total_tokens,
            )

            # Check for tool calls
            round_tool_calls = self._parse_tool_calls(parsed)

            if not round_tool_calls:
                # No tool calls — final answer
                break

            # Execute each tool call
            self.logger.info(
                f"Round {_round + 1}: executing {len(round_tool_calls)} tool call(s)"
            )

            # Append the assistant message with tool_calls to conversation
            chat_messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": ""}],
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in round_tool_calls
                ],
            })

            for tc in round_tool_calls:
                try:
                    result = await self._execute_tool(
                        tc.name, tc.arguments
                    )
                    tc.result = result
                except Exception as e:
                    tc.error = str(e)
                    result = f"Error: {e}"
                    self.logger.error(
                        f"Tool '{tc.name}' failed: {e}"
                    )

                # Append tool result as a message for the next round
                chat_messages.append({
                    "role": "tool",
                    "name": tc.name,
                    "content": [{"type": "text", "text": str(result)}],
                })
                all_tool_calls.append(tc)
        else:
            self.logger.warning(
                f"Tool-calling loop hit MAX_TOOL_ROUNDS ({MAX_TOOL_ROUNDS})"
            )

        # Extract final text content
        response_text = (parsed.get("content") or "").strip()

        ai_message = AIMessageFactory.create_message(
            response=response_text,
            input_text=original_prompt,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            model=self.model_name,
            text_response=response_text,
            usage=total_usage,
            response_time=total_generation_time,
        )

        # Attach tool calls to the message
        if all_tool_calls:
            ai_message.tool_calls = all_tool_calls

        # Update conversation memory
        tools_used = [tc.name for tc in all_tool_calls]
        await self._update_conversation_memory(
            user_id,
            session_id,
            conversation_session,
            messages,
            system_prompt,
            turn_id,
            original_prompt,
            response_text,
            tools_used,
        )

        # Structured output
        if structured_output:
            try:
                structured_result = await self._handle_structured_output(
                    {"content": [{"type": "text", "text": response_text}]},
                    structured_output,
                )
                ai_message.structured_output = structured_result
            except Exception as e:
                self.logger.warning(f"Failed to parse structured output: {e}")

        return ai_message

    # ------------------------------------------------------------------
    # Streaming (pseudo — yields chunks after full generation)
    # ------------------------------------------------------------------

    async def ask_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 1.0,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """Pseudo-streaming: generates fully then yields chunks."""
        response = await self.ask(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            files=files,
            system_prompt=system_prompt,
            user_id=user_id,
            session_id=session_id,
            tools=tools,
            **kwargs
        )
        text = response.content
        chunk_size = 10
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]
            await asyncio.sleep(0.01)

    # ------------------------------------------------------------------
    # Invoke / Resume (abstract method implementations)
    # ------------------------------------------------------------------

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Lightweight stateless invocation."""
        config = self._build_invoke_structured_config(output_type, structured_output)
        resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)

        response = await self.ask(
            prompt=prompt,
            system_prompt=resolved_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            structured_output=config,
        )

        output = response.content
        if config and config.output_type:
            try:
                output = await self._handle_structured_output(
                    {"content": [{"type": "text", "text": response.content}]},
                    config,
                )
            except Exception as e:
                self.logger.warning(f"Structured output parsing failed: {e}")

        return InvokeResult(
            output=output,
            output_type=config.output_type if config else None,
            model=self.model_name,
            usage=response.usage or CompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
            raw_response=response,
        )

    async def resume(
        self,
        session_id: str,
        user_input: str,
        state: Dict[str, Any],
    ) -> MessageResponse:
        """Resume a suspended tool-calling conversation.

        Injects the user's input as a tool result and re-runs generation.
        """
        chat_messages = state.get("messages", [])
        tool_call_id = state.get("tool_call_id")

        if tool_call_id:
            chat_messages.append({
                "role": "tool",
                "name": state.get("tool_name", "handoff_tool"),
                "content": user_input,
            })

        gemma_tools = state.get("tools")
        inputs = self._apply_chat_template(
            chat_messages, tools=gemma_tools
        )
        parsed, usage, gen_time = self._generate(
            inputs,
            max_tokens=state.get("max_tokens", 4096),
            temperature=state.get("temperature", 1.0),
        )
        response_text = (parsed.get("content") or "").strip()

        ai_message = AIMessageFactory.create_message(
            response=response_text,
            input_text=user_input,
            session_id=session_id,
            turn_id=str(uuid.uuid4()),
            model=self.model_name,
            text_response=response_text,
            usage=usage,
            response_time=gen_time,
        )
        return MessageResponse(
            response=ai_message,
            tool_calls=[],
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        if not self.model:
            return {"status": "not_loaded"}

        inner_tok = getattr(self.processor, "tokenizer", None)
        return {
            "model_name": self.model_name,
            "device": self.device,
            "dtype": str(self.dtype),
            "status": "loaded",
            "enable_thinking": self.enable_thinking,
            "vocab_size": inner_tok.vocab_size if inner_tok else None,
            "max_position_embeddings": getattr(
                self.model.config, "max_position_embeddings", None
            ),
        }

    async def clear_model(self):
        """Clear model and processor from memory."""
        if self.model:
            del self.model
            self.model = None
        if self.processor:
            del self.processor
            self.processor = None
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self.logger.info("Model cleared from memory")
