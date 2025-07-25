import asyncio
from navconfig import BASE_DIR
from parrot.loaders import (
    PDFLoader
)

async def process_pdf():
    # Add LLM
    doc1 = BASE_DIR.joinpath('documents', 'AR_Certification_Skill_Practice_Scorecard_EXAMPLE.pdf')
    doc2 = BASE_DIR.joinpath('documents', 'Day 1_Essentials_AR_PPT.pdf')
    docs = [doc1, doc2]
    # PDF Files
    loader = PDFLoader(
        docs,
        source_type="PDF",
        language="en",
        parse_images=False,
        summarization=True,  # Enable summarization
        page_as_images=True
    )
    docs = await loader.load()
    print('DOCS > ', docs)

if __name__ == "__main__":
    agent = asyncio.run(process_pdf())
