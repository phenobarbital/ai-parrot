from typing import Any, Dict, Optional
import uuid
from navigator.views import BaseView
from navigator.types import WebApp
from navigator.applications.base import BaseApplication
from navconfig.logging import logging
from parrot.bots.orchestration.crew import AgentCrew
from parrot.handlers.crew.models import (
    JobStatus,
    ExecutionMode,
)
from ..jobs import JobManager


class CrewExecutionHandler(BaseView):
    """
    REST API Handler for running Crew execution and monitoring.

    Responsibilities:
    - Execute Crews (POST /api/v1/crews)
    - Monitor Job Status (PATCH /api/v1/crews?job_id=...)
    - List Active/Completed Jobs (GET /api/v1/crews?mode=...)
    - Detailed Agent Status (GET /api/v1/crews/{job_id}/{crew_id})
    - Interact with Running Crews (POST /api/v1/crews/{job_id}/{crew_id}/ask)
    """
    
    path: str = '/api/v1/crews'
    app: WebApp = None
    # Cache of active crew instances by job_id
    _active_crews: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger('Parrot.CrewExecutionHandler')
        self._bot_manager = None
        self.job_manager: JobManager = self.app['job_manager'] if 'job_manager' in self.app else JobManager()

    @property
    def bot_manager(self):
        """Get bot manager."""
        if not self._bot_manager:
            app = self.request.app
            self._bot_manager = app['bot_manager'] if 'bot_manager' in app else None
        return self._bot_manager

    @staticmethod
    async def configure_job_manager(app: WebApp):
        """Configure and start job manager."""
        if 'job_manager' not in app:
            app['job_manager'] = JobManager()
            await app['job_manager'].start()

    @staticmethod
    async def start_cleanup_task(app: WebApp):
        """Start background cleanup for finished jobs/crews if needed."""
        # Placeholder for future cleanup logic if not handled by JobManager
        pass

    @classmethod
    def configure(cls, app: WebApp = None, path: str = None, **kwargs) -> WebApp:
        if isinstance(app, BaseApplication):
            cls.app = app.get_app()
        elif isinstance(app, WebApp):
            cls.app = app
        
        if app:
            # Root route for Execute, List, and Generic Status
            app.router.add_view(
                r"{url}".format(url=cls.path), cls
            )
            # Route for agent statuses: /api/v1/crews/{job_id}/{crew_id}
            app.router.add_view(
                r"{url}/{{job_id}}/{{crew_id}}".format(url=cls.path), cls
            )
            # Route for agent result: /api/v1/crews/{job_id}/{crew_id}/{agent_id}
            app.router.add_view(
                r"{url}/{{job_id}}/{{crew_id}}/{{agent_id}}".format(url=cls.path), cls
            )
            # Route for specific actions like ask/summary
            app.router.add_view(
                r"{url}/{{job_id}}/{{crew_id}}/{{action:ask|summary}}".format(url=cls.path), cls
            )
            
            # Configure dependencies
            app.on_startup.append(cls.configure_job_manager)
            app.on_startup.append(cls.start_cleanup_task)

    async def _get_crew(self, job_id: str) -> Optional[AgentCrew]:
        """Retrieve active crew from local cache."""
        if job_id in self._active_crews:
            return self._active_crews[job_id]
        return None

    async def get(self):
        """
        Handle GET requests:
        1. List active/completed jobs (query params: mode=active_jobs|completed_jobs)
        2. Get specific job/crew/agent details (path params)
        """
        match_params = self.match_parameters(self.request)
        job_id = match_params.get('job_id')
        crew_id = match_params.get('crew_id')
        agent_id = match_params.get('agent_id')
        qs = self.get_arguments(self.request)

        # CASE 1: Path Parameters Present -> Detailed Status
        if job_id and crew_id:
            crew = await self._get_crew(job_id)
            if not crew:
                 # If not in memory but we have IDs, check if job is known to JobManager
                 # But we need the AgentCrew instance for agent-level details.
                return self.error(
                    response={
                        "message": f"Crew execution context for job {job_id} not found (may be expired or restarted)"
                    },
                    status=404
                )

            try:
                if agent_id:
                    # Return specific agent result
                    result = crew.get_agent_result(agent_id)
                    if result:
                        return self.json_response(result.dict())
                    else:
                        # Check if agent exists anywhere and has result in status
                        if agent_id in crew.agents:
                            status_info = crew._agent_statuses.get(agent_id, {})
                            # Fallback: check if result is in status_info (it should be for completed agents)
                            if 'result' in status_info and status_info['result']:
                                return self.json_response(status_info) # Return full status info which includes result
                            
                            return self.json_response({
                                "agent_id": agent_id,
                                "status": status_info.get("status", "idle"),
                                "message": "No result available yet"
                            })
                        return self.error(
                           response={"message": f"Agent {agent_id} not found"},
                           status=404
                       )
                else:
                    # Return all agent statuses
                    statuses = crew.get_agents_status()
                    return self.json_response(statuses)

            except Exception as e:
                self.logger.error(f"Error retrieving crew info: {e}", exc_info=True)
                return self.error(
                    response={"message": f"Server error: {str(e)}"},
                    status=500
                )

        # CASE 2: No Path Params -> List Jobs (based on query params)
        mode = qs.get('mode')
        
        if mode == 'active_jobs':
            active_jobs = []
            # Iterate over a copy of keys to avoid runtime modification issues
            for j_id in list(self._active_crews.keys()):
                crew = self._active_crews[j_id]
                job = self.job_manager.get_job(j_id)
                if job and job.status not in [JobStatus.COMPLETED, JobStatus.FAILED]:
                    active_jobs.append({
                        "job_id": job.job_id,
                        "crew_id": job.obj_id,
                        "crew_name": crew.name if hasattr(crew, 'name') and (crew.name != "Unknown Crew") else job.metadata.get('crew_name', "Unknown Crew"),
                        "status": job.status.value,
                        "created_at": job.created_at.isoformat(),
                        "query": job.query,
                        "execution_mode": job.execution_mode
                    })
            return self.json_response(active_jobs)

        elif mode == 'completed_jobs':
            completed_jobs = []
            sorted_jobs = []
            
            if hasattr(self.job_manager, 'list_jobs'):
                all_jobs = self.job_manager.list_jobs(limit=100) 
                sorted_jobs = [j for j in all_jobs if j.status in [JobStatus.COMPLETED, JobStatus.FAILED]]
            elif hasattr(self.job_manager, '_jobs'):
                sorted_jobs = sorted(
                   [j for j in self.job_manager._jobs.values() if j.status in [JobStatus.COMPLETED, JobStatus.FAILED]],
                   key=lambda x: x.created_at,
                   reverse=True
                )
            
            sorted_jobs = sorted_jobs[:50]
            
            for job in sorted_jobs:
                crew_name = job.metadata.get('crew_name')
                if not crew_name or crew_name == "Unknown Crew":
                    # Try to fetch from bot_manager
                    try:
                        _, crew_def = await self.bot_manager.get_crew(job.obj_id)
                        if crew_def:
                            crew_name = crew_def.name
                            job.metadata['crew_name'] = crew_name
                        else:
                            crew_name = "Unknown Crew"
                    except Exception:
                        crew_name = "Unknown Crew"

                completed_jobs.append({
                    "job_id": job.job_id,
                    "crew_name": crew_name,
                    "crew_id": job.obj_id,
                    "status": job.status.value,
                    "created_at": job.created_at.isoformat(),
                    "query": job.query,
                    "execution_mode": job.execution_mode
                })
            return self.json_response(completed_jobs)
        
        return self.error(status=400, response={"message": "Missing required parameters (job_id/crew_id) or valid 'mode'"})

    async def patch(self):
        """
        Handle PATCH requests:
        1. Get Job Status (Legacy/Generic endpoint) via query param `job_id`
        """
        match_params = self.match_parameters(self.request)
        # Check if this maps to a specific resource via path (though usually PATCH isn't used for GET semantics there)
        # We focus on the generic status retrieval pattern requested by user: "PATCH: returning the results from Crew"
        
        try:
            qs = self.get_arguments(self.request)
            job_id = match_params.get('job_id') or qs.get('job_id')
            
            data = {}
            if self.request.body_exists:
                try:
                    data = await self.request.json()
                except Exception:
                    pass

            if not job_id:
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
                "metadata": self._safe_serialize_result(job.metadata, path="response_data.metadata"),
                "execution_mode": job.execution_mode
            }

            # Retrieve active crew instance
            crew = self._active_crews.get(job_id)
            
            if crew:
                response_data["crew_active"] = True
                
                # Check for granular scopes (Legacy support or explicit generic requests)
                scope = qs.get('scope') or data.get('scope')
                
                if scope == 'agents':
                    if hasattr(crew, 'get_agent_statuses'):
                        response_data["agents"] = self._safe_serialize_result(
                            crew.get_agent_statuses(),
                            path="response_data.agents",
                        )
                        
                elif scope == 'agent_result':
                    agent_id = qs.get('agent_id') or data.get('agent_id')
                    if agent_id:
                        if hasattr(crew, 'get_agent_result'):
                            result_info = crew.get_agent_result(agent_id)
                            if result_info:
                                response_data["result"] = self._safe_serialize_result(
                                    result_info,
                                    path="response_data.result",
                                )
            else:
                response_data["crew_active"] = False

            # Add result if completed
            if job.status == JobStatus.COMPLETED:
                response_data["result"] = self._safe_serialize_result(
                    job.result,
                    path="response_data.result",
                )
                response_data["completed_at"] = job.completed_at.isoformat()
                # Do NOT remove from active_crews yet, so user can fetch agent details.
                # self._active_crews.pop(job_id, None)
            elif job.status == JobStatus.FAILED:
                response_data["error"] = str(job.error) # execute str() to avoid object reference issues
                response_data["completed_at"] = job.completed_at.isoformat()
                # Do NOT remove from active_crews yet
                # self._active_crews.pop(job_id, None)
            elif job.status == JobStatus.RUNNING:
                response_data["started_at"] = job.started_at.isoformat()

            # Ensure response_data itself is safely serialized
            safe_response = self._safe_serialize_result(response_data, path="response_data")
            return self.json_response(safe_response)
        except Exception as e:
            self.logger.error(f"Error getting job status: {e}", exc_info=True)
            return self.error(
                response={"message": f"Error: {str(e)}"},
                status=500
            )

    def _safe_serialize_result(
        self,
        result: Any,
        visited: Optional[set] = None,
        path: str = "root",
    ) -> Any:
        """
        Safely serialize execution results to prevent recursion errors.
        Handles CrewResult, AgentResponse, AIMessage, and other complex objects.
        Tracks visited objects to prevent infinite recursion.
        """
        def _format_child_path(parent: str, key: Any) -> str:
            try:
                key_str = str(key)
            except Exception:
                key_str = "<unprintable>"
            if key_str.isidentifier():
                return f"{parent}.{key_str}"
            return f"{parent}[{ascii(key_str)}]"

        if result is None:
            return None

        # Initialize visited set
        if visited is None:
            visited = set()

        # Handle ID for circular reference detection
        try:
            obj_id = id(result)
            if obj_id in visited:
                self.logger.warning(
                    "Serialization circular reference at %s (%s)",
                    path,
                    type(result).__name__,
                )
                return f"<Circular Reference: {type(result).__name__}>"
            visited.add(obj_id)
        except Exception:
            # If id() fails or checks fail, continue best effort
            pass
            
        try:
            # Handle dataclasses (including CrewResult) - prefer to_dict if available
            if hasattr(result, '__dataclass_fields__') and not isinstance(result, bool):
                if hasattr(result, 'to_dict') and callable(result.to_dict):
                    try:
                        res = result.to_dict()
                        return self._safe_serialize_result(
                            res,
                            visited.copy(),
                            path=f"{path}.to_dict",
                        )
                    except Exception:
                        self.logger.warning(
                            "Serialization to_dict failed at %s (%s)",
                            path,
                            type(result).__name__,
                            exc_info=True,
                        )
                        return str(result)
                # Generic dataclass
                from dataclasses import asdict
                try:
                    # Generic handling: convert to dict first
                    d = asdict(result)
                    return {
                        k: self._safe_serialize_result(
                            v,
                            visited.copy(),
                            path=_format_child_path(path, k),
                        )
                        for k, v in d.items()
                    }
                except Exception:
                    self.logger.warning(
                        "Serialization asdict failed at %s (%s)",
                        path,
                        type(result).__name__,
                        exc_info=True,
                    )
                    return str(result)
                    
            # Handle AgentExecutionInfo (dataclass with to_dict)
            if hasattr(result, 'to_dict') and callable(result.to_dict):
                try:
                    res = result.to_dict()
                    return self._safe_serialize_result(
                        res,
                        visited.copy(),
                        path=f"{path}.to_dict",
                    )
                except Exception:
                    self.logger.warning(
                        "Serialization to_dict failed at %s (%s)",
                        path,
                        type(result).__name__,
                        exc_info=True,
                    )
                    return str(result)
                
            # Handle Pydantic Models (AIMessage, AgentResponse)
            if hasattr(result, 'model_dump'):
                return self._safe_serialize_result(
                    result.model_dump(),
                    visited.copy(),
                    path=f"{path}.model_dump",
                )
            if hasattr(result, 'dict') and callable(result.dict):
                return self._safe_serialize_result(
                    result.dict(),
                    visited.copy(),
                    path=f"{path}.dict",
                )
                
            # Handle lists and dicts
            if isinstance(result, list):
                return [
                    self._safe_serialize_result(
                        item,
                        visited.copy(),
                        path=f"{path}[{idx}]",
                    )
                    for idx, item in enumerate(result)
                ]
            if isinstance(result, dict):
                return {
                    str(k): self._safe_serialize_result(
                        v,
                        visited.copy(),
                        path=_format_child_path(path, k),
                    )
                    for k, v in result.items()
                }
                
            # Primitives
            if isinstance(result, (str, int, float, bool)):
                return result
                
            # Fallback
            return str(result)
        except Exception as e:
            # Fallback for ANY error during serialization
            self.logger.error(
                "Serialization error at %s (%s): %s",
                path,
                type(result).__name__,
                e,
                exc_info=True,
            )
            return f"<Serialization Error: {str(e)}>"
        finally:
            if visited and 'obj_id' in locals() and obj_id in visited:
                visited.remove(obj_id)

    async def post(self):
        """
        Handle POST requests:
        1. Execute Crew (Root path)
        2. Ask/Summary (Path params)
        """
        match_params = self.match_parameters(self.request)
        action = match_params.get('action')
        
        # Parse Body
        try:
            data = await self.request.json()
        except Exception:
            data = {}

        # CASE 1: Specific Action (Ask/Summary)
        if action:
            job_id = match_params.get('job_id')
            crew_id = match_params.get('crew_id')
            
            if not job_id or not crew_id:
                return self.error(status=400, response={"message": "Missing IDs"})

            crew = await self._get_crew(job_id)
            if not crew:
                return self.error(status=404, response={"message": "Crew context not found"})

            try:
                if action == 'ask':
                    question = data.get('question')
                    if not question:
                        return self.error(status=400, response={"message": "Missing 'question'"})
                    if hasattr(crew, 'ask'):
                        response = await crew.ask(question)
                        content = response.content if hasattr(response, 'content') else str(response)
                        return self.json_response({"response": content})
                    else:
                        return self.error(status=400, response={"message": "Crew does not support 'ask'"})

                elif action == 'summary':
                    mode = data.get('mode', 'executive_summary')
                    summary_prompt = data.get('summary_prompt')
                    
                    if hasattr(crew, 'summary'):
                        summary = await crew.summary(
                            mode=mode,
                            summary_prompt=summary_prompt,
                            **data.get('kwargs', {})
                        )
                        return self.json_response({"summary": summary})
                    else:
                         return self.error(status=400, response={"message": "Crew does not support 'summary'"})
                
                else:
                    return self.error(status=400, response={"message": f"Unknown action: {action}"})
            
            except Exception as e:
                self.logger.error(f"Error performing {action}: {e}", exc_info=True)
                return self.error(status=500, response={"message": str(e)})

        # CASE 2: Execute Crew (Root path)
        # Corresponds to: POST /api/v1/crews
        else:
            return await self.execute_crew(data)

    async def execute_crew(self, data: Dict[str, Any]):
        """Logic to initialize and run a crew execution job."""
        try:
            crew_id = data.get('crew_id') or data.get('name')
            if not crew_id:
                return self.error(response={"message": "crew_id or name is required"}, status=400)

            query = data.get('query')
            if not query:
                return self.error(response={"message": "query is required"}, status=400)

            if not self.bot_manager:
                return self.error(response={"message": "BotManager not available"}, status=500)

            # Load Crew
            crew, crew_def = await self.bot_manager.get_crew(crew_id, as_new=True)
            if not crew:
                return self.error(response={"message": f"Crew '{crew_id}' not found"}, status=404)

            # Mode selection
            requested_mode = data.get('execution_mode')
            override_mode: Optional[ExecutionMode] = None
            if requested_mode:
                try:
                    override_mode = ExecutionMode(requested_mode)
                except ValueError:
                    return self.error(response={"message": f"Invalid execution mode: {requested_mode}"}, status=400)

            selected_mode = override_mode or crew_def.execution_mode
            
            # Create Job
            job_id = str(uuid.uuid4())
            job = self.job_manager.create_job(
                job_id=job_id,
                obj_id=crew_def.crew_id,
                query=query,
                user_id=data.get('user_id'),
                session_id=data.get('session_id'),
                execution_mode=selected_mode.value
            )
            
            # Store crew name in metadata for future persistence
            job.metadata['crew_name'] = crew_def.name

            # Cache the running crew
            self._active_crews[job_id] = crew

            # Prepare Args
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

            # Execution Logic Wrapper
            async def run_logic():
                try:
                    mode = override_mode or crew_def.execution_mode
                    if mode == ExecutionMode.SEQUENTIAL:
                        result = await crew.run_sequential(query=query, **execution_kwargs)
                    elif mode == ExecutionMode.PARALLEL:
                        if isinstance(query, dict):
                            tasks = [{"agent_id": k, "query": v} for k, v in query.items()]
                        else:
                            tasks = [{"agent_id": k, "query": query} for k in crew.agents.keys()]
                        result = await crew.run_parallel(tasks=tasks, **execution_kwargs)
                    elif mode == ExecutionMode.LOOP:
                        # (Validation logic omitted for brevity as it's handled in original)
                        loop_condition = execution_kwargs.pop('condition', None)
                        agent_sequence = execution_kwargs.pop('agent_sequence', None)
                        max_iterations = execution_kwargs.pop('max_iterations', 2)
                        result = await crew.run_loop(
                            initial_task=query, 
                            condition=loop_condition, 
                            agent_sequence=agent_sequence, 
                            max_iterations=max_iterations, 
                            **execution_kwargs
                        )
                    elif mode == ExecutionMode.FLOW:
                        result = await crew.run_flow(initial_task=query, **execution_kwargs)
                    else:
                        raise ValueError(f"Unknown mode: {mode}")

                    if hasattr(result, 'to_dict'): return result.to_dict()
                    elif hasattr(result, '__dict__'): return result.__dict__
                    return result
                except Exception as e:
                    self.logger.error(f"Error executing crew {crew_id}: {e}", exc_info=True)
                    raise

            # Start Job
            await self.job_manager.execute_job(job.job_id, run_logic)

            return self.json_response({
                "job_id": job.job_id,
                "crew_id": crew_def.crew_id,
                "status": job.status.value,
                "message": "Crew execution started",
                "created_at": job.created_at.isoformat(),
                "execution_mode": selected_mode.value
            }, status=202)

        except Exception as e:
            self.logger.error(f"Error creating job: {e}", exc_info=True)
            return self.error(response={"message": f"Error: {str(e)}"}, status=500)
