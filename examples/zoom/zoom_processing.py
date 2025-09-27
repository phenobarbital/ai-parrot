import asyncio
from navconfig import BASE_DIR
from parrot.loaders.audio import AudioLoader

RECORDING_SAMPLE = BASE_DIR / "examples" / "zoom" / "call_recording_1a564a4a_faa9_484c_a1bf_215a7f8ce878_20250925165311.mp3"


async def process_audio():
    loader = AudioLoader(
        source=[RECORDING_SAMPLE],
        source_type="AUDIO",
        language="en",
        chunk_size=1000,
        chunk_overlap=200,
        summarization=True,
        diarization=True,
    )
    docs = await loader.load()
    print("DOCS > ", docs)
    return docs


if __name__ == "__main__":
    agent = asyncio.run(process_audio())
