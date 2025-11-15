"""
AgentTalk - HTTP Handler for Agent Conversations
=================================================
Provides a flexible HTTP interface for talking with agents/bots using the ask() method
with support for multiple output modes and MCP server integration.
"""
from typing import Dict, Any, List, Union
import tempfile
import os
import json
import inspect
from aiohttp import web
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611
from navconfig.logging import logging
from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView
from ..bots.abstract import AbstractBot
from ..models.responses import AIMessage, AgentResponse
from ..outputs import OutputMode, OutputFormatter
from ..mcp.integration import MCPServerConfig


logging.getLogger("parrot").setLevel(logging.DEBUG)


@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    """
    AgentTalk Handler - Universal agent conversation interface.

    Endpoints:
        POST /api/v1/agents/chat/ - Main chat endpoint with format negotiation

    Features:
    - POST to /api/v1/agents/chat/ to interact with agents
    - Uses BotManager to retrieve the agent
    - Supports multiple output formats (JSON, HTML, Markdown, Terminal)
    - Can add MCP servers dynamically via POST attributes
    - Leverages OutputMode for consistent formatting
    - Session-based conversation management
    """
    def _get_output_format(
        self,
        data: Dict[str, Any],
        qs: Dict[str, Any]
    ) -> str:
        """
        Determine the output format from request.

        Priority:
        1. Explicit 'output_format' in request body or query string
        2. Content-Type header from Accept header
        3. Default to 'json'

        Args:
            data: Request body data
            qs: Query string parameters

        Returns:
            Output format string: 'json', 'html', 'markdown', or 'text'
        """
        # Check explicit output_format parameter
        output_format = data.pop('output_format', None) or qs.get('output_format')
        if output_format:
            return output_format.lower()

        # Check Accept header
        accept_header = self.request.headers.get('Accept', 'application/json')

        if 'text/html' in accept_header:
            return 'html'
        elif 'text/markdown' in accept_header:
            return 'markdown'
        elif 'text/plain' in accept_header:
            return 'text'
        else:
            return 'json'

    def _get_output_mode(self, request: web.Request) -> OutputMode:
        """
        Determine output mode from request headers and parameters.

        Priority:
        1. Query parameter 'output_mode'
        2. Content-Type header
        3. Accept header
        4. Default to OutputMode.DEFAULT
        """
        # Check query parameters first
        qs = self.query_parameters(request)
        if 'output_mode' in qs:
            mode = qs['output_mode'].lower()
            if mode in ['json', 'html', 'terminal', 'markdown', 'default']:
                return OutputMode(mode if mode != 'markdown' else 'default')

        # Check Content-Type header
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type:
            return OutputMode.JSON
        elif 'text/html' in content_type:
            return OutputMode.HTML

        # Check Accept header
        accept = request.headers.get('Accept', '').lower()
        if 'application/json' in accept:
            return OutputMode.JSON
        elif 'text/html' in accept:
            return OutputMode.HTML
        elif 'text/plain' in accept:
            return OutputMode.DEFAULT

        return OutputMode.DEFAULT

    def _format_to_output_mode(self, format_str: str) -> OutputMode:
        """
        Convert format string to OutputMode enum.

        Args:
            format_str: Format string (json, html, markdown, text, terminal)

        Returns:
            OutputMode enum value
        """
        format_map = {
            'json': OutputMode.JSON,
            'html': OutputMode.HTML,
            'markdown': OutputMode.DEFAULT,
            'text': OutputMode.DEFAULT,
            'terminal': OutputMode.TERMINAL,
            'default': OutputMode.DEFAULT
        }
        return format_map.get(format_str.lower(), OutputMode.DEFAULT)

    def _prepare_response(
        self,
        ai_message: AIMessage,
        output_mode: OutputMode,
        format_kwargs: Dict[str, Any] = None
    ):
        """
        Format and return the response based on output mode.

        Args:
            ai_message: The AIMessage response from the agent
            output_mode: The desired output format
            format_kwargs: Additional formatting options
        """
        formatter = OutputFormatter()

        if output_mode == OutputMode.JSON:
            # Return structured JSON response
            response_data = {
                "content": ai_message.content,
                "metadata": {
                    "session_id": getattr(ai_message, 'session_id', None),
                    "user_id": getattr(ai_message, 'user_id', None),
                    "timestamp": getattr(ai_message, 'timestamp', None),
                },
                "tool_calls": getattr(ai_message, 'tool_calls', []),
                "sources": getattr(ai_message, 'documents', []) if hasattr(ai_message, 'documents') else []
            }

            if hasattr(ai_message, 'error') and ai_message.error:
                response_data['error'] = ai_message.error
                return self.json_response(response_data, status=400)

            return self.json_response(response_data)

        elif output_mode == OutputMode.HTML:
            # Return formatted HTML
            formatted_content = formatter.format(
                mode=output_mode,
                data=ai_message,
                **(format_kwargs or {})
            )

            # Create complete HTML page
            html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Response</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.6;
            background-color: #f5f5f5;
        }}
        .response-container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metadata {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #eee;
        }}
        .content {{
            color: #333;
        }}
        .sources {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.9em;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <div class="response-container">
        <div class="metadata">
            <strong>Agent Response</strong>
        </div>
        <div class="content">
            {formatted_content}
        </div>
    </div>
</body>
</html>
            """
            return web.Response(
                text=html_template,
                content_type='text/html',
                charset='utf-8'
            )

        else:
            # Return markdown/plain text
            formatted_content = formatter.format(ai_message, **(format_kwargs or {}))
            return web.Response(
                text=str(formatted_content),
                content_type='text/plain',
                charset='utf-8'
            )

    async def _add_mcp_servers(self, agent: AbstractBot, mcp_configs: list):
        """
        Add MCP servers to the agent if it supports MCP.

        Args:
            agent: The agent instance
            mcp_configs: List of MCP server configurations
        """
        if not hasattr(agent, 'add_mcp_server'):
            self.logger.warning(
                f"Agent {agent.name} does not support MCP servers. "
                "Ensure BasicAgent has MCPEnabledMixin."
            )
            return

        for config_dict in mcp_configs:
            try:
                # Create MCPServerConfig from dict
                config = MCPServerConfig(
                    name=config_dict.get('name'),
                    url=config_dict.get('url'),
                    auth_type=config_dict.get('auth_type'),
                    auth_config=config_dict.get('auth_config', {}),
                    headers=config_dict.get('headers', {}),
                    allowed_tools=config_dict.get('allowed_tools'),
                    blocked_tools=config_dict.get('blocked_tools'),
                )

                tools = await agent.add_mcp_server(config)
                self.logger.info(
                    f"Added MCP server '{config.name}' with {len(tools)} tools to agent {agent.name}"
                )
            except Exception as e:
                self.logger.error(f"Failed to add MCP server: {e}")

    def _check_methods(self, bot: AbstractBot, method_name: str):
        """Check if the method exists in the bot and is callable."""
        forbidden_methods = {
            '__init__', '__del__', '__getattribute__', '__setattr__',
            'configure', '_setup_database_tools', 'save', 'delete',
            'update', 'insert', '__dict__', '__class__', 'retrieval',
            '_define_prompt', 'configure_llm', 'configure_store', 'default_tools'
        }
        if not method_name:
            return None
        if method_name.startswith('_') or method_name in forbidden_methods:
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        if not hasattr(bot, method_name):
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        method = getattr(bot, method_name)
        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} is not callable in bot {bot.name}."
            )
        return method

    async def _execute_agent_method(
        self,
        bot: AbstractBot,
        method_name: str,
        data: Dict[str, Any],
        attachments: Dict[str, Any],
        use_background: bool,
    ) -> web.Response:
        """Resolve and invoke an agent method safely."""
        try:
            method = self._check_methods(bot, method_name)
        except (AttributeError, TypeError) as exc:
            self.logger.error(f"Method {method_name} not available: {exc}")
            return self.json_response(
                {"error": f"Method {method_name} not available."},
                status=400,
            )

        sig = inspect.signature(method)
        method_params: Dict[str, Any] = {}
        missing_required: List[str] = []
        remaining_kwargs = dict(data)

        for param_name, param in sig.parameters.items():
            if param_name == 'self' or param_name == 'kwargs':
                continue

            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                continue

            if param_name in remaining_kwargs:
                method_params[param_name] = remaining_kwargs.pop(param_name)
            elif param.default == inspect.Parameter.empty:
                missing_required.append(param_name)

            if param_name in attachments:
                method_params[param_name] = attachments[param_name]
                remaining_kwargs.pop(param_name, None)

        if missing_required:
            return self.json_response(
                {
                    "message": (
                        "Required parameters missing: "
                        f"{', '.join(missing_required)}"
                    ),
                    "required_params": [
                        p for p in sig.parameters.keys() if p != 'self'
                    ],
                },
                status=400,
            )

        final_kwargs = {**method_params, **remaining_kwargs}

        try:
            if use_background:
                self.request.app.loop.create_task(method(**final_kwargs))
                return self.json_response(
                    {"message": "Request is being processed in the background."}
                )

            response = await method(**final_kwargs)
            if isinstance(response, web.Response):
                return response

            return self.json_response(
                {
                    "message": (
                        f"Method {method_name} was executed successfully."
                    ),
                    "response": str(response),
                }
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                f"Error calling method {method_name}: {exc}",
                exc_info=True,
            )
            return self.json_response(
                {"error": f"Error calling method {method_name}: {exc}"},
                status=500,
            )

    async def post(self):
        """
        POST handler for agent interaction.

        Endpoint: POST /api/v1/agents/chat/

        Request body:
        {
            "agent_name": "my_agent",
            "query": "What is the weather like?",
            "session_id": "optional-session-id",
            "user_id": "optional-user-id",
            "output_mode": "json|html|markdown|terminal|default",
            "search_type": str,          # Optional: "similarity", "mmr", "ensemble"
            "use_vector_context": bool,  # Optional: Use vector store context
            "format_kwargs": {
                "show_metadata": true,
                "show_sources": true
            },
            "mcp_servers": [
                {
                    "name": "weather_api",
                    "url": "https://api.example.com/mcp",
                    "auth_type": "api_key",
                    "auth_config": {"api_key": "xxx"},
                    "headers": {"User-Agent": "AI-Parrot/1.0"}
                }
            ]
        }

        Returns:
        - JSON response if output_mode is 'json' or Accept header is application/json
        - HTML page if output_mode is 'html' or Accept header is text/html
        - Markdown/plain text otherwise
        """
        try:
            qs = self.query_parameters(self.request)
            app = self.request.app
            method_name = self.request.match_info.get('method_name', None)
            try:
                attachments, data = await self.handle_upload()
            except web.HTTPUnsupportedMediaType:
                # if no file is provided, then is a JSON request:
                data = await self.request.json()
                attachments = {}

            # Support method invocation via body or query parameter in addition to the
            # /{agent_id}/{method_name} route so clients don't need to construct a
            # different URL for maintenance operations like refresh_data.
            method_name = (
                method_name
                or data.pop('method_name', None)
                or qs.get('method_name')
            )
            # Get BotManager
            manager = self.request.app.get('bot_manager')
            if not manager:
                return self.json_response(
                    {"error": "BotManager is not installed."},
                    status=500
                )

            # Extract agent name
            agent_name = self.request.match_info.get('agent_id', None)
            if not agent_name:
                agent_name = data.pop('agent_name', None) or qs.get('agent_name')
            if not agent_name:
                return self.error(
                    "Missing Agent Name",
                    status=400
                )
            query = data.pop('query', None)
            # Get the agent
            try:
                agent: AbstractBot = await manager.get_bot(agent_name)
                if not agent:
                    return self.error(
                        f"Agent '{agent_name}' not found.",
                        status=404
                    )
            except Exception as e:
                self.logger.error(f"Error retrieving agent {agent_name}: {e}")
                return self.error(
                    f"Error retrieving agent: {e}",
                    status=500
                )

            # task background:
            use_background = data.pop('background', False)

            # Add MCP servers if provided
            mcp_servers = data.pop('mcp_servers', [])
            if mcp_servers and isinstance(mcp_servers, list):
                await self._add_mcp_servers(agent, mcp_servers)

            # TODO: Get session information
            session_id = data.pop('session_id', None)
            user_id = data.pop('user_id', None)

            # Try to get from request session if not provided
            try:
                request_session = self.request.session
                if not session_id:
                    session_id = request_session.get('session_id')
                if not user_id:
                    user_id = request_session.get('user_id')
            except AttributeError:
                pass

            # Determine output mode
            # output_mode = self._get_output_mode(self.request)
            # Determine output format
            output_format = self._get_output_format(data, qs)
            output_mode = data.pop('output_mode', OutputMode.DEFAULT)

            # Extract parameters for ask()
            search_type = data.pop('search_type', 'similarity')
            return_sources = data.pop('return_sources', True)
            use_vector_context = data.pop('use_vector_context', True)
            use_conversation_history = data.pop('use_conversation_history', True)

            # Override with explicit parameter if provided
            if 'output_mode' in data:
                try:
                    output_mode = OutputMode(data['output_mode'])
                except ValueError:
                    pass  # Keep the detected mode

            # Prepare ask() parameters
            format_kwargs = data.pop('format_kwargs', {})
            response = None
            async with agent.retrieval(self.request, app=app) as bot:
                if method_name:
                    return await self._execute_agent_method(
                        bot=bot,
                        method_name=method_name,
                        data=data,
                        attachments=attachments,
                        use_background=use_background,
                    )
                else:
                    if not query:
                        return self.json_response(
                            {"error": "query is required"},
                            status=400
                        )
                    response: AIMessage = await bot.ask(
                        question=query,
                        session_id=session_id,
                        user_id=user_id,
                        search_type=search_type,
                        return_sources=return_sources,
                        use_vector_context=use_vector_context,
                        use_conversation_history=use_conversation_history,
                        output_mode=output_mode,
                        format_kwargs=format_kwargs,
                        **data,
                    )

            # Return formatted response
            return self._format_response(
                response,
                output_format,
                format_kwargs
            )

        except json.JSONDecodeError:
            return self.json_response(
                {"error": "Invalid JSON in request body"},
                status=400
            )
        except Exception as e:
            self.logger.error(f"Error in AgentTalk: {e}", exc_info=True)
            return self.json_response(
                {
                    "error": "Internal server error",
                    "message": str(e)
                },
                status=500
            )

    async def get(self):
        """
        GET /api/v1/agents/chat/

        Returns information about the AgentTalk endpoint.
        """
        method_name = self.request.match_info.get('method_name', None)
        if method_name == 'debug':
            agent_name = self.request.match_info.get('agent_id', None)
            if not agent_name:
                return self.error(
                    "Missing Agent Name for debug.",
                    status=400
                )
            manager = self.request.app.get('bot_manager')
            if not manager:
                return self.json_response(
                    {"error": "BotManager is not installed."},
                    status=500
                )
            try:
                agent: AbstractBot = await manager.get_bot(agent_name)
                if not agent:
                    return self.error(
                        f"Agent '{agent_name}' not found.",
                        status=404
                    )
            except Exception as e:
                self.logger.error(f"Error retrieving agent {agent_name}: {e}")
                return self.error(
                    f"Error retrieving agent: {e}",
                    status=500
                )
            debug_info = await self.debug_agent(agent)
            return self.json_response(debug_info)

        return self.json_response({
            "message": "AgentTalk - Universal Agent Conversation Interface",
            "version": "1.0",
            "usage": {
                "method": "POST",
                "endpoint": "/api/v1/agents/chat/",
                "required_fields": ["agent_name", "query"],
                "optional_fields": [
                    "session_id",
                    "user_id",
                    "output_mode",
                    "format_kwargs",
                    "mcp_servers",
                    "ask_kwargs"
                ],
                "output_modes": ["json", "html", "markdown", "terminal", "default"]
            }
        })

    def _format_response(
        self,
        response: Union[AIMessage, AgentResponse],
        output_format: str,
        format_kwargs: Dict[str, Any]
    ) -> web.Response:
        """
        Format the response based on the requested output format.

        Args:
            response: AIMessage from agent
            output_format: Requested format
            format_kwargs: Additional formatting options

        Returns:
            web.Response with appropriate content type
        """

        if isinstance(response, AgentResponse):
            response = response.response

        if output_format == 'json':
            # Return structured JSON response
            return web.json_response({
                "input": response.input,
                "output": response.output,
                "content": response.content,
                "response": response.response,
                "metadata": {
                    "model": getattr(response, 'model', None),
                    "provider": getattr(response, 'provider', None),
                    "session_id": str(getattr(response, 'session_id', '')),
                    "turn_id": str(getattr(response, 'turn_id', '')),
                    "response_time": getattr(response, 'response_time', None),
                },
                "sources": [
                    {
                        "content": source.content,
                        "metadata": source.metadata
                    }
                    for source in getattr(response, 'sources', [])
                ] if format_kwargs.get('include_sources', True) else [],
                "tool_calls": [
                    {
                        "name": getattr(tool, 'name', 'unknown'),
                        "status": getattr(tool, 'status', 'completed'),
                        "output": getattr(tool, 'output', None),
                        'arguments': getattr(tool, 'arguments', None)
                    }
                    for tool in getattr(response, 'tool_calls', [])
                ] if format_kwargs.get('include_tool_calls', True) else []
            }, dumps=json_encoder)

        elif output_format == 'html':
            interactive = format_kwargs.get('interactive', False)
            if interactive:
                return self._serve_panel_dashboard(response)

            # Return HTML response
            html_content = response.content
            if isinstance(html_content, str):
                html_str = html_content
            elif hasattr(html_content, '_repr_html_'):
                # Panel/IPython displayable object (for HTML mode)
                html_str = html_content._repr_html_()
            elif hasattr(html_content, '__str__'):
                # Other objects with string representation
                html_str = str(html_content)
            else:
                html_str = str(html_content)
            # Wrap in complete HTML document
            full_html = self._create_html_document(html_str, response)

            return web.Response(
                text=full_html,
                content_type='text/html',
                charset='utf-8'
            )

        else:  # markdown or text
            # Return plain text/markdown response
            content = response.content

            # Ensure it's a string
            if not isinstance(content, str):
                content = str(content)

            # Optionally append sources
            if format_kwargs.get('include_sources', False) and hasattr(response, 'sources'):
                content += "\n\n## Sources\n"
                for idx, source in enumerate(response.sources, 1):
                    content += f"\n{idx}. {source.content[:200]}...\n"

            return web.Response(
                text=content,
                content_type='text/plain' if output_format == 'text' else 'text/markdown',
                charset='utf-8'
            )

    def _create_html_document(self, content: str, response: AIMessage) -> str:
        """
        Create a complete HTML document wrapper.

        Args:
            content: HTML content to wrap
            response: AIMessage for metadata

        Returns:
            Complete HTML document string
        """
        if content.startswith("<!DOCTYPE"):
            # If content is already a complete HTML document, return it as-is
            return content

        title = f"Agent Response"

        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header {{
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}
        .content {{
            margin-top: 20px;
        }}
        pre {{
            background-color: #f5f5f5;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        code {{
            background-color: #f5f5f5;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f0f0f0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
        </div>
        <div class="content">
            {content}
        </div>
    </div>
</body>
</html>"""

        return html_template

    def _serve_panel_dashboard(self, response: AIMessage) -> web.Response:
        """
        Serve an interactive Panel dashboard.

        This converts the Panel object to a standalone HTML application
        with embedded JavaScript for interactivity.

        Args:
            response: AIMessage with Panel object in .content

        Returns:
            web.Response with interactive HTML
        """
        try:
            panel_obj = response.content
            # Create temporary file for the Panel HTML
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.html',
                delete=False
            ) as tmp:
                tmp_path = tmp.name

            try:
                # Save Panel to HTML with all resources embedded
                panel_obj.save(
                    tmp_path,
                    embed=True,  # Embed all JS/CSS resources
                    title=f"AI Agent Response - {response.session_id[:8] if response.session_id else 'interactive'}",
                    resources='inline'  # Inline all resources
                )

                # Read the HTML content
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # Return as HTML response
                return web.Response(
                    text=html_content,
                    content_type='text/html',
                    charset='utf-8'
                )

            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        self.logger.warning(f"Failed to delete temp file {tmp_path}: {e}")

        except ImportError:
            self.logger.error(
                "Panel library not available for interactive dashboards"
            )
            # Fallback to static HTML
            return web.Response(
                text=str(response.content),
                content_type='text/html',
                charset='utf-8'
            )
        except Exception as e:
            self.logger.error(f"Error serving Panel dashboard: {e}", exc_info=True)
            # Fallback to error response
            return self.error(
                f"Error rendering interactive dashboard: {e}",
                status=500
            )

    async def debug_agent(self, agent):
        return {
            "dataframes": list(agent.dataframes.keys()),
            "df_metadata": {k: v['shape'] for k, v in agent.df_metadata.items()},
            "pandas_tool": {
                "exists": agent._get_python_pandas_tool() is not None,
                "dataframes": list(agent._get_python_pandas_tool().dataframes.keys())
                    if agent._get_python_pandas_tool() else []
            },
            "metadata_tool": {
                "exists": agent._get_metadata_tool() is not None,
                "dataframes": list(agent._get_metadata_tool().dataframes.keys())
                    if agent._get_metadata_tool() else [],
                "metadata": list(agent._get_metadata_tool().metadata.keys())
                    if agent._get_metadata_tool() else []
            }
        }
