# DocumentDB Interface Guide

This guide describes how to use the `DocumentDb` interface to interact with AWS DocumentDB (or MongoDB-compatible databases).

## Initialization

The interface automatically loads credentials from `navconfig` (environment variables).

```python
from parrot.interfaces.documentdb import DocumentDb

db = DocumentDb()
# Connection is lazy, but you can explicitly connect:
await db.documentdb_connect()
```

## Creating Buckets and Collections

In DocumentDB/MongoDB, databases and collections are typically created on the first write. However, you can explicitly create them to set options or ensure existence.

```python
# Create a collection with specific options (implicit creation or explicit validation)
await db.create_collection("conversations")

# Create a 'bucket' (GridFS bucket or logical grouping)
# This usually ensures the necessary GridFS collections (chunks/files) exist.
await db.create_bucket("conversation_attachments")
```

## Indexing

You can improve query performance by indexing specific fields.

**Example: Indexing conversations by `session_id` and `turn_id`**

```python
# Create a compound index on session_id (ascending) and turn_id (ascending)
# 1 = Ascending, -1 = Descending
keys = [
    ("session_id", 1),
    ("turn_id", 1)
]

await db.create_indexes("conversations", keys)
```

## Streaming Data

When dealing with large datasets (e.g., retrieving all turns of a long conversation), use streaming to process items without loading everything into memory.

### Streaming Items (Iterate)

Process documents one by one as they are retrieved from the database cursor.

```python
collection = "conversations"
query = {"session_id": "12345-abcde"}

# 'iterate' (or 'read_batch') yields individual documents
async for turn in db.iterate(collection, query):
    print(f"Processing turn {turn['turn_id']}")
    # process_turn(turn)
```

### Streaming Batches (Chunked)

Process documents in chunks (lists) of a specific size. Useful for bulk API processing.

```python
# 'read_chunks' yields lists of documents
async for batch in db.read_chunks(collection, query, chunk_size=50):
    print(f"Sending batch of {len(batch)} turns to analytics...")
    # await send_to_analytics(batch)
```

## Background Saving (Fire-and-Forget)

Use `save_background` to write data without blocking the main execution flow. The save operation runs as a background asyncio task.

```python
data = {
    "session_id": "12345-abcde",
    "turn_id": 1,
    "user_input": "Hello",
    "timestamp": "2023-10-27T10:00:00Z"
}

# Returns immediately; save happens in background
db.save_background("conversations", data)

print("Turn processed, saving in background...")
```

## Full Example

```python
import asyncio
from parrot.interfaces.documentdb import DocumentDb

async def main():
    db = DocumentDb()
    
    # 1. Setup Collection & Index
    await db.create_collection("conversations")
    await db.create_indexes("conversations", [("session_id", 1), ("turn_id", 1)])
    
    # 2. Fire-and-forget save
    turn_data = {"session_id": "sess-01", "turn_id": 10, "content": "Hi"}
    db.save_background("conversations", turn_data)
    
    # 3. Stream back data
    async for turn in db.iterate("conversations", {"session_id": "sess-01"}):
        print("Read turn:", turn)

if __name__ == "__main__":
    asyncio.run(main())
```
