import asyncio
from navconfig import BASE_DIR
from parrot.tools.file import FileManagerTool


async def sample_usage():
    file_tool = FileManagerTool(
        manager_type="fs"
    )
    result = await file_tool._execute(
        operation="list",
        path=BASE_DIR.joinpath("docs/"),
        pattern="*.md"
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(sample_usage())
