import asyncio
from parrot.loaders.web import WebLoader

async def load_web():
    loader = WebLoader(browser="chrome")
    docs = await loader.load("https://trocglobal.com")
    print(docs)


if __name__ == "__main__":
    asyncio.run(load_web())
