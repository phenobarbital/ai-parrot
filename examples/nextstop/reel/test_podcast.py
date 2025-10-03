import asyncio
from pathlib import Path
from navconfig import BASE_DIR
from parrot.clients.google import GoogleGenAIClient
from parrot.models import VideoGenerationPrompt, GoogleModel



async def example_podcast():
    """Example: Generate a podcast narration using TTS."""
    google = GoogleGenAIClient()
    language = "en-US"
    BASE_OUTPUT_DIR = BASE_DIR / "examples" / "nextstop" / "reel" / "outputs"
    BASE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    podcast_name = BASE_OUTPUT_DIR / "podcast_voice.wav"
    script_name = BASE_OUTPUT_DIR / "podcast_script.txt"
    content = """
Welcome to your Nextstop Video reel, showcasing the highlights of our next store visit.

What's is your work for today's visit:
- Successfully trained Best Buy reps.
- Continued focus on follow-up with reps to assess training impact.
- Maintained strong customer and staff engagement.
- Follow-up with reps is your consistent priority.

and your next steps?:
• Prioritize follow-up with reps to evaluate training effectiveness and customer interaction
improvements.
• Consider expanding training to new locations to broaden impact.
• Develop and implement strategies to improve Hisense brand visibility, including enhanced
product placement, signage, and promotional activities.
• Monitor competitive landscape regularly to anticipate and respond to market changes.

Thank you for being part of the T-ROC Nextstop experience.

Let's make this visit a success!
    """
    try:
        async with google as client:
            # 1. Generate the conversational script and podcast:
            response = await client.create_speech(
                content=content,
                output_directory=BASE_OUTPUT_DIR,
                only_script=False,
                script_file=script_name,
                podcast_file=podcast_name,
                language=language,
            )
            print(f"Podcast narration saved to: {podcast_name}")
    except Exception as e:
        print(f"Error during podcast generation: {e}")
        return None


if __name__ == "__main__":
    asyncio.run(example_podcast())
