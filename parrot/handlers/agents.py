from typing import Dict, List
from abc import abstractmethod
from datetime import datetime
import aiofiles
from aiohttp import web
import pandas as pd
from langchain_core.tools import BaseTool
from datamodel import BaseModel, Field
from navconfig import BASE_DIR
from navigator_auth.decorators import (
    is_authenticated,
    user_session
)
from navigator.views import BaseView
from querysource.queries.qs import QS
from querysource.queries.multi import MultiQS
from ..bots.abstract import AbstractBot
from ..llms.vertex import VertexLLM
from ..bots.data import PandasAgent
from ..models import AgentModel
from .abstract import AbstractAgentHandler


@is_authenticated()
@user_session()
class AgentManager(BaseView):
    """
    AgentManager.
    description: Agent Handler for Parrot Application.

    TODO: Support for per-user session agents.
    - Tool for doing an EDA (exploratory data-analysis) on a dataframe.
    - Tool for doing a data profiling on a dataframe.
    """
    async def put(self, *args, **kwargs):
        """
        put.
        description: Put method for AgentManager

        Use this method to create a new Agent.
        """
        app = self.request.app
        _id = self.request.match_info.get('agent_name', None)
        data = await self.request.json()
        name = data.pop('name', None)
        if not name:
            return self.json_response(
                {
                "message": "Agent name not found."
                },
                status=404
            )
        _id = data.pop('chatbot_id', None)
        # To create a new agent, we need:
        # A list of queries (Query slugs) to be converted into dataframes
        query = data.pop('query', None)
        if not query:
            return self.json_response(
                {
                "message": "No query was found."
                },
                status=400
            )
        # A list of tools to be used by the agent
        tools = kwargs.pop('tools', [])
        # a backstory and an optional capabilities for Bot.
        backstory = data.pop('backstory', None)
        capabilities = data.pop('capabilities', None)
        try:
            manager = app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        if agent := manager.get_agent(_id):
            args = {
                "message": f"Agent {name} already exists.",
                "agent": agent.name,
                "agent_id": agent.chatbot_id,
                "description": agent.description,
                "backstory": agent.backstory,
                "capabilities": agent.get_capabilities(),
                "type": 'PandasAgent',
                "llm": f"{agent.llm!r}",
                "temperature": agent.llm.temperature,
            }
            return self.json_response(
                args,
                status=208
            )
        try:
            # Generate the Data Frames from the queries:
            dfs = await PandasAgent.gen_data(
                query=query.copy(),
                agent_name=_id,
                refresh=True,
                no_cache=True
            )
        except Exception as e:
            return self.json_response(
                {
                "message": f"Error generating dataframes: {e}"
                },
                status=400
            )
        try:
            args = {
                "name": name,
                "df": dfs,
                "query": query,
                "tools": tools,
                "backstory": backstory,
                "capabilities": capabilities,
                **data
            }
            if _id:
                args['chatbot_id'] = _id
            # Create and Add the agent to the manager
            agent = await manager.create_agent(
                class_name=PandasAgent,
                **args
            )
            await agent.configure(app=app)
        except Exception as e:
            return self.json_response(
                {
                "message": f"Error on Agent creation: {e}"
                },
                status=400
            )
        # Check if the agent was created successfully
        if not agent:
            return self.json_response(
                {
                "message": f"Error creating agent: {e}"
                },
                status=400
            )
        # Saving Agent into DB:
        try:
            args.pop('df')
            args['query'] = query
            result = await manager.save_agent(**args)
            if not result:
                manager.remove_agent(agent)
                return self.json_response(
                    {
                    "message": f"Error saving agent {agent.name}"
                    },
                    status=400
                )
        except Exception as e:
            manager.remove_agent(agent)
            return self.json_response(
                {
                "message": f"Error saving agent {agent.name}: {e}"
                },
                status=400
            )
        # Return the agent information
        return self.json_response(
            {
                "message": f"Agent {name} created successfully.",
                "agent": agent.name,
                "agent_id": agent.chatbot_id,
                "description": agent.description,
                "backstory": agent.backstory,
                "capabilities": agent.get_capabilities(),
                "type": 'PandasAgent',
                "llm": f"{agent.llm!r}",
                "temperature": agent.llm.temperature,
            },
            status=201
        )

    async def post(self, *args, **kwargs):
        """
        post.
        description: Do a query to the Agent.
        Use this method to interact with a Agent.
        """
        app = self.request.app
        try:
            manager = app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        name = self.request.match_info.get('agent_name', None)
        if not name:
            return self.json_response(
                {
                "message": "Agent name not found."
                },
                status=404
            )
        data = await self.request.json()
        if not 'query' in data:
            return self.json_response(
                {
                "message": "No query was found."
                },
                status=400
            )
        if agent := manager.get_agent(name):
            # doing a question to the agent:
            try:
                response, result = await agent.invoke(
                    data['query']
                )
                result.response = response
                # null the chat_history:
                result.chat_history = []
                return self.json_response(response=result)
            except Exception as e:
                return self.json_response(
                    {
                    "message": f"Error invoking agent: {e}"
                    },
                    status=400
                )
        else:
            return self.json_response(
                {
                "message": f"Agent {name} not found."
                },
                status=404
            )

    async def patch(self, *args, **kwargs):
        """
        patch.
        description: Update the data of the Agent.
        Use this method to update the dataframes assigned to the Agent.
        """
        app = self.request.app
        try:
            manager = app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        name = self.request.match_info.get('agent_name', None)
        if not name:
            return self.json_response(
                {
                "message": "Agent name not found."
                },
                status=404
            )
        try:
            data = await self.request.json()
        except Exception as e:
            data = {}
        query = data.pop('query', None)
        if agent := manager.get_agent(name):
            # dextract the new query from the request, or from agent
            qry = query if query else agent.get_query()
            try:
                # Generate the Data Frames from the queries:
                dfs = await PandasAgent.gen_data(
                    agent_name=str(agent.chatbot_id),
                    query=qry,
                    refresh=True
                )
                if dfs:
                    # Update the agent with the new dataframes
                    agent.df = dfs
                    # Update the agent with the new query
                    await agent.configure(df=dfs)
                return self.json_response(
                    {
                    "message": f"{agent.name}: Agent Data was Updated."
                    },
                    status=202
                )
            except Exception as e:
                return self.json_response(
                    {
                    "message": f"Error refreshing agent {agent.name}: {e}"
                    },
                    status=400
                )
        else:
            return self.json_response(
                {
                "message": f"Agent {name} not found."
                },
                status=404
            )


class AgentAnswer(BaseModel):
    """
    AgentAnswer is a model that defines the structure of the response
    for Any Parrot agent.
    """
    # session_id: str = Field(..., description="Unique identifier for the session")
    user_id: str = Field(..., description="Unique identifier for the user")
    agent_name: str = Field(required=False, description="Name of the agent that processed the request")
    data: str = Field(..., description="Data returned by the agent")
    status: str = Field(default="success", description="Status of the response")
    output: str = Field(required=False)
    transcript: str = Field(default=None, description="Transcript of the conversation with the agent")
    attributes: Dict[str, str] = Field(default_factory=dict, description="Attributes associated with the response")
    created_at: datetime = Field(default=datetime.now)
    podcast_path: str = Field(required=False, description="Path to the podcast associated with the session")
    pdf_path: str = Field(required=False, description="Path to the PDF associated with the session")
    document_path: str = Field(required=False, description="Path to document generated during session")
    documents: List[str] = Field(default_factory=list, description="List of documents associated with the session")


@user_session()
class AgentHandler(AbstractAgentHandler):
    """
    AgentHandler.
    description: Handler for Agents in Parrot Application.

    This handler is used to manage the agents in the Parrot application.
    It provides methods to create, update, and interact with agents.
    """
    _backstory: str = """This agent is designed to assist users in finding store information, such as store hours, locations, and services.
It can also provide weather updates and perform basic Python code execution.
The agent can answer questions about store locations, hours of operation, and available services.
It can also provide weather updates for the store's location, helping users plan their visits accordingly.
The agent can execute Python code snippets to perform calculations or data processing tasks.
    """
    _tools: List[BaseTool] = []
    _agent: AbstractBot = None
    agent_name: str = "NextStopAgent"
    agent_id: str = "nextstop_agent"
    _model_response: BaseModel = AgentAnswer

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)

    async def _build_agent(self) -> None:
        """Build the agent."""
        tools = self._tools or []
        vertex = VertexLLM(
            model="gemini-2.5-pro",
            temperature=0.1,
            max_tokens=4096,
            top_p=0.95,
            top_k=40,
            verbose=True,
            use_chat=True
        )
        self.app[self.agent_id] = await self.create_agent(
            # llm=vertex,
            tools=tools,
            backstory=self._backstory,
        )
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

    async def ask_agent(self, query: str = None, prompt_file: str = None, *args, **kwargs) -> AgentAnswer:
        """
        Asks the agent a question and returns the response.
        """
        agent = self._agent or self.request.app[self.agent_id]
        userid = self._userid if self._userid else self.request.session.get('user_id', None)
        if not userid:
            raise RuntimeError("User ID is not set in the session.")
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
            data, response, result = await agent.invoke(query)
            if isinstance(result, Exception):
                raise result
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
                    if tool == 'pdf_print_tool':
                        pdf_path = url
                    elif tool == 'podcast_generator_tool':
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
