import asyncio
from pathlib import Path
from parrot.loaders import PowerPointLoader, PDFLoader

async def load_file(filename):
    loader = PowerPointLoader()
    docs = await loader.load(Path(filename))
    print(docs)
    print(' :: Print the First document extracted ::')
    print(docs[0])


async def load_pdf(filename):
    loader = PDFLoader()
    docs = await loader.load(Path(filename))
    print(docs)
    print(' :: Print the First document extracted ::')
    print(docs[1])


if __name__ == "__main__":
    file = '/home/ubuntu/symbits/files/Nextstop Mockup V0.51.pptx'
    pdf = "/home/ubuntu/symbits/primo/bot/SRS BJ'S ReadyRefresh Manual 2024.pdf"
    # asyncio.run(load_file(file))
    asyncio.run(load_pdf(pdf))
