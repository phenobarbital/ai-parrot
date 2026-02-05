import asyncio
import os
from parrot.interfaces.documentdb import DocumentDb
from navconfig import config

# Ensure env vars are loaded or use what's in config
# User provided example credentials in prompt, assuming they are in env or config now.

async def test_documentdb():
    print("Initializing DocumentDb...")
    db = DocumentDb()
    
    # 1. Connection
    print("Testing connection...")
    try:
        await db.documentdb_connect()
        print("Connected successfully.")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    collection_name = 'test_races'
    
    # 2. Write (Insert)
    print(f"Testing write to {collection_name}...")
    data = {"race_name": "Test Race", "race_id": 12345, "status": "active"}
    try:
        await db.write(collection_name, data)
        print("Write successful.")
    except Exception as e:
        print(f"Write failed: {e}")

    # 3. Read
    print(f"Testing read from {collection_name}...")
    query = {"race_id": 12345}
    try:
        results = await db.read(collection_name, query)
        print(f"Read results: {results}")
    except Exception as e:
        print(f"Read failed: {e}")

    # 4. Background Save
    print("Testing background save...")
    try:
        task = db.save_background(collection_name, {"race_name": "Background Race", "race_id": 67890})
        await asyncio.sleep(1) # Yield to let background task run
        print("Background save task initiated.")
    except Exception as e:
        print(f"Background save failed: {e}")

    # 5. Batch Read
    print("Testing batch read...")
    try:
        async for doc in db.read_batch(collection_name, {}, batch_size=2):
            print(f"Batch Item: {doc}")
    except Exception as e:
        print(f"Batch read failed: {e}")

    # 6. Indexing
    print("Testing indexing...")
    try:
        # Example index on race_id
        await db.create_indexes(collection_name, [("race_id", 1)])
        print("Index creation successful.")
    except Exception as e:
        print(f"Index creation failed: {e}")
        
    print("Test complete.")

if __name__ == '__main__':
    try:
        asyncio.run(test_documentdb())
    except KeyboardInterrupt:
        pass
