import asyncio
from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.loaders.videolocal import (
    VideoLocalLoader
)




async def process_video(doc):
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    print(':: Processing: ', doc)
    loader = VideoLocalLoader(
        doc,
        source_type=f"Video {doc.name}",
        llm=llm.get_llm(),
        language="en"
    )
    docs = loader.extract()
    print('DOCS > ', docs)


if __name__ == '__main__':
    doc = BASE_DIR.joinpath('documents', 'video_2024-09-11_19-43-58.mp4')
    asyncio.run(
        process_video(doc)
    )
