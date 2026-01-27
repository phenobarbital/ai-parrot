import asyncio
from parrot.clients.google import GoogleGenAIClient

async def main():
    client = GoogleGenAIClient()
    response = await client.generate_image(
        prompt="A futuristic city in cyberpunk style",
        aspect_ratio="16:9",
        output_directory="./output_images"
    )
    print(f"Image saved to: {response.images}")

if __name__ == "__main__":
    asyncio.run(main())