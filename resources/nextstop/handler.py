from typing import Any
import re
from datetime import datetime
import textwrap
from pathlib import Path
import asyncio
from aiohttp import web
from datamodel import BaseModel, Field
from datamodel.parsers.json import json_encoder  # pylint: disable=E0611
from asyncdb.exceptions import NoDataFound
from navconfig import BASE_DIR
from navigator_session import get_session, AUTH_SESSION_OBJECT
from navigator_auth.decorators import (
    is_authenticated,
    user_session
)
from navigator.responses import JSONResponse
from navigator.views import ModelView
from parrot.bots.nextstop import NextStop
from parrot.handlers.agents import AgentHandler
from parrot.tools.nextstop import StoreInfo, EmployeeToolkit
from .models import NextStopStore


class NextStopStoreView(ModelView):
    """
    NextStopStoreView is a view that handles the NextStopStore model.
    It provides methods to interact with the NextStopStore data.
    """
    model = NextStopStore
    name = "NextStopStore"
    path = '/api/v1/nextstop_responses'
    pk: str = 'report_id'


    async def _set_created_by(self, value, column, data):
        return await self.get_userid(session=self._session)

    async def _set_is_new(self, value, column, data):
        """Always mark as false for existing records."""
        return False


class NextStopResponse(BaseModel):
    """
    NextStopResponse is a model that defines the structure of the response
    for the NextStop agent.
    """
    user_id: str = Field(..., description="Unique identifier for the user")
    agent_name: str = Field(
        required=False,
        description="Name of the agent that processed the request"
    )
    program: str = Field(default="hisense", description="Program slug for the agent")
    data: str = Field(..., description="Data returned by the agent")
    status: str = Field(default="success", description="Status of the response")
    output: str = Field(required=False)
    transcript: str = Field(
        required=False,
        description="Transcript of the conversation with the agent"
    )
    attributes: dict = Field(
        default_factory=dict,
        description="Additional attributes related to the response"
    )
    store_id: str = Field(
        required=False,
        description="ID of the store associated with the session"
    )
    employee_id: str = Field(
        required=False,
        description="ID of the employee associated with the session"
    )
    manager_id: str = Field(
        required=False,
        description="ID of the manager associated with the session"
    )
    created_at: datetime = Field(default=datetime.now)
    podcast_path: str = Field(
        required=False,
        description="Path to the podcast associated with the session"
    )
    script_path: str = Field(
        required=False,
        description="Path to the script associated with the session"
    )
    pdf_path: str = Field(
        required=False,
        description="Path to the PDF associated with the session"
    )
    document_path: str = Field(
        required=False,
        description="Path to document generated during session"
    )
    documents: list[Path] = Field(
        default_factory=list,
        description="List of documents associated with the session"
    )


@user_session()
@is_authenticated()
class NextStopAgent(AgentHandler):
    """
    NextStopAgent is an abstract agent handler that extends the AgentHandler.
    It provides a framework for implementing specific agent functionalities.
    """
    agent_name: str = "NextStopAgent"
    agent_id: str = "nextstop"
    _agent_class: type = NextStop
    _agent_response = NextStopResponse
    _use_llm: str = 'openai'
    _use_model: str = 'gpt-4.1-mini'
    # _use_llm: str = 'google'
    # _use_model: str = 'gemini-2.5-pro'
    _tools = []

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

    def define_tools(self):
        """Define the tools for the NextStop agent."""
        # Get program from session or default
        program = getattr(self, '_program', 'hisense')
        tools = StoreInfo(program=program).get_tools()
        tools.extend(EmployeeToolkit(program=program).get_tools())
        self._tools = tools

    async def get_results(self, request: web.Request) -> web.Response:
        """Return the results of the agent."""
        sid = request.match_info.get('sid', None)
        if not sid:
            return web.json_response(
                {
                    "error": "Session ID is required"
                }, status=400
            )
        # Retrieve the task status using uuid of background task:
        return await self.get_task_status(sid, request)

    async def done_question(
        self,
        result: NextStopResponse,
        exc: Exception,
        loop: asyncio.AbstractEventLoop = None,
        job_record: Any = None,
        task_id: str = None,
        **kwargs
    ):
        """Callback function to handle the completion of a question."""
        if exc:
            print(f"Error in done_question: {exc}")
            return
        # Process the result of the question
        # Save the result into the database:
        pg = self.db_connection()
        async with await pg.connection() as conn:  # pylint: disable=E1101  # noqa
            # Save the result to the database
            NextStopStore.Meta.connection = conn
            try:
                # Determine the kind value based on the job record and attributes
                base_kind = job_record.name if job_record else 'nextstop'
                def extract_store_id_from_data(data_content: str) -> str:
                    """Extract store ID from the data content using regex."""
                    # Look for patterns like "Store ID:** BBY1220" or "**Store ID:** BBY1220"
                    store_id_pattern = r'\*\*Store ID:\*\*\s*([A-Z0-9]+)'
                    match = re.search(store_id_pattern, data_content)
                    return match.group(1) if match else None

                def extract_employee_id_from_data(data_content: str) -> str:
                    """Extract employee ID from the data content."""
                    # Look for employee ID patterns in the content
                    employee_pattern = r'employee[_\s]*id[:\s]*([A-Z0-9]+)'
                    match = re.search(employee_pattern, data_content, re.IGNORECASE)
                    return match.group(1) if match else None

                if base_kind == '_nextstop_store':
                    if result.store_id:
                        # Use store_id from attributes
                        kind = f"{base_kind}_{result.store_id}"
                    elif result.data:
                        # Extract from data content
                        store_id = extract_store_id_from_data(result.data)
                        kind = f"{base_kind}_{store_id}" if store_id else base_kind
                    else:
                        kind = base_kind
                elif base_kind == '_nextstop_employee':
                    if result.employee_id:
                        # Use employee_id from attributes
                        kind = f"{base_kind}_{result.employee_id}"
                    elif result.data:
                        # Extract from data content
                        employee_id = extract_employee_id_from_data(result.data)
                        kind = f"{base_kind}_{employee_id}" if employee_id else base_kind
                    else:
                        kind = base_kind
                else:
                    kind = base_kind

            except Exception as e:
                print(f"Error determining kind: {e}")
                kind = 'nextstop'

            # Create a new NextStopStore record
            try:
                record = NextStopStore(
                    user_id=int(result.user_id),
                    agent_name=result.agent_name,
                    program_slug=result.program,
                    kind=kind,
                    content=job_record.content,
                    data=result.data,
                    output=result.output,
                    podcast_path=str(result.podcast_path),
                    pdf_path=str(result.pdf_path),
                    documents=json_encoder(result.documents),
                    attributes=result.attributes,
                    manager_id=result.manager_id,
                    employee_id=result.employee_id,
                    created_by=result.user_id
                )
                await record.save()
            except Exception as e:
                print(f"Error creating NextStopStore record: {e}")
                return

    async def get_agent_status(self, request: web.Request) -> web.Response:
        """Return the status of the agent."""
        # Placeholder for actual status retrieval logic
        status = {"agent_name": self.agent_name, "status": "running"}
        return web.json_response(status)

    @AgentHandler.service_auth
    async def get(self) -> web.Response:
        """Handle GET requests."""
        pg = self.db_connection()
        async with await pg.connection() as conn:  # pylint: disable=E1101  # noqa
            NextStopStore.Meta.connection = conn
            try:
                # Retrieve all records from the NextStopStore table
                session = await get_session(self.request)
                if not session:
                    return web.json_response(
                        {"error": "Session not found"}, status=401
                    )
                userinfo = session.get(AUTH_SESSION_OBJECT, {})
                userid = self._userid if self._userid else userinfo.get('user_id', None)
                email = userinfo.get('email', None)
                if not userid:
                    return web.json_response(
                        {"error": "User ID not found in session"}, status=401
                    )
                _filter = {
                    "where": {
                        "$or": [
                            {"employee_id": email},
                            {"manager_id": email},
                        ],
                        "agent_name": self.agent_name,
                    }
                }
                records = await NextStopStore.filter(**_filter)
                if not records:
                    return web.json_response(
                        headers={"x-message": "No records found for the NextStop agent."},
                        status=204
                    )
            except NoDataFound as e:
                return web.json_response(
                    {"error": "No records found for the NextStop agent."},
                    status=404
                )
            try:
                # If records are found, process them
                # Convert records to a list of dictionaries
                results = [record.to_dict() for record in records]
                return self.json_response(
                    results,
                    status=200,
                    headers={
                        "x-message": "Records retrieved successfully."
                    }
                )
            except Exception as e:
                print(f"Error connecting to the database: {e}")
                return self.json_response(
                    {
                        "error": f"Database connection error: {e}"
                    },
                    status=400
                )

    @AgentHandler.service_auth
    async def post(self) -> web.Response:
        """Handle POST requests."""
        security_groups = {'hisense360', 'epson360', 'hisense', 'epson'}
        data = await self.request.json()
        session_email = self._session['email']
        program_slug = data.get('program', 'hisense')
        if program_slug not in self._session['programs']:
            # check if in session['programs'] is one of the security groups:
            if not any(group in self._session['programs'] for group in security_groups):
                # If the program is not available, return an error response
                self.logger.error(
                    f"Program {program_slug} is not available for user {session_email}"
                )
        # Get Store ID if Provided:
        store_id = data.get('store_id', None)
        manager_id = data.get('manager_id', None)
        employee_id = data.get('employee_id')
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
            task=self._nextstop_store,
            done_callback=self.done_question,
                **{
                    'content': f"Store: {store_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "store_id": store_id
                    },
                    'store_id': store_id,
                    'employee_id': employee_id if employee_id else session_email,
                    'program_slug': program_slug
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for store {store_id}",
                'store_id': store_id,
                'program_slug': program_slug,

            }
        elif manager_id and employee_id:
            job = await self.register_background_task(
                task=self._nextstop_manager,
                done_callback=self.done_question,
                **{
                    'content': f"Manager: {manager_id}, Employee: {employee_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "manager_id": manager_id,
                        "employee_id": employee_id
                    },
                    'manager_id': manager_id,
                    'employee_id': session_email if not employee_id else employee_id,
                    'program_slug': program_slug
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for manager {manager_id} and employee {employee_id}",
                'manager_id': manager_id,
                'employee': employee_id,
                'program_slug': program_slug
            }
        elif employee_id:
            # Execute the NextStop agent for a specific employee using the Background task:
            job = await self.register_background_task(
                task=self._nextstop_employee,
                done_callback=self.done_question,
                **{
                    'content': f"Employee: {employee_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "employee_id": employee_id
                    },
                    'employee_id': employee_id,
                    'program_slug': program_slug
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for employee {employee_id}",
                'employee_id': employee_id,
                'program_slug': program_slug
            }
        elif manager_id:
            # Execute the NextStop agent for a specific manager using the Background task:
            job = await self.register_background_task(
                task=self._team_performance,
                done_callback=self.done_question,
                **{
                    'content': f"Manager: {manager_id}",
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid,
                        "manager_id": manager_id
                    },
                    'manager_id': manager_id,
                    'employee_id': manager_id,
                    'project': data.get('project', 'Navigator'),
                    'program_slug': program_slug
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for manager {manager_id}",
                'manager_id': manager_id,
                'program_slug': program_slug
            }
        else:
            query = data.get('query', None)
            # Execute the NextStop agent for an arbitrary query using the Background task:
            job = await self.register_background_task(
                task=self._query,
                done_callback=self.done_question,
                **{
                    'content': query,
                    'attributes': {
                        'agent_name': self.agent_name,
                        'user_id': self._userid
                    },
                    'project': data.get('project', 'Navigator'),
                    'query': query,
                    'program_slug': program_slug
                }
            )
            rsp_args = {
                "message": f"NextStopAgent is processing the request for query {query}",
                'program_slug': program_slug
            }
        # Return the response data
        if job:
            response = {
                'user_id': self._userid,
                'task_id': job.task_id,
                'agent_name': self.agent_name,
                'program_slug': program_slug,
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

    async def get_manager_id(self, request: web.Request) -> str:
        """Retrieve the manager ID from the request session."""
        session = await get_session(request)
        manager_id = None
        if not session:
            raise web.HTTPUnauthorized(reason="Session not found")
        userinfo = session.get(AUTH_SESSION_OBJECT, {})
        email = userinfo.get('email', None)
        if not userinfo:
            return None
        manager_id = userinfo.get('manager_id', None)
        if not manager_id:
            # retrieve manager id from database:
            pg = self.db_connection()
            async with await pg.connection() as conn:  # pylint: disable=E1101  # noqa
                qry = f"""
SELECT m.corporate_email as manager_id from troc.troc_employees e
INNER JOIN troc.troc_employees m ON e.reports_to_associate_oid = m.associate_oid
where e.corporate_email = '{email!s}'
                """
                result = await conn.fetch_one(qry)
                manager_id = result['manager_id'] if result else None
        return manager_id

    async def _generate_report(self, response: NextStopResponse) -> NextStopResponse:
        """Generate a report from the response data."""
        final_report = response.output.strip()
        # print(f"Final report generated: {final_report}")
        if not final_report:
            response.output = "No report generated."
            response.status = "error"
            return response
        response.transcript = final_report
        # generate the transcript file:
        if not self._agent:
            agent = self.request.app[self.agent_id]
        else:
            agent = self._agent
        # Set the manager ID from session:
        manager_id = await self.get_manager_id(self.request)
        if manager_id:
            response.manager_id = manager_id
        try:
            _path = await agent.save_transcript(
                transcript=final_report,
            )
            response.document_path = str(_path)
            response.documents.append(response.document_path)
        except Exception as e:
            self.logger.error(f"Error generating transcript: {e}")
        # generate the PDF file:
        try:
            pdf_output = await agent.pdf_report(
                content=final_report
            )
            response.pdf_path = str(pdf_output.result.get('file_path', None))
            response.documents.append(response.pdf_path)
        except Exception as e:
            self.logger.error(f"Error generating PDF: {e}")
        # generate the podcast file:
        try:
            podcast_output = await agent.speech_report(
                report=final_report,
                max_lines=20,
                num_speakers=1
            )
            response.podcast_path = str(podcast_output.get('podcast_path', None))
            response.script_path = str(podcast_output.get('script_path', None))
            response.documents.append(response.podcast_path)
            response.documents.append(response.script_path)
        except Exception as e:
            self.logger.error(
                f"Error generating podcast: {e}"
            )
        # Save the final report to the response
        response.output = textwrap.fill(final_report, width=80)
        response.status = "success"
        return response

    async def _nextstop_store(self, store_id: str, employee_id: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        # Get program from data or session
        program_slug = kwargs.get('program_slug', 'hisense')  # fallback to hisense

        query = await self.open_prompt('for_store.txt')
        question = query.format(store_id=store_id, program_slug=program_slug)

        # Set program in agent before asking
        if hasattr(self._agent, 'set_program'):
            self._agent.set_program(program_slug)

        try:
            response, _ = await self.ask_agent(query=question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response.store_id = store_id
        response.employee_id = employee_id
        response.program = program_slug
        return await self._generate_report(response)

    async def _nextstop_employee(self, employee_id: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        program_slug = kwargs.get('program_slug', 'hisense')  # fallback to hisense

        # Set program in agent before asking
        if hasattr(self._agent, 'set_program'):
            self._agent.set_program(program_slug)

        query = await self.open_prompt('for_employee.txt')
        question = query.format(employee_id=employee_id, program_slug=program_slug)
        try:
            response, _ = await self.ask_agent(query=question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response.employee_id = employee_id
        return await self._generate_report(response)

    async def _nextstop_manager(
        self,
        manager_id: str,
        employee_id: str,
        **kwargs
    ) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        program_slug = kwargs.get('program_slug', 'hisense')  # fallback to hisense
        query = await self.open_prompt('employee_comparison.txt')
        question = query.format(
            manager_id=manager_id,
            employee_id=employee_id,
            program_slug=program_slug
        )
        try:
            # Invoke the agent with the formatted question
            response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            ) from e
        response.manager_id = manager_id
        response.employee_id = manager_id
        return await self._generate_report(response)

    async def _team_performance(
        self,
        manager_id: str,
        project: str,
        **kwargs
    ) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        program_slug = kwargs.get('program_slug', 'hisense')  # fallback to hisense
        query = await self.open_prompt('team_performance.txt')
        question = query.format(
            manager_id=manager_id,
            project=project,
            program_slug=program_slug
        )
        try:
            response, _ = await self.ask_agent(question)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            ) from e
        response.manager_id = manager_id
        response.employee_id = manager_id
        return await self._generate_report(response)

    async def _query(self, query: str, **kwargs) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        try:
            response_data, response = await self.ask_agent(query)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        response_data.output = response.output.strip()
        return response_data
