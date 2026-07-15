---
type: Wiki Summary
title: parrot.integrations.slack.files
id: mod:parrot.integrations.slack.files
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: File handling for Slack integration.
relates_to:
- concept: func:parrot.integrations.slack.files.download_slack_file
  rel: defines
- concept: func:parrot.integrations.slack.files.extract_files_from_event
  rel: defines
- concept: func:parrot.integrations.slack.files.get_file_extension
  rel: defines
- concept: func:parrot.integrations.slack.files.is_processable_file
  rel: defines
- concept: func:parrot.integrations.slack.files.upload_file_to_slack
  rel: defines
---

# `parrot.integrations.slack.files`

File handling for Slack integration.

Provides functions for downloading and uploading files using
Slack's authenticated API, including the v2 async upload flow.

Part of FEAT-010: Slack Wrapper Integration Enhancements.

## Functions

- `def extract_files_from_event(event: Dict[str, Any]) -> List[Dict[str, Any]]` — Extract file information from a Slack event.
- `async def download_slack_file(file_info: Dict[str, Any], bot_token: str, download_dir: Optional[str]=None, allowed_types: Optional[set]=None) -> Optional[Path]` — Download a file from Slack using bot token authentication.
- `async def upload_file_to_slack(bot_token: str, channel: str, file_path: Path, title: Optional[str]=None, thread_ts: Optional[str]=None, initial_comment: Optional[str]=None) -> bool` — Upload file to Slack using v2 async upload flow.
- `def is_processable_file(file_info: Dict[str, Any]) -> bool` — Check if a file can be processed by AI-Parrot loaders.
- `def get_file_extension(file_info: Dict[str, Any]) -> str` — Get file extension from file info.
