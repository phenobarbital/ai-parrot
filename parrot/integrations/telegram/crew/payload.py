"""DataPayload — file exchange between agents via Telegram documents.

Handles downloading documents from Telegram messages, uploading files
to the group, MIME type validation, CSV convenience methods, and
temp file management.
"""
import logging
import os
from pathlib import Path
from typing import List, Optional

from aiogram import Bot
from aiogram.types import FSInputFile, Message

logger = logging.getLogger(__name__)

TELEGRAM_CAPTION_LIMIT = 1024


class DataPayload:
    """Manages file exchange between agents in a Telegram crew.

    Args:
        temp_dir: Directory for temporary file storage.
        max_file_size_mb: Maximum allowed file size in megabytes.
        allowed_mime_types: List of allowed MIME types for document exchange.
    """

    def __init__(
        self,
        temp_dir: str = "/tmp/parrot_crew",
        max_file_size_mb: int = 50,
        allowed_mime_types: Optional[List[str]] = None,
    ) -> None:
        self.temp_dir = temp_dir
        self.max_file_size_mb = max_file_size_mb
        self.allowed_mime_types = allowed_mime_types or [
            "text/csv",
            "application/json",
            "text/plain",
            "image/png",
            "image/jpeg",
            "application/pdf",
            "application/vnd.apache.parquet",
        ]
        self.logger = logging.getLogger(__name__)
        self._ensure_temp_dir()

    def _ensure_temp_dir(self) -> None:
        """Create temp directory if it does not exist."""
        os.makedirs(self.temp_dir, exist_ok=True)

    def validate_mime(self, mime_type: str) -> bool:
        """Check if a MIME type is in the allowed list.

        Args:
            mime_type: The MIME type to validate.

        Returns:
            True if allowed, False otherwise.
        """
        return mime_type in self.allowed_mime_types

    def _validate_file_size(self, file_size: int) -> bool:
        """Check if file size is within the allowed limit.

        Args:
            file_size: File size in bytes.

        Returns:
            True if within limit, False otherwise.
        """
        max_bytes = self.max_file_size_mb * 1024 * 1024
        return file_size <= max_bytes

    async def download_document(
        self,
        bot: Bot,
        message: Message,
    ) -> Optional[str]:
        """Download a document from a Telegram message to the temp directory.

        Args:
            bot: The aiogram Bot instance.
            message: The Telegram message containing the document.

        Returns:
            Path to the downloaded file, or None if validation fails.
        """
        document = message.document
        if document is None:
            self.logger.warning("Message has no document attachment")
            return None

        # Validate MIME type
        mime_type = document.mime_type or "application/octet-stream"
        if not self.validate_mime(mime_type):
            self.logger.warning(
                "Rejected document with MIME type %s (file: %s)",
                mime_type,
                document.file_name,
            )
            return None

        # Validate file size
        if document.file_size and not self._validate_file_size(document.file_size):
            self.logger.warning(
                "Rejected document %s: size %d bytes exceeds limit %d MB",
                document.file_name,
                document.file_size,
                self.max_file_size_mb,
            )
            return None

        # Download
        file_name = document.file_name or f"document_{document.file_id}"
        dest_path = os.path.join(self.temp_dir, file_name)

        file = await bot.get_file(document.file_id)
        await bot.download_file(file.file_path, destination=dest_path)

        self.logger.info("Downloaded document to %s", dest_path)
        return dest_path

    async def send_document(
        self,
        bot: Bot,
        chat_id: int,
        file_path: str,
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Upload a file to the Telegram group as a document.

        If the caption exceeds 1024 characters, it is sent as a separate
        message after the document.

        Args:
            bot: The aiogram Bot instance.
            chat_id: Target chat ID.
            file_path: Path to the file to upload.
            caption: Optional caption for the document.
            reply_to_message_id: Optional message ID to reply to.
        """
        input_file = FSInputFile(file_path)

        if len(caption) <= TELEGRAM_CAPTION_LIMIT:
            await bot.send_document(
                chat_id=chat_id,
                document=input_file,
                caption=caption or None,
                reply_to_message_id=reply_to_message_id,
            )
        else:
            # Send document without caption, then caption as separate message
            sent = await bot.send_document(
                chat_id=chat_id,
                document=input_file,
                reply_to_message_id=reply_to_message_id,
            )
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_to_message_id=sent.message_id if sent else reply_to_message_id,
            )

        self.logger.info("Sent document %s to chat %d", file_path, chat_id)

    async def send_csv(
        self,
        bot: Bot,
        chat_id: int,
        dataframe,
        filename: str = "data.csv",
        caption: str = "",
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        """Serialize a pandas DataFrame to CSV and send as a document.

        Args:
            bot: The aiogram Bot instance.
            chat_id: Target chat ID.
            dataframe: A pandas DataFrame to serialize.
            filename: Output filename for the CSV.
            caption: Optional caption for the document.
            reply_to_message_id: Optional message ID to reply to.
        """
        csv_path = os.path.join(self.temp_dir, filename)
        dataframe.to_csv(csv_path, index=False)

        self.logger.info("Serialized DataFrame to %s (%d rows)", csv_path, len(dataframe))

        try:
            await self.send_document(
                bot=bot,
                chat_id=chat_id,
                file_path=csv_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
            )
        finally:
            self.cleanup_file(csv_path)

    def cleanup_file(self, file_path: str) -> None:
        """Remove a temporary file if it exists.

        Args:
            file_path: Path to the file to remove.
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.logger.debug("Cleaned up temp file %s", file_path)
        except OSError as e:
            self.logger.warning("Failed to clean up %s: %s", file_path, e)

    def cleanup_all(self) -> None:
        """Remove all files in the temp directory."""
        if not os.path.isdir(self.temp_dir):
            return
        for fname in os.listdir(self.temp_dir):
            fpath = os.path.join(self.temp_dir, fname)
            if os.path.isfile(fpath):
                self.cleanup_file(fpath)
