"""
NotificationTool - Send notifications via email, Telegram, Slack, or MS Teams.

A unified tool for LLM agents to send notifications through various channels
using the async-notify library.
"""
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from enum import Enum
import mimetypes
from pydantic import BaseModel, Field
from notify.models import Actor, Channel, Chat
from notify.providers.email import Email
from notify.providers.slack import Slack
from notify.providers.telegram import Telegram
from notify.providers.teams import Teams
from .abstract import AbstractTool


class NotificationType(str, Enum):
    """Supported notification types."""
    EMAIL = "email"
    SLACK = "slack"
    TELEGRAM = "telegram"
    TEAMS = "teams"


class FileType(Enum):
    """File types for smart handling."""
    IMAGE = "image"
    DOCUMENT = "document"
    VIDEO = "video"
    AUDIO = "audio"
    UNKNOWN = "unknown"


class NotificationInput(BaseModel):
    """Input schema for notification tool."""
    message: str = Field(
        ...,
        description="The message content to send"
    )
    type: str = Field(
        ...,
        description="Notification type: 'email', 'slack', 'telegram', or 'teams'"
    )
    recipients: str = Field(
        ...,
        description=(
            "Recipients for the notification. Format depends on type: "
            "email: 'user@example.com' or comma-separated list; "
            "telegram: chat_id (e.g., '123456789'); "
            "slack: channel_id (e.g., 'C123456') or #channel-name; "
            "teams: user email or channel ID"
        )
    )
    subject: Optional[str] = Field(
        None,
        description="Subject line (mainly for email notifications)"
    )
    files: Optional[str] = Field(
        None,
        description="Comma-separated list of file paths to attach"
    )
    disable_notification: bool = Field(
        False,
        description="Disable notification sound (Telegram only)"
    )


class NotificationTool(AbstractTool):
    """
    Unified notification tool for sending messages through multiple channels.

    Supports:
    - Email: Send emails with attachments
    - Telegram: Smart file handling (images as photos, docs as documents)
    - Slack: Channel messages
    - MS Teams: Team messages with file references

    Examples:
        # Email with subject
        send(message="Report ready", type="email",
             recipients="user@example.com", subject="Daily Report")

        # Telegram with image
        send(message="Check this chart", type="telegram",
             recipients="123456789", files="/path/to/chart.png")

        # Slack channel
        send(message="Deployment complete", type="slack",
             recipients="C123456")
    """

    args_schema = NotificationInput

    def __init__(self, teams_config: Optional[Dict[str, str]] = None):
        """
        Initialize notification tool.

        Args:
            teams_config: Optional Teams configuration with keys:
                - tenant_id
                - client_id
                - client_secret
                - username
                - password
        """
        super().__init__()
        self.name = "send_notification"
        self.description = (
            "Send notifications to users via email, Telegram, Slack, or MS Teams. "
            "Supports file attachments with smart handling (images sent as photos "
            "in Telegram, documents as files, etc.)"
        )
        self.teams_config = teams_config or {}

    def _classify_file(self, file_path: Path) -> FileType:
        """Classify file type based on extension and MIME type."""
        if not file_path.exists():
            return FileType.UNKNOWN

        mime_type, _ = mimetypes.guess_type(str(file_path))

        if mime_type:
            if mime_type.startswith('image/'):
                return FileType.IMAGE
            elif mime_type.startswith('video/'):
                return FileType.VIDEO
            elif mime_type.startswith('audio/'):
                return FileType.AUDIO

        ext = file_path.suffix.lower()
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
        video_extensions = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'}
        audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}

        if ext in image_extensions:
            return FileType.IMAGE
        elif ext in video_extensions:
            return FileType.VIDEO
        elif ext in audio_extensions:
            return FileType.AUDIO
        else:
            return FileType.DOCUMENT

    def _categorize_files(self, files: List[Path]) -> Dict[FileType, List[Path]]:
        """Categorize files by type."""
        categorized = {
            FileType.IMAGE: [],
            FileType.DOCUMENT: [],
            FileType.VIDEO: [],
            FileType.AUDIO: []
        }

        for file in files:
            file_type = self._classify_file(file)
            if file_type != FileType.UNKNOWN:
                categorized[file_type].append(file)

        return categorized

    def _parse_recipients(
        self,
        recipients_str: str,
        notification_type: NotificationType
    ) -> Union[Actor, List[Actor], Channel, Chat]:
        """Parse recipient string into appropriate format."""
        recipients_str = recipients_str.strip()

        # Email: support comma-separated
        if notification_type == NotificationType.EMAIL:
            if ',' not in recipients_str:
                return Actor(
                    name=recipients_str.split('@')[0],
                    account={"address": recipients_str}
                )
            emails = [email.strip() for email in recipients_str.split(',')]
            return [
                Actor(
                    name=email.split('@')[0],
                    account={"address": email}
                )
                for email in emails if '@' in email
            ]

        # Telegram: chat_id
        elif notification_type == NotificationType.TELEGRAM:
            return Chat(chat_id=recipients_str)

        # Slack: channel_id or #channel-name
        elif notification_type == NotificationType.SLACK:
            channel_name = recipients_str.lstrip('#')
            return Channel(
                channel_id=None if recipients_str.startswith('#') else recipients_str,
                channel_name=channel_name
            )

        # Teams: email or channel
        elif notification_type == NotificationType.TEAMS:
            if '@' in recipients_str:
                return Actor(
                    name=recipients_str.split('@')[0],
                    account={"address": recipients_str}
                )
            return Channel(channel_id=recipients_str)

        return recipients_str

    def _parse_files(self, files_str: Optional[str]) -> List[Path]:
        """Parse comma-separated file paths into Path objects."""
        if not files_str:
            return []

        file_paths = [
            Path(f.strip())
            for f in files_str.split(',')
            if f.strip()
        ]

        # Filter to existing files
        valid_files = [f for f in file_paths if f.exists()]

        if len(valid_files) < len(file_paths):
            missing = [str(f) for f in file_paths if not f.exists()]
            self.logger.warning(f"Some files not found: {missing}")

        return valid_files

    async def _execute(self, **kwargs) -> str:
        """
        Execute notification sending.

        Args:
            **kwargs: Contains message, type, recipients, subject, files, etc.

        Returns:
            Status message with delivery information
        """
        try:
            # Extract parameters
            message = kwargs.get('message')
            notification_type = NotificationType(kwargs.get('type').lower())
            recipients_str = kwargs.get('recipients')
            subject = kwargs.get('subject')
            files_str = kwargs.get('files')
            disable_notification = kwargs.get('disable_notification', False)

            # Parse recipients
            recipients = self._parse_recipients(recipients_str, notification_type)

            # Parse files
            files = self._parse_files(files_str)

            # Route to appropriate provider
            if notification_type == NotificationType.EMAIL:
                result = await self._send_email(
                    message=message,
                    recipients=recipients,
                    subject=subject,
                    files=files
                )

            elif notification_type == NotificationType.SLACK:
                result = await self._send_slack(
                    message=message,
                    recipients=recipients
                )

            elif notification_type == NotificationType.TELEGRAM:
                result = await self._send_telegram(
                    message=message,
                    recipients=recipients,
                    files=files,
                    disable_notification=disable_notification
                )

            elif notification_type == NotificationType.TEAMS:
                result = await self._send_teams(
                    message=message,
                    recipients=recipients,
                    files=files
                )

            else:
                return f"❌ Unsupported notification type: {notification_type}"

            # Format success message
            recipient_count = len(recipients) if isinstance(recipients, list) else 1
            file_info = f" with {len(files)} file(s)" if files else ""

            return (
                f"✅ Notification sent via {notification_type.value}\n"
                f"Recipients: {recipient_count}\n"
                f"Files: {len(files) if files else 0}{file_info}\n"
                f"Status: {result.get('status', 'sent')}"
            )

        except Exception as e:
            self.logger.error(f"Notification failed: {e}", exc_info=True)
            return f"❌ Failed to send notification: {str(e)}"

    async def _send_email(
        self,
        message: str,
        recipients: Union[Actor, List[Actor]],
        subject: Optional[str],
        files: List[Path]
    ) -> Dict[str, Any]:
        """Send email with attachments."""
        email = Email()
        async with email as conn:
            result = await conn.send(
                message=message,
                recipient=recipients,
                subject=subject or "Notification",
                attachments=files or None
            )
        return {"status": "sent", "result": result}

    async def _send_slack(
        self,
        message: str,
        recipients: Channel
    ) -> Dict[str, Any]:
        """Send Slack message."""
        slack = Slack()
        async with slack as conn:
            result = await conn.send(
                message=message,
                recipient=recipients
            )
        return {"status": "sent", "result": result}

    async def _send_telegram(
        self,
        message: str,
        recipients: Chat,
        files: List[Path],
        disable_notification: bool
    ) -> Dict[str, Any]:
        """Send Telegram message with smart file handling."""
        telegram = Telegram()
        results = []

        async with telegram as conn:
            if files:
                # Categorize files for smart sending
                categorized = self._categorize_files(files)

                # Send images as photos
                for image in categorized[FileType.IMAGE]:
                    try:
                        result = await conn.send_photo(
                            photo=image,
                            caption=message[:1024],
                            disable_notification=disable_notification
                        )
                        results.append({"type": "photo", "file": image.name})
                    except Exception as e:
                        self.logger.error(f"Failed to send image {image}: {e}")

                # Send videos
                for video in categorized[FileType.VIDEO]:
                    try:
                        result = await conn.send_video(
                            video=video,
                            caption=message[:1024],
                            disable_notification=disable_notification
                        )
                        results.append({"type": "video", "file": video.name})
                    except Exception as e:
                        self.logger.error(f"Failed to send video {video}: {e}")

                # Send audio
                for audio in categorized[FileType.AUDIO]:
                    try:
                        result = await conn.send_audio(
                            audio=audio,
                            caption=message[:1024],
                            disable_notification=disable_notification
                        )
                        results.append({"type": "audio", "file": audio.name})
                    except Exception as e:
                        self.logger.error(f"Failed to send audio {audio}: {e}")

                # Send documents
                for doc in categorized[FileType.DOCUMENT]:
                    try:
                        result = await conn.send_document(
                            document=doc,
                            caption=message[:1024],
                            disable_notification=disable_notification
                        )
                        results.append({"type": "document", "file": doc.name})
                    except Exception as e:
                        self.logger.error(f"Failed to send document {doc}: {e}")

                # Send text if no captions were used
                if not any(categorized.values()):
                    result = await conn.send(message=message, recipient=recipients)
                    results.append({"type": "text"})
            else:
                # No files, just text
                result = await conn.send(message=message, recipient=recipients)
                results.append({"type": "text"})

        return {"status": "sent", "results": results}

    async def _send_teams(
        self,
        message: str,
        recipients: Union[Actor, Channel],
        files: List[Path]
    ) -> Dict[str, Any]:
        """Send MS Teams message."""
        teams = Teams(
            as_user=True,
            **self.teams_config
        )

        # Add file references to message
        if files:
            file_list = "\n".join([f"- {f.name}" for f in files])
            enhanced_message = f"{message}\n\n**Attached Files:**\n{file_list}"
        else:
            enhanced_message = message

        async with teams as conn:
            result = await conn.send(
                message=enhanced_message,
                recipient=recipients
            )

        return {"status": "sent", "result": result}
