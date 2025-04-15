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
from ..bots.pd import PandasAgent


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
    async def call_qs(self, queries: list) -> List[pd.DataFrame]:
        """
        call_qs.
        description: Call the QuerySource queries.
        """
        dfs = []
        for query in queries:
            if not isinstance(query, str):
                return self.json_response(
                    {
                    "message": f"Query {query} is not a string."
                    },
                    status=400
                )
            # now, the only query accepted is a slug:
            qy = QS(
                slug=query
            )
            df, error = await qy.query(output_format='pandas')
            if error:
                return self.json_response(
                    {
                    "message": f"Query {query} fail with error {error}."
                    },
                    status=404
                )
            if not isinstance(df, pd.DataFrame):
                return self.json_response(
                    {
                    "message": f"Query {query} is not returning a dataframe."
                    },
                    status=404
                )
            dfs.append(df)
        return dfs

    async def call_multiquery(self, query: dict) -> List[pd.DataFrame]:
        """
        call_multiquery.
        description: Call the MultiQuery queries.
        """
        data = {}
        _queries = query.pop('queries', {})
        _files = query.pop('files', {})
        if not _queries or not _files:
            raise ValueError(
                "Queries or files are required."
            )
        try:
            ## Step 1: Running all Queries and Files on QueryObject
            qs = MultiQS(
                slug=[],
                queries=_queries,
                files=_files,
                query=query,
                conditions=data,
                return_all=True
            )
            result, _ = await qs.execute()
        except Exception as e:
            raise ValueError(
                f"Error executing MultiQuery: {e}"
            )
        if not isinstance(result, dict):
            raise ValueError(
                "MultiQuery is not returning a dictionary."
            )
        return list(result.values())


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
        # A list of dataframes to be used as context for the agent
        if isinstance(query, dict):
            # is a MultiQuery execution, use the MultiQS class engine to do it:
            try:
                dfs = await self.call_multiquery(query)
            except ValueError as e:
                return self.json_response(
                    {
                    "message": f"Error creating agent: {e}"
                    },
                    status=400
                )
        if isinstance(query, str):
            query = [query]
        if isinstance(query, list):
            dfs = await self.call_qs(query)
        else:
            return self.json_response(
                {
                "message": "Incompatible Query in the request."
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
            return self.json_response(
                {
                "message": f"Agent {name} already exists."
                },
                status=400
            )
        try:
            args = {
                "name": name,
                "df": dfs,
                "tools": tools,
                "backstory": backstory,
                "capabilities": capabilities,
                **data
            }
            if _id:
                args['chatbot_id'] = _id
            agent = PandasAgent(
                **args
            )
            await agent.configure()
        except Exception as e:
            return self.json_response(
                {
                "message": f"Error creating agent: {e}"
                },
                status=400
            )
        # Add the agent to the manager
        manager.add_agent(agent)
        # Return the agent
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
                return self.json_response(response=result)
            except Exception as e:
                return self.json_response(
                    {
                    "message": f"Error invoking agent: {e}"
                    },
                    status=400
                )
