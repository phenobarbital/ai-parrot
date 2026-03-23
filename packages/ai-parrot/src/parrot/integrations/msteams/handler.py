from typing import Any, Dict, Optional
from pathlib import Path
import mimetypes
from botbuilder.core import (
    CardFactory,
    MessageFactory,
    TurnContext
)
from botbuilder.schema import Attachment, Activity, ActivityTypes


class MessageHandler:
    """
    Interface for handling messages sent by Bot.

    Supports text, images, documents, and Adaptive Cards.
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

    async def send_card(
        self,
        card_data: Dict[str, Any],
        turn_context: TurnContext
    ) -> None:
        """
        Send an Adaptive Card to the user.

        Args:
            card_data: Adaptive Card JSON structure
            turn_context: The turn context for sending
        """
        attachment = CardFactory.adaptive_card(card_data)
        message = Activity(
            type=ActivityTypes.message,
            attachments=[attachment]
        )
        await turn_context.send_activity(message)

    async def send_document(
        self,
        file_path: Path,
        turn_context: TurnContext,
        filename: Optional[str] = None
    ) -> None:
        """
        Send a document as an attachment.

        Args:
            file_path: Path to the file to send
            turn_context: The turn context for sending
            filename: Optional display name for the file
        """
        if not file_path.exists():
            return

        name = filename or file_path.name
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or 'application/octet-stream'

        # For MS Teams, we typically need to upload to a location
        # and provide a URL, or use a content attachment
        # This is a simplified implementation using content URL
        # In production, you'd use OneDrive/SharePoint integration

        attachment = Attachment(
            content_type=mime_type,
            name=name
        )

        message = Activity(
            type=ActivityTypes.message,
            text=f"📎 Document: {name}",
            attachments=[attachment]
        )
        await turn_context.send_activity(message)

    async def send_file_attachment(
        self,
        file_path: Path,
        turn_context: TurnContext,
        caption: Optional[str] = None
    ) -> None:
        """
        Send a file attachment with optional caption.

        Args:
            file_path: Path to the file
            turn_context: The turn context for sending
            caption: Optional caption for the file
        """
        if not file_path.exists():
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or 'application/octet-stream'

        # Check if it's an image - can be sent inline
        if mime_type.startswith('image/'):
            # For local files, we'd need to upload and get a URL
            # This is a placeholder - in production, upload to blob storage
            attachment = Attachment(
                content_type=mime_type,
                name=file_path.name
            )
        else:
            attachment = Attachment(
                content_type=mime_type,
                name=file_path.name
            )

        text = caption or f"📎 {file_path.name}"
        message = Activity(
            type=ActivityTypes.message,
            text=text,
            attachments=[attachment]
        )
        await turn_context.send_activity(message)
