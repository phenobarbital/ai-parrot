import asyncio
from parrot.loaders.pdfmark import PDFMarkdownLoader

async def load_pdf(filename):
    # Auto-select best backend
    loader = PDFMarkdownLoader(filename)
    docs = await loader.load()
    print(docs)

    print(' :: Print the First document extracted ::')
    # Force specific backend
    loader = PDFMarkdownLoader(
        filename,
        markdown_backend="markitdown"
    )
    docs = await loader.load()
    print(docs)
    print(' :: Print the Second document extracted ::')

    # Configure chunking
    loader = PDFMarkdownLoader(
        filename,
        chunk_size=2048,
        chunk_overlap=50,
        preserve_tables=True
    )
    # Load documents
    docs = await loader.load()
    print(docs)
    print(' :: Print the Third document extracted ::')

if __name__ == "__main__":
    pdf = "/home/ubuntu/symbits/primo/bot/SRS BJ'S ReadyRefresh Manual 2024.pdf"
    asyncio.run(load_pdf(pdf))
