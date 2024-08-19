from navigator_auth.decorators import (
    is_authenticated,
    user_session
)
from navigator.views import BaseView


@is_authenticated()
@user_session()
class ChatHandler(BaseView):
    """
    ChatHandler.
    description: ChatHandler for Parrot Application.
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
            manager = self.request.app['chatbot_manager']
            chatbot = manager.get_chatbot(name)
            if not chatbot:
                return self.error(
                    f"Chatbot {name} not found.",
                    status=404
                )
            return self.json_response({
                "chatbot": chatbot.name,
                "description": chatbot.description,
                "role": chatbot.role,
                "embedding_model_name": chatbot.embedding_model_name,
                "llm": f"{chatbot.get_llm()!r}",
                "temperature": chatbot.get_llm().temperature,
                "args": chatbot.get_llm().args,
                "config_file": chatbot.config_file
            })

    async def post(self, *args, **kwargs):
        """
        post.
        description: Post method for ChatHandler.
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
            manager = app['chatbot_manager']
        except KeyError:
            return self.json_response(
                {
                "message": "Chatbot Manager is not installed."
                },
                status=404
            )
        try:
            chatbot = manager.get_chatbot(name)
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
        question = data.get('query')
        session = self.request.session
        try:
            session_id = session.get('session_id', None)
            memory_key = f'{session.session_id}_{name}_message_store'
            memory = chatbot.get_memory(session_id=memory_key)
            with chatbot.get_retrieval(request=self.request) as retrieval:
                result = await retrieval.question(
                    question=question,
                    memory=memory
                )
                # Drop "memory" information:
                result.chat_history = None
                result.source_documents = None
            return self.json_response(response=result)
        except ValueError as exc:
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


    Use this handler to interact with a brand new chatbot, consuming a configuration.
    """
    async def put(self):
        """Create a New Bot (passing a configuration).
        """
        try:
            manager = self.request.app['chatbot_manager']
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
            chatbot = manager.create_chatbot(name=name, **data)
            await chatbot.configure(name=name, app=self.request.app)
            return self.json_response(
                {
                    "message": f"Chatbot {name} created successfully."
                }
            )
        except Exception as exc:
            return self.error(
                f"Error creating chatbot {name}: {exc}",
                exception=exc,
                status=400
            )
