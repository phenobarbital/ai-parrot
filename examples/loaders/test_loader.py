import asyncio
from navconfig import BASE_DIR
from parrot.loaders.txt import TextLoader


async def test_loader():
    a = BASE_DIR.joinpath('..', 'navigator-ai', 'documents').resolve()
    loader = TextLoader(path=a)
    async with loader as ld:
        result = await ld.load()
        print(result)
        print(f"Loaded {len(result)} documents")


if __name__ == "__main__":
    asyncio.run(test_loader())
