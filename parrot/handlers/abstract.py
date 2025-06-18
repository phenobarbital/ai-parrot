from pathlib import Path
from typing import Tuple, Union, List, Dict, Any, Optional, Callable
from abc import abstractmethod
from io import BytesIO
import tempfile
import aiofiles
# Parrot:
from aiohttp import web
# AsyncDB:
from asyncdb import AsyncDB
# Requirements from Notify API:
from notify import Notify  # para envio local
from notify.providers.teams import Teams
from notify.server import NotifyClient  # envio a traves de los workers
from notify.models import Actor, Chat, TeamsCard, TeamsChannel
from notify.conf import NOTIFY_REDIS, NOTIFY_WORKER_STREAM, NOTIFY_CHANNEL
# Navigator:
from navconfig import config
# Tasker:
from navigator.background import BackgroundQueue
# File Managers
from navigator.utils.file import (
    TempFileManager,
    GCSFileManager,
    S3FileManager
)
from navigator.applications.base import BaseApplication  # pylint: disable=E0611
from navigator.views import BaseView
from navigator.types import WebApp  # pylint: disable=E0611
from navigator.conf import CACHE_URL



class RedisWriter:
    """RedisWriter class."""
    def __init__(self):
        self.conn = AsyncDB('redis', dsn=CACHE_URL)

    @property
    def redis(self):
        """Get Redis Connection."""
        return self.conn


class AbstractAgentHandler(BaseView):
    """Abstract class for agent handlers.

    Provide a complete abstraction for exposing AI Agents as a REST API.
    """
    agent_name: str = None
    bot_manager: str = 'bot_manager'
    _startup_: Optional[Callable] = None
    _shutdown_: Optional[Callable] = None
    _init_: Optional[Callable] = None

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.redis = RedisWriter()
        self.gcs = None  # GCS Manager
        self.s3 = None  # S3 Manager

    def setup(self, app: Union[WebApp, web.Application], route: List[Dict[Any, str]]) -> None:
        """Setup the handler with the application and route.

        Args:
            app (Union[WebApp, web.Application]): The web application instance.
            route (List[Dict[Any, str]]): The route configuration.
        """
        if isinstance(app, BaseApplication):
            self.app = app.get_app()
        elif isinstance(app, WebApp):
            self.app = app  # register the app into the Extension
        else:
            raise TypeError(
                "Expected app to be an instance of BaseApplication."
            )
        # Tasker: Background Task Manager:
        BackgroundQueue(
            app=self.app,
            max_workers=5,
            queue_size=5,
            service_name=f"{self.app.app_name}_tasker"
        )
        ### startup and shutdown:
        self.app.on_startup.append(
            self.start_app
        )
        self.app.on_shutdown.append(
            self.stop_app
        )
        app.on_cleanup.append(
            self.cleanup
        )
        if self._startup_:
            self.app.on_startup.append(
                self._startup_
            )
        if self._shutdown_:
            self.app.on_shutdown.append(
                self._shutdown_
            )


    @abstractmethod
    async def start_app(self, app: Union[WebApp, web.Application]) -> None:
        """Start the application."""
        pass

    @abstractmethod
    async def stop_app(self, app: Union[WebApp, web.Application]) -> None:
        """Stop the application."""
        pass

    async def cleanup(self, app: WebApp):
        pass

    def get_agent(self, name: Optional[str] = None) -> Any:
        """Return the agent instance."""
        try:
            app = self.request.app
            manager = app[self.bot_manager]
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
        if agent := manager.get_agent(name):
            return agent
        else:
            raise RuntimeError(
                f"Agent {name} not found in Bot manager."
            )

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
