import textwrap
from typing import Dict, List, Tuple, Any, Optional, Union, Callable
from datetime import datetime
from pathlib import Path
import aiofiles
import pandas as pd
from navconfig import BASE_DIR
from navconfig.logging import logging
from ..models.responses import AIMessage, AgentResponse
from ..clients.google import GoogleGenAIClient
from .chatbot import Chatbot
from .prompts import AGENT_PROMPT
from ..tools.abstract import AbstractTool
from ..tools.pythonrepl import PythonREPLTool
from ..tools.pythonpandas import PythonPandasTool
from ..tools.pdfprint import PDFPrintTool
from ..tools.powerpoint import PowerPointTool
from ..tools.agent import AgentTool, AgentContext
from ..models.google import (
    ConversationalScriptConfig,
    FictionalSpeaker
)
# MCP Integration
from ..mcp import (
    MCPEnabledMixin,
    MCPServerConfig,
    MCPToolManager,
    create_http_mcp_server,
    create_local_mcp_server,
    create_api_key_mcp_server
)
from ..conf import STATIC_DIR, AGENTS_BOTS_PROMPT_DIR, AGENTS_DIR
from ..notifications import NotificationMixin


class BasicAgent(MCPEnabledMixin, Chatbot, NotificationMixin):
    """Represents an Agent in Navigator.

        Agents are chatbots that can access to Tools and execute commands.
        Each Agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).

        These agents are designed to interact with structured and unstructured data sources.

        Features:
        - Built-in MCP server support (no separate mixin needed)
        - Can connect to HTTP, OAuth, API-key authenticated, and local MCP servers
        - Automatic tool registration from MCP servers
        - Compatible with all existing agent functionality
        - Notification capabilities through various channels (e.g., email, Slack, Teams)
    """
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    _agent_response = AgentResponse
    speech_context: str = ""
    speech_system_prompt: str = ""
    podcast_system_instruction: str = None
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 1  # Default number of speakers for the podcast
    speakers: Dict[str, str] = {
        "interviewer": {
            "name": "Lydia",
            "role": "interviewer",
            "characteristic": "Bright",
            "gender": "female"
        },
        "interviewee": {
            "name": "Brian",
            "role": "interviewee",
            "characteristic": "Informative",
            "gender": "male"
        }
    }
    max_tokens: int = None # Use default max tokens from Chatbot
    model_name: str = None  # Use default model from Chatbot
    report_template: str = "report_template.html"
    system_prompt_template: str = AGENT_PROMPT

    def __init__(
        self,
        name: str = 'Agent',
        agent_id: str = 'agent',
        use_llm: str = 'google',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        use_tools: bool = True,
        instructions: Optional[str] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs
    ):
        self.agent_id = self.agent_id or agent_id
        self.agent_name = self.agent_name or name
        tools = self._get_default_tools(tools)
        kwargs.setdefault('model', self.model_name)
        kwargs.setdefault('max_tokens', self.max_tokens)
        super().__init__(
            name=name,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            use_tools=use_tools,
            **kwargs
        )
        if instructions:
            self.goal = instructions
        self.enable_tools = True  # Enable tools by default
        self.operation_mode = 'agentic' # Default operation mode
        self.auto_tool_detection = True  # Enable auto tool detection by default
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )
        ## Google GenAI Client (for multi-modal responses and TTS generation):
        self.client = GoogleGenAIClient()
        # install agent-specific tools:
        self.tools = self.agent_tools()
        self.tool_manager.register_tools(self.tools)
        # Initialize MCP support
        self.mcp_manager = MCPToolManager(
            self.tool_manager
        )
        # to work with dataframes:
        self.dataframes = dataframes or {}
        self._dataframe_info_cache = None

    def _get_default_tools(self, tools: list) -> List[AbstractTool]:
        """Return Agent-specific tools."""
        if not tools:
            tools = []
        tools.extend(
            [
                PythonREPLTool(
                    report_dir=AGENTS_DIR.joinpath(self.agent_id, 'documents')
                ),
            ]
        )
        return tools

    def agent_tools(self) -> List[AbstractTool]:
        """Return the agent-specific tools."""
        return []

    def set_response(self, response: AgentResponse):
        """Set the response for the agent."""
        self._agent_response = response

    async def setup_mcp_servers(self, configurations: List[MCPServerConfig]) -> None:
        """
        Setup multiple MCP servers during initialization.

        This is useful for configuring an agent with multiple MCP servers
        at once, typically during agent creation or from configuration files.

        Args:
            configurations: List of MCPServerConfig objects

        Example:
            >>> configs = [
            ...     create_http_mcp_server("weather", "https://api.weather.com/mcp"),
            ...     create_local_mcp_server("files", "./mcp_servers/files.py")
            ... ]
            >>> await agent.setup_mcp_servers(configs)
        """
        for config in configurations:
            try:
                tools = await self.add_mcp_server(config)
                self.logger.info(
                    f"Added MCP server '{config.name}' with tools: {tools}"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to add MCP server '{config.name}': {e}",
                    exc_info=True
                )

    def _create_filename(self, prefix: str = 'report', extension: str = 'pdf') -> str:
        """Create a unique filename for the report."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"{prefix}_{timestamp}.{extension}"

    async def save_document(
        self,
        content: str,
        prefix: str = 'report',
        extension: str = 'txt',
        directory: Optional[Path] = None,
        subdir: str = 'documents'
    ) -> None:
        """Save the document to a file."""
        report_filename = self._create_filename(
            prefix=prefix, extension=extension
        )
        if not directory:
            directory = STATIC_DIR.joinpath(self.agent_id, subdir)
        try:
            async with aiofiles.open(
                directory.joinpath(report_filename),
                'w'
            ) as report_file:
                await report_file.write(content)
        except Exception as e:
            self.logger.error(
                f"Failed to save document {report_filename}: {e}"
            )

    async def open_prompt(self, prompt_file: str = None) -> str:
        """
        Opens a prompt file and returns its content.
        """
        if not prompt_file:
            raise ValueError("No prompt file specified.")
        file = AGENTS_DIR.joinpath(self.agent_id, 'prompts', prompt_file)
        try:
            async with aiofiles.open(file, 'r') as f:
                content = await f.read()
            return content
        except Exception as e:
            self.logger.error(
                f"Failed to read prompt file {prompt_file}: {e}"
            )
            return None

    async def open_query(self, query: str, directory: Optional[Path] = None, **kwargs) -> str:
        """
        Opens a query string and formats it with provided keyword arguments.
        """
        if not query:
            raise ValueError("No query specified.")
        if not directory:
            directory = AGENTS_DIR.joinpath(self.agent_id, 'queries')
        try:
            query_file = directory.joinpath(query)
            return query_file.read_text().format(**kwargs)
        except Exception as e:
            self.logger.error(
                f"Failed to format query: {e}"
            )
            return None

    async def generate_report(
        self,
        prompt_file: str,
        save: bool = False,
        directory: Optional[Path] = None,
        **kwargs
    ) -> Tuple[AIMessage, AgentResponse]:
        """Generate a report based on the provided prompt."""
        try:
            query = await self.open_prompt(prompt_file)
            query = textwrap.dedent(query)
        except (ValueError, RuntimeError) as e:
            self.logger.error(f"Error opening prompt file: {e}")
            return str(e)
        # Format the question based on keyword arguments:
        question = query.format(**kwargs)
        if not directory:
            directory = STATIC_DIR.joinpath(self.agent_id, 'documents')
        try:
            response = await self.invoke(
                question=question,
            )
            # Create the response object
            final_report = response.output.strip()
            if not final_report:
                raise ValueError("The generated report is empty.")
            response_data = self._agent_response(
                session_id=response.turn_id,
                data=final_report,
                agent_name=self.name,
                agent_id=self.agent_id,
                response=response,
                status="success",
                created_at=datetime.now(),
                output=response.output,
                **kwargs
            )
            # before returning, we can save the report if needed:
            if save:
                try:
                    report_filename = self._create_filename(
                        prefix='report', extension='txt'
                    )
                    async with aiofiles.open(
                        directory.joinpath(report_filename),
                        'w'
                    ) as report_file:
                        await report_file.write(final_report)
                    response_data.document_path = report_filename
                    self.logger.info(f"Report saved as {report_filename}")
                except Exception as e:
                    self.logger.error(f"Error saving report: {e}")
            return response, response_data
        except Exception as e:
            self.logger.error(f"Error generating report: {e}")
            return str(e)

    async def save_transcript(
        self,
        transcript: str,
        filename: str = None,
        prefix: str = 'transcript',
        directory: Optional[str] = None,
        subdir='transcripts'
    ) -> str:
        """Save the transcript to a file."""
        if not directory:
            directory = STATIC_DIR.joinpath(self.agent_id, subdir)
        directory.mkdir(parents=True, exist_ok=True)
        # Create a unique filename if not provided
        if not filename:
            filename = self._create_filename(prefix=prefix, extension='txt')
        file_path = directory.joinpath(filename)
        try:
            async with aiofiles.open(file_path, 'w') as f:
                await f.write(transcript)
            self.logger.info(f"Transcript saved to {file_path}")
            return file_path
        except Exception as e:
            self.logger.error(f"Error saving transcript: {e}")
            raise RuntimeError(
                f"Failed to save transcript: {e}"
            ) from e

    async def pdf_report(
        self,
        content: str,
        filename_prefix: str = 'report',
        directory: Optional[Path] = None,
        title: str = None,
        **kwargs
    ) -> str:
        """Generate a report based on the provided prompt."""
        # Create a unique filename for the report
        if not directory:
            directory = STATIC_DIR.joinpath(self.agent_id, 'documents')
        pdf_tool = PDFPrintTool(
            templates_dir=BASE_DIR.joinpath('templates'),
            output_dir=directory
        )
        return await pdf_tool.execute(
            text=content,
            template_vars={"title": title or 'Report'},
            template_name=self.report_template,
            file_prefix=filename_prefix,

        )

    async def markdown_report(
        self,
        content: str,
        filename: Optional[str] = None,
        filename_prefix: str = 'report',
        directory: Optional[Path] = None,
        subdir: str = 'documents',
        **kwargs
    ) -> str:
        """Saving Markdown report based on provided file."""
        # Create a unique filename for the report
        if not directory:
            directory = STATIC_DIR.joinpath(self.agent_id, subdir)
        directory.mkdir(parents=True, exist_ok=True)
        # Create a unique filename if not provided
        if not filename:
            filename = self._create_filename(prefix=filename_prefix, extension='md')
        file_path = directory.joinpath(filename)
        try:
            async with aiofiles.open(file_path, 'w') as f:
                await f.write(content)
            self.logger.info(f"Transcript saved to {file_path}")
            return file_path
        except Exception as e:
            self.logger.error(f"Error saving transcript: {e}")
            raise RuntimeError(
                f"Failed to save transcript: {e}"
            ) from e

    async def speech_report(
        self,
        report: str,
        max_lines: int = 15,
        num_speakers: int = 2,
        podcast_instructions: Optional[str] = 'for_podcast.txt',
        directory: Optional[Path] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a Transcript Report and a Podcast based on findings."""
        if directory:
            output_directory = directory
        else:
            output_directory = STATIC_DIR.joinpath(self.agent_id, 'generated_scripts')
        output_directory.mkdir(parents=True, exist_ok=True)
        script_name = self._create_filename(prefix='script', extension='txt')
        # creation of speakers:
        speakers = []
        for _, speaker in self.speakers.items():
            speaker['gender'] = speaker.get('gender', 'neutral').lower()
            speakers.append(FictionalSpeaker(**speaker))
            if len(speakers) > num_speakers:
                self.logger.warning(
                    f"Too many speakers defined, limiting to {num_speakers}."
                )
                break

        # 1. Define the script configuration
        # Check if podcast_instructions is content or filename
        if podcast_instructions and (
            '\n' in podcast_instructions or len(podcast_instructions) > 100
        ):
            # It's likely content (has newlines or is long), use it directly
            podcast_instruction = podcast_instructions
        else:
            # It's a filename, load it
            podcast_instruction = await self.open_prompt(
                podcast_instructions or 'for_podcast.txt'
            )

        # Format the instruction with report text if it has placeholders
        if podcast_instruction and '{report_text}' in podcast_instruction:
            podcast_instruction = podcast_instruction.format(report_text=report)
        script_config = ConversationalScriptConfig(
            context=self.speech_context,
            speakers=speakers,
            report_text=report,
            system_prompt=self.speech_system_prompt,
            length=self.speech_length,  # Use the speech_length attribute
            system_instruction=podcast_instruction or None
        )
        async with self.client as client:
            # 2. Generate the conversational script
            response = await client.create_conversation_script(
                report_data=script_config,
                max_lines=max_lines,  # Limit to 15 lines for brevity,
                use_structured_output=True  # Use structured output for TTS
            )
            voice_prompt = response.output
            # 3. Save the script to a File:
            script_output_path = output_directory.joinpath(script_name)
            async with aiofiles.open(script_output_path, 'w') as script_file:
                await script_file.write(voice_prompt.prompt)
            self.logger.info(f"Script saved to {script_output_path}")
        # 4. Generate the audio podcast
        output_directory = STATIC_DIR.joinpath(self.agent_id, 'podcasts')
        output_directory.mkdir(parents=True, exist_ok=True)
        async with self.client as client:
            speech_result = await client.generate_speech(
                prompt_data=voice_prompt,
                output_directory=output_directory,
            )
            if speech_result and speech_result.files:
                print(f"✅ Multi-voice speech saved to: {speech_result.files[0]}")
            # 5 Return the script and audio file paths
            return {
                'script_path': script_output_path,
                'podcast_path': speech_result.files[0] if speech_result.files else None
            }

    async def report(self, prompt_file: str, **kwargs) -> AgentResponse:
        """Generate a report based on the provided prompt."""
        query = await self.open_prompt(prompt_file)
        question = query.format(
            **kwargs
        )
        try:
            response = await self.conversation(
                question=question,
                max_tokens=8192
            )
            if isinstance(response, Exception):
                raise response
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # Prepare the response object:
        final_report = response.output.strip()
        for key, value in kwargs.items():
            if hasattr(response, key):
                setattr(response, key, value)
        response = self._agent_response(
            user_id=str(kwargs.get('user_id', 1)),
            agent_name=self.name,
            attributes=kwargs.pop('attributes', {}),
            data=final_report,
            status="success",
            created_at=datetime.now(),
            output=response.output,
            response=response,
            **kwargs
        )
        return await self._generate_report(response)

    async def _generate_report(
        self,
        response: AgentResponse,
        with_speech: bool = True
    ) -> AgentResponse:
        """Generate a report from the response data."""
        final_report = response.output.strip()
        if not final_report:
            response.output = "No report generated."
            response.status = "error"
            return response
        response.transcript = final_report
        try:
            _path = await self.save_transcript(
                transcript=final_report,
            )
            response.add_document(_path)
        except Exception as e:
            self.logger.error(f"Error generating transcript: {e}")
        # generate the PDF file:
        try:
            pdf_output = await self.pdf_report(
                content=final_report
            )
            response.set_pdf_path(
                pdf_output.result.get('file_path', None)
            )
        except Exception as e:
            self.logger.error(f"Error generating PDF: {e}")
        # generate the podcast file:
        if with_speech:
            try:
                podcast_output = await self.speech_report(
                    report=final_report,
                    max_lines=self.speech_length,
                    num_speakers=self.num_speakers
                )
                response.podcast_path = str(podcast_output.get('podcast_path', None))
                response.script_path = str(podcast_output.get('script_path', None))
                response.set_podcast_path(podcast_output.get('podcast_path', None))
            except Exception as e:
                self.logger.error(
                    f"Error generating podcast: {e}"
                )
        # Save the final report to the response
        response.output = textwrap.fill(final_report, width=80)
        response.status = "success"
        return response

    async def generate_presentation(
        self,
        content: str,
        filename_prefix: str = 'report',
        template_name: Optional[str] = None,
        pptx_template: str = "corporate_template.pptx",
        output_dir: Optional[Path] = None,
        title: str = None,
        **kwargs
    ):
        """Generate a PowerPoint presentation using the provided tool."""
        if not output_dir:
            output_dir = STATIC_DIR.joinpath(self.agent_id, 'documents')
        tool = PowerPointTool(
            templates_dir=BASE_DIR.joinpath('templates'),
            output_dir=output_dir
        )
        return await tool.execute(
            content=content,
            template_name=None,  # Explicitly disable HTML template
            template_vars=None,  # No template variables
            split_by_headings=True,  # Ensure heading-based splitting is enabled
            pptx_template=pptx_template,
            slide_layout=1,
            title_styles={
                "font_name": "Segoe UI",
                "font_size": 24,
                "bold": True,
                "font_color": "#1f497d"
            },
            content_styles={
                "font_name": "Segoe UI",
                "font_size": 14,
                "alignment": "left",
                "font_color": "#333333"
            },
            max_slides=20,
            file_prefix=filename_prefix,
        )

    async def create_speech(
        self,
        content: str,
        language: str = "en-US",
        only_script: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a Transcript Report and a Podcast based on findings."""
        output_directory = STATIC_DIR.joinpath(self.agent_id, 'documents')
        output_directory.mkdir(parents=True, exist_ok=True)
        script_name = self._create_filename(prefix='script', extension='txt')
        podcast_name = self._create_filename(prefix='podcast', extension='wav')
        try:
            async with self.client as client:
                # 1. Generate the conversational script and podcast:
                return await client.create_speech(
                    content=content,
                    output_directory=output_directory,
                    only_script=only_script,
                    script_file=script_name,
                    podcast_file=podcast_name,
                    language=language,
                )
        except Exception as e:
            self.logger.error(
                f"Error generating speech: {e}"
            )
            raise RuntimeError(
                f"Failed to generate speech: {e}"
            ) from e

    # =================================================================
    # MCP Server Management Methods
    # =================================================================

    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]:
        """
        Add an MCP server and register its tools.

        Args:
            config: MCPServerConfig with connection details

        Returns:
            List of registered tool names

        Example:
            >>> config = MCPServerConfig(
            ...     name="weather_api",
            ...     url="https://api.example.com/mcp",
            ...     auth_type="api_key",
            ...     auth_config={"api_key": "xxx"}
            ... )
            >>> tools = await agent.add_mcp_server(config)
        """
        return await self.mcp_manager.add_mcp_server(config)

    async def add_mcp_server_url(
        self,
        name: str,
        url: str,
        auth_type: Optional[str] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        allowed_tools: Optional[List[str]] = None,
        blocked_tools: Optional[List[str]] = None,
        **kwargs
    ) -> List[str]:
        """
        Convenience method to add a public URL-based MCP server.

        This is a simplified interface for adding HTTP MCP servers
        without manually creating MCPServerConfig objects.

        Args:
            name: Unique name for the MCP server
            url: Base URL of the MCP server
            auth_type: Optional authentication type ('api_key', 'bearer', 'oauth', 'basic')
            auth_config: Authentication configuration dict
            headers: Additional HTTP headers
            allowed_tools: Whitelist of tool names to register
            blocked_tools: Blacklist of tool names to skip
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Examples:
            >>> # Public server with no auth
            >>> tools = await agent.add_mcp_server_url(
            ...     "public_api",
            ...     "https://api.example.com/mcp"
            ... )

            >>> # API key authenticated server
            >>> tools = await agent.add_mcp_server_url(
            ...     "weather",
            ...     "https://weather.example.com/mcp",
            ...     auth_type="api_key",
            ...     auth_config={"api_key": "your-key-here"}
            ... )

            >>> # Server with custom headers and tool filtering
            >>> tools = await agent.add_mcp_server_url(
            ...     "finance",
            ...     "https://finance.example.com/mcp",
            ...     headers={"User-Agent": "AI-Parrot/1.0"},
            ...     allowed_tools=["get_stock_price", "get_market_data"]
            ... )
        """
        config = create_http_mcp_server(
            name=name,
            url=url,
            auth_type=auth_type,
            auth_config=auth_config,
            headers=headers,
            **kwargs
        )

        # Apply tool filtering if specified
        if allowed_tools:
            config.allowed_tools = allowed_tools
        if blocked_tools:
            config.blocked_tools = blocked_tools

        return await self.add_mcp_server(config)

    async def add_local_mcp_server(
        self,
        name: str,
        script_path: Union[str, Path],
        interpreter: str = "python",
        **kwargs
    ) -> List[str]:
        """
        Add a local stdio MCP server.

        Args:
            name: Unique name for the MCP server
            script_path: Path to the MCP server script
            interpreter: Interpreter to use (default: "python")
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Example:
            >>> tools = await agent.add_local_mcp_server(
            ...     "local_tools",
            ...     "/path/to/mcp_server.py"
            ... )
        """
        config = create_local_mcp_server(name, script_path, interpreter, **kwargs)
        return await self.add_mcp_server(config)

    async def add_http_mcp_server(
        self,
        name: str,
        url: str,
        auth_type: Optional[str] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> List[str]:
        """
        Add an HTTP MCP server with optional authentication.

        This is an alias for add_mcp_server_url for backward compatibility.

        Args:
            name: Unique name for the MCP server
            url: Base URL of the MCP server
            auth_type: Optional authentication type
            auth_config: Authentication configuration
            headers: Additional HTTP headers
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names
        """
        config = create_http_mcp_server(
            name, url, auth_type, auth_config, headers, **kwargs
        )
        return await self.add_mcp_server(config)

    async def add_api_key_mcp_server(
        self,
        name: str,
        url: str,
        api_key: str,
        header_name: str = "X-API-Key",
        **kwargs
    ) -> List[str]:
        """
        Add an API-key authenticated MCP server.

        Args:
            name: Unique name for the MCP server
            url: Base URL of the MCP server
            api_key: API key for authentication
            header_name: Header name for the API key (default: "X-API-Key")
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Example:
            >>> tools = await agent.add_api_key_mcp_server(
            ...     "weather_api",
            ...     "https://api.weather.com/mcp",
            ...     api_key="your-api-key",
            ...     header_name="Authorization"
            ... )
        """
        config = create_api_key_mcp_server(
            name=name,
            url=url,
            api_key=api_key,
            header_name=header_name,
            **kwargs
        )
        return await self.add_mcp_server(config)

    async def remove_mcp_server(self, server_name: str):
        """
        Remove an MCP server and unregister its tools.

        Args:
            server_name: Name of the MCP server to remove
        """
        await self.mcp_manager.remove_mcp_server(server_name)
        self.logger.info(f"Removed MCP server: {server_name}")

    def list_mcp_servers(self) -> List[str]:
        """
        List all connected MCP servers.

        Returns:
            List of MCP server names
        """
        return self.mcp_manager.list_mcp_servers()

    def get_mcp_client(self, server_name: str):
        """
        Get the MCP client for a specific server.

        Args:
            server_name: Name of the MCP server

        Returns:
            MCPClient instance or None
        """
        return self.mcp_manager.get_mcp_client(server_name)

    async def shutdown(self, **kwargs):
        """
        Shutdown the agent and disconnect all MCP servers.
        """
        if hasattr(self, 'mcp_manager'):
            await self.mcp_manager.disconnect_all()
            self.logger.info("Disconnected all MCP servers")

        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)

    def as_tool(
        self,
        tool_name: str = None,
        tool_description: str = None,
        use_conversation_method: bool = True,
        context_filter: Optional[Callable[[AgentContext], AgentContext]] = None
    ) -> 'AgentTool':
        """
        Convert this agent into an AgentTool that can be used by other agents.

        This allows agents to be composed and used as tools in orchestration scenarios.

        Args:
            tool_name: Custom name for the tool (defaults to agent name)
            tool_description: Description of what this agent does
            use_conversation_method: Whether to use conversation() or invoke()
            context_filter: Optional function to filter context before execution
            question_description: Custom description for the query parameter
            context_description: Custom description for the context parameter

        Returns:
            AgentTool: Tool wrapper for this agent

        Example:
            >>> hr_agent = BasicAgent(name="HRAgent", ...)
            >>> hr_tool = hr_agent.as_tool(
            ...     tool_description="Handles HR policy questions"
            ... )
            >>> orchestrator.tool_manager.add_tool(hr_tool)
        """
        # Default descriptions based on agent properties
        default_description = (
            f"Specialized agent: {self.name}. "
            f"Role: {self.role}. "
            f"Goal: {self.goal}."
        )

        return AgentTool(
            agent=self,
            tool_name=tool_name,
            tool_description=tool_description or default_description,
            use_conversation_method=use_conversation_method,
            context_filter=context_filter,
        )


    def register_as_tool(
        self,
        target_agent: 'BasicAgent',
        tool_name: str = None,
        tool_description: str = None,
        **kwargs
    ) -> None:
        """
        Register this agent as a tool in another agent's tool manager.

        This is a convenience method that combines as_tool() and registration.

        Args:
            target_agent: The agent to register this tool with
            tool_name: Custom name for the tool
            tool_description: Description of what this agent does
            **kwargs: Additional arguments for as_tool()

        Example:
            >>> hr_agent = BasicAgent(name="HRAgent", ...)
            >>> employee_agent = BasicAgent(name="EmployeeAgent", ...)
            >>> orchestrator = OrchestratorAgent(name="Orchestrator")
            >>>
            >>> hr_agent.register_as_tool(
            ...     orchestrator,
            ...     tool_description="Handles HR policies and procedures"
            ... )
            >>> employee_agent.register_as_tool(
            ...     orchestrator,
            ...     tool_description="Manages employee data"
            ... )
        """
        agent_tool = self.as_tool(
            tool_name=tool_name,
            tool_description=tool_description,
            **kwargs
        )

        # Register in bot's tool manager
        target_agent.tool_manager.add_tool(agent_tool)

        # CRITICAL: Sync tools to LLM after registration
        if hasattr(target_agent, '_sync_tools_to_llm'):
            target_agent._sync_tools_to_llm()

        self.logger.info(
            f"Registered {self.name} as tool '{agent_tool.name}' "
            f"in {target_agent.name}'s tool manager"
        )

    def add_dataframe(self, df, name: str = None):
        """
        Add a dataframe to the agent and configure PythonPandasTool.

        Args:
            df: pandas DataFrame to add
            name: Optional name for the dataframe. If None, uses df{index}
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Input must be a pandas DataFrame")

        # Generate name if not provided
        if name is None:
            name = f"df{len(self.dataframes)}"

        # Store dataframe
        self.dataframes[name] = df

        # Clear cache to regenerate dataframe info
        self._dataframe_info_cache = None

        # Add or update PythonPandasTool
        self._configure_pandas_tool()

        # Update system prompt
        self._update_system_prompt_with_dataframes()

        return self

    def _configure_pandas_tool(self):
        """Add or reconfigure PythonPandasTool with current dataframes."""
        # Check if tool already exists
        pandas_tool = next(
            (tool for tool in self.tools if isinstance(tool, PythonPandasTool)),
            None,
        )

        if pandas_tool is None:
            # Create new PythonPandasTool
            pandas_tool = PythonPandasTool(
                dataframes=self.dataframes
            )
            self.tool_manager.add_tool(pandas_tool)
        else:
            # Update existing tool with new dataframes
            pandas_tool.dataframes = self.dataframes

    def _generate_dataframe_info(self) -> str:
        """Generate dataframe information for system prompt."""
        if not self.dataframes:
            return ""

        if self._dataframe_info_cache is not None:
            return self._dataframe_info_cache

        info_parts = ["# Available DataFrames\n"]

        for name, df in self.dataframes.items():
            info_parts.extend(
                (
                    f"\n## DataFrame: `{name}`",
                    f"- Shape: {df.shape[0]} rows × {df.shape[1]} columns",
                    f"- Columns: {', '.join(df.columns.tolist())}",
                    "- Column Types:",
                )
            )
            info_parts.extend(f"  - {col}: {dtype}" for col, dtype in df.dtypes.items())

            # Add sample statistics for numeric columns
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                info_parts.append("- Summary Statistics (numeric columns):")
                info_parts.extend(
                    f"  - {col}: min={df[col].min():.2f}, max={df[col].max():.2f}, mean={df[col].mean():.2f}"
                    for col in numeric_cols[:5]
                )
            # Add sample rows
            info_parts.append(f"- Sample (first 3 rows):\n{df.head(3).to_string()}")

        info_parts.append("\nUse PythonPandasTool to query and analyze these dataframes.")

        self._dataframe_info_cache = "\n".join(info_parts)
        return self._dataframe_info_cache

    def _update_system_prompt_with_dataframes(self):
        """Inject dataframe information into system prompt."""
        df_info = self._generate_dataframe_info()

        if not df_info:
            return

        # Find the position to inject (before $pre_context or $context)
        if "$pre_context" in self.system_prompt_template:
            marker = "$pre_context"
        elif "$context" in self.system_prompt_template:
            marker = "$context"
        else:
            # Append at the end if no markers found
            self.system_prompt_template += f"\n\n{df_info}"
            return

        # Inject before the marker
        parts = self.system_prompt_template.split(marker, 1)
        self.system_prompt_template = f"{parts[0]}{df_info}\n\n{marker}{parts[1]}"

    def remove_dataframe(self, name: str):
        """Remove a dataframe by name."""
        if name in self.dataframes:
            del self.dataframes[name]
            self._dataframe_info_cache = None
            self._configure_pandas_tool()
            self._update_system_prompt_with_dataframes()

class Agent(BasicAgent):
    """A general-purpose agent with no additional tools."""

    def agent_tools(self) -> List[AbstractTool]:
        """Return the agent-specific tools."""
        return []
