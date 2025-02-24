from asyncdb import AsyncDB
from navigator.views import (
    ModelView,
    BaseView,
    FormModel
)
from parrot.conf import (
    BIGQUERY_CREDENTIALS,
    BIGQUERY_PROJECT_ID,
)
from ..models import (
    ChatbotModel,
    ChatbotUsage,
    PromptLibrary,
    ChatbotFeedback,
    FeedbackType
)


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
    credentials: dict = {
        "credentials": BIGQUERY_CREDENTIALS,
        "project_id": BIGQUERY_PROJECT_ID,
    }
    name: str = "Chatbot Usage"
    path: str = '/api/v1/chatbots/usage'
    pk: str = 'sid'


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

    model = ChatbotModel
    name: str = "Chatbot Management"
    pk: str = 'chatbot_id'


    async def _set_created_by(self, value, column, data):
        return await self.get_userid(session=self._session)
