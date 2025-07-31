from typing import List
import aiofiles
from aiohttp import web
from navconfig import BASE_DIR
from navigator_auth.decorators import (
    user_session
)
from .abstract import AbstractAgentHandler
from ...tools.abstract import AbstractTool
from ...bots.agent import BasicAgent
from ...models.responses import AgentResponse


@user_session()
class AgentHandler(AbstractAgentHandler):
    """
    AgentHandler.
    description: Handler for Agents in Parrot Application.

    This handler is used to manage the agents in the Parrot application.
    It provides methods to create, update, and interact with agents.
    """
    _tools: List[AbstractTool] = []
    _agent: BasicAgent = None
    agent_name: str = "NextStop"
    agent_id: str = "nextstop"

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)

    async def _build_agent(self) -> None:
        """Build the agent."""
        tools = self._tools or []
        self.app[self.agent_id] = self.get_agent()
        print(
            f"Agent {self._agent}:{self.agent_name} initialized with tools: {', '.join(tool.name for tool in tools)}"
        )

    async def on_startup(self, app: web.Application) -> None:
        """Start the application."""
        self._agent = await self._build_agent()

    async def on_shutdown(self, app: web.Application) -> None:
        """Stop the application."""
        self._agent = None

    async def open_prompt(self, prompt_file: str = None) -> str:
        """
        Opens a prompt file and returns its content.
        """
        if not prompt_file:
            raise ValueError("No prompt file specified.")
        file = BASE_DIR.joinpath('prompts', self.agent_id, prompt_file)
        try:
            async with aiofiles.open(file, 'r') as f:
                content = await f.read()
            return content
        except Exception as e:
            raise RuntimeError(f"Failed to read prompt file {prompt_file}: {e}")

    async def ask_agent(self, query: str = None, prompt_file: str = None, *args, **kwargs) -> AgentResponse:
        """
        Asks the agent a question and returns the response.
        """
        agent = self._agent or self.request.app[self.agent_id]
        userid = self._userid if self._userid else self.request.session.get('user_id', None)
        if not userid:
            raise RuntimeError(
                "User ID is not set in the session."
            )
        if not agent:
            raise RuntimeError(
                f"Agent {self.agent_name} is not initialized or not found."
            )
        if not query:
            # extract the query from the prompt file if provided:
            if prompt_file:
                query = await self.open_prompt(prompt_file)
            elif hasattr(self.request, 'query') and 'query' in self.request.query:
                query = self.request.query.get('query', None)
            elif hasattr(self.request, 'json'):
                data = await self.request.json()
                query = data.get('query', None)
            elif hasattr(self.request, 'data'):
                data = await self.request.data()
                query = data.get('query', None)
            elif hasattr(self.request, 'text'):
                query = self.request.text
            else:
                raise ValueError(
                    "No query provided and no prompt file specified."
                )
            if not query:
                raise ValueError(
                    "No query provided or found in the request."
                )
        try:
            response = await agent.invoke(query)
            if isinstance(response, Exception):
                raise response
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )

        # Create the response object
        final_report = response.output.strip()
        # parse the intermediate steps if available to extract PDF and podcast paths:
        pdf_path = None
        podcast_path = None
        transcript = None
        document_path = None
        if response.intermediate_steps:
            for step in response.intermediate_steps:
                tool = step['tool']
                result = step['result']
                tool_input = step.get('tool_input', {})
                if 'text' in tool_input:
                    transcript = tool_input['text']
                if isinstance(result, dict):
                    # Extract the URL from the result if available
                    url = result.get('url', None)
                    if tool == 'PDFPrintTool':
                        pdf_path = url
                    elif tool == 'GoogleVoiceTool':
                        podcast_path = url
                    else:
                        document_path = url
        response_data = self._model_response(
            user_id=str(userid),
            agent_name=self.agent_name,
            attributes=kwargs.pop('attributes', {}),
            data=final_report,
            status="success",
            created_at=datetime.now(),
            output=result.get('output', ''),
            transcript=transcript,
            pdf_path=str(pdf_path),
            podcast_path=str(podcast_path),
            document_path=str(document_path),
            documents=response.documents if hasattr(response, 'documents') else [],
            **kwargs
        )
        return response_data, response, result
