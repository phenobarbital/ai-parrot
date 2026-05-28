"""
File handling for Slack integration.

Provides functions for downloading and uploading files using
Slack's authenticated API, including the v2 async upload flow.

Part of FEAT-010: Slack Wrapper Integration Enhancements.
"""
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession, ClientTimeout

logger = logging.getLogger("SlackFiles")

# MIME types that AI-Parrot can process via loaders
PROCESSABLE_MIME_TYPES = {
    # Images
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    # Documents
    "application/pdf",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    # Office documents
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # Legacy Office formats
    "application/msword",
    "application/vnd.ms-excel",
    # Code files
    "text/html",
    "text/xml",
    "application/xml",
    "text/x-python",
    "application/javascript",
}


def extract_files_from_event(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract file information from a Slack event.

    Args:
        event: The Slack event dictionary.

    Returns:
        List of file info dictionaries from the event.
    """
    files = event.get("files", [])
    if not files:
        # Check for file_share events
        if event.get("subtype") == "file_share":
            file_info = event.get("file")
            if file_info:
                files = [file_info]
    return files


async def download_slack_file(
    file_info: Dict[str, Any],
    bot_token: str,
    download_dir: Optional[str] = None,
    allowed_types: Optional[set] = None,
) -> Optional[Path]:
    """
    Download a file from Slack using bot token authentication.

    Slack files require authentication via the bot token in the
    Authorization header. This function downloads supported file
    types to a local directory.

    Args:
        file_info: File metadata from Slack event containing
            url_private_download or url_private, mimetype, name.
        bot_token: Slack bot OAuth token (xoxb-...).
        download_dir: Directory to save file. If None, uses temp dir.
        allowed_types: Set of allowed MIME types. Defaults to
            PROCESSABLE_MIME_TYPES if None.

    Returns:
        Path to downloaded file, or None if download failed or
        MIME type is not supported.

    Example::

        file_info = event["files"][0]
        path = await download_slack_file(file_info, bot_token)
        if path:
            content = await process_file(path)
    """
    # Get download URL (prefer url_private_download)
    url = file_info.get("url_private_download") or file_info.get("url_private")
    if not url:
        logger.warning(
            "No download URL in file info: %s",
            file_info.get("id", "unknown"),
        )
        return None

    # Check MIME type
    mimetype = file_info.get("mimetype", "")
    types_to_check = allowed_types if allowed_types is not None else PROCESSABLE_MIME_TYPES

    if mimetype not in types_to_check:
        logger.info(
            "Skipping unsupported file type: %s (%s)",
            file_info.get("name", "unknown"),
            mimetype,
        )
        return None

    filename = file_info.get("name", "unknown_file")

    # Determine destination path
    if download_dir:
        dest_dir = Path(download_dir)
    else:
        dest_dir = Path(tempfile.mkdtemp(prefix="slack_file_"))
    dest = dest_dir / filename

    # Download with authentication
    headers = {"Authorization": f"Bearer {bot_token}"}
    timeout = ClientTimeout(total=300)  # 5 min timeout for large files

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.error(
                        "Failed to download %s: HTTP %s",
                        filename,
                        resp.status,
                    )
                    return None

                # Ensure directory exists
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Stream to file
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)

        file_size = dest.stat().st_size
        logger.info(
            "Downloaded: %s (%d bytes)",
            dest.name,
            file_size,
        )
        return dest

    except Exception as e:
        logger.error(
            "Error downloading %s: %s",
            filename,
            e,
        )
        # Clean up partial file if it exists
        if dest.exists():
            dest.unlink()
        return None


async def upload_file_to_slack(
    bot_token: str,
    channel: str,
    file_path: Path,
    title: Optional[str] = None,
    thread_ts: Optional[str] = None,
    initial_comment: Optional[str] = None,
) -> bool:
    """
    Upload file to Slack using v2 async upload flow.

    The v2 upload flow is a 3-step process:
    1. Get upload URL via files.getUploadURLExternal
    2. Upload file content to the provided URL
    3. Complete upload via files.completeUploadExternal

    This method is preferred over the deprecated files.upload API.

    Args:
        bot_token: Slack bot OAuth token (xoxb-...).
        channel: Channel ID to share the file in.
        file_path: Path to the file to upload.
        title: Optional title for the file.
        thread_ts: Optional thread timestamp to reply to.
        initial_comment: Optional comment to add with the file.

    Returns:
        True if upload succeeded, False otherwise.

    Example::

        success = await upload_file_to_slack(
            bot_token="xoxb-...",
            channel="C123456",
            file_path=Path("report.pdf"),
            title="Monthly Report",
            initial_comment="Here's the report you requested!",
        )
    """
    if not file_path.exists():
        logger.error("File does not exist: %s", file_path)
        return False

    headers = {"Authorization": f"Bearer {bot_token}"}
    file_size = file_path.stat().st_size
    timeout = ClientTimeout(total=300)

    try:
        async with ClientSession(timeout=timeout) as session:
            # Step 1: Get upload URL
            step1_params = {
                "filename": file_path.name,
                "length": str(file_size),
            }

            async with session.get(
                "https://slack.com/api/files.getUploadURLExternal",
                headers=headers,
                params=step1_params,
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(
                        "Failed to get upload URL: %s",
                        data.get("error", "unknown"),
                    )
                    return False

                upload_url = data["upload_url"]
                file_id = data["file_id"]

            logger.debug(
                "Got upload URL for file_id=%s",
                file_id,
            )

            # Step 2: Upload file content
            with open(file_path, "rb") as f:
                file_content = f.read()

            async with session.post(upload_url, data=file_content) as resp:
                if resp.status != 200:
                    logger.error(
                        "Failed to upload content: HTTP %s",
                        resp.status,
                    )
                    return False

            logger.debug("Uploaded file content for file_id=%s", file_id)

            # Step 3: Complete upload
            complete_payload = {
                "files": [{"id": file_id, "title": title or file_path.name}],
                "channel_id": channel,
            }
            if thread_ts:
                complete_payload["thread_ts"] = thread_ts
            if initial_comment:
                complete_payload["initial_comment"] = initial_comment

            async with session.post(
                "https://slack.com/api/files.completeUploadExternal",
                headers={**headers, "Content-Type": "application/json"},
                data=json.dumps(complete_payload),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(
                        "Failed to complete upload: %s",
                        data.get("error", "unknown"),
                    )
                    return False

        logger.info(
            "Successfully uploaded file: %s to channel %s",
            file_path.name,
            channel,
        )
        return True

    except Exception as e:
        logger.error(
            "Error uploading %s: %s",
            file_path.name,
            e,
        )
        return False


def is_processable_file(file_info: Dict[str, Any]) -> bool:
    """
    Check if a file can be processed by AI-Parrot loaders.

    Args:
        file_info: File metadata from Slack event.

    Returns:
        True if the file's MIME type is supported.
    """
    mimetype = file_info.get("mimetype", "")
    return mimetype in PROCESSABLE_MIME_TYPES


def get_file_extension(file_info: Dict[str, Any]) -> str:
    """
    Get file extension from file info.

    Args:
        file_info: File metadata from Slack event.

    Returns:
        File extension including the dot (e.g., ".pdf").
    """
    # Try to get from filetype field first
    filetype = file_info.get("filetype", "")
    if filetype:
        return f".{filetype}"

    # Fallback to extracting from name
    name = file_info.get("name", "")
    if "." in name:
        return f".{name.rsplit('.', 1)[-1]}"

    # Map common MIME types
    mime_to_ext = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "text/plain": ".txt",
        "text/csv": ".csv",
        "application/json": ".json",
    }
    mimetype = file_info.get("mimetype", "")
    return mime_to_ext.get(mimetype, "")
