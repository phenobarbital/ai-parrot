import asyncio
from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.loaders import (
    PDFLoader
)

async def process_pdf():
    llm = VertexLLM(
        model='gemini-1.5-flash-001',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    # Add LLM
    doc = BASE_DIR.joinpath('documents', 'AR_Certification_Skill_Practice_Scorecard_EXAMPLE.pdf')
    print(':: Processing: ', doc)
    # PDF Files
    loader = PDFLoader(
        doc,
        source_type=f"PDF {doc.name}",
        llm=llm.get_llm(),
        language="en",
        parse_images=False,
        page_as_images=True
    )
    docs = loader.load()
    print('DOCS > ', docs)

if __name__ == "__main__":
    agent = asyncio.run(process_pdf())
