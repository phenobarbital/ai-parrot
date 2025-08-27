import uuid
from aiohttp import web
from asyncdb.exceptions.exceptions import NoDataFound  # pylint: disable=E0611  # noqa
from datamodel.exceptions import ValidationError  # pylint: disable=E0611  # noqa
from navigator_auth.decorators import (
    is_authenticated,
    user_session,
    allowed_organizations
)
from navigator.views import BaseView
from ..bots.abstract import AbstractBot
from ..loaders import AVAILABLE_LOADERS
from .models import BotModel


@is_authenticated()
@user_session()
class ChatHandler(BaseView):
    """
    ChatHandler.
    description: Chat Handler for Parrot Application.
    """

    async def get(self, **kwargs):
        """
        get.
        description: Get method for ChatHandler.
        """
        name = self.request.match_info.get('chatbot_name', None)
        if not name:
            return self.json_response({
                "message": "Welcome to Parrot Chatbot Service."
            })
        else:
            # retrieve chatbof information:
            manager = self.request.app['bot_manager']
            chatbot = manager.get_bot(name)
            if not chatbot:
                return self.error(
                    f"Chatbot {name} not found.",
                    status=404
                )
            config_file = getattr(chatbot, 'config_file', None)
            return self.json_response({
                "chatbot": chatbot.name,
                "description": chatbot.description,
                "role": chatbot.role,
                "embedding_model": chatbot.embedding_model,
                "llm": f"{chatbot.llm!r}",
                "temperature": chatbot.llm.temperature,
                "config_file": config_file
            })

    async def post(self, *args, **kwargs):
        """
        post.
        description: Post method for ChatHandler.

        Use this method to interact with a Chatbot.
        """
        app = self.request.app
        name = self.request.match_info.get('chatbot_name', None)
        qs = self.query_parameters(self.request)
        data = await self.request.json()
        if not 'query' in data:
            return self.json_response(
                {
                "message": "No query was found."
                },
                status=400
            )
        if 'llm' in qs:
            # passing another LLM to the Chatbot:
            llm = data.pop('llm')
            model = data.pop('model', None)
        else:
            llm = None
            model = None
        try:
            manager = app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            chatbot: AbstractBot = manager.get_bot(name)
            if not chatbot:
                raise KeyError(
                    f"Chatbot {name} not found."
                )
        except (TypeError, KeyError):
            return self.json_response(
                {
                "message": f"Chatbot {name} not found."
                },
                status=404
            )
        # getting the question:
        question = data.pop('query')
        search_type = data.pop('search_type', 'similarity')
        return_sources = data.pop('return_sources', True)
        try:
            session = self.request.session
        except AttributeError:
            session = None
        if not session:
            return self.json_response(
                {
                "message": "User Session is required to interact with a Chatbot."
                },
                status=400
            )
        try:
            async with chatbot.retrieval(self.request) as bot:
                session_id = session.get('session_id', None)
                user_id = session.get('user_id', None)
                if not session_id:
                    session_id = str(uuid.uuid4())
                result = await bot.conversation(
                    question=question,
                    session_id=session_id,
                    user_id=user_id,
                    search_type=search_type,
                    llm=llm,
                    model=model,
                    return_sources=return_sources,
                    **data
                )
                return self.json_response(
                    response=result.model_dump()
                )
        except ValueError as exc:
            return self.error(
                f"{exc}",
                exception=exc,
                status=400
            )
        except web.HTTPException as exc:
            return self.error(
                f"{exc}",
                exception=exc,
                status=400
            )
        except Exception as exc:
            return self.error(
                f"Error invoking chatbot {name}: {exc}",
                exception=exc,
                status=400
            )


@is_authenticated()
@user_session()
class BotHandler(BaseView):
    """BotHandler.
    description: Bot Handler for Parrot Application.
    Use this handler to interact with a brand new chatbot, consuming a configuration.
    """
    async def _create_bot(self, name: str, data: dict):
        """Create a New Bot (passing a configuration).
        """
        db = self.request.app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            # check first if chatbot already exists:
            exists = None
            try:
                exists = await BotModel.get(name=name)
            except NoDataFound:
                exists = False
            if exists:
                return self.json_response(
                    {
                        "message": f"Chatbot {name} already exists with id {exists.chatbot_id}"
                    },
                    status=202
                )
            try:
                chatbot_model = BotModel(
                    name=name,
                    **data
                )
                print('Chatbot Model: ', chatbot_model)
                chatbot_model = await chatbot_model.insert()
                return chatbot_model
            except ValidationError:
                raise
            except Exception:
                raise

    async def put(self):
        """Create a New Bot (passing a configuration).
        """
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        # TODO: Making a Validation of data
        data = await self.request.json()
        name = data.pop('name', None)
        if not name:
            return self.json_response(
                {
                "message": "Name for Bot Creation is required."
                },
                status=400
            )
        try:
            bot = manager.create_bot(name=name, **data)
        except Exception as exc:
            print(exc.__traceback__)
            return self.error(
                response={
                    "message": f"Error creating chatbot {name}.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        try:
            # if bot is created:
            await self._create_bot(name=name, data=data)
        except ValidationError as exc:
            return self.error(
                f"Validation Error for {name}: {exc}",
                exception=exc.payload,
                status=400
            )
        except Exception as exc:
            print(exc.__traceback__)
            return self.error(
                response={
                    "message": f"Error creating chatbot {name}.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        try:
            # Then Configure the bot:
            await bot.configure(app=self.request.app)
            return self.json_response(
                {
                    "message": f"Chatbot {name} created successfully."
                }
            )
        except Exception as exc:
            return self.error(
                f"Error on chatbot configuration: {name}: {exc}",
                exception=exc,
                status=400
            )


@is_authenticated()
@user_session()
class BotManagement(BaseView):
    """BotManagement.
    description: Bot Management Handler for Parrot Application.
    Use this handler to list all available chatbots, upload files, and delete chatbots.
    """
    async def get(self):
        """List all available chatbots.
        """
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            all_bots = manager.get_bots()
            bots = []
            for bot_name, bot in all_bots.items():
                bots.append({
                    "name": bot_name,
                    "bot_id": bot.chatbot_id,
                    "bot_class": str(bot.__class__.__name__),
                    "description": bot.description,
                    "backstory": bot.backstory,
                    "role": bot.role,
                    "embedding_model": bot.embedding_model,
                    "llm": f"{bot.llm!r}",
                    "temperature": bot.llm.temperature,
                    "documents": bot.get_vector_store()
                })
        except Exception as exc:
            return self.error(
                response={
                    "message": f"Error retrieving chatbots.",
                    "exception": str(exc),
                    "stacktrace": str(exc.__traceback__)
                },
                exception=exc,
                status=400
            )
        return self.json_response(
            {
                "bots": bots
            }
        )

    async def put(self):
        """Upload a file to a chatbot.
        """
        attachments, form_data = await self.handle_upload()
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        qs = self.query_parameters(self.request)
        chatbot_name = qs.get('chatbot', None)
        if not chatbot_name:
            return self.json_response(
                {
                    "message": "Chatbot name is required."
                },
                status=400
            )
        try:
            manager = self.request.app['bot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            chatbot: AbstractBot = manager.get_bot(chatbot_name)
            if not chatbot:
                raise KeyError(
                    f"Chatbot {chatbot_name} not found."
                )
        except (TypeError, KeyError):
            return self.json_response(
                {
                "message": f"Chatbot {chatbot_name} not found."
                },
                status=404
            )
        # get the file extension:
        ext = filename.split('.')[-1].lower()
        if ext not in AVAILABLE_LOADERS:
            return self.json_response(
                {
                    "message": f"File extension {ext} is not supported."
                },
                status=400
            )
        # Create a temp file to store the uploaded file:
        import tempfile
        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            # write the file to the temp file:
            while True:
                chunk = await field.read_chunk()
