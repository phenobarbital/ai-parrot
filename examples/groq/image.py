import base64
from pathlib import Path
from PIL import Image, ImageEnhance
from io import BytesIO
from groq import Groq
from parrot.conf import GROQ_API_KEY



ENTRANCE_PROPT = """
I am a brand ambassador entering into an store, what can you tell me about the entrance, cleanness, as expected customer experience
Please provide a detailed report addressing the following points:
- Overall Organization and condition
- Cleaning Condition
- Specific Observations
- Are there any safety hazards?
"""

ENDCAP_PROMPT = """
We are EPSON field representatives, visiting stores and making sure products are displayed, end caps are well put together, labels are right, and the customer experience is great.
Analyze the provided image of a retail endcap. Please provide a detailed report addressing the following points:

**Statistics:**
- number of shelves and percent of occupation per shelf
- Identify the shelves as "top", "middle", "bottom"
- number of products on shelves, per shelf, and types
- Extract the brand and product name for each printer, if possible.
- Identify any non-Epson product as competitive products

**Overall Organization and condition:**
- Describe the general layout and organization of the products. Is it neat, cluttered, or somewhere in between?
- Are products consistently aligned and facing forward?
- Are there any noticeable gaps or empty spaces that suggest restocking is needed?

**Cleaning Condition:**
- Assess the cleanliness of the endcap. Are there visible signs of dust, dirt, spills, or other debris?
- Are the shelves and products themselves clean?
- Is there any trash present? if so describe where and if is a non-shopping product
- Are there any non-printer or non-ink related products present? If so, list them and describe their location.

**Specific Observations:**
- Note any other relevant observations about the endcap's condition or presentation.
- Are there any damaged or misplaced labels?
- Are there any safety hazards?
- Please provide a concise summary of your findings, highlighting any areas that require attention.

**IMPORTANT:** take care about the following instructions:
 * identify a shelf by the pricing label (with a QR code) identifying the product.
"""


def image_prompt(client, image_data: str):
    completion = client.chat.completions.create(
        model="llama-3.2-90b-vision-preview",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": ENDCAP_PROMPT
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data
                        }
                    }
                ]
            }
        ],
        temperature=1,
        max_completion_tokens=1024,
        top_p=1,
        stream=False,
        stop=None,
    )
    print(completion.choices[0].message)

def process_images(client, images_path):
    # Iterate through all images in the directory
    # List to hold the Base64 encoded image strings
    for image_path in images_path.glob("*.jpeg"):
        with Image.open(image_path) as img:
            # Enhance the image
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(1.5)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.5)
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(1.5)
            # Save the enhanced image to a buffer in JPEG format
            buffer = BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            # Encode the image in Base64
            base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
            image_content = f"data:image/jpeg;base64,{base64_image}"
            image_prompt(client, image_content)
            buffer.close()


if __name__ == "__main__":
    # Create a Groq client
    client = Groq(
        api_key=GROQ_API_KEY
    )
    images_path = Path(
        "/home/ubuntu/symbits/bridgestone/photos"
    ).resolve()
    process_images(client, images_path)
