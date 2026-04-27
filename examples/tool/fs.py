"""FileManagerToolkit example — preferred API.

Demonstrates how to use ``FileManagerToolkit`` where each file operation is a
separate, focused tool.  Unlike the legacy ``FileManagerTool`` (which required
an ``operation`` dispatch field), the toolkit exposes each operation as its own
callable with a minimal, unambiguous schema.

Run::

    source .venv/bin/activate
    python examples/tool/fs.py
"""
import asyncio
from navconfig import BASE_DIR
from parrot.tools import FileManagerToolkit


async def sample_usage():
    """Demonstrate core FileManagerToolkit operations."""

    # Create toolkit with local filesystem backend.
    # Each file operation becomes a separate tool: fs_list_files, fs_create_file, etc.
    toolkit = FileManagerToolkit(manager_type="fs")

    # Inspect which tools are available
    print("Available tools:", toolkit.list_tool_names())

    # --- list_files: focused schema, no 'operation' field needed ---
    result = await toolkit.list_files(
        path=str(BASE_DIR / "docs"),
        pattern="*.md",
    )
    print(f"Markdown files found: {result['count']}")
    for f in result["files"][:3]:
        print(f"  {f['name']} ({f['size']} bytes)")

    # --- create_file: create a demo output file ---
    create_result = await toolkit.create_file(
        path="output/hello_toolkit.txt",
        content="Hello from FileManagerToolkit!\n",
    )
    print(f"Created: {create_result['path']}")

    # --- file_exists: check it was written ---
    exists_result = await toolkit.file_exists(path=create_result["path"])
    print(f"File exists: {exists_result['exists']}")

    # --- get_file_metadata: inspect the new file ---
    meta_result = await toolkit.get_file_metadata(path=create_result["path"])
    print(f"Metadata — size: {meta_result['size']} bytes, type: {meta_result['content_type']}")

    # --- delete_file: clean up ---
    del_result = await toolkit.delete_file(path=create_result["path"])
    print(f"Deleted: {del_result['deleted']}")


# ---------------------------------------------------------------------------
# Legacy usage (kept for reference — prefer FileManagerToolkit above)
# ---------------------------------------------------------------------------
#
# from parrot.tools import FileManagerTool
#
# async def legacy_usage():
#     file_tool = FileManagerTool(manager_type="fs")
#     result = await file_tool._execute(
#         operation="list",
#         path=BASE_DIR.joinpath("docs/"),
#         pattern="*.md",
#     )
#     print(result)
#
# if __name__ == "__main__":
#     asyncio.run(legacy_usage())


if __name__ == "__main__":
    asyncio.run(sample_usage())
