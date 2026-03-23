"""
Notification Mixin for AI-Parrot Agents.

Provides notification capabilities to agents using the async-notify library.
"""
from typing import Union, List, Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import mimetypes
from notify import Notify
from notify.models import (
    Actor,
    Channel,
    Chat,
    TeamsChannel,
    TeamsWebhook,
    TeamsCard
)
from notify.providers.email import Email
from notify.providers.slack import Slack
from notify.providers.telegram import Telegram
from notify.providers.teams import Teams
from ..conf import (
    TEAMS_NOTIFY_TENANT_ID,
    TEAMS_NOTIFY_CLIENT_ID,
    TEAMS_NOTIFY_CLIENT_SECRET,
    TEAMS_NOTIFY_USERNAME,
    TEAMS_NOTIFY_PASSWORD
)


class NotificationProvider(Enum):
    """Supported notification providers."""
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


@dataclass
class NotificationConfig:
    """Configuration for sending notifications."""
    provider: NotificationProvider = NotificationProvider.EMAIL
    recipients: Union[List[Actor], Actor, Channel, Chat] = None
    subject: Optional[str] = None
    template: Optional[str] = None
    disable_notification: bool = False
    # Email specific
    with_attachments: bool = True
    # Teams specific
    teams_config: Optional[Dict[str, Any]] = None
    # Additional provider kwargs
    provider_kwargs: Optional[Dict[str, Any]] = None


class NotificationMixin:
    """
    Mixin to provide notification capabilities to agents.

    This mixin integrates async-notify library to send messages
    through various channels (email, slack, telegram, teams) with
    smart file handling.
    """

    def _classify_file(self, file_path: Path) -> FileType:
        """
        Classify file type based on extension and MIME type.

        Args:
            file_path: Path to the file

        Returns:
            FileType enum value
        """
        if not file_path.exists():
            return FileType.UNKNOWN

        # Get MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))

        if mime_type:
            if mime_type.startswith('image/'):
                return FileType.IMAGE
            elif mime_type.startswith('video/'):
                return FileType.VIDEO
            elif mime_type.startswith('audio/'):
                return FileType.AUDIO

        # Check by extension if MIME failed
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
        """
        Categorize files by type.

        Args:
            files: List of file paths

        Returns:
            Dictionary mapping FileType to list of files
        """
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

    async def send_notification(
        self,
        message: Union[str, Any],
        recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]],
        provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL,
        subject: Optional[str] = None,
        report: Optional[Any] = None,
        template: Optional[str] = None,
        with_attachments: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send notification to users through various channels.

        Args:
            message: Message text to send or AgentResponse/AIMessage object
            recipients: Recipients (can be Actor objects, email strings, etc.)
            provider: Notification provider (email, slack, telegram, teams)
            subject: Subject line (mainly for email)
            report: Optional AgentResponse or AIMessage containing output/files
            template: Email template name
            with_attachments: Whether to include file attachments
            **kwargs: Additional provider-specific arguments

        Returns:
            Dict with notification status and results

        Example:
            # Simple email notification
            await agent.send_notification(
                message="Daily report ready",
                recipients="user@example.com",
                subject="Daily Report"
            )

            # With AIMessage containing files (images sent as photos in Telegram)
            response = await agent.chat("Generate report with charts")
            await agent.send_notification(
                message="Your report is ready",
                recipients="123456789",  # Telegram chat_id
                report=response,
                provider="telegram"
            )

            # To Slack channel
            channel = Channel(channel_id="C123456", channel_name="reports")
            await agent.send_notification(
                message="New insights available",
                recipients=channel,
                provider="slack"
            )
        """
        try:
            # Normalize provider
            if isinstance(provider, str):
                provider = NotificationProvider(provider.lower())

            # Extract message content from AgentResponse/AIMessage if needed
            message_text, files = self._extract_message_content(message, report)

            # Parse recipients
            recipient_list = self._parse_recipients(recipients, provider)

            # Prepare notification arguments
            notify_args = {
                "message": message_text,
                "recipient": recipient_list
            }

            # Add provider-specific arguments
            if provider == NotificationProvider.EMAIL:
                if subject:
                    notify_args["subject"] = subject
                if template:
                    notify_args["template"] = template
                if files and with_attachments:
                    notify_args["attachments"] = files

            elif provider == NotificationProvider.TELEGRAM:
                notify_args["disable_notification"] = kwargs.get(
                    "disable_notification", False
                )

            elif provider == NotificationProvider.TEAMS:
                # Teams might need special card formatting
                pass

            # Merge additional kwargs
            notify_args |= kwargs

            # Send notification with smart file handling
            result = await self._send_with_provider(
                provider=provider,
                notify_args=notify_args,
                files=files if with_attachments else None
            )

            self.logger.info(
                f"Notification sent via {provider.value} to {len(recipient_list) if isinstance(recipient_list, list) else 1} recipient(s)"
            )

            return {
                "status": "success",
                "provider": provider.value,
                "recipients": len(recipient_list) if isinstance(recipient_list, list) else 1,
                "files_sent": len(files) if files else 0,
                "result": result
            }

        except Exception as e:
            self.logger.error(f"Failed to send notification: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "provider": provider.value if provider else None
            }

    def _extract_message_content(
        self,
        message: Union[str, Any],
        report: Optional[Any] = None
    ) -> tuple[str, List[Path]]:
        """
        Extract message text and files from various input types.

        Handles:
        - Plain strings
        - AgentResponse objects
        - AIMessage objects

        Returns:
            Tuple of (message_text, list_of_file_paths)
        """
        message_text = ""
        files = []

        # Extract from message if it's an object
        if isinstance(message, str):
            message_text = message
        elif hasattr(message, 'content'):
            # AIMessage or similar
            message_text = getattr(message, 'content', str(message))
        elif hasattr(message, 'output'):
            # AgentResponse
            message_text = getattr(message, 'output', str(message))
        else:
            message_text = str(message)

        # Extract from report if provided
        if report:
            if hasattr(report, 'output'):
                # AgentResponse with output
                output = getattr(report, 'output', None)
                if output and not message_text:
                    message_text = output

            # PRIORITY 1: Check for 'files' attribute first (preferred for AgentResponse)
            if hasattr(report, 'files'):
                report_files = getattr(report, 'files', None)
                if report_files:
                    if isinstance(report_files, list):
                        for file_path in report_files:
                            if file_path and self._is_valid_file_path(file_path):
                                files.append(Path(file_path))
                    elif isinstance(report_files, (str, Path)):
                        if self._is_valid_file_path(report_files):
                            files.append(Path(report_files))

            # PRIORITY 2: Check for 'documents' attribute (but filter out text content)
            elif hasattr(report, 'documents'):
                documents = getattr(report, 'documents', None)
                if documents:
                    if isinstance(documents, list):
                        for document in documents:
                            if isinstance(document, dict) and 'path' in document:
                                doc_path = document['path']
                                if self._is_valid_file_path(doc_path):
                                    files.append(Path(doc_path))
                            elif isinstance(document, (str, Path)):
                                # Only add if it looks like a file path, not text content
                                if self._is_valid_file_path(document):
                                    files.append(Path(document))

            # Check for content blocks with files (Claude-style responses)
            if hasattr(report, 'content') and isinstance(report.content, list):
                for block in report.content:
                    if isinstance(block, dict):
                        if block.get('type') == 'file' and 'path' in block:
                            file_path = block['path']
                            if self._is_valid_file_path(file_path):
                                files.append(Path(file_path))
                        elif block.get('type') == 'image' and 'source' in block:
                            # Handle image sources
                            source = block['source']
                            if isinstance(source, dict) and 'data' in source:
                                # Base64 image - would need to save first
                                pass
                            elif isinstance(source, (str, Path)):
                                if self._is_valid_file_path(source):
                                    files.append(Path(source))

            # PRIORITY 3: Check AIMessage nested inside AgentResponse
            if hasattr(report, 'response') and isinstance(report.response, object):
                ai_message = report.response

                # Extract files from AIMessage
                if hasattr(ai_message, 'files'):
                    ai_files = getattr(ai_message, 'files', None)
                    if ai_files and isinstance(ai_files, list):
                        for file_path in ai_files:
                            if file_path and self._is_valid_file_path(file_path):
                                path_obj = Path(file_path)
                                if path_obj not in files:  # Avoid duplicates
                                    files.append(path_obj)

        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for file in files:
            if file not in seen:
                seen.add(file)
                unique_files.append(file)

        files = unique_files

        # Validate files exist
        valid_files = [f for f in files if f.exists()]
        if len(valid_files) < len(files):
            missing_count = len(files) - len(valid_files)
            missing_files = [str(f) for f in files if not f.exists()]
            self.logger.warning(
                f"Some files not found: {missing_count} missing - {missing_files[:3]}"
            )

        return message_text, valid_files

    def _is_valid_file_path(self, path: Union[str, Path]) -> bool:
        """
        Check if a string looks like a valid file path rather than text content.

        Args:
            path: String or Path to validate

        Returns:
            bool: True if it looks like a file path, False otherwise
        """
        if not path:
            return False

        path_str = str(path)

        # Filter out obvious text content (too long or contains newlines)
        if len(path_str) > 500 or '\n' in path_str:
            return False

        # Must contain path separators or start with common path patterns
        has_separator = '/' in path_str or '\\' in path_str

        # Check for common file extensions
        common_extensions = [
            '.txt', '.pdf', '.doc', '.docx', '.xls', '.xlsx',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg',
            '.mp4', '.avi', '.mov', '.mp3', '.wav',
            '.json', '.xml', '.csv', '.html', '.md'
        ]
        has_extension = any(path_str.lower().endswith(ext) for ext in common_extensions)

        # Valid if it has separators or a file extension
        return has_separator or has_extension

    def _parse_recipients(
        self,
        recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]],
        provider: NotificationProvider
    ) -> Union[List[Actor], Actor, Channel, Chat]:
        """
        Parse recipients into appropriate format for the provider.

        Args:
            recipients: Various recipient formats
            provider: The notification provider

        Returns:
            Formatted recipient(s) for the provider
        """
        # Already formatted objects
        if isinstance(recipients, (Actor, Channel, Chat, TeamsChannel, TeamsWebhook)):
            return recipients

        # List of formatted objects
        if isinstance(recipients, list) and len(recipients) > 0:
            if isinstance(recipients[0], (Actor, Channel, Chat)):
                return recipients

        # String email address(es)
        if isinstance(recipients, str):
            # Single email
            if '@' in recipients:
                return Actor(
                    name=recipients.split('@')[0],
                    account={"address": recipients}
                )
            # Might be a chat_id or channel_id
            elif provider == NotificationProvider.TELEGRAM:
                return Chat(chat_id=recipients)
            elif provider == NotificationProvider.SLACK:
                return Channel(channel_id=recipients)
            else:
                # Try as generic actor
                return Actor(
                    name="User",
                    account={"address": recipients}
                )

        # List of email strings
        if isinstance(recipients, list):
            actors = []
            for recipient in recipients:
                if isinstance(recipient, str) and '@' in recipient:
                    actors.append(Actor(
                        name=recipient.split('@')[0],
                        account={"address": recipient}
                    ))
                elif isinstance(recipient, (Actor, Channel, Chat)):
                    actors.append(recipient)
            return actors if actors else recipients

        # Fallback
        return recipients

    async def _send_with_provider(
        self,
        provider: NotificationProvider,
        notify_args: Dict[str, Any],
        files: Optional[List[Path]] = None
    ) -> Any:
        """
        Send notification using the specified provider with smart file handling.

        Args:
            provider: Notification provider to use
            notify_args: Arguments for the notification
            files: Optional list of file attachments

        Returns:
            Provider-specific result
        """
        if provider == NotificationProvider.EMAIL:
            return await self._send_email(notify_args, files)

        elif provider == NotificationProvider.SLACK:
            return await self._send_slack(notify_args)

        elif provider == NotificationProvider.TELEGRAM:
            return await self._send_telegram(notify_args, files)

        elif provider == NotificationProvider.TEAMS:
            return await self._send_teams(notify_args, files)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def _send_email(
        self,
        notify_args: Dict[str, Any],
        files: Optional[List[Path]] = None
    ) -> Any:
        """Send email notification with attachments."""
        email = Email()
        async with email as conn:
            result = await conn.send(**notify_args)
        return result

    async def _send_slack(self, notify_args: Dict[str, Any]) -> Any:
        """Send Slack notification."""
        slack = Slack()
        async with slack as conn:
            result = await conn.send(**notify_args)
        return result

    async def _send_telegram(
        self,
        notify_args: Dict[str, Any],
        files: Optional[List[Path]] = None
    ) -> Any:
        """
        Send Telegram notification with smart file handling.

        Images are sent as photos, documents as documents, videos as videos.
        """
        telegram = Telegram()
        results = []

        async with telegram as conn:
            # If files, send them appropriately based on type
            if files and len(files) > 0:
                # Categorize files
                categorized_files = self._categorize_files(files)

                # Send images as photos
                for image in categorized_files[FileType.IMAGE]:
                    try:
                        result = await conn.send_photo(
                            photo=image,
                            caption=notify_args.get("message", "")[:1024],  # Telegram caption limit
                            disable_notification=notify_args.get("disable_notification", False)
                        )
                        results.append({
                            "type": "photo",
                            "file": str(image),
                            "result": result
                        })
                        self.logger.info(f"Sent image via Telegram: {image.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to send image {image}: {e}")

                # Send videos
                for video in categorized_files[FileType.VIDEO]:
                    try:
                        result = await conn.send_video(
                            video=video,
                            caption=notify_args.get("message", "")[:1024],
                            supports_streaming=True,
                            disable_notification=notify_args.get("disable_notification", False)
                        )
                        results.append({
                            "type": "video",
                            "file": str(video),
                            "result": result
                        })
                        self.logger.info(f"Sent video via Telegram: {video.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to send video {video}: {e}")

                # Send audio files
                for audio in categorized_files[FileType.AUDIO]:
                    try:
                        result = await conn.send_audio(
                            audio=audio,
                            caption=notify_args.get("message", "")[:1024],
                            disable_notification=notify_args.get("disable_notification", False)
                        )
                        results.append({
                            "type": "audio",
                            "file": str(audio),
                            "result": result
                        })
                        self.logger.info(f"Sent audio via Telegram: {audio.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to send audio {audio}: {e}")

                # Send documents (PDFs, Excel, etc.)
                for document in categorized_files[FileType.DOCUMENT]:
                    try:
                        result = await conn.send_document(
                            document=document,
                            caption=notify_args.get("message", "")[:1024],
                            disable_notification=notify_args.get("disable_notification", False)
                        )
                        results.append({
                            "type": "document",
                            "file": str(document),
                            "result": result
                        })
                        self.logger.info(f"Sent document via Telegram: {document.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to send document {document}: {e}")

                # If message was used as caption, we're done
                # Otherwise send a separate text message
                if len(results) > 0 and notify_args.get("message"):
                    # Message already sent as captions
                    pass
                else:
                    # Send text message
                    text_result = await conn.send(**notify_args)
                    results.append({
                        "type": "text",
                        "result": text_result
                    })
            else:
                # No files, just send text message
                result = await conn.send(**notify_args)
                results.append({
                    "type": "text",
                    "result": result
                })

        return results

    async def _send_teams(
        self,
        notify_args: Dict[str, Any],
        files: Optional[List[Path]] = None
    ) -> Any:
        """
        Send Microsoft Teams notification.

        Teams supports file attachments in cards.
        """
        teams = Teams(
            as_user=True,
            tenant_id=TEAMS_NOTIFY_TENANT_ID,
            client_id=TEAMS_NOTIFY_CLIENT_ID,
            client_secret=TEAMS_NOTIFY_CLIENT_SECRET,
            username=TEAMS_NOTIFY_USERNAME,
            password=TEAMS_NOTIFY_PASSWORD
        )

        # If files provided, we can add them as attachments or links in the card
        if files and len(files) > 0:
            # Create a Teams card with file information
            message_text = notify_args.get("message", "")

            # Add file list to message
            file_list = "\n".join([f"- {f.name}" for f in files])
            enhanced_message = f"{message_text}\n\n**Attached Files:**\n{file_list}"

            notify_args["message"] = enhanced_message

            # Note: Teams API has limitations on direct file uploads
            # For full file upload support, would need to use Graph API file upload
            self.logger.info(
                f"Teams notification with {len(files)} files (file list added to message)"
            )

        async with teams as conn:
            result = await conn.send(**notify_args)
        return result

    # Convenience methods for specific providers

    async def send_email(
        self,
        message: str,
        recipients: Union[List[str], str],
        subject: str,
        report: Optional[Any] = None,
        template: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Convenience method for sending emails."""
        return await self.send_notification(
            message=message,
            recipients=recipients,
            provider=NotificationProvider.EMAIL,
            subject=subject,
            report=report,
            template=template,
            **kwargs
        )

    async def send_slack_message(
        self,
        message: str,
        channel: Union[Channel, str],
        report: Optional[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Convenience method for sending Slack messages."""
        return await self.send_notification(
            message=message,
            recipients=channel,
            provider=NotificationProvider.SLACK,
            report=report,
            **kwargs
        )

    async def send_telegram_message(
        self,
        message: str,
        chat: Union[Chat, str],
        report: Optional[Any] = None,
        disable_notification: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convenience method for sending Telegram messages.

        Automatically detects and sends images as photos, documents as files.
        """
        return await self.send_notification(
            message=message,
            recipients=chat,
            provider=NotificationProvider.TELEGRAM,
            report=report,
            disable_notification=disable_notification,
            **kwargs
        )

    async def send_teams_message(
        self,
        message: str,
        recipient: Union[Actor, TeamsChannel, TeamsWebhook],
        report: Optional[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Convenience method for sending Teams messages."""
        return await self.send_notification(
            message=message,
            recipients=recipient,
            provider=NotificationProvider.TEAMS,
            report=report,
            **kwargs
        )
