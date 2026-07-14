---
type: Wiki Summary
title: parrot.interfaces.documentdb
id: mod:parrot.interfaces.documentdb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DocumentDB Interface.
relates_to:
- concept: class:parrot.interfaces.documentdb.DocumentDb
  rel: defines
- concept: class:parrot.interfaces.documentdb.FailedWrite
  rel: defines
---

# `parrot.interfaces.documentdb`

DocumentDB Interface.

Provides an async interface for managing DocumentDB/MongoDB connections
using the asyncdb library with Motor driver.

Features:
- Async-first design with proper connection management
- Fire-and-forget background saves with automatic retry
- Failed writes queue for inspection and manual retry
- Streaming iteration for large datasets
- Chunked reading for batch processing
- Async context manager support for clean resource handling

Usage:
    async with DocumentDb() as db:
        await db.write("conversations", {"user": "alice", "message": "hello"})

    # Or for fire-and-forget:
    db = DocumentDb()
    await db.documentdb_connect()
    db.save_background("logs", {"event": "user_login"})

## Classes

- **`FailedWrite`** — Represents a failed write operation for later retry or inspection.
- **`DocumentDb`** — Interface for managing DocumentDB connections using asyncdb "documentdb" driver.
