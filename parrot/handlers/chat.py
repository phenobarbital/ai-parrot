from aiohttp import web
from asyncdb.exceptions.exceptions import NoDataFound
from datamodel.exceptions import ValidationError
from navigator_auth.decorators import (
    is_authenticated,
    user_session,
    allowed_organizations
)
from navigator.views import BaseView
from ..bots.abstract import AbstractBot
from ..models import ChatbotModel


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
        if 'use_llm' in qs:
            # passing another LLM to the Chatbot:
            llm = qs.get('use_llm')
        else:
            llm = None
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
            async with chatbot.retrieval(request=self.request) as retrieval:
                session_id = session.get('session_id', None)
                memory_key = f'{session.session_id}_{name}_message_store'
                memory = retrieval.get_memory(session_id=memory_key)
                result = await retrieval.invoke(
                    question=question,
                    llm=llm,
                    memory=memory,
                    **data
                )
                # Drop "memory" information:
                result.chat_history = None
                if result.source_documents:
                    documents = []
                    for doc in result.source_documents:
                        dc = {
                            **doc.metadata
                        }
                        documents.append(dc)
                    result.source_documents = documents
                return self.json_response(response=result)
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
            ChatbotModel.Meta.connection = conn
            # check first if chatbot already exists:
            exists = None
            try:
                exists = await ChatbotModel.get(name=name)
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
                chatbot_model = ChatbotModel(
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
