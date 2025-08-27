import asyncio
from pathlib import Path
from parrot.loaders.ppt import PowerPointLoader

async def load_file(filename):
    loader = PowerPointLoader(Path(filename))
    docs = await loader.load()
    print(docs)
    print(' :: Print the First document extracted ::')
    print(docs[0])


if __name__ == "__main__":
    file = '/home/ubuntu/symbits/files/Nextstop Mockup V0.51.pptx'
    asyncio.run(load_file(file))
