---
type: Wiki Entity
title: RedditToolkit
id: class:parrot_tools.reddit.RedditToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reddit Toolkit for extracting data from Reddit using PRAW.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# RedditToolkit

Defined in [`parrot_tools.reddit`](../summaries/mod:parrot_tools.reddit.md).

```python
class RedditToolkit(AbstractToolkit)
```

Reddit Toolkit for extracting data from Reddit using PRAW.

Requires PRAW to be installed (`pip install praw`).

Authentication configuration (environment variables recommended):
- REDDIT_CLIENT_ID
- REDDIT_CLIENT_SECRET
- REDDIT_USER_AGENT
- REDDIT_USERNAME (optional)
- REDDIT_PASSWORD (optional)

## Methods

- `async def reddit_extract_subreddit_posts(self, subreddit_name: str, query: str, limit: int=10, search_sort: str='new', time_filter: str='year', fetch_comments: bool=True, max_top_level_comments: int=10) -> ToolResult` — Extract posts and optionally comments from a subreddit based on a search query.
