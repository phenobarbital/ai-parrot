from datetime import datetime
import textwrap
from pathlib import Path
from aiohttp import web
from datamodel import BaseModel, Field
from navconfig import BASE_DIR
from navigator_auth.decorators import (
    is_authenticated,
    user_session
)
from navigator.responses import JSONResponse
from parrot.handlers.abstract import AbstractAgentHandler
from parrot.handlers.agents import AgentHandler
from parrot.tools.weather import OpenWeather
from parrot.tools import PythonREPLTool
from parrot.tools.excel import ExcelTool
from parrot.tools.ppt import PowerPointGeneratorTool
from .tools import StoreInfo


class NextStopResponse(BaseModel):
    """
    NextStopResponse is a model that defines the structure of the response
    for the NextStop agent.
    """
    user_id: str = Field(..., description="Unique identifier for the user")
    agent_name: str = Field(required=False, description="Name of the agent that processed the request")
    data: str = Field(..., description="Data returned by the agent")
    status: str = Field(default="success", description="Status of the response")
    output: str = Field(required=False)
    transcript: str = Field(required=False, description="Transcript of the conversation with the agent")
    attributes: dict = Field(default_factory=dict, description="Additional attributes related to the response")
    store_id: str = Field(required=False, description="ID of the store associated with the session")
    employee_id: str = Field(required=False, description="ID of the employee associated with the session")
    manager_id: str = Field(required=False, description="ID of the manager associated with the session")
    created_at: datetime = Field(default=datetime.now())
    podcast_path: str = Field(required=False, description="Path to the podcast associated with the session")
    pdf_path: str = Field(required=False, description="Path to the PDF associated with the session")
    documents: list[Path] = Field(default_factory=list, description="List of documents associated with the session")


@user_session()
@is_authenticated()
class NextStopAgent(AgentHandler):
    """
    NextStopAgent is an abstract agent handler that extends the AgentHandler.
    It provides a framework for implementing specific agent functionalities.
    """
    agent_name: str = "NextStopAgent"
    agent_id: str = "nextstop_agent"
    base_route: str = '/api/v1/agents/nextstop'
    additional_routes: dict = [
        {
            "method": "GET",
            "path": "/api/v1/agents/nextstop/results/{sid}",
            "handler": "get_results"
        },
        {
            "method": "GET",
            "path": "/api/v1/agents/nextstop/status",
            "handler": "get_agent_status"
        },
        {
            "method": "GET",
            "path": "/api/v1/agents/nextstop/find_jobs",
            "handler": "find_jobs"
        }
    ]
    _backstory = """
Users can find store information, such as store hours, locations, and services.
The agent can also provide weather updates and perform basic Python code execution.
It is designed to assist users in planning their visits to stores by providing relevant information.
The agent can answer questions about store locations, hours of operation, and available services.
It can also provide weather updates for the store's location, helping users plan their visits accordingly.
The agent can execute Python code snippets to perform calculations or data processing tasks.
        """
    _model_response = NextStopResponse

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        # Initialize the agent with a specific LLM and tools
        self._tools = [
            OpenWeather(request='weather'),
            PythonREPLTool(
                report_dir=BASE_DIR.joinpath('static', self.agent_name, 'documents')
            ),
            ExcelTool(
                output_dir=BASE_DIR.joinpath('static', self.agent_name, 'documents')
            ),
            PowerPointGeneratorTool(
                output_dir=BASE_DIR.joinpath('static', self.agent_name, 'documents')
            )
        ] + StoreInfo().get_tools()

    async def get_results(self, request: web.Request) -> web.Response:
        """Return the results of the agent."""
        sid = request.match_info.get('sid', None)
        if not sid:
            return web.json_response(
                {"error": "Session ID is required"}, status=400
            )
        # Retrieve the task status using uuid of background task:
        return await self.get_task_status(sid, request)

    async def done_blocking(self, *args, **kwargs):
        print('Done Blocking Code :::')
        print('ARGS > ', args)
        print('KWARGS > ', kwargs)

    async def get_agent_status(self, request: web.Request) -> web.Response:
        """Return the status of the agent."""
        # Placeholder for actual status retrieval logic
        status = {"agent_name": self.agent_name, "status": "running"}
        return web.json_response(status)

    @AbstractAgentHandler.service_auth
    async def get(self) -> web.Response:
        """Handle GET requests."""
        # Placeholder for GET request handling logic
        return web.json_response({"message": "NextStopAgent is ready to assist!"})

    @AbstractAgentHandler.service_auth
    async def post(self) -> web.Response:
        """Handle POST requests."""
        data = await self.request.json()
        # Get Store ID if Provided:
        store_id = data.get('store_id', None)
        manager_id = data.get('manager_id', None)
        employee = data.get('employee_name', None)
        employee_id = data.get('employee_id', None)
        query = data.get('query', None)
        if not store_id and not manager_id and not employee_id and not query:
            return web.json_response(
                {"error": "Store ID or Manager ID is required"}, status=400
            )
        response = None
        job = None
        rsp_args = {}
        if store_id:
            # Execute the NextStop agent for a specific store using the Background task:
            job = await self.register_background_task(
            task=self._nextstop_report,
            done_callback=self.done_blocking,
                **{
                    'content': f"Store: {store_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "store_id": store_id
                    },
                    'store_id': store_id,
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for store {store_id}",
                'store_id': store_id,

            }
        elif employee_id:
            # Execute the NextStop agent for a specific employee using the Background task:
            job = await self.register_background_task(
                task=self._nextstop_employee,
                done_callback=self.done_blocking,
                **{
                    'content': f"Employee: {employee_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "employee_id": employee_id
                    },
                    'employee_id': employee_id
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for employee {employee_id}",
                'employee_id': employee_id
            }
        elif manager_id and employee:
            job = await self.register_background_task(
                task=self._nextstop_manager,
                done_callback=self.done_blocking,
                **{
                    'content': f"Manager: {manager_id}, Employee: {employee}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "manager_id": manager_id,
                        "employee_name": employee
                    },
                    'manager_id': manager_id,
                    'employee_name': employee
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for manager {manager_id} and employee {employee}",
                'manager_id': manager_id,
                'employee': employee
            }
        elif manager_id:
            # Execute the NextStop agent for a specific manager using the Background task:
            job = await self.register_background_task(
                task=self._team_performance,
                done_callback=self.done_blocking,
                **{
                    'content': f"Manager: {manager_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "manager_id": manager_id
                    },
                    'manager_id': manager_id,
                    'project': data.get('project', 'Navigator')
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for manager {manager_id}",
                'manager_id': manager_id,
            }
        else:
            query = data.get('query', None)
            # Execute the NextStop agent for an arbitrary query using the Background task:
            job = await self.register_background_task(
                task=self._query,
                done_callback=self.done_blocking,
                **{
                    'content': query,
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid
                    },
                    'project': data.get('project', 'Navigator'),
                    'query': query
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for query {query}"
            }
        # Return the response data
        if job:
            response = {
                'user_id': self._userid,
                'task_id': job.task_id,
                "job": job,
                **rsp_args
            }
            return JSONResponse(
                response,
                status=202,
            )
        return web.json_response(
            response,
            status=204,
        )

    async def _nextstop_report(self, store_id: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        query = await self.open_prompt('for_store.txt')
        question = query.format(store_id=store_id)
        try:
            _, response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # sections.append(response.output.strip())
        # Join all sections into a single report
        # final_report = "\n\n".join(sections)
        final_report = response.output.strip()
        # Use the joined report to generate a PDF and a Podcast:
        query = await self.open_prompt('for_pdf.txt')
        query = textwrap.dedent(query)
        for_pdf = query.format(
            final_report=final_report
        )
        # Invoke the agent with the PDF generation prompt
        try:
            response_data, response, _ = await self.ask_agent(for_pdf, store_id=store_id)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response_data.output = final_report
        return response_data

    async def _nextstop_employee(self, employee_id: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        query = await self.open_prompt('for_employee.txt')
        question = query.format(employee_id=employee_id)
        try:
            _, response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # sections.append(response.output.strip())
        # Join all sections into a single report
        # final_report = "\n\n".join(sections)
        final_report = response.output.strip()
        # Use the joined report to generate a PDF and a Podcast:
        query = await self.open_prompt('for_pdf.txt')
        query = textwrap.dedent(query)
        for_pdf = query.format(
            final_report=final_report
        )
        # Invoke the agent with the PDF generation prompt
        try:
            response_data, response, _ = await self.ask_agent(for_pdf, employee_id=employee_id)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response_data.output = final_report
        return response_data

    async def _nextstop_manager(self, manager_id: str, employee_name: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        # TODO: migrate to safeDict on open_prompt and using Jinja2 templating
        query = await self.open_prompt('manager.txt')
        question = query.format(
            manager_id=manager_id,
            employee_name=employee_name
        )
        try:
            _, response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # Join all sections into a single report
        final_report = response.output.strip()
        # Use the joined report to generate a PDF and a Podcast:
        query = await self.open_prompt('for_pdf.txt')
        query = textwrap.dedent(query)
        for_pdf = query.format(
            final_report=final_report,
            manager_id=manager_id,
            employee_name=employee_name
        )
        # Invoke the agent with the PDF generation prompt
        try:
            response_data, response, _ = await self.ask_agent(for_pdf)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        return response_data


    async def _team_performance(self, manager_id: str, project: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        query = await self.open_prompt('team_performance.txt')
        question = query.format(
            manager_id=manager_id,
            project=project
        )
        try:
            _, response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        # Join all sections into a single report
        final_report = response.output.strip()
        # Use the joined report to generate a PDF and a Podcast:
        query = await self.open_prompt('for_pdf.txt')
        query = textwrap.dedent(query)
        for_pdf = query.format(
            final_report=final_report
        )
        # Invoke the agent with the PDF generation prompt
        try:
            response_data, response, _ = await self.ask_agent(for_pdf)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        return response_data


    async def _query(self, query: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        try:
            response_data, response, _ = await self.ask_agent(query)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response_data.output = response.output.strip()
        return response_data
