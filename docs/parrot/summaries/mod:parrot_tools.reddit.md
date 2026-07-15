---
type: Wiki Summary
title: parrot_tools.reddit
id: mod:parrot_tools.reddit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reddit Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.reddit.RedditToolkit
  rel: defines
- concept: class:parrot_tools.reddit.SubredditSearchInput
  rel: defines
- concept: func:parrot_tools.reddit.safe_author
  rel: defines
- concept: func:parrot_tools.reddit.utc_iso
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.reddit`

Reddit Toolkit for AI-Parrot.

This toolkit provides Reddit data extraction capabilities using PRAW (Python Reddit API Wrapper),
implementing proper backoff retry for rate limiting and OAuth2 authentication.

## Classes

- **`SubredditSearchInput(BaseModel)`** — Input parameters for searching a subreddit.
- **`RedditToolkit(AbstractToolkit)`** — Reddit Toolkit for extracting data from Reddit using PRAW.

## Functions

- `def utc_iso(ts: Optional[float]) -> Optional[str]` — Convert a timestamp to an ISO 8601 string (UTC).
- `def safe_author(author) -> Optional[str]` — Safely get author name, handling deleted users.
