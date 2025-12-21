from botbuilder.core import (
    CardFactory, MessageFactory, TurnContext
)
from botbuilder.schema import Attachment, Activity, ActivityTypes


class MessageHandler:
    """
    Interface for handling messages sent by Bot.
    """
    async def send_image(
        self,
        url: str,
        turn_context: TurnContext,
        mimetype: str = 'image/png',
    ):
        """
        Send an image to the user.
        """
        attachment = Attachment(content_type=mimetype, content_url=url)
        message = Activity(
            type=ActivityTypes.message,
            attachments=[attachment]
        )
        await turn_context.send_activity(message)

    async def send_text(self, text: str, turn_context: TurnContext):
        """
        Send a text message to the user.
        """
        await turn_context.send_activity(
            MessageFactory.text(text)
        )

    def text_message(self, message_data: str) -> MessageFactory:
        return MessageFactory.text(
            message_data
        )

    async def send_message(self, message: Activity, turn_context: TurnContext):
        """
        Send a message to the user.
        """
        await turn_context.send_activity(message)

    def get_card(self, card_data: str) -> CardFactory:
        return CardFactory.adaptive_card(card_data)

    def create_card(self, card_data) -> Attachment:
        return CardFactory.adaptive_card(card_data)
