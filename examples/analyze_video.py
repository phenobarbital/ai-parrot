import asyncio
from pathlib import Path
from pprint import pprint
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
        language="en",
        compress_speed=True
    )
    docs = loader.extract()
    pprint(docs)
    print('========')
    pprint(docs[0])


if __name__ == '__main__':
    doc = Path(
        '/home/jesuslara/proyectos/navigator-ai'
    ).joinpath('docs', 'askbuddy', 'videos', 'MSO Rally Call - Sep 6 2024.mp4')
    # doc = BASE_DIR.joinpath('documents', 'video_2024-09-11_19-43-58.mp4')
    asyncio.run(
        process_video(doc)
    )
