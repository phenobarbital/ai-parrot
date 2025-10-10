from datetime import datetime
from pathlib import Path
from typing import Tuple, Union, List, Dict, Any, Optional, Callable, Sequence, Awaitable
import functools
from io import BytesIO
import tempfile
import aiofiles
# Parrot:
from aiohttp import web
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611
# AsyncDB:
from asyncdb import AsyncDB
# Requirements from Notify API:
from notify import Notify  # para envio local
from notify.providers.teams import Teams
from notify.server import NotifyClient  # envio a traves de los workers
from notify.models import Actor, Chat, TeamsCard, TeamsChannel
from notify.conf import NOTIFY_REDIS, NOTIFY_WORKER_STREAM, NOTIFY_CHANNEL
# Navigator:
from navconfig import config, BASE_DIR
from navconfig.logging import logging
from navigator_session import get_session
# Auth
from navigator_auth.decorators import (
    is_authenticated,
)
from navigator_auth.conf import AUTH_SESSION_OBJECT
# Tasker:
from navigator.background import (
    BackgroundService,
    TaskWrapper,
    JobRecord
)
from navigator.services.ws import WebSocketManager
from navigator.applications.base import BaseApplication  # pylint: disable=E0611
from navigator.views import BaseView
from navigator.responses import JSONResponse
from navigator.types import WebApp  # pylint: disable=E0611
from navigator.conf import CACHE_URL, default_dsn
# Parrot:
from ...bots.agent import BasicAgent
from ...tools.abstract import AbstractTool
from ...models.responses import AgentResponse, AIMessage
from ...clients.gpt import OpenAIClient
from ...clients.claude import ClaudeClient
from ...conf import STATIC_DIR, AGENTS_BOTS_PROMPT_DIR, AGENTS_DIR


class RedisWriter:
    """RedisWriter class."""
    def __init__(self):
        self.conn = AsyncDB('redis', dsn=CACHE_URL)

    @property
    def redis(self):
        """Get Redis Connection."""
        return self.conn


class JobWSManager(WebSocketManager):
    """
    Extends the generic WebSocketManager with one helper that sends
    a direct message to the user owning a finished job.
    """
    async def notify_job_done(
        self,
        *,
        user_id: int | str,
        job_id: str,
        status: str,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Push a JSON message to every open WS belonging to `user_id`.
        """
        payload = {
            "type":   "job_status",
            "job_id": job_id,
            "status": status,        # "done" / "failed"
            "result": result,
            "error":  error,
        }
        message = json_encoder(payload)
        delivered = 0
        for ws, info in list(self.clients.items()):
            if ws.closed:
                continue
            if info.get("user_id") == str(user_id):
                await ws.send_str(message)
                delivered += 1

        if delivered == 0:
            self.logger.debug(
                "No active WS for user_id=%s when job %s finished", user_id, job_id
            )

def auth_groups(
    allowed: Sequence[str]
) -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]:
    """Ensure the request is authenticated *and* the user belongs
    to at least one of `allowed` groups.
    """
    def decorator(fn: Union[Any, Any]) -> Any:
        # 1️⃣ first wrap the target function with the base auth check
        fn = AgentHandler.service_auth(fn)
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            # At this point `service_auth` has already:
            #   * verified the session
            #   * populated `self._session` and `self._superuser`
            if self._superuser:
                # If the user is a superuser, skip group checks
                return await fn(self, *args, **kwargs)
            # Now add the group check
            user_groups = set(self._session.get("groups", []))
            if not user_groups.intersection(allowed):
                self.error(
                    response={
                        "error": "Forbidden",
                        "message": f"User lacks required group(s): {allowed}"
                    },
                    status=403
                )
            return await fn(self, *args, **kwargs)
        return wrapper
    return decorator

def auth_by_attribute(
    allowed: Sequence[str],
    attribute: str = 'job_code'
) -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]:
    """Ensure the request is authenticated *and* the user belongs
    to at least one of `allowed` Job Codes.
    """
    def decorator(fn: Union[Any, Any]) -> Any:
        # 1️⃣ first wrap the target function with the base auth check
        fn = AgentHandler.service_auth(fn)
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            # At this point `service_auth` has already:
            #   * verified the session
            #   * populated `self._session` and `self._superuser`
            if self._superuser:
                # If the user is a superuser, skip job code checks
                return await fn(self, *args, **kwargs)
            # Now add the jobcode check
            userinfo = self._session.get(AUTH_SESSION_OBJECT, {})
            attr = userinfo.get(attribute, None)
            if not attr:
                self.error(
                    response={
                        "error": "Forbidden",
                        "message": f"User does not have a valid {attribute}."
                    },
                    status=403
                )
            if not attr in allowed:
                self.error(
                    response={
                        "error": "Forbidden",
                        "message": f"User lacks required attribute(s) ({attribute})."
                    },
                    status=403
                )
            return await fn(self, *args, **kwargs)
        return wrapper
    return decorator


@is_authenticated()
class AgentHandler(BaseView):
    """Abstract class for chatbot/agent handlers.

    Provide a complete abstraction for exposing AI Agents as a REST API.
    """
    app: web.Application = None
    agent_name: str = "NextStop"
    agent_id: str = "nextstop"
    _tools: List[AbstractTool] = []
    _agent: BasicAgent = None
    _use_llm: str = 'google'
    _use_model: str = 'gemini-2.5-pro'
    # signals
    on_startup: Optional[Callable] = None
    on_shutdown: Optional[Callable] = None
    on_cleanup: Optional[Callable] = None

    # Define base routes - can be overridden in subclasses
    base_route: str = None  # e.g., "/api/v1/agent/{agent_name}"
    additional_routes: List[Dict[str, Any]] = []  # Custom routes
    _agent_class: type = BasicAgent  # Default agent class
    _agent_response: type = AgentResponse  # Default response type

    def __init__(
        self,
        request: web.Request = None,
        *args,
        app: web.Application = None,
        **kwargs
    ):
        if request is not None:
            super().__init__(request, *args, **kwargs)
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
        self.redis = RedisWriter()
        self.gcs = None  # GCS Manager
        self.s3 = None  # S3 Manager
        # Session and User ID
        self._session: Optional[Dict[str, Any]] = None
        self._userid: Optional[str] = None
        # Temporal Agent Uploader
        self.temp_dir = self.create_temp_directory()
        self.app = app
        self._program: str = kwargs.pop('program_slug', 'parrot')  # Default program slug

    def set_program(self, program_slug: str) -> None:
        """Set the program slug for the agent."""
        self._program = program_slug

    def setup(
        self,
        app: Union[WebApp, web.Application],
        route: List[Dict[Any, str]] = None
    ) -> None:
        """Setup the handler with the application and route.

        Args:
            app (Union[WebApp, web.Application]): The web application instance.
            route (List[Dict[Any, str]]): The route configuration.
        """
        if isinstance(app, BaseApplication):
            app = app.get_app()
        elif isinstance(app, WebApp):
            app = app  # register the app into the Extension
        else:
            raise TypeError(
                "Expected app to be an instance of BaseApplication."
            )
        self.app = app
        # Register the main view class route
        if route:
            self.app.router.add_view(route, self.__class__)
        elif self.base_route:
            self.app.router.add_view(self.base_route, self.__class__)

        # And register any additional custom routes
        self._register_additional_routes()

        # Tasker: Background Task Manager (if not already registered):
        if 'background_service' not in app:
            BackgroundService(
                app=self.app,
                max_workers=10,
                queue_size=10,
                tracker_type='redis',  # Use 'redis' for Redis-based tracking
                service_name=f"{self.agent_name}_tasker"
            )
        # Tool definition:
        self.define_tools()

        # Startup and shutdown callbacks
        app.on_startup.append(self.create_agent)
        # Register Signals:
        if callable(self.on_startup):
            app.on_startup.append(self.on_startup)
        if callable(self.on_shutdown):
            app.on_shutdown.append(self.on_shutdown)
        if callable(self.on_cleanup):
            app.on_cleanup.append(self.on_cleanup)

    async def create_agent(self, app: web.Application):
        self.logger.info("Starting up agent handler...")
        # Initialize the agent
        await self._create_agent(app)

    def define_tools(self):
        """Define additional tools for the agent."""
        pass

    def db_connection(
        self,
        driver: str = 'pg',
        dsn: str = None,
        credentials: dict = None
    ) -> AsyncDB:
        """Return a database connection."""
        if not dsn:
            dsn = config.get(f'{driver.upper()}_DSN', fallback=default_dsn)
        if not dsn and credentials:
            dsn = credentials.get('dsn', default_dsn)
        if not dsn:
            raise ValueError(
                f"DSN for {driver} is not provided."
            )
        return AsyncDB(driver, dsn=dsn, credentials=credentials)

    async def register_background_task(
        self,
        task: Callable[..., Awaitable],
        request: web.Request = None,
        done_callback: Optional[Callable[..., Awaitable]] = None,
        *args,
        **kwargs
    ) -> JobRecord:
        """Register a background task with the BackgroundService.
        Add an optional task wrapper to handle the task execution.
        Args:
            task (Callable[..., Awaitable]): The task to be executed.
            request (web.Request, optional): The request object. Defaults to None.
            done_callback (Optional[Callable[..., Awaitable]], optional):
                A callback to be called when the task is done. Defaults to None.
            *args: Positional arguments to pass to the task.
            **kwargs: Keyword arguments to pass to the task.
        Returns:
            JobRecord: The job record containing the task ID and other details.
        Raises:
            RuntimeError: If the request is not available.
        """
        if not request:
            request = self.request
        if not request:
            raise RuntimeError("Request is not available.")
        # Get the BackgroundService instance
        service: BackgroundService = request.app['background_service']
        # Create a TaskWrapper instance
        task = TaskWrapper(
            *args,
            fn=task,
            logger=self.logger,
            **kwargs
        )
        task.add_callback(done_callback)
        # Register the task with the service
        job = await service.submit(task)
        self.logger.notice(
            f"Registered background task: {task!r} with ID: {job.task_id}"
        )
        return job

    async def find_jobs(self, request: web.Request) -> web.Response:
        """Return Jobs by User."""
        # Get the BackgroundService instance
        service: BackgroundService = request.app['background_service']
        # get service tracker:
        tracker = service.tracker
        session = await self.get_user_session()
        userid = self.get_userid(session=session)
        if not userid:
            return JSONResponse(
                content=None,
                headers={"x-message": "User ID not found in session."},
                status=401
            )
        search = {
            'user_id': userid,
            'agent_name': self.agent_name,
        }
        result = await tracker.find_jobs(
            attrs=search
        )
        if not result:
            return JSONResponse(
                content=None,
                headers={"x-message": "No jobs found for this user."},
                status=204
            )
        return JSONResponse(result)

    def _register_additional_routes(self):
        """Register additional custom routes defined in the class."""
        for route_config in self.additional_routes:
            method = route_config.get('method', 'GET').upper()
            path = route_config['path']
            handler_name = route_config['handler']

            # Get the handler method from the class
            handler_method = getattr(self.__class__, handler_name)

            # Create a wrapper that instantiates the class and calls the method
            async def route_wrapper(request, handler_method=handler_method):
                instance = self.__class__(request)
                return await handler_method(instance, request)

            # Add the route to the router
            self.app.router.add_route(method, path, route_wrapper)

    async def get_task_status(self, task_id: str, request: web.Request = None) -> JSONResponse:
        """Get the status of a background task by its ID."""
        req = request or self.request
        if not req:
            raise RuntimeError("Request is not available.")
        service: BackgroundService = req.app['background_service']
        try:
            job = await service.record(task_id)
            if job:
                return JSONResponse(
                    {
                        "task_id": job.task_id,
                        "status": job.status,
                        "result": job.result,
                        "created_at": job.created_at,
                        "started_at": job.started_at,
                        "error": job.error,
                        "stacktrace": job.stacktrace,
                        "attributes": job.attributes,
                        "finished_at": job.finished_at,
                        "name": job.name,
                        # "job": job
                    }
                )
            else:
                return JSONResponse(
                    {"message": "Task not found"},
                    status=404
                )
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status=500
            )

    def add_route(self, method: str, path: str, handler: str):
        """Instance method to add custom routes."""
        if not hasattr(self, 'additional_routes'):
            self.additional_routes = []
        self.additional_routes.append({
            'method': method,
            'path': path,
            'handler': handler
        })

    def create_temp_directory(self, name: str = 'documents'):
        """Create the temporary directory for saving Agent Documents."""
        tmp_dir = tempfile.TemporaryDirectory()
        # Create the "documents" subdirectory inside the temporary directory
        p_dir = Path(tmp_dir.name).joinpath(self.agent_name, name)
        p_dir.mkdir(parents=True, exist_ok=True)
        return p_dir

    async def get_user_session(self):
        """Return the user session from the request."""
        # TODO: Add ABAC Support.
        if not self.request:
            raise RuntimeError("Request is not available.")
        try:
            session = self.request.session
        except AttributeError:
            session = await get_session(self.request)
        if not session:
            self.error(
                response={'message': 'Session not found'},
                status=401
            )
        if not session:
            self.error(
                response={
                    "error": "Unauthorized",
                    "message": "Hint: maybe need to login and pass Authorization token."
                },
                status=403
            )
        return session

    def get_userid(
        self,
        session: Optional[Dict[str, Any]] = None,
        idx: str = 'user_id'
    ) -> Optional[str]:
        """Return the user ID from the session."""
        if not session:
            session = self._session
        if not session:
            return None
        if AUTH_SESSION_OBJECT in session:
            return session[AUTH_SESSION_OBJECT][idx]
        return session.get(idx, None)

    @staticmethod
    def service_auth(fn: Union[Any, Any]) -> Any:
        """Decorator to ensure the service is authenticated."""
        async def wrapper(self, *args, **kwargs):
            session = await self.get_user_session()
            if not session:
                self.error(
                    response={
                        "error": "Unauthorized",
                        "message": "Hint: maybe need to login and pass Authorization token."
                    },
                    status=403
                )
            # define in-request variables for session and userid
            self._userid = self.get_userid(session)
            self._session = session
            # extract other user information as groups, programs and username:
            userinfo = session.get(AUTH_SESSION_OBJECT, {})
            self._session['email'] = userinfo.get('email', None)
            self._session['username'] = userinfo.get('username', None)
            self._session['programs'] = userinfo.get('programs', [])
            self._session['groups'] = userinfo.get('groups', [])
            self._superuser = userinfo.get('superuser', False)
            self._session['is_superuser'] = self._superuser
            # Set the session in the request for further use
            ## Calling post-authorization Model:
            await self._post_auth(self, *args, **kwargs)
            return await fn(self, *args, **kwargs)
        return wrapper

    async def _post_auth(self, *args, **kwargs):
        """Post-authorization Model."""
        return True

    def get_agent(self) -> Any:
        """Return the agent instance."""
        return self._agent

    def _create_actors(self, recipients: Union[List[dict], dict] = None) -> List:
        if isinstance(recipients, dict):
                recipients = [recipients]
        if not recipients:
            return self.error(
                {'message': 'Recipients are required'},
                status=400
            )
        rcpts = []
        for recipient in recipients:
            name = recipient.get('name', 'Navigator')
            email = recipient.get('address')
            if not email:
                return self.error(
                    {'message': 'Address is required'},
                    status=400
                )
            rcpt = Actor(**{
                "name": name,
                "account": {
                    "address": email
                }
            })
            rcpts.append(rcpt)
        return rcpts

    async def send_notification(
        self,
        content: str,
        provider: str = 'telegram',
        recipients: Union[List[dict], dict] = None,
        **kwargs
    ) -> Any:
        """Return the notification provider instance."""
        provider = kwargs.get('provider', provider).lower()
        response = []
        if provider == 'telegram':
            sender = Notify(provider)
            chat_id = kwargs.get('chat_id', config.get('TELEGRAM_CHAT_ID'))
            chat = Chat(
                chat_id=chat_id
            )
            async with sender as message:  # pylint: disable=E1701 # noqa: E501
                result = await message.send(
                    recipient=chat,
                    **kwargs
                )
                for r in result:
                    res = {
                        "provider": provider,
                        "message_id": r.message_id,
                        "title": r.chat.title,
                    }
                    response.append(res)
        elif provider == 'email':
            rcpts = self._create_actors(recipients)
            credentials = {
                "hostname": config.get('smtp_host'),
                "port": config.get('smtp_port'),
                "username": config.get('smtp_host_user'),
                "password": config.get('smtp_host_password')
            }
            sender = Notify(provider, **credentials)
            async with sender as message:  # pylint: disable=E1701 # noqa: E501
                result = await message.send(
                    recipient=rcpts,
                    **kwargs,
                    **credentials
                )
                for r in result:
                    res = {
                        "provider": provider,
                        "status": r[1],
                    }
                    response.append(res)
        elif provider == 'teams':
            # Support for private messages:
            sender = Teams(as_user=True)
            if recipients:
                rcpts = self._create_actors(recipients)
            else:
                # by Teams Channel
                default_teams_id = config.get('MS_TEAMS_DEFAULT_TEAMS_ID')
                default_chat_id = config.get('MS_TEAMS_DEFAULT_CHANNEL_ID')
                teams_id = kwargs.pop('teams_id', default_teams_id)
                chat_id = kwargs.pop('chat_id', default_chat_id)
                rcpts = TeamsChannel(
                    name="General",
                    team_id=teams_id,
                    channel_id=chat_id
                )
            card = TeamsCard(
                title=kwargs.get('title'),
                summary=kwargs.get('summary'),
                text=kwargs.get('message'),
                sections=kwargs.get('sections', [])
            )
            async with sender as message:  # pylint: disable=E1701 # noqa: E501
                result = await message.send(
                    recipient=rcpts,
                    message=card
                )
                for r in result:
                    res = {
                        "message_id": r['id'],
                        "webUrl": r['webUrl']
                    }
                    response.append(res)
        elif provider == 'ses':
            credentials = {
                "aws_access_key_id": config.get('AWS_ACCESS_KEY_ID'),
                "aws_secret_access_key": config.get('AWS_SECRET_ACCESS_KEY'),
                "aws_region_name": config.get('AWS_REGION_NAME'),
                "sender_email": config.get('SENDER_EMAIL')
            }
            message = {
                "provider": "ses",
                "message": content,
                "template": 'email_applied.html',
                **credentials,
            }
            async with NotifyClient(
                redis_url=NOTIFY_REDIS
            ) as client:
                # Stream but using Wrapper:
                await client.stream(
                    message,
                    stream=NOTIFY_WORKER_STREAM,
                    use_wrapper=True
                )
        elif provider == 'mail':
            rcpts = self._create_actors(recipients)
            name = kwargs.pop('name', 'Navigator')
            email = kwargs.pop('address')
            message = {
                "provider": 'email',
                "recipient": {
                    "name": name,
                    "account": {
                        "address": email
                    }
                },
                "message": 'Congratulations!',
                "template": 'email_applied.html'
                **kwargs
            }
            async with NotifyClient(
                redis_url=NOTIFY_REDIS
            ) as client:
                for recipient in rcpts:
                    message['recipient'] = [recipient]
                    await client.publish(
                        message,
                        channel=NOTIFY_CHANNEL,
                        use_wrapper=True
                    )
                response = "Message sent"
        else:
            payload = {
                "provider": provider,
                **kwargs
            }
            # Create a NotifyClient instance
            async with NotifyClient(redis_url=NOTIFY_REDIS) as client:
                for recipient in recipients:
                    payload['recipient'] = [recipient]
                    # Stream but using Wrapper:
                    await client.stream(
                        payload,
                        stream=NOTIFY_WORKER_STREAM,
                        use_wrapper=True
                    )
        return response

    async def _handle_uploads(
        self,
        key: str,
        ext: str = '.csv',
        mime_type: str = 'text/csv',
        preserve_filenames: bool = True,
        as_bytes: bool = False
    ) -> Tuple[List[dict], dict]:
        """handle file uploads."""
        # Check if Content-Type is correctly set
        content_type = self.request.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            raise web.HTTPUnsupportedMediaType(
                text='Invalid Content-Type. Use multipart/form-data',
                content_type='application/json'
            )
        form_data = {}  # return any other form data, if exists.
        uploaded_files_info = []
        try:
            reader = await self.request.multipart()
        except KeyError:
            raise FileNotFoundError(
                "No files found in the request. Please upload a file."
            )
        # Process each part of the multipart request
        async for part in reader:
            if part.filename:
                if key and part.name != key:
                    continue
                # Create a temporary file for each uploaded file
                file_ext = Path(part.filename).suffix or ext
                if preserve_filenames:
                    # Use the original filename and save in the temp directory
                    temp_file_path = Path(tempfile.gettempdir()) / part.filename
                else:
                    with tempfile.NamedTemporaryFile(
                        delete=False,
                        dir=tempfile.gettempdir(),
                        suffix=file_ext
                    ) as temp_file:
                        temp_file_path = Path(temp_file.name)
                # save as a byte stream if required
                file_content = None
                if as_bytes:
                    # Read the file content as bytes
                    file_content = BytesIO()
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        file_content.write(chunk)
                    # Write the bytes to the temp file
                    async with aiofiles.open(temp_file_path, 'wb') as f:
                        await f.write(file_content.getvalue())
                else:
                    # Write the file content
                    with temp_file_path.open("wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                # Get Content-Type header
                mime_type = part.headers.get('Content-Type', mime_type)
                # Store file information
                file_info = {
                    'filename': part.filename,
                    'path': str(temp_file_path),
                    'content_type': mime_type,
                    'size': temp_file_path.stat().st_size
                }
                if file_content is not None:
                    file_info['content'] = file_content
                uploaded_files_info.append(file_info)
            else:
                # If it's a form field, add it to the dictionary
                form_field_name = part.name
                form_field_value = await part.text()
                form_data[form_field_name] = form_field_value
        # Check if any files were uploaded
        if not uploaded_files_info:
            raise FileNotFoundError(
                "No files found in the request. Please upload a file."
            )
        # Return the list of uploaded files and any other form data
        return uploaded_files_info, form_data

    async def _create_agent(
        self,
        app: web.Application
    ) -> BasicAgent:
        """Create and configure a BasicAgent instance."""
        try:
            print('AGENTE > ', self._use_llm, self._use_model)
            agent = self._agent_class(
                name=self.agent_name,
                tools=self._tools,
                llm=self._use_llm,
                model=self._use_model
            )
            print('AGENTE 2 > ', agent)
            agent.set_response(self._agent_response)
            await agent.configure()
            # define the main agent:
            self._agent = agent
            # Store the agent in the application context
            app[self.agent_id] = agent
            self.logger.info(
                f"Agent {self.agent_name} created and configured successfully."
            )
            return agent
        except Exception as e:
            raise RuntimeError(
                f"Failed to create agent {self.agent_name}: {str(e)}"
            ) from e

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
            raise RuntimeError(
                f"Failed to read prompt file {prompt_file}: {e}"
            ) from e

    async def ask_agent(
        self,
        query: str = None,
        prompt_file: str = None,
        *args,
        **kwargs
    ) -> Tuple[AgentResponse, AIMessage]:
        """
        Asks the agent a question and returns the response.
        """
        if not self._agent:
            agent = self.request.app[self.agent_id]
        else:
            agent = self._agent
        if not agent:
            raise RuntimeError(
                f"Agent {self.agent_name} is not initialized or not found."
            )
        userid = self._userid if self._userid else self.request.session.get('user_id', None)
        if not userid:
            raise RuntimeError(
                "User ID is not set in the session."
            )
        if not agent:
            raise RuntimeError(
                f"Agent {self.agent_name} is not initialized or not found."
            )
        # query:
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
            response = await agent.conversation(
                question=query,
                max_tokens=8192
            )
            if isinstance(response, Exception):
                raise response
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )

        # Create the response object
        final_report = response.output.strip()
        # when final report is made, then generate the transcript, pdf and podcast:
        response_data = self._agent_response(
            user_id=str(userid),
            agent_name=self.agent_name,
            attributes=kwargs.pop('attributes', {}),
            data=final_report,
            status="success",
            created_at=datetime.now(),
            output=response.output,
            **kwargs
        )
        return response_data, response
