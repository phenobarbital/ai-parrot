"""
REST API Handler for AgentCrew Management.

Provides endpoints for creating, managing, and executing agent crews.

Endpoints:
    PUT /api/v1/crew - Create a new crew
    GET /api/v1/crew - List all crews or get specific crew by name
    POST /api/v1/crew/execute - Execute a crew asynchronously
    PATCH /api/v1/crew/job - Get job status and results
    DELETE /api/v1/crew - Delete a crew
"""
from typing import Any, List, Optional
import uuid
import json
from aiohttp import web
from navigator.views import BaseView
from navigator.types import WebApp  # pylint: disable=E0611,E0401
from navigator.applications.base import BaseApplication  # pylint: disable=E0611,E0401
from navconfig.logging import logging
from parrot.bots.orchestration.crew import AgentCrew
from .models import (
    CrewDefinition,
    JobStatus,
    ExecutionMode,
)
from ..jobs import JobManager


class CrewHandler(BaseView):
    """
    REST API Handler for AgentCrew operations.

    This handler provides a complete REST API for managing and executing
    agent crews with support for sequential, parallel, and flow-based
    execution modes.
    """

    path: str = '/api/v1/crew'
    app: WebApp = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewHandler')
        # Get bot manager from app if available
        self._bot_manager = None
        self.job_manager: JobManager = self.app['job_manager'] if 'job_manager' in self.app else JobManager()

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

    @staticmethod
    async def configure_job_manager(app: WebApp):
        """Configure and start job manager."""
        app['job_manager'] = JobManager()
        await app['job_manager'].start()

    @classmethod
    def configure(cls, app: WebApp = None, path: str = None, **kwargs) -> WebApp:
        """configure.
        Configure the CrewHandler in an aiohttp Web Application.
        Args:
            app (WebApp): aiohttp Web Application instance.
            path (str, optional): route path for Model.

        Raises:
            TypeError: Invalid aiohttp Application.
            ConfigError: Wrong configuration parameters.
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
            app.on_startup.append(cls.configure_job_manager)

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
                self.bot_manager.add_crew(crew_def.name, crew, crew_def)

                self.logger.info(
                    f"Uploaded and created crew '{crew_def.name}' with {len(crew_def.agents)} agents"
                )

                return self.json_response(
                    {
                        "message": "Crew uploaded and created successfully",
                        "crew_id": crew_def.crew_id,
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
            "agents": [
                {
                    "agent_id": "researcher",
                    "agent_class": "BaseAgent",
                    "name": "Research Agent",
                    "config": {"model": "gpt-4", "temperature": 0.7},
                    "tools": ["web_search"],
                    "system_prompt": "You are a researcher..."
                }
            ],
            "flow_relations": [  // Only for flow mode
                {"source": "agent1", "target": ["agent2", "agent3"]},
                {"source": ["agent2", "agent3"], "target": "agent4"}
            ],
            "shared_tools": ["calculator"],
            "max_parallel_tasks": 10
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
                existing_crew = self.bot_manager.get_crew(url_crew_id)
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
                self.bot_manager.remove_crew(url_crew_id)

                self.logger.info(f"Updating crew '{url_crew_id}'")

            # Create the crew via bot manager
            try:
                crew = await self._create_crew_from_definition(crew_def)

                crew_key = url_crew_id or crew_def.name

                # Register crew in bot manager
                self.bot_manager.add_crew(crew_key, crew, crew_def)

                action = "updated" if url_crew_id else "created"
                status_code = 202 if url_crew_id else 201

                self.logger.info(
                    f"{action.capitalize()} crew '{crew_def.name}' with {len(crew_def.agents)} agents"
                )

                return self.json_response(
                    {
                        "message": f"Crew {action} successfully",
                        "crew_id": crew_def.crew_id,
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

            if not self.bot_manager:
                return self.error(
                    response={"message": "BotManager not available"},
                    status=400
                )

            # Get specific crew
            if crew_name or crew_id:
                identifier = crew_name or crew_id
                crew_data = self.bot_manager.get_crew(identifier)

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

            # List all crews
            crews = self.bot_manager.list_crews()
            crew_list = []

            crew_list.extend(
                {
                    "crew_id": crew_def.crew_id,
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

    async def post(self):
        """
        Execute a crew asynchronously.

        Request body:
        {
            "crew_id": "uuid" or "name": "crew_name",
            "query": "What is the status of AI research?" or {"agent1": "task1", "agent2": "task2"},
            "execution_mode": "sequential|parallel|loop|flow",
            "user_id": "optional_user_id",
            "session_id": "optional_session_id",
            "synthesis_prompt": "optional synthesis prompt for research mode",
            "kwargs": {}  // Additional execution arguments
        }

        Returns:
            202: Job created and queued
            400: Invalid request
            404: Crew not found
            500: Server error
        """
        try:
            # Parse request
            data = await self.request.json()

            # Get crew identifier
            crew_id = data.get('crew_id') or data.get('name')
            if not crew_id:
                return self.error(
                    response={"message": "crew_id or name is required"},
                    status=400
                )

            query = data.get('query')
            if not query:
                return self.error(
                    response={"message": "query is required"},
                    status=400
                )

            # Get crew
            if not self.bot_manager:
                return self.error(
                    response={"message": "BotManager not available"},
                    status=500
                )

            crew_data = self.bot_manager.get_crew(crew_id)
            if not crew_data:
                return self.error(
                    response={"message": f"Crew '{crew_id}' not found"},
                    status=404
                )

            crew, crew_def = crew_data
            requested_mode = data.get('execution_mode')
            override_mode: Optional[ExecutionMode] = None
            if requested_mode:
                try:
                    override_mode = ExecutionMode(requested_mode)
                except ValueError:
                    return self.error(
                        response={"message": f"Invalid execution mode: {requested_mode}"},
                        status=400
                    )

            selected_mode = override_mode or crew_def.execution_mode
            # Create a job for async execution
            job_id = str(uuid.uuid4())

            # Create job
            job = self.job_manager.create_job(
                job_id=job_id,
                obj_id=crew_def.crew_id,
                query=query,
                user_id=data.get('user_id'),
                session_id=data.get('session_id'),
                execution_mode=selected_mode.value
            )

            # Execute asynchronously
            execution_kwargs = data.get('kwargs', {})
            synthesis_prompt = data.get('synthesis_prompt', None)

            execution_kwargs.update({
                'user_id': job.user_id,
                'session_id': job.session_id,
                "max_tokens": execution_kwargs.get("max_tokens", 4096),
                "temperature": execution_kwargs.get("temperature", 0.1)
            })
            if synthesis_prompt:
                execution_kwargs['synthesis_prompt'] = synthesis_prompt

            async def execute_crew():
                """Async execution function."""
                try:
                    # Determine execution mode
                    mode = override_mode or crew_def.execution_mode

                    if mode == ExecutionMode.SEQUENTIAL:
                        result = await crew.run_sequential(
                            query=query,
                            **execution_kwargs
                        )
                    elif mode == ExecutionMode.PARALLEL:
                        # Handle parallel execution
                        if isinstance(query, dict):
                            tasks = [
                                {"agent_id": agent_id, "query": agent_query}
                                for agent_id, agent_query in query.items()
                            ]
                        else:
                            tasks = [
                                {"agent_id": agent_id, "query": query}
                                for agent_id in crew.agents.keys()
                            ]

                        result = await crew.run_parallel(
                            tasks=tasks,
                            **execution_kwargs
                        )
                    elif mode == ExecutionMode.LOOP:
                        if not isinstance(query, str):
                            raise ValueError("Loop execution requires a string query for the initial task")

                        loop_condition = execution_kwargs.pop('condition', None)
                        if not loop_condition or not isinstance(loop_condition, str):
                            raise ValueError("Loop execution requires a 'condition' string in kwargs")

                        agent_sequence = execution_kwargs.pop('agent_sequence', None)
                        if agent_sequence is not None:
                            if not isinstance(agent_sequence, list):
                                raise ValueError("'agent_sequence' must be a list of agent identifiers")
                            if not all(isinstance(agent_id, str) for agent_id in agent_sequence):
                                raise ValueError("'agent_sequence' values must be strings")

                        max_iterations = execution_kwargs.pop('max_iterations', None)
                        if max_iterations is None:
                            max_iterations = 2
                        elif not isinstance(max_iterations, int):
                            raise ValueError("'max_iterations' must be an integer")

                        result = await crew.run_loop(
                            initial_task=query,
                            condition=loop_condition,
                            agent_sequence=agent_sequence,
                            max_iterations=max_iterations,
                            **execution_kwargs
                        )
                    elif mode == ExecutionMode.FLOW:
                        result = await crew.run_flow(
                            initial_task=query,
                            **execution_kwargs
                        )
                    else:
                        raise ValueError(f"Unknown execution mode: {mode}")

                    # Convert CrewResult to dict if necessary
                    if hasattr(result, 'to_dict'):
                        return result.to_dict()
                    elif hasattr(result, '__dict__'):
                        return result.__dict__
                    else:
                        return result

                except Exception as e:
                    self.logger.error(
                        f"Error executing crew {crew_id}: {e}",
                        exc_info=True
                    )
                    raise

            # Start execution
            await self.job_manager.execute_job(
                job.job_id,
                execute_crew
            )

            # Return job ID for tracking
            return self.json_response(
                {
                    "job_id": job.job_id,
                    "crew_id": crew_def.crew_id,
                    "status": job.status.value,
                    "message": "Crew execution started",
                    "created_at": job.created_at.isoformat(),
                    "execution_mode": selected_mode.value
                },
                status=202
            )
        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error creating job: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error: {str(e)}"},
                status=500
            )

    async def patch(self):
        """
        Get job status and results.

        Query parameters:
            - job_id: Job identifier (required)

        Returns:
            200: Job status and results if completed
            404: Job not found
            500: Server error
        """
        try:
            qs = self.get_arguments(self.request)
            match_params = self.match_parameters(self.request)
            job_id = match_params.get('id') or qs.get('job_id')
            if not job_id:
                # get from json body as fallback
                data = await self.request.json()
                job_id = data.get('job_id')

            if not job_id:
                return self.error(
                    response={"message": "job_id is required"},
                    status=400
                )

            # Get job
            job = self.job_manager.get_job(job_id)
            if not job:
                return self.error(
                    response={"message": f"Job '{job_id}' not found"},
                    status=404
                )

            # Return job status
            response_data = {
                "job_id": job.job_id,
                "crew_id": job.obj_id,
                "status": job.status.value,
                "elapsed_time": job.elapsed_time,
                "created_at": job.created_at.isoformat(),
                "metadata": job.metadata,
                "execution_mode": job.execution_mode
            }

            # Add result if completed
            if job.status == JobStatus.COMPLETED:
                response_data["result"] = job.result
                response_data["completed_at"] = job.completed_at.isoformat()
            elif job.status == JobStatus.FAILED:
                response_data["error"] = job.error
                response_data["completed_at"] = job.completed_at.isoformat()
            elif job.status == JobStatus.RUNNING:
                response_data["started_at"] = job.started_at.isoformat()

            return self.json_response(response_data)
        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting job status: {e}", exc_info=True)
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
            success = self.bot_manager.remove_crew(identifier)

            if success:
                return self.json_response({
                    "message": f"Crew '{identifier}' deleted successfully"
                })
            else:
                return self.error(
                    response={"message": f"Crew '{identifier}' not found"},
                    status=404
                )
        except web.HTTPError:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting crew: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error: {str(e)}"},
                status=500
            )

    async def _create_crew_from_definition(
        self,
        crew_def: CrewDefinition
    ) -> AgentCrew:
        """
        Create an AgentCrew instance from a CrewDefinition.

        Args:
            crew_def: Crew definition

        Returns:
            AgentCrew instance
        """
        # Create agents
        agents = []
        for agent_def in crew_def.agents:
            # Get agent class
            agent_class = self.bot_manager.get_bot_class(agent_def.agent_class)

            tools = []
            if agent_def.tools:
                tools.extend(iter(agent_def.tools))

            # Create agent instance
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

    def _get_agents_by_ids(
        self,
        crew: AgentCrew,
        agent_ids: List[str]
    ) -> List[Any]:
        """
        Get agent objects from crew by their IDs.

        Args:
            crew: AgentCrew instance
            agent_ids: List of agent IDs

        Returns:
            List of agent objects
        """
        agents = []
        for agent_id in agent_ids:
            if agent := crew.agents.get(agent_id):
                agents.append(agent)
            else:
                self.logger.warning(f"Agent '{agent_id}' not found in crew")
        return agents
