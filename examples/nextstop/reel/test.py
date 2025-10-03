import asyncio
from pathlib import Path
from navconfig import BASE_DIR
from parrot.clients.google import GoogleGenAIClient
from parrot.models import VideoGenerationPrompt, GoogleModel



async def example_imagen_and_video():
    """Example: Generate image first using Imagen, then create video."""
    google = GoogleGenAIClient()
#     phrase = """
# Develop and implement strategies to improve Hisense brand visibility, including enhanced
# product placement, signage, and promotional activities."""
#     following_scene = "- Stores associates ordering hisense products on endcap - admiring a Hisense Signage - Doing promotional activities with customers"
#     image_prompt = f"Generate a high-quality, detailed visual prompt based on the abstract idea of '{phrase}', on a Best Buy Store, retail style, vibrant colors, professional photography, no text, no logo, no watermarks"
#     prompt = f"""
# We are creating a short video reel for Vendor representatives, for today's visit to the store:
# - The video should start with a dynamic opening shot that captures the essence of '{phrase}'
# - Follow with scenes showing {following_scene}
# IMPORTANT:
#   - No text overlays or captions or subtitles should be included in the video.
#   - The video should maintain a professional and polished look, suitable for a corporate audience.
#     """

    prompt = """
    - put the logo in a white background, Nextstop text below the logo.
    - do fast zoom in to the logo and fade it to white.
"""

    async with google as client:
        result = await client.video_generation(
            prompt_data=prompt,
            model=GoogleModel.VEO_3_0_FAST,
            reference_image=BASE_DIR / "examples" / "nextstop" / "reel" / "thumbnail_digital_ecosystem_logo.png",
            # generate_image_first=True,
            # image_prompt=image_prompt,
            # image_generation_model="imagen-4.0-generate-001",
            aspect_ratio="9:16",
            output_directory=BASE_DIR / "examples" / "nextstop" / "reel" / "outputs",
            resolution="720p",
            negative_prompt="ugly, low quality, static, weird physics"
        )

    print(f"Used image generation: {result.metadata['image_generation_used']}")


if __name__ == "__main__":
    asyncio.run(example_imagen_and_video())
