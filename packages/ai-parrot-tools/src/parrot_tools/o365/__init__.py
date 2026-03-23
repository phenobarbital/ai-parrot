"""
Office 365 Tools and Toolkit integration.
"""

from .mail import (
    CreateDraftMessageTool,
    SearchEmailTool,
    SendEmailTool,
    GetMessageTool,
    ListMessagesTool,
    DownloadAttachmentTool,
)
from .events import (
    CreateEventTool,
    UpdateEventTool,
    GetEventTool,
    ListEventsTool,
)
from .onedrive import (
    ListOneDriveFilesTool,
    SearchOneDriveFilesTool,
    DownloadOneDriveFileTool,
    UploadOneDriveFileTool
)


__all__ = (
    "CreateDraftMessageTool",
    "SearchEmailTool",
    "SendEmailTool",
    "GetMessageTool",
    "ListMessagesTool",
    "DownloadAttachmentTool",
    "CreateEventTool",
    "UpdateEventTool",
    "GetEventTool",
    "ListEventsTool",
    "ListOneDriveFilesTool",
    "SearchOneDriveFilesTool",
    "DownloadOneDriveFileTool",
    "UploadOneDriveFileTool",
)
