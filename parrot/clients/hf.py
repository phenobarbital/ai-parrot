"""
TransformersClient for ai-parrot framework.
Supports micro-LLMs from HuggingFace transformers for small tasks.
"""
import asyncio
import logging
import uuid
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from pathlib import Path
from enum import Enum

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    GenerationConfig
)

from .base import AbstractClient, MessageResponse, StreamingRetryConfig
from ..models import (
    AIMessage,
    AIMessageFactory,
    CompletionUsage,
    StructuredOutputConfig,
    OutputFormat
)
from ..memory import ConversationHistory, ConversationTurn


class TransformersModel(Enum):
    """Enum for supported transformer models."""
    DIALOPT_MEDIUM = "microsoft/DialoGPT-medium"
    DIALOPT_SMALL = "microsoft/DialoGPT-small"
    DIALOPT_LARGE = "microsoft/DialoGPT-large"
    TINY_LLM = "arnir0/Tiny-LLM"
    GEMMA_2B = "google/gemma-2-2b-it"
    GEMMA_9B = "google/gemma-2-9b-it"
    GEMMA_3_4B = "google/gemma-3-4b-it"
    GEMMA_3_1B = "google/gemma-3-1b-pt"
    QWEN_1_5B = "Qwen/Qwen2.5-1.5B-Instruct"
    QWEN_3B = "Qwen/Qwen2.5-3B-Instruct"
    QWEN_7B = "Qwen/Qwen2.5-7B-Instruct"
    BCCARD_QWEN_32B = "BCCard/Qwen2.5-VL-32B-Instruct-FP8-Dynamic"
    PHI_3_MINI = "microsoft/Phi-3-mini-4k-instruct"
    PHI_3_SMALL = "microsoft/Phi-3-small-8k-instruct"
    PHI_3_5_MINI = "microsoft/Phi-3.5-mini-instruct"
    OPENAI_GPT_20B = "openai/gpt-oss-20b"
    HUGGINGFACE_TB_SMOLLM2_1_7B = "HuggingFaceTB/SmolLM2-1.7B"
    DEEPSEEK_R1_1B = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    DEEPSEEK_R1_7B = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"


class TransformersClient(AbstractClient):
    """
    Client for interacting with HuggingFace transformers micro-LLMs.

    This client is designed for small, local models that can run efficiently
    on CPU or single GPU setups for quick tasks and lightweight inference.
    """

    client_type: str = "transformers"
    client_name: str = "transformers"

    def __init__(
        self,
        model: Union[str, TransformersModel] = TransformersModel.QWEN_3B,
        device: Optional[str] = None,
        torch_dtype: Optional[torch.dtype] = None,
        trust_remote_code: bool = False,
        use_fast_tokenizer: bool = True,
        **kwargs
    ):
        """
        Initialize the TransformersClient.

        Args:
            model: Model name or TransformersModel enum
            device: Device to run the model on ('cpu', 'cuda', 'auto')
            torch_dtype: PyTorch data type for the model
            trust_remote_code: Whether to trust remote code
            use_fast_tokenizer: Whether to use fast tokenizer
            **kwargs: Additional arguments for AbstractClient
        """
        super().__init__(**kwargs)

        # Model configuration
        self.model_name = model.value if isinstance(model, TransformersModel) else model
        self.client_name = self.model_name.split("/")[-1]  # Use last part of model name as client name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.torch_dtype = torch_dtype or (torch.float16 if torch.cuda.is_available() else torch.float32)
        self.trust_remote_code = trust_remote_code
        self.use_fast_tokenizer = use_fast_tokenizer

        # Model and tokenizer (will be loaded lazily)
        self.model = None
        self.tokenizer = None

        # Generation configuration
        self.generation_config = GenerationConfig(
            max_new_tokens=512,
            temperature=0.7,
            top_p=0.9,
            top_k=50,
            do_sample=True,
            pad_token_id=None,  # Will be set after tokenizer is loaded
            eos_token_id=None,  # Will be set after tokenizer is loaded
        )

        self.logger = logging.getLogger(f"parrot.TransformersClient.{self.model_name}")

    async def __aenter__(self):
        """Initialize the client context and load the model."""
        await self._load_model()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources."""
        # Clear model from memory if needed
        if self.model:
            del self.model
        if self.tokenizer:
            del self.tokenizer
        # Clear CUDA cache if using GPU
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    async def _load_model(self):
        """Load the model and tokenizer asynchronously."""
        if self.model is not None and self.tokenizer is not None:
            return

        self.logger.info(f"Loading model: {self.model_name}")

        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            use_fast=self.use_fast_tokenizer,
            trust_remote_code=self.trust_remote_code,
            padding_side='left'  # Important for batch generation
        )

        # Set pad token if not available
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Load model
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=self.torch_dtype,
            device_map=self.device if self.device != "cpu" else None,
            trust_remote_code=self.trust_remote_code,
        )

        if self.device == "cpu":
            self.model = self.model.to(self.device)

        # Update generation config with tokenizer info
        self.generation_config.pad_token_id = self.tokenizer.pad_token_id
        self.generation_config.eos_token_id = self.tokenizer.eos_token_id

        self.logger.info(f"Model loaded successfully on {self.device}")

    def _prepare_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Prepare the prompt based on the model type.

        Args:
            prompt: User prompt
            system_prompt: System prompt
            conversation_history: Previous conversation turns

        Returns:
            Formatted prompt string
        """
        # Handle different model formats
        if "gemma" in self.model_name.lower():
            return self._format_gemma_prompt(prompt, system_prompt, conversation_history)
        elif "qwen" in self.model_name.lower():
            return self._format_qwen_prompt(prompt, system_prompt, conversation_history)
        elif "phi" in self.model_name.lower():
            return self._format_phi_prompt(prompt, system_prompt, conversation_history)
        elif "dialogpt" in self.model_name.lower():
            return self._format_dialogpt_prompt(prompt, conversation_history)
        else:
            # Default simple format
            return self._format_simple_prompt(prompt, system_prompt, conversation_history)

    def _format_gemma_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Format prompt for Gemma models."""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": prompt})

        # Use tokenizer's chat template if available
        if hasattr(self.tokenizer, 'apply_chat_template'):
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
        else:
            # Fallback format
            formatted = ""
            for msg in messages:
                formatted += f"<{msg['role']}>\n{msg['content']}\n</{msg['role']}>\n"
            return formatted

    def _format_qwen_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Format prompt for Qwen models."""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({
                "role": "system",
                "content": "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."
            })

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": prompt})

        if hasattr(self.tokenizer, 'apply_chat_template'):
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
        else:
            # Fallback format
            formatted = ""
            for msg in messages:
                formatted += f"<|im_start|>{msg['role']}\n{msg['content']}<|im_end|>\n"
            formatted += "<|im_start|>assistant\n"
            return formatted

    def _format_phi_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Format prompt for Phi models."""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": prompt})

        if hasattr(self.tokenizer, 'apply_chat_template'):
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
        else:
            # Phi-3 format
            formatted = ""
            for msg in messages:
                formatted += f"<|{msg['role']}|>\n{msg['content']}<|end|>\n"
            formatted += "<|assistant|>\n"
            return formatted

    def _format_dialogpt_prompt(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Format prompt for DialoGPT models."""
        # DialoGPT is conversational, so we concatenate with EOS tokens
        conversation = ""

        if conversation_history:
            for turn in conversation_history:
                if turn["role"] == "user":
                    conversation += turn["content"] + self.tokenizer.eos_token
                elif turn["role"] == "assistant":
                    conversation += turn["content"] + self.tokenizer.eos_token

        conversation += prompt + self.tokenizer.eos_token
        return conversation

    def _format_simple_prompt(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Simple fallback prompt format."""
        formatted = ""

        if system_prompt:
            formatted += f"System: {system_prompt}\n\n"

        if conversation_history:
            for turn in conversation_history:
                formatted += f"{turn['role'].title()}: {turn['content']}\n"

        formatted += f"User: {prompt}\nAssistant:"
        return formatted

    def _get_conversation_history(
        self,
        user_id: Optional[str],
        session_id: Optional[str]
    ) -> List[Dict[str, str]]:
        """Get conversation history from memory."""
        if not self.conversation_memory or not user_id or not session_id:
            return []

        try:
            # This would be implemented based on your memory system
            # For now, return empty list
            return []
        except Exception as e:
            self.logger.warning(f"Could not retrieve conversation history: {e}")
            return []

    async def ask(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        structured_output: Optional[Union[type, StructuredOutputConfig]] = None,
        **kwargs
    ) -> AIMessage:
        """
        Send a prompt to the transformer model and return the response.

        Args:
            prompt: The input prompt
            model: Model name (ignored, uses initialized model)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            files: File attachments (not supported by transformers)
            system_prompt: System prompt
            user_id: User ID for conversation memory
            session_id: Session ID for conversation memory
            tools: Tool definitions (not supported)
            structured_output: Structured output configuration
            **kwargs: Additional generation parameters

        Returns:
            AIMessage response
        """
        if not self.model or not self.tokenizer:
            await self._load_model()

        turn_id = str(uuid.uuid4())
        original_prompt = prompt

        messages, conversation_session, system_prompt = await self._prepare_conversation_context(
            prompt, files, user_id, session_id, system_prompt
        )

        if files:
            self.logger.warning(
                "File attachments not supported by TransformersClient"
            )

        if tools:
            self.logger.warning(
                "Tool calling not supported by TransformersClient"
            )
        all_tool_calls = []

        # Get conversation history
        conversation_history = self._get_conversation_history(user_id, session_id)

        # Prepare the prompt
        formatted_prompt = self._prepare_prompt(prompt, system_prompt, conversation_history)

        # Update generation config
        gen_config = GenerationConfig(
            max_new_tokens=max_tokens,
            temperature=temperature,
            top_p=kwargs.get('top_p', 0.9),
            top_k=kwargs.get('top_k', 50),
            do_sample=temperature > 0,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
            repetition_penalty=kwargs.get('repetition_penalty', 1.1),
        )

        # Tokenize input
        inputs = self.tokenizer.encode(formatted_prompt, return_tensors="pt")
        if self.device != "cpu":
            inputs = inputs.to(self.device)

        # Generate response
        start_time = time.time()

        with torch.no_grad():
            outputs = self.model.generate(
                inputs,
                generation_config=gen_config,
                **kwargs
            )

        generation_time = time.time() - start_time

        # Decode response
        input_length = inputs.shape[1]
        generated_ids = outputs[0][input_length:]
        response_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Clean up response
        response_text = response_text.strip()

        # Create usage statistics
        usage = CompletionUsage(
            prompt_tokens=input_length,
            completion_tokens=len(generated_ids),
            total_tokens=input_length + len(generated_ids)
        )

        # Create AIMessage response
        ai_message = AIMessageFactory.create_message(
            response=response_text,
            input_text=original_prompt,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            model=self.model_name,
            text_response=response_text,
            usage=usage,
            response_time=generation_time,
        )

        # Store conversation turn if memory is available
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
            tools_used
        )

        # Handle structured output if requested
        if structured_output:
            try:
                structured_result = await self._handle_structured_output(
                    {"content": [{"type": "text", "text": response_text}]},
                    structured_output
                )
                ai_message.structured_output = structured_result
            except Exception as e:
                self.logger.warning(f"Failed to parse structured output: {e}")

        return ai_message

    async def ask_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Path]]] = None,
        system_prompt: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        Stream the model's response.

        Note: True streaming is not easily available with transformers,
        so this implementation yields the complete response.
        """
        response = await self.ask(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            files=files,
            system_prompt=system_prompt,
            user_id=user_id,
            session_id=session_id,
            tools=tools,
            **kwargs
        )

        # Simulate streaming by yielding chunks
        text = response.content
        chunk_size = 10  # Characters per chunk

        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            yield chunk
            await asyncio.sleep(0.01)  # Small delay to simulate streaming

    async def batch_ask(self, requests: List[Dict[str, Any]]) -> List[AIMessage]:
        """
        Process multiple requests in batch.

        Note: This processes requests sequentially to avoid memory issues
        with multiple models loaded simultaneously.
        """
        results = []
        for request in requests:
            try:
                result = await self.ask(**request)
                results.append(result)
            except Exception as e:
                self.logger.error(f"Error in batch request: {e}")
                # Create error response
                error_message = AIMessageFactory.create_message(
                    response=result,
                    input_text=request.get('prompt', ''),
                    user_id=request.get('user_id'),
                    session_id=request.get('session_id'),
                    turn_id=str(uuid.uuid4()),
                    model=self.model_name,
                    usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
                )
                results.append(error_message)

        return results

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        if not self.model:
            return {"status": "not_loaded"}

        return {
            "model_name": self.model_name,
            "device": self.device,
            "torch_dtype": str(self.torch_dtype),
            "status": "loaded",
            "vocab_size": self.tokenizer.vocab_size if self.tokenizer else None,
            "max_position_embeddings": getattr(self.model.config, 'max_position_embeddings', None),
        }

    async def clear_model(self):
        """Clear the model from memory."""
        if self.model:
            del self.model
            self.model = None
        if self.tokenizer:
            del self.tokenizer
            self.tokenizer = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self.logger.info(
            "Model cleared from memory"
        )
