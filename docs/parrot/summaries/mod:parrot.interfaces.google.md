---
type: Wiki Summary
title: parrot.interfaces.google
id: mod:parrot.interfaces.google
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Google Services Client for AI-Parrot.
relates_to:
- concept: class:parrot.interfaces.google.CredentialsInterface
  rel: defines
- concept: class:parrot.interfaces.google.GoogleClient
  rel: defines
- concept: func:parrot.interfaces.google.create_google_client
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.exceptions
  rel: references
---

# `parrot.interfaces.google`

Google Services Client for AI-Parrot.

Simplified async-only implementation using aiogoogle.
Provides unified interface for Google services with credential management
and environment variable replacement.

## Classes

- **`CredentialsInterface`** — Mixin for processing credentials with environment variable replacement.
- **`GoogleClient(CredentialsInterface, ABC)`** — Google Services Client for AI-Parrot.

## Functions

- `def create_google_client(credentials: Optional[Union[str, dict, Path]]=None, scopes: Optional[Union[List[str], str]]=None, **kwargs) -> GoogleClient` — Factory function to create a GoogleClient.
