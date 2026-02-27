"""
REST API Handler for AgentCrew Management.

Provides endpoints for creating, managing, and deleting agent crews.

Endpoints:
    PUT /api/v1/crew - Create a new crew
    GET /api/v1/crew - List all crews or get specific crew by name
    DELETE /api/v1/crew - Delete a crew
"""
import json
from aiohttp import web
from navigator.views import BaseView
from navigator.types import WebApp  # pylint: disable=E0611,E0401
from navigator.applications.base import BaseApplication  # pylint: disable=E0611,E0401
from navconfig.logging import logging
from .models import CrewDefinition, ExecutionMode
from parrot.bots.orchestration.crew import AgentCrew


class CrewHandler(BaseView):
    """
    REST API Handler for AgentCrew CRUD operations.

    This handler manages the lifecycle of crew definitions (Create, Read, Update, Delete).
    Execution and runtime management are handled by CrewExecutionHandler.
    """

    path: str = '/api/v1/crew'
    app: WebApp = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewHandler')
        # Get bot manager from app if available
        self._bot_manager = None
        # Job Manager moved to CrewExecutionHandler

    @property
    def bot_manager(self):
        """Get bot manager."""
        if not self._bot_manager:
            app = self.request.app
            self._bot_manager = app['bot_manager'] if 'bot_manager' in app else None
        return self._bot_manager

    @bot_manager.setter
    def bot_manager(self, value):
        """Set bot manager."""
        self._bot_manager = value

    @classmethod
    def configure(cls, app: WebApp = None, path: str = None, **kwargs) -> WebApp:
        """configure.
        Configure the CrewHandler in an aiohttp Web Application.
        args:
            app (WebApp): aiohttp Web Application instance.
            path (str, optional): route path for Model.
            **kwargs: Additional keyword arguments.
        """
        if isinstance(app, BaseApplication):
            cls.app = app.get_app()
        elif isinstance(app, WebApp):
            cls.app = app  # register the app into the Extension
        # startup operations over extension backend
        if app:
            url = f"{path}"
            app.router.add_view(
                r"{url}/{{id:.*}}".format(url=url), cls
            )
            app.router.add_view(
                r"{url}{{meta:(:.*)?}}".format(url=url), cls
            )
            # Job Manager config moved to CrewExecutionHandler
    
    async def _create_crew_from_definition(
        self,
        crew_def: CrewDefinition
    ) -> AgentCrew:
        """
        Create an AgentCrew instance from a CrewDefinition.

        Args:
            crew_def: Crew definition containing agent definitions with their configs.
                      For WebSearchAgent, config may include:
                      - contrastive_search (bool): Enable two-step contrastive analysis
                      - contrastive_prompt (str): Custom prompt for contrastive step
                      - synthesize (bool): Enable LLM synthesis of results
                      - synthesize_prompt (str): Custom prompt for synthesis step

        Returns:
            AgentCrew instance with all agents configured
        """
        # Create agents
        agents = []
        for agent_def in crew_def.agents:
            # Get agent class from BotManager registry
            agent_class = self.bot_manager.get_bot_class(agent_def.agent_class)

            tools = []
            if agent_def.tools:
                tools.extend(iter(agent_def.tools))

            # Debug logging for WebSearchAgent to trace config passthrough
            if agent_def.agent_class == "WebSearchAgent":
                self.logger.debug(
                    f"Creating WebSearchAgent '{agent_def.name or agent_def.agent_id}' "
                    f"with config: contrastive_search={agent_def.config.get('contrastive_search', False)}, "
                    f"synthesize={agent_def.config.get('synthesize', False)}, "
                    f"temperature={agent_def.config.get('temperature', 'default')}"
                )

            # Create agent instance — config dict is unpacked as kwargs
            # This allows WebSearchAgent to receive contrastive_search, synthesize, etc.
            agent = agent_class(
                name=agent_def.name or agent_def.agent_id,
                tools=tools,
                **agent_def.config
            )

            # Set system prompt if provided
            if agent_def.system_prompt:
                agent.system_prompt = agent_def.system_prompt

            agents.append(agent)

        # Create crew
        crew = AgentCrew(
            name=crew_def.name,
            agents=agents,
            max_parallel_tasks=crew_def.max_parallel_tasks
        )

        # Add shared tools
        for tool_name in crew_def.shared_tools:
            if tool := self.bot_manager.get_tool(tool_name):
                crew.add_shared_tool(tool, tool_name)

        # Setup flow relations if in flow mode
        if crew_def.execution_mode == ExecutionMode.FLOW and crew_def.flow_relations:
            for relation in crew_def.flow_relations:
                # Convert agent IDs to agent objects
                source_agents = self._get_agents_by_ids(
                    crew,
                    relation.source if isinstance(relation.source, list) else [relation.source]
                )
                target_agents = self._get_agents_by_ids(
                    crew,
                    relation.target if isinstance(relation.target, list) else [relation.target]
                )

                # Setup flow
                crew.task_flow(
                    source_agents if len(source_agents) > 1 else source_agents[0],
                    target_agents if len(target_agents) > 1 else target_agents[0]
                )

        return crew

    def _get_agents_by_ids(self, crew: AgentCrew, agent_ids: list) -> list:
        """Helper to get agent instances by their IDs/names."""
        # This helper might also be missing, implementing a simple version based on context
        # Assumes agent name matches what was set during creation (name or agent_id)
        # But wait, User snippet used self._get_agents_by_ids so I should check if that exists or add it.
        # Since I am adding it here, I should implement it.
        found = []
        for aid in agent_ids:
            # Logic to find agent in crew.agents list
            # The agent.name was set to agent_def.name or agent_def.agent_id
            # This might be tricky if names are not unique or if we don't know the exact mapping.
            # Ideally AgentCrew has a method to get agent by valid identifier?
            # For now, let's iterate.
            for agent in crew.agents:
                if agent.name == aid: # weak match?
                    found.append(agent)
                    break
        return found

    async def upload(self):
        """
        Upload a crew definition from a JSON file.

        This endpoint accepts multipart/form-data with a JSON file containing
        the crew definition from the visual builder.

        Form data:
            - file: JSON file with crew definition

        Returns:
            201: Crew created successfully from file
            400: Invalid file or format
            500: Server error
        """
        try:
            # Get multipart reader
            reader = await self.request.multipart()

            # Read file field
            field = await reader.next()

            if not field or field.name != 'file':
                return self.error(
                    response={"message": "No file provided. Expected 'file' field."},
                    status=400
                )

            # Read file content
            content = await field.read(decode=True)
            try:
                crew_data = json.loads(content)
            except json.JSONDecodeError as e:
                return self.error(
                    response={"message": f"Invalid JSON format: {str(e)}"},
                    status=400
                )

            # Validate bot manager availability
            if not self.bot_manager:
                return self.error(
                    response={"message": "BotManager not available"},
                    status=500
                )

            # Parse into CrewDefinition
            try:
                crew_def = CrewDefinition(**crew_data)
            except Exception as e:
                return self.error(
                    response={"message": f"Invalid crew definition: {str(e)}"},
                    status=400
                )

            # Create the crew
            try:
                crew = await self._create_crew_from_definition(crew_def)

                # Register crew in bot manager
                await self.bot_manager.add_crew(crew_def.name, crew, crew_def)

                self.logger.info(
                    f"Uploaded and created crew '{crew_def.name}' with {len(crew_def.agents)} agents"
                )

                return self.json_response(
                    {
                        "message": "Crew uploaded and created successfully",
                        "crew_id": crew_def.crew_id,
                        "tenant": crew_def.tenant,
                        "name": crew_def.name,
                        "execution_mode": crew_def.execution_mode.value,  # pylint: disable=E1101  #noqa
                        "agents": [agent.agent_id for agent in crew_def.agents],
                        "created_at": crew_def.created_at.isoformat()
                    },
                    status=201
                )

            except Exception as e:
                self.logger.error(f"Error creating crew from upload: {e}", exc_info=True)
                return self.error(
                    response={"message": f"Error creating crew: {str(e)}"},
                    status=400
                )

        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error processing upload: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error processing upload: {str(e)}"},
                status=500
            )

    async def put(self):
        """
        Create a new AgentCrew or update an existing one.

        URL parameters:
            - id: Crew ID or name (optional, for updates)
                e.g., /api/v1/crew/my-crew-id

        Request body should contain CrewDefinition:
        {
            "name": "research_crew",
            "execution_mode": "sequential|parallel|flow",
            "agents": [...],
            ...
        }

        Returns:
            201: Crew created successfully
            200: Crew updated successfully
            400: Invalid request
            404: Crew not found (for updates)
            500: Server error
        """
        try:
            # Get crew ID from URL if provided
            match_params = self.match_parameters(self.request)
            url_crew_id = match_params.get('id')

            # Parse request body
            data = await self.request.json()
            crew_def = CrewDefinition(**data)
            tenant = crew_def.tenant

            # Validate bot manager availability
            if not self.bot_manager:
                return self.error(
                    response={
                        "message": "BotManager not available"
                    },
                    status=500
                )
            # if crew_id is provided, then is an update
            if url_crew_id:
                existing_crew = await self.bot_manager.get_crew(url_crew_id, tenant=tenant)
                if not existing_crew:
                    return self.error(
                        response={
                            "message": f"Crew '{url_crew_id}' not found for update"
                        },
                        status=404
                    )
                # Update existing crew definition
                _, existing_def = existing_crew
                crew_def.crew_id = existing_def.crew_id  # Preserve original ID
                crew_def.created_at = existing_def.created_at  # Preserve creation time
                crew_def.updated_at = None  # Will be set on save

                # Remove old crew
                await self.bot_manager.remove_crew(url_crew_id, tenant=tenant)

                self.logger.info(f"Updating crew '{url_crew_id}'")

            # Create the crew via bot manager
            try:
                crew = await self._create_crew_from_definition(crew_def)

                crew_key = url_crew_id or crew_def.name

                # Register crew in bot manager
                await self.bot_manager.add_crew(crew_key, crew, crew_def)

                action = "updated" if url_crew_id else "created"
                status_code = 202 if url_crew_id else 201

                self.logger.info(
                    f"{action.capitalize()} crew '{crew_def.name}' with {len(crew_def.agents)} agents"
                )

                return self.json_response(
                    {
                        "message": f"Crew {action} successfully",
                        "crew_id": crew_def.crew_id,
                        "tenant": crew_def.tenant,
                        "name": crew_def.name,
                        "execution_mode": crew_def.execution_mode.value,  # pylint: disable=E1101
                        "agents": [agent.agent_id for agent in crew_def.agents],
                        "created_at": crew_def.created_at.isoformat()  # pylint: disable=E1101
                    },
                    status=status_code
                )

            except Exception as e:
                self.logger.error(f"Error creating crew: {e}", exc_info=True)
                return self.error(
                    response={
                        "message": f"Error creating crew: {str(e)}"
                    },
                    status=400
                )
        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error parsing request: {e}", exc_info=True)
            return self.error(
                response={
                    "message": f"Invalid request: {str(e)}"
                },
                status=400
            )

    async def get(self):
        """
        Get crew information.

        Query parameters:
            - name: Crew name (optional) - returns specific crew if provided
            - crew_id: Crew ID (optional) - returns specific crew if provided

        Returns:
            200: Crew definition(s)
            404: Crew not found
            500: Server error
        """
        try:
            qs = self.get_arguments(self.request)
            match_params = self.match_parameters(self.request)
            crew_id = match_params.get('id') or qs.get('crew_id')
            crew_name = qs.get('name')
            tenant = qs.get('tenant') or "global"

            if not self.bot_manager:
                return self.error(
                    response={"message": "BotManager not available"},
                    status=400
                )

            # Get specific crew
            if crew_name or crew_id:
                identifier = crew_name or crew_id
                crew_data = await self.bot_manager.get_crew(identifier, tenant=tenant)

                if not crew_data:
                    return self.error(
                        response={
                            "message": f"Crew '{identifier}' not found"
                        },
                        status=404
                    )

                crew, crew_def = crew_data
                return self.json_response({
                    "crew_id": crew_def.crew_id,
                    "tenant": crew_def.tenant,
                    "name": crew_def.name,
                    "description": crew_def.description,
                    "execution_mode": crew_def.execution_mode.value,
                    "agents": [agent.dict() for agent in crew_def.agents],
                    "flow_relations": [
                        rel.dict() for rel in crew_def.flow_relations
                    ],
                    "shared_tools": crew_def.shared_tools,
                    "max_parallel_tasks": crew_def.max_parallel_tasks,
                    "created_at": crew_def.created_at.isoformat(),
                    "updated_at": crew_def.updated_at.isoformat(),
                    "metadata": crew_def.metadata
                })

            # Sync crews from Redis first
            await self.bot_manager.sync_crews()
            
            # List all crews
            crews = self.bot_manager.list_crews(tenant=tenant)
            crew_list = []

            crew_list.extend(
                {
                    "crew_id": crew_def.crew_id,
                    "tenant": crew_def.tenant,
                    "name": crew_def.name,
                    "description": crew_def.description,
                    "execution_mode": crew_def.execution_mode.value,
                    "agent_count": len(crew_def.agents),
                    "created_at": crew_def.created_at.isoformat(),
                }
                for name, (crew, crew_def) in crews.items()
            )

            return self.json_response({
                "crews": crew_list,
                "total": len(crew_list)
            })
        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting crew: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error: {str(e)}"},
                status=500
            )

    async def delete(self):
        """
        Delete a crew.

        Query parameters:
            - name: Crew name (optional)
            - crew_id: Crew ID (optional)

        Returns:
            200: Crew deleted successfully
            404: Crew not found
            500: Server error
        """
        try:
            match_params = self.match_parameters(self.request)
            qs = self.get_arguments(self.request)
            crew_id = match_params.get('id') or qs.get('crew_id')
            crew_name = qs.get('name')
            tenant = qs.get('tenant') or "global"

            if not crew_name and not crew_id:
                return self.error(
                    response={"message": "name or crew_id is required"},
                    status=400
                )

            if not self.bot_manager:
                return self.error(
                    response={"message": "BotManager not available"},
                    status=500
                )

            identifier = crew_name or crew_id
            
            # Check if exists first
            crew_data = await self.bot_manager.get_crew(identifier, tenant=tenant)
            if not crew_data:
                return self.error(
                    response={"message": f"Crew '{identifier}' not found"},
                    status=404
                )

            # Remove crew
            await self.bot_manager.remove_crew(identifier, tenant=tenant)

            return self.json_response({
                "message": f"Crew '{identifier}' deleted successfully"
            })

        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting crew: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error: {str(e)}"},
                status=500
            )
