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
    embed_model = {
        "model": "thenlper/gte-base",
        "model_type": "huggingface"
    }
    agent.define_store(
        vector_store='postgres',
        embedding_model=embed_model,
        dsn="postgresql+asyncpg://troc_pgdata:12345678@127.0.0.1:5432/navigator",
        dimension=768,
    )
    await agent.configure()
    directory = Path('/home/jesuslara/proyectos/navigator/navigator-ai').joinpath("docs", "askbuddy")
    # for filename in directory.glob('*.pdf'):
        # Loading File by File to avoid overheat in database
        # PDF Files
    loader = PDFLoader(
        directory,
        source_type=f"MSO",
        language="en",
        parse_images=False,
        as_markdown=True,
        use_chapters=True
    )
    docs = await loader.load()
    pprint(docs)
    await agent.store.add_documents(
        table='employee_information',
        schema='mso',
        documents=docs
    )
    return agent




if __name__ == "__main__":
    agent = asyncio.run(get_agent())
