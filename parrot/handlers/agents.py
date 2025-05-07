from typing import List
from aiohttp import web
import pandas as pd
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


@is_authenticated()
@user_session()
class AgentHandler(BaseView):
    """
    AgentHandler.
    description: Agent Handler for Parrot Application.

    TODO: Support for per-user session agents.
    - Tool for doing an EDA (exploratory data-analysis) on a dataframe.
    - Tool for doing a data profiling on a dataframe.
    """
    async def put(self, *args, **kwargs):
        """
        put.
        description: Put method for AgentHandler

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
