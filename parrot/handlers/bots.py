from asyncdb import AsyncDB
from navigator.views import (
    BaseHandler,
    ModelView,
    BaseView,
    FormModel
)
from navigator_auth.decorators import user_session
from parrot.conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
)
from .models import (
    BotModel,
    ChatbotUsage,
    PromptLibrary,
    ChatbotFeedback,
    FeedbackType
)
from ..tools.abstract import ToolRegistry


class PromptLibraryManagement(ModelView):
    """
    PromptLibraryManagement.
    description: PromptLibraryManagement for Parrot Application.
    """

    model = PromptLibrary
    name: str = "Prompt Library Management"
    path: str = '/api/v1/prompt_library'
    pk: str = 'prompt_id'

    async def _set_created_by(self, value, column, data):
        if not value:
            return await self.get_userid(session=self._session)
        return value


class ChatbotUsageHandler(ModelView):
    """
    ChatbotUsageHandler.
    description: ChatbotUsageHandler for Parrot Application.
    """

    model = ChatbotUsage
    driver: str = 'bigquery'
    name: str = "Chatbot Usage"
    path: str = '/api/v1/chatbots_usage'
    pk: str = 'sid'

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params,
            force_closing=False
        )

    async def post(self):
        # Try to use validator when available (as in FormModel); otherwise parse JSON.
        usage = None
        if hasattr(self, 'validate_payload'):
            usage = await self.validate_payload()
        if usage is None:
            try:
                payload = await self.request.json()
            except Exception:
                payload = None
            if not payload:
                return self.error(
                    response={
                        "message": "Error on Chatbot Usage payload"
                    },
                    status=400
                )
            try:
                usage = ChatbotUsage(**payload)
            except Exception as exc:
                return self.error(
                    response={
                        "message": f"Invalid Chatbot Usage payload: {exc}"
                    },
                    status=400
                )

        db = self.get_connection()
        try:
            async with await db.connection() as conn:  #pylint: disable=E1101
                data = usage.to_dict()
                # Normalize types for BigQuery
                if 'sid' in data:
                    data['sid'] = str(data['sid'])
                if 'chatbot_id' in data:
                    data['chatbot_id'] = str(data['chatbot_id'])
                if 'event_timestamp' in data:
                    data['event_timestamp'] = str(data['event_timestamp'])

                # Enrich from request context if missing
                if not data.get('origin'):
                    data['origin'] = getattr(self.request, 'remote', None)
                if not data.get('user_agent'):
                    data['user_agent'] = self.request.headers.get('User-Agent', '')
                if not data.get('user_id'):
                    try:
                        data['user_id'] = await self.get_userid(session=self._session)
                    except Exception:
                        pass

                # Ensure _at exists (sid:used_at)
                if not data.get('_at') and data.get('sid') and data.get('used_at'):
                    data['_at'] = f"{data['sid']}:{data['used_at']}"

                await conn.write(
                    [data],
                    table_id=ChatbotUsage.Meta.name,
                    dataset_id=ChatbotUsage.Meta.schema,
                    use_streams=False,
                    use_pandas=False
                )
                return self.json_response({
                    "message": "Chatbot Usage recorded.",
                    "question": data.get('question'),
                    "sid": data.get('sid')
                }, status=201)
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Chatbot Usage: {e}"
                },
                status=400
            )


class ChatbotSharingQuestion(BaseView):
    """
    ChatbotSharingQuestion.
    description: ChatbotSharingQuestion for Parrot Application.
    """

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params
        )

    async def get(self):
        qs = self.get_arguments(self.request)
        sid = qs.get('sid', None)
        if not sid:
            return self.error(
                response={
                    "message": "You need to Provided a ID of Question"
                },
                status=400
            )
        db = self.get_connection()
        try:
            async with await db.connection() as conn:  #pylint: disable=E1101
                ChatbotUsage.Meta.connection = conn
                # Getting a SID from sid
                question = await ChatbotUsage.get(sid=sid)
                if not question:
                    return self.error(
                        response={
                            "message": "Question not found"
                        },
                        status=404
                    )
                return self.json_response(
                    {
                        "chatbot": question.chatbot_id,
                        "question": question.question,
                        "answer": question.response,
                        "at": question.used_at
                    }
                )
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Chatbot Sharing Question: {e}"
                },
                status=400
            )



class FeedbackTypeHandler(BaseView):
    """
    FeedbackTypeHandler.
    description: FeedbackTypeHandler for Parrot Application.
    """

    async def get(self):
        qs = self.get_arguments(self.request)
        category = qs.get('feedback_type', 'good').capitalize()
        feedback_list = FeedbackType.list_feedback(category)
        return self.json_response({
            "feedback": feedback_list
        })

# Manage Feedback:
class ChatbotFeedbackHandler(FormModel):
    """
    ChatbotFeedbackHandler.
    description: ChatbotFeedbackHandler for Parrot Application.
    """
    model = ChatbotFeedback
    path: str = '/api/v1/bot_feedback'

    def get_connection(self):
        params = {
            "credentials": BIGQUERY_CREDENTIALS,
            "project_id": BIGQUERY_PROJECT_ID,
        }
        return AsyncDB(
            'bigquery',
            params=params,
            force_closing=False
        )

    async def post(self):
        feedback = await self.validate_payload()
        if not feedback:
            return self.error(
                response={
                    "message": "Error on Bot Feedback"
                },
                status=400
            )
        db = self.get_connection()
        try:
            async with await db.connection() as conn:  #pylint: disable=E1101
                data = feedback.to_dict()
                # convert to string (bigquery uses json.dumps to convert to string)
                data['sid'] = str(data['sid'])
                data['chatbot_id'] = str(data['chatbot_id'])
                data['expiration_timestamp'] = str(data['expiration_timestamp'])
                data['feedback_type'] = feedback.feedback_type.value
                # writing directly to bigquery
                await conn.write(
                    [data],
                    table_id=ChatbotFeedback.Meta.name,
                    dataset_id=ChatbotFeedback.Meta.schema,
                    use_streams=False,
                    use_pandas=False
                )
                return self.json_response({
                    "message": "Bot Feedback Submitted, Thank you for your feedback!.",
                    "question": f"Question of ID: {feedback.sid} for bot {feedback.chatbot_id}"
                }, status=201)
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Bot Feedback: {e}"
                },
                status=400
            )


class ChatbotHandler(ModelView):
    """
    ChatbotHandler.
    description: ChatbotHandler for Parrot Application.
    """

    model = BotModel
    name: str = "Chatbot Management"
    pk: str = 'chatbot_id'

    async def _set_created_by(self, value, column, data):
        return await self.get_userid(session=self._session)

    async def _put_callback(self, response, bot_model):
        if response.status == 201:
            # a New Bot was created:
            app = self.request.app
            manager = None
            try:
                manager = app['bot_manager']
            except KeyError:
                self.logger.error("No Bot Manager found on App")
            # add the new bot into the manager
            data = bot_model.to_dict()
            clsname = data.pop('bot_class', 'BasicBot')
            botclass = manager.get_bot_class(clsname)
            name = data.pop('name', 'NoName')
            try:
                bot = manager.create_bot(
                    class_name=botclass,
                    name=name,
                    **data
                )
            except Exception as e:
                self.logger.error(
                    f"Error creating bot instance of class {clsname}: {e}"
                )
                return
            if not bot:
                self.logger.error(f"Error creating bot instance of class {clsname}")
                return
            # configure the bot:
            try:
                await bot.configure(app)
            except Exception as e:
                self.logger.error(f"Error configuring bot {name}: {e}")
                return
            # add to manager
            manager.add_bot(bot)
            return True

@user_session()
class ToolList(BaseView):
    """
    ToolList.
    description: ToolList for Parrot Application.
    """
    async def get(self):
        registry = ToolRegistry()
        try:
            tools = registry.discover_tools()
            return self.json_response({
                "tools": tools
            })
        except Exception as e:
            return self.error(
                response={
                    "message": f"Error on Tool List: {e}"
                },
                status=400
            )
