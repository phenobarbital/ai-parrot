import asyncio
from navconfig import BASE_DIR
from parrot.loaders import VideoLocalLoader


async def load_video(path):
    # Single video
    loader = VideoLocalLoader(
        source=path,
        diarization=True
    )
    documents = await loader.load()
    print(documents)
    print(' :: Finished loading Video :: ')

if __name__ == "__main__":
    path = BASE_DIR.joinpath('examples', 'loaders', 'Nishesh Follow Up-20250929_170228-Meeting Recording.mp4')
    asyncio.run(load_video(path))
    print(' :: Finished loading Video :: ')
