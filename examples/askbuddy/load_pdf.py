"""
Load RFP documents into bot.
"""
import asyncio
from navconfig import BASE_DIR
from pprint import pprint
from pathlib import Path
from parrot.chatbots.basic import Chatbot
from parrot.llms.vertex import VertexLLM
from parrot.loaders import (
    PDFLoader
)

async def get_agent():
    llm = VertexLLM(
        model='gemini-1.5-pro',
        temperature=0.1,
        top_k=30,
        Top_p=0.5,
    )
    agent = Chatbot(
        name='AskBuddy',
        llm=llm
    )
    # Add LLM
    await agent.configure()
    # directory = BASE_DIR.joinpath("docs", "askbuddy")
    directory = Path('/home/jesuslara/proyectos/navigator/navigator-ai').joinpath("docs", "askbuddy")
    for filename in directory.glob('*.pdf'):
        # Loading File by File to avoid overheat in database
        print(':: Processing: ', filename)
        # PDF Files
        loader = PDFLoader(
            filename,
            source_type=f"MSO {filename.name}",
            llm=llm.get_llm(),
            language="en",
            parse_images=False,
            page_as_images=True
        )
        docs = loader.load()
        pprint(docs)
        await agent.load_documents(
            docs
        )
    return agent




if __name__ == "__main__":
    agent = asyncio.run(get_agent())
