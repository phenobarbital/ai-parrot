"""
LLMClient Handler - HTTP Interface for LLM Clients
==================================================
Allows direct interaction with LLM clients (parrot.clients) without using an Agent/Bot.
Supports configuration via LLMFactory and dynamic ToolManager creation.
"""
from typing import Dict, Any, List, Optional, Union
import logging
from aiohttp import web
import pandas as pd
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.tools.manager import ToolManager
from parrot.models.responses import AIMessage
from parrot.outputs import OutputMode

# Try to import Model Enums for listing supported models
try:
    from parrot.models.openai import OpenAIModel
except ImportError:
    OpenAIModel = None

try:
    from parrot.models.groq import GroqModel
except ImportError:
    GroqModel = None

try:
    from parrot.clients.claude import ClaudeModel
except ImportError:
    ClaudeModel = None

try:
    from parrot.models.google import GoogleModel
except ImportError:
    GoogleModel = None


@is_authenticated()
@user_session()
class LLMClient(BaseView):
    """
    LLMClient Handler - Interface for direct LLM interaction.

    Endpoints:
        GET /api/v1/ai/clients: List available clients
        GET /api/v1/ai/clients/models: List supported models (optional ?client= filter)
        POST /api/v1/ai/client: Create client and ask (requires 'llm' or 'client' in body)
        POST /api/v1/ai/client/{client_name}: Use specific client and ask
    """
    _logger_name: str = "Parrot.LLMClient"

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)

    def _get_supported_models(self, provider: str) -> List[str]:
        """Get list of supported models for a given provider."""
        provider = provider.lower()
        
        if provider in ['openai', 'azure'] and OpenAIModel:
            return [m.value for m in OpenAIModel]
        elif provider == 'groq' and GroqModel:
            return [m.value for m in GroqModel]
        elif provider in ['anthropic', 'claude'] and ClaudeModel:
            return [m.value for m in ClaudeModel]
        elif provider == 'google' and GoogleModel:
            return [m.value for m in GoogleModel]
        
        # Fallback or Todo: inspect the client class if possible, or return empty
        return []

    async def get(self):
        """
        GET handler for clients and models.
        """
        # Check if we are asking for models
        if 'models' in self.request.path:
            return self._list_models()
        
        # Otherwise list clients
        return self.json_response({
            "clients": list(SUPPORTED_CLIENTS.keys()),
            "message": "Available LLM Clients"
        })

    def _list_models(self):
        """List supported models."""
        qs = self.query_parameters(self.request)
        client_filter = qs.get('client')

        if client_filter:
            if client_filter not in SUPPORTED_CLIENTS:
                return self.error(f"Client '{client_filter}' not supported.", status=404)
            models = self._get_supported_models(client_filter)
            return self.json_response({
                "client": client_filter,
                "models": models
            })
        
        # Return all supported models
        all_models = {}
        for client in SUPPORTED_CLIENTS:
            models = self._get_supported_models(client)
            if models:
                all_models[client] = models
        
        return self.json_response(all_models)

    async def post(self):
        """
        POST handler for client interaction.
        
        Usage:
            POST /api/v1/ai/client
            BODY: {
                "client": "openai",  # or "openai:gpt-4o"
                "input": "User question",
                "tools": [...],
                "config": {...}
            }
            
            OR
            
            POST /api/v1/ai/client/{client_name}
            BODY: {
                "input": "User question",
                ...
            }
        """
        try:
            data = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body", status=400)

        # 1. Determine Client and Model
        client_name = self.request.match_info.get('client_name')
        llm_string = data.get('client') or data.get('llm')

        if client_name:
            if llm_string and not llm_string.startswith(client_name):
                # Warning or override? Let's treat URL as primary provider source
                pass
            llm_target = f"{client_name}:{data.get('model')}" if data.get('model') else client_name
        elif llm_string:
            llm_target = llm_string
        else:
            return self.error("Missing client/llm specification", status=400)

        # 2. Extract Input/Question
        prompt = data.get('input') or data.get('query') or data.get('question')
        if not prompt:
            return self.error("Missing 'input' (or query/question) in payload", status=400)

        # 3. Setup ToolManager if tools specificed
        tools_def = data.get('tools')
        tool_manager = None
        if tools_def:
            try:
                tool_manager = ToolManager(debug=True)
                # Register tools from list of dicts or definitions
                tool_manager.register_tools(tools_def)
                self.logger.info(f"Initialized ToolManager with {len(tools_def)} tools")
            except Exception as e:
                self.logger.error(f"Failed to initialize tools: {e}")
                return self.error(f"Invalid tools configuration: {e}", status=400)

        # 4. Create Client using Factory
        model_args = data.get('model_args', {})
        # Flatten valid known args from root of data if not in model_args
        for key in ['temperature', 'max_tokens', 'top_p', 'top_k']:
            if key in data:
                model_args[key] = data[key]

        try:
            # Parse the llm_target to get cleaner provider for validation
            provider, _ = LLMFactory.parse_llm_string(llm_target)
            if provider not in SUPPORTED_CLIENTS:
                 return self.error(f"Unsupported client provider: {provider}", status=400)

            client = LLMFactory.create(
                llm=llm_target,
                model_args=model_args,
                tool_manager=tool_manager,
                **data.get('config', {}) # Pass extra config like api_keys if allowed/needed
            )
        except ValueError as e:
            return self.error(str(e), status=400)
        except Exception as e:
            self.logger.exception("Error creating client")
            return self.error(f"Error creating client: {e}", status=500)

        # 5. Ask the question
        try:
            # Extract ask-specific parameters
            ask_kwargs = data.get('ask_kwargs', {})
            
            # Map top-level params to ask arguments if present
            if 'session_id' in data:
                ask_kwargs['session_id'] = data['session_id']
            if 'user_id' in data:
                ask_kwargs['user_id'] = data['user_id']
            
            async with client:
                response: AIMessage = await client.ask(
                    prompt=prompt,
                    **ask_kwargs
                )
                
            # 6. Format Response
            output_format = data.get('output_format', 'json')
            format_kwargs = data.get('format_kwargs', {})
            
            return self._format_response(response, output_format, format_kwargs)

        except Exception as e:
            self.logger.exception("Error during client interaction")
            return self.error(f"Client execution error: {e}", status=500)

    def _format_response(
        self,
        response: AIMessage,
        output_format: str,
        format_kwargs: Dict[str, Any]
    ) -> web.Response:
        """
        Format the response based on the requested output format.
        Adapted from AgentTalk.
        """
        # Defaults
        output_format = output_format.lower()
        
        if output_format == 'json':
            # Construct structured JSON response
            output = response.content
            
            # Handle if content is complex object
            if isinstance(output, pd.DataFrame):
                output = output.to_dict(orient='records')
            
            obj_response = {
                "content": output,
                "metadata": {
                    "model": getattr(response, 'model', None),
                    "session_id": getattr(response, 'session_id', None),
                    "turn_id": getattr(response, 'turn_id', None),
                    "timestamp": getattr(response, 'timestamp', None),
                },
                "tool_calls": [
                    {
                        "name": getattr(tool, 'name', 'unknown'),
                        "status": getattr(tool, 'status', 'completed'),
                        "output": getattr(tool, 'output', None),
                        'arguments': getattr(tool, 'arguments', None)
                    }
                    for tool in getattr(response, 'tool_calls', [])
                ] if getattr(response, 'tool_calls', None) else []
            }
            
            # Include sources if available and requested
            if hasattr(response, 'documents') and response.documents:
                obj_response["sources"] = response.documents

            return web.json_response(
                obj_response, dumps=json_encoder, content_type='application/json'
            )

        else:
            # Text/Markdown response
            return web.Response(
                text=str(response.content),
                content_type='text/plain',
                charset='utf-8'
            )
