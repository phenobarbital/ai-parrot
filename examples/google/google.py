import asyncio
from navconfig import BASE_DIR
from parrot.clients.google import GoogleGenAIClient, GoogleModel

async def test_video_understanding():
    """Test video understanding with Google GenAI."""
    google = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_FLASH_IMAGE_PREVIEW)
    # Sample video from Workday about clocking in and out
    workday_video = BASE_DIR.joinpath(
        "examples", "google", "Clocking_in_and_out_via_Workday.mp4"
    )
    async with google as client:
        response = await client.video_understanding(
            video=workday_video,
            prompt="""
Analyze the video and extract step-by-step instructions for employees to follow, and the spoken text into quotation marks, related to Clocking In and Out in Workday.
""",
            stateless=True,
            prompt_instruction="""
            Video Analysis Instructions:
            1. Videos are training materials for employees to learn how to use Workday.
            2. There are several step-by-step processes shown in the video, with screenshots and spoken text.
            3. Break down the video into distinct scenes based on changes in visuals or context.
            4. For each scene, extract all step-by-step instructions, including any spoken text in quotation marks.
            5. Place each caption into an object with the timecode of the caption in the video.
            """,
            temperature=0.2
        )
        print("Video Understanding Response:\n", response)


if __name__ == "__main__":
    asyncio.run(test_video_understanding())
