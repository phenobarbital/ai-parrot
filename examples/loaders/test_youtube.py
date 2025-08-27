import asyncio
from parrot.loaders.youtube import YoutubeLoader


async def load_youtube(url):
    # Single video
    loader = YoutubeLoader([url])
    documents = await loader.load()
    print(documents)
    print(' :: Finished loading Youtube video :: ')

    # # Multiple videos concurrently
    # loader = YoutubeLoader([
    #     'https://www.youtube.com/watch?v=XS088Opj9o0',
    #     'https://www.youtube.com/watch?v=qeMFqkcPYcg'
    # ])
    # documents = await loader.load()


if __name__ == "__main__":
    URL = "https://www.youtube.com/watch?v=NDq2LNDBOqU"
    asyncio.run(load_youtube(URL))
    print(' :: Finished loading Youtube video :: ')
