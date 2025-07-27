"""
Load RFP documents into bot.
"""
import asyncio
from pprint import pprint
from pathlib import Path
from parrot.bots.basic import BasicBot
from parrot.loaders import (
    PDFLoader
)

async def get_agent():
    agent = BasicBot(
        name='AskBuddy'
    )
    # Add LLM
    await agent.configure()
    directory = Path('/home/jesuslara/proyectos/navigator/navigator-ai').joinpath("docs", "askbuddy")
    for filename in directory.glob('*.pdf'):
        # Loading File by File to avoid overheat in database
        print(':: Processing: ', filename)
        # PDF Files
        loader = PDFLoader(
            filename,
            source_type=f"MSO {filename.name}",
            language="en",
            parse_images=False,
            page_as_images=True
        )
        docs = await loader.load()
        pprint(docs)
        await agent.store.add_documents(
            docs
        )
    return agent




if __name__ == "__main__":
    agent = asyncio.run(get_agent())
