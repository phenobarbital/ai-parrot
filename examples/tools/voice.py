import asyncio
from parrot.tools.gvoice import GoogleTTSTool

async def example_usage():
    # Create tool instance
    tts_tool = GoogleTTSTool()

    # Basic text-to-speech
    result = await tts_tool.execute(
        text="Hello world! This is a test of the Google Text-to-Speech system.",
        voice_gender="FEMALE",
        language_code="en-US",
        output_format="MP3"
    )

    # Markdown to speech with custom voice
    markdown_text = '''# Welcome to Our Podcast

    ## Today's Topic: AI and Machine Learning

    Today we'll discuss:
    - **Neural networks** and deep learning
    - *Natural language processing*
    - The future of AI

    Visit [our website](https://example.com) for more information!
    '''

    result = await tts_tool.execute(
        text=markdown_text,
        voice_model="en-US-Neural2-F",
        speaking_rate=1.1,
        pitch=2.0,
        file_prefix="ai_podcast_episode_1"
    )

    # Spanish speech synthesis
    response = await tts_tool.execute(
        text="Hola mundo! Bienvenidos a nuestro podcast en español.",
        language_code="es-ES",
        voice_gender="MALE",
        output_format="OGG_OPUS"
    )
    result = response.result
    print(f"Audio generated: {result['file_url']}")
    print(f"Duration: ~{result['synthesis_info']['estimated_duration_seconds']} seconds")
    print(f"Voice used: {result['synthesis_info']['voice_model']}")

    # Preview SSML
    ssml_preview = tts_tool.preview_ssml("# Hello\n\nThis is **bold** text.")
    print("SSML Preview:", ssml_preview)

    # Cost estimation
    cost_info = tts_tool.estimate_cost(markdown_text)
    print(f"Estimated cost: ${cost_info['estimated_cost_usd']}")

    # Get available voices
    voices = tts_tool.get_available_voices("en-US")
    print("Available EN-US voices:", voices)


if __name__ == "__main__":
    # Run the example usage
    asyncio.run(example_usage())
    # Note: Ensure that the Google Cloud credentials are set up correctly for TTS to work.
