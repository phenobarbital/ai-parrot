from typing import Any, List, Optional, Union
from enum import Enum
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from navconfig import BASE_DIR
from parrot.clients import GoogleGenAIClient, GoogleModel
from parrot.models import (
    ImageGenerationPrompt,
    SpeechGenerationPrompt,
    VideoGenerationPrompt,
    SpeakerConfig
)
from parrot.models.google import ConversationalScriptConfig, FictionalSpeaker
from parrot.tools.math import MathTool

async def main():
    # question = "Give me a list of 10 European cities and their capitals. Use a list format."

    # print("\n--- Asking Google GenAI ---")
    # async with GoogleGenAIClient() as client:
    #     response = await client.ask(
    #         question
    #     )
    #     print(response.output)                    # Response text
    #     print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
    #     print(response.usage.completion_tokens) # 5 (from usage_metadata)
    #     print(response.usage.total_tokens)      # 110 (from usage_metadata)
    #     print(response.provider)                # "vertex_ai"

    # async with GoogleGenAIClient() as client:
    #     math_tool = MathTool()

    #     # Register the tool's methods
    #     client.register_tool(
    #         math_tool
    #     )
    #     # question = "What is 150 plus 79, and also what is 1024 divided by 256?"
    #     question = "use the tool for calculate (245*38)/3"
    #     response = await client.ask(
    #         question,
    #     )
    #     print('--- Google GenAI Tool Call Response ---')
    #     print(response.output)                    # Response text
    #     print(response.usage.prompt_tokens)     # 39 (from usage_metadata)
    #     print(response.usage.completion_tokens) # 5 (from usage_metadata)
    #     print(response.usage.total_tokens)      # 110 (from usage_metadata)
    #     print(response.provider)                # "google_genai"
    #     print("Has tools:", response.has_tools)
    #     print("Tool calls:", [f"{tc.name}({tc.arguments}) = {tc.result}" for tc in response.tool_calls])
    #     print("Total execution time:", sum(tc.execution_time for tc in response.tool_calls))

    #     response = await client.ask(
    #         "What is the result of multiplying 5 and 10?"
    #     )
    #     print('--- Google AI Tool Call Response ---')
    #     print(response.output)                    # Response text

    #     print('Math Tool Results:')
    #     class MathOperations(BaseModel):
    #         addition_result: float
    #         multiplication_result: float
    #         explanation: str

    #     math_response = await client.ask(
    #         "use the tool and calculate 12 + 8 and 6 * 9, then format the results",
    #         structured_output=MathOperations,
    #     )
    #     print("Structured math response:")
    #     print("- Is structured:", math_response.is_structured)
    #     print("- Output type:", type(math_response.output))
    #     print("- Math data:", math_response.output)
    #     print("- Parallel tools used:", len(math_response.tool_calls))

    #     # Register multiple tools for parallel execution
    #     def add_numbers(a: float, b: float) -> float:
    #         """Add two numbers."""
    #         return a + b

    #     def multiply_numbers(a: float, b: float) -> float:
    #         """Multiply two numbers."""
    #         return a * b

    #     client.register_tool(
    #         name="add_numbers",
    #         description="Add two numbers together",
    #         input_schema={
    #             "type": "object",
    #             "properties": {
    #                 "a": {"type": "number", "description": "First number"},
    #                 "b": {"type": "number", "description": "Second number"}
    #             },
    #             "required": ["a", "b"]
    #         },
    #         function=add_numbers
    #     )

    #     client.register_tool(
    #         name="multiply_numbers",
    #         description="Multiply two numbers together",
    #         input_schema={
    #             "type": "object",
    #             "properties": {
    #                 "a": {"type": "number", "description": "First number"},
    #                 "b": {"type": "number", "description": "Second number"}
    #             },
    #             "required": ["a", "b"]
    #         },
    #         function=multiply_numbers
    #     )

    #     # Parallel tool execution
    #     response = await client.ask(
    #         "Calculate both: 5 + 3 and 4 * 7. Use the appropriate tools for each calculation.",
    #         model=GoogleModel.GEMINI_2_5_FLASH
    #     )
    #     print("Response text:", response.output)
    #     print("Model used:", response.model)
    #     print("Provider:", response.provider)
    #     print("Has tools:", response.has_tools)
    #     print("Tool calls:", [f"{tc.name}({tc.arguments}) = {tc.result}" for tc in response.tool_calls])
    #     print("Total execution time:", sum(tc.execution_time for tc in response.tool_calls))

    # memory = GoogleGenAIClient.create_conversation_memory("memory")
    # async with GoogleGenAIClient(conversation_memory=memory) as client:
    #     math_tool = MathTool()
    #     # Conversation with memory
    #     user_id = "user123"
    #     session_id = "chat001"

    #     client.register_tool(math_tool)

    #     # await client.start_conversation(user_id, session_id, "You are a helpful math assistant.")

    #     response1 = await client.ask(
    #         "My lucky numbers are 3 and 7",
    #         user_id=user_id,
    #         session_id=session_id,
    #         model=GoogleModel.GEMINI_2_5_FLASH,
    #     )
    #     print("Response 1 text:", response1.output)

    #     response2 = await client.ask(
    #         "Add my two lucky numbers together using the add function and multiply by 7",
    #         user_id=user_id,
    #         session_id=session_id,
    #         model=GoogleModel.GEMINI_2_5_FLASH
    #     )
    #     print("Response 2:", response2)
    #     print("Tools used:", [tc.name for tc in response2.tool_calls])

    # print('Using Google GenAI Client with conversation memory:')
    # memory = GoogleGenAIClient.create_conversation_memory("memory")
    # user_id = "user123"
    # session_id = "google_session_010"
    # async with GoogleGenAIClient(conversation_memory=memory) as client:
    #     # Streaming response
    #     print("Streaming response:")
    #     async for chunk in client.ask_stream(
    #         "Tell me an interesting fact about mathematics",
    #         temperature=0.7,
    #         model=GoogleModel.GEMINI_2_5_FLASH,
    #         user_id=user_id,
    #         session_id=session_id
    #     ):
    #         print(chunk, end="", flush=True)
    #     print()  # New line after streaming

    #     # For questions that definitely need search
    #     response = await client.ask(
    #         "What are the latest Python releases?",
    #         force_tool_usage="builtin_tools"
    #     )
    #     print("Search response text:", response.text)

    #     class MathOperations(BaseModel):
    #         addition_result: float
    #         multiplication_result: float
    #         explanation: str

    #     math_response = await client.ask(
    #         "Calculate 12 + 8 and 6 * 9, then format the results",
    #         structured_output=MathOperations,
    #         model=GoogleModel.GEMINI_2_5_FLASH
    #     )
    #     print("Structured math response:")
    #     print("- Is structured:", math_response.is_structured)
    #     print("- Output type:", type(math_response.output))
    #     print("- Math data:", math_response.output)
    #     print("- Parallel tools used:", len(math_response.tool_calls))

    # print(' --- Video Features --- ')
    # async with GoogleGenAIClient() as client:
    #     # video generation:
    #     prompt_data = VideoGenerationPrompt(
    #         # prompt="a Bison running for cover in a dense forest, a close-up shot of the bison's face, with the camera following its movement, is cold and we can see the bison's breath in the air, the camera is moving quickly to keep up with the bison, the bison is running through a dense forest with snow on the ground, the camera is following the bison's movement, the bison is running for cover in a dense forest, a close-up shot of the bison's face, with the camera following its movement, is cold and we can see the bison's breath in the air, the camera is moving quickly to keep up with the bison",
    #         #prompt="Un peluche de gato con alas volando en un cielo azul con nubes esponjosas, el peluche tiene un diseño colorido y amigable, las alas son grandes y suaves, el cielo es brillante y soleado, el peluche parece feliz mientras vuela entre las nubes",
    #         #styles=["fantasy", "whimsical"],
    #         prompt="Una amable señora en un paisaje de la Toscana Italiana tejiendo crochet bajo un árbol de olivo, el sol brilla suavemente, creando un ambiente cálido y acogedor, la señora sonríe mientras trabaja en su proyecto de crochet, rodeada de campos verdes y colinas suaves",
    #         styles=["photorealistic", "warm"],
    #         number_of_videos=1,
    #         model=GoogleModel.VEO_3_0,
    #         aspect_ratio="16:9",
    #         duration=8,  # Duration in seconds
    #     )
    #     output_directory = BASE_DIR.joinpath('static', 'generated_videos')
    #     output_directory.mkdir(parents=True, exist_ok=True)

    #     response = await client.generate_videos(
    #         prompt=prompt_data,
    #         output_directory=output_directory,
    #         mime_format="video/mp4",
    #     )
    #     print("Generated videos:")
    #     for video in response.videos:
    #         print(f"✅ Video saved to: {video.video}")

    print(' --- Image Features --- ')
    async with GoogleGenAIClient() as client:
        # Image Generation:
        prompt_data = ImageGenerationPrompt(
            prompt="A futuristic city skyline at sunset, with flying cars and neon lights, the buildings are tall and sleek, reflecting the vibrant colors of the sky, the scene is bustling with activity, showcasing a blend of technology and nature",
            styles=["photorealistic", "vibrant"],
            model=GoogleModel.IMAGEN_3,
            aspect_ratio="16:9",
            negative_prompt="no people, no buildings"
        )
        output_directory = BASE_DIR.joinpath('static', 'generated_images')
        output_directory.mkdir(parents=True, exist_ok=True)

        response = await client.generate_images(
            prompt_data=prompt_data,
            output_directory=output_directory,
            # output_mime_type="image/jpeg",
            number_of_images=3,  # Generate 3 images
            user_id="user123",
            session_id="session001"
        )
        print("Generated images:")
        for img in response.images:
            print(f"- {img}")

#     print(' --- Audio Features --- ')
#     async with GoogleGenAIClient() as client:
#         output_directory = BASE_DIR.joinpath('static', 'generated_audio')
#         output_directory.mkdir(parents=True, exist_ok=True)
#         print("--- Starting Single-Voice Speech Generation ---")
#         single_voice_prompt = SpeechGenerationPrompt(
#             prompt="Say cheerfully: Hello! Welcome to NextStop Report!",
#             speakers=[SpeakerConfig(name="Narrator", voice="zephyr")]
#         )

#         speech_result_1 = await client.generate_speech(
#             prompt_data=single_voice_prompt,
#             output_directory=output_directory
#         )

#         if speech_result_1 and speech_result_1.files:
#             print(f"✅ Single-voice speech saved to: {speech_result_1.files[0]}")

#         # --- 2. Multi-Voice Example ---
#         print("--- Starting Multi-Voice Speech Generation ---")
#         multi_voice_prompt = SpeechGenerationPrompt(
#             prompt="""
# Jesus: How are you today, Lara?
# Lara: I'm doing great, thanks for asking, Jesus! How about you?
# Jesus: I'm feeling fantastic!
#             """,
#             speakers=[
#                 SpeakerConfig(name="Jesus", voice="enceladus"),
#                 SpeakerConfig(name="Lara", voice="vindemiatrix"),
#             ]
#         )

#         speech_result_2 = await client.generate_speech(
#             prompt_data=multi_voice_prompt,
#             output_directory=output_directory,
#         )

#         if speech_result_2 and speech_result_2.files:
#             print(f"✅ Multi-voice speech saved to: {speech_result_2.files[0]}")
#         else:
#             print("❌ Failed to generate multi-voice speech.")

        # Image Clasification:
    # async with GoogleGenAIClient() as client:
    #     class ImageCategory(str, Enum):
    #         """Enumeration for retail image categories."""
    #         INK_WALL = "Ink Wall"
    #         SHELVES_WITH_PRODUCTS = "Shelves with Products"
    #         PRODUCTS_ON_FLOOR = "Products on Floor"
    #         MERCHANDISING_ENDCAP = "Merchandising Endcap"
    #         OTHER = "Other"

    #     class ImageClassification(BaseModel):
    #         """Schema for classifying a retail image."""
    #         category: ImageCategory = Field(..., description="The best-fitting category for the image based on the provided definitions.")
    #         confidence_score: float = Field(..., ge=0.0, le=1.0, description="The model's confidence in its classification, from 0.0 to 1.0.")
    #         reasoning: str = Field(..., description="A brief explanation for why the image was assigned to this category.")

        # classification_prompt = """
        # You are an expert in retail image analysis. Your task is to classify the provided image into one of the following categories.
        # Please read the definitions carefully and choose the single best fit.

        # Category Definitions:
        # - 'Ink Wall': The primary subject is a large wall or multi-shelf gondola where the **majority of shelf space is dedicated to small consumables like ink cartridges and toner**. The presence of a few larger, related items (like printers) does not disqualify this category if the dominant visual element is the dense array of small boxes.
        # - 'Shelves with Products': The image shows standard retail shelves displaying **predominantly larger products**, like printers, scanners, or other electronics. While some ink or consumables may be present, they are not the main focus of the display.
        # - 'Products on Floor': The primary subject is multiple product boxes stacked directly on the floor, not on shelves. This is often called a "pallet display" or "stack-out".
        # - 'Merchandising Endcap': The image shows a display at the **end of an aisle**, often featuring a specific promotion, brand, or a mix of products with prominent marketing signage. Location is key.
        # - 'Other': Use this category if the image does not clearly fit any of the above descriptions (e.g., a single product photo, a picture of a person, an outdoor scene).

        # Analyze the image and provide your classification in the requested JSON format.
        # """
    #     image_path = BASE_DIR.joinpath('static', "be51ca05-802e-4dfd-bc53-fec65616d569-recap.jpeg")
    #     classification_result = await client.ask_to_image(
    #         image=image_path,
    #         prompt=classification_prompt,
    #         structured_output=ImageClassification,
    #         model=GoogleModel.GEMINI_2_5_FLASH
    #     )
    #     print(classification_result)
    #     if classification_result and isinstance(classification_result.output, ImageClassification):
    #         # The code is assigning the output of a classification result to the variable `result` in
    #         # Python.
    #         result = classification_result.output
    #         print("\n✅ Classification Complete:\n")
    #         print(f"  - Category: {result.category.value}")
    #         print(f"  - Confidence: {result.confidence_score:.2f}")
    #         print(f"  - Reasoning: {result.reasoning}")
    #         print("\n" + "-"*40)

    # async with GoogleGenAIClient() as client:
    #     image_path = BASE_DIR.joinpath('static', "1bc3e9e8-3072-4c3a-8620-07fff9413a69-recap.jpeg")
    #     shaq = BASE_DIR.joinpath('static', "Shaq.jpg")
    #     response_shaq = await client.ask_to_image(
    #         image=image_path,
    #         reference_images=[shaq],
    #         prompt=(
    #             "First, analyze the image to see if Shaquille O'Neal (from the reference image) is present. "
    #             "If he is, describe his location in the image, including any notable features or context. "
    #             "Then, provide bounding boxes for his location. "
    #             "Format your entire response as a single JSON object with 'analysis' and 'detections' keys."
    #         ),
    #         model=GoogleModel.GEMINI_2_5_FLASH,
    #         count_objects=True
    #     )
    #     print("✅ analysis successful!")
    #     result = response_shaq.output
    #     print(f"Text Analysis: {result.analysis}")
    #     print(f"Detections Found: {len(result.detections)}")
    #     for box in result.detections:
    #         print(f"  - Label: {box.label}, Box: {box.box_2d}")
    #     # Product Detection
    #     image_path = BASE_DIR.joinpath('static', "e1ad2662-c624-4f9b-a7aa-7518613a893a-recap.jpeg")
    #     response_image = await client.ask_to_image(
    #         image=image_path,
    #         prompt=(
    #             "Analyze the image methodically: identify and count the products in the image, even if it's partially visible."
    #             " our main goal is to identify Epson products and competitive products in the image, "
    #             " Epson competitors are: HP, Canon, Brother, Lexmark, Xerox, Dell, Samsung, Ricoh, Konica Minolta, Kyocera, Sharp, Toshiba, Panasonic."
    #             " if there is no Epson or competitive products in the image, just say 'No Epson or competitive products found'. "
    #             " if there are Epson or competitive products in the image, please provide the following information: "
    #             "* Count number of products in the image (in box and unboxed) "
    #             "* Provide a list of the products with their brand, model and type (printers, scanners, etc.)"
    #             "* Provide a briefly description of the products "
    #         ),
    #         model=GoogleModel.GEMINI_2_5_FLASH,
    #     )
    #     print(response_image)
    #     print("Image response text:", response_image.text)


        # image_path = BASE_DIR.joinpath('static', "8455b202-28cf-4231-a9d9-7c175def0a93-recap.jpeg")
        # response_image = await client.ask_to_image(
        #     image_path=image_path,
        #     prompt=(
        #         "Analyze the image methodically: identify and count the products in the image, even if it's partially visible."
        #         "* Count number of products boxes on floor "
        #         "* Detect the brand of the products "
        #         "* Identify the type of products (printers, scanners, etc.) "
        #         "* Provide a briefly description of the products, extracting if possible the price and model "
        #         "* Provide a list of the products boxes with their brand, model and type "
        #     ),
        #     model=GoogleModel.GEMINI_2_5_FLASH
        # )
        # print(response_image)
        # print("Image response text:", response_image.text)

        # Ink-Wall Analysis:
        # class CleanlinessLevel(str, Enum):
        #     """Enumeration for cleanliness condition."""
        #     CLEAN = "Clean"
        #     SLIGHTLY_DUSTY = "Slightly Dusty"
        #     NEEDS_CLEANING = "Needs Cleaning"

        # class InkWallAnalysis(BaseModel):
        #     """Schema for a detailed retail ink-wall analysis."""
        #     epson_product_count: int = Field(..., description="The total count of all visible Epson branded products (boxed or unboxed).")
        #     competitor_product_count: int = Field(..., description="The total count of all visible competitor products (HP, Canon, Brother, etc.).")
        #     competitors_found: List[str] = Field(..., description="A list of competitor brand names found on the shelves.")
        #     shelf_occupancy_percentage: float = Field(..., description="An estimated percentage of how full the shelves are overall (0-100).")
        #     overall_condition: str = Field(..., description="A brief description of the overall condition of the ink wall (e.g., 'well-stocked', 'needs restocking'), evaluate product alignment, cleanliness, and any visible damage")
        #     has_gaps: bool = Field(..., description="True if there are noticeable empty spaces or gaps on the shelves where products should be.")
        #     gaps_description: Optional[str] = Field(None, description="A brief description of where the most significant gaps are located.")
        #     restocking_needed: bool = Field(..., description="True if the gaps or low stock levels suggest that restocking is required.")
        #     is_shelf_empty: bool = Field(..., description="True if any single shelf is completely empty, otherwise False.")
        #     misplaced_products_found: bool = Field(..., description="True if any product appears to be in the wrong location (e.g., an HP cartridge in an Epson section).")
        #     cleanliness_condition: CleanlinessLevel = Field(..., description="The overall cleanliness of the shelves and products.")
        #     trash_present: bool = Field(..., description="True if any visible trash, debris, or stray packaging is present on the shelves or floor.")


        # image_path = BASE_DIR.joinpath('static', "a95ac304-8636-4772-99e1-4ed6fabaded1-recap.jpeg")
        # analysis_result = await client.ask_to_image(
        #     image_path=image_path,
        #     prompt="""
        #     Analyze the provided image of a retail ink wall. Perform a detailed planogram and shelf-space analysis.
        #     Use the following list of known competitors to identify non-Epson products: ['HP', 'Canon', 'Brother', 'Lexmark'].
        #     Based on your visual analysis, populate all fields of the requested JSON schema.
        #     """,
        #     structured_output=InkWallAnalysis,
        #     model=GoogleModel.GEMINI_2_5_FLASH
        # )
        # print(analysis_result)
        # if analysis_result and isinstance(analysis_result.output, InkWallAnalysis):
        #     result = analysis_result.output
        #     print("\n✅ Analysis Complete. Structured Data Received:\n")
        #     print(f"  - Epson Products Count: {result.epson_product_count}")
        #     print(f"  - Competitor Products Count: {result.competitor_product_count}")
        #     print(f"  - Competitors Found: {', '.join(result.competitors_found) if result.competitors_found else 'None'}")
        #     print(f"  - Shelf Occupancy: {result.shelf_occupancy_percentage:.1f}%")
        #     print(f" - Overall Condition: {result.overall_condition}")
        #     print(f"  - Gaps Present: {result.has_gaps}")
        #     if result.has_gaps:
        #         print(f"    - Gap Description: {result.gaps_description}")
        #     print(f"  - Restocking Needed: {result.restocking_needed}")
        #     print(f"  - Completely Empty Shelf: {result.is_shelf_empty}")
        #     print(f"  - Misplaced Products: {result.misplaced_products_found}")
        #     print(f"  - Cleanliness: {result.cleanliness_condition.value}")
        #     print(f"  - Trash Present: {result.trash_present}")
        #     print("\n" + "-"*40)

        #     if result.restocking_needed:
        #         print("\nACTION REQUIRED: Restocking is needed based on the analysis.")

        # else:
        #     print("\n❌ Failed to get a structured analysis.")
        #     # Access the raw text via the .text property of the AIMessage
        #     print("Raw response:", analysis_result.text if analysis_result else "No response returned.")
#     memory = GoogleGenAIClient.create_conversation_memory("memory")
#     user_id = "user123"
#     session_id = "google_session_010"
#     async with GoogleGenAIClient(conversation_memory=memory) as client:
#         # do an iteration 3 times:
#         for _ in range(3):
#             # First interaction
#             response1 = await client.ask(
#                 "Hi, my name is Jesus and I love Python programming",
#                 user_id=user_id,
#                 session_id=session_id
#             )
#             print("Response 1:", response1.output)

#             # Second interaction with memory
#             response2 = await client.ask(
#                 "What's my name and what do I like?",
#                 user_id=user_id,
#                 session_id=session_id
#             )
#             print("Response 2:", response2.output)

#             # Third interaction with tools
#             response3 = await client.ask(
#                 "Can you search for recent Python news?",
#                 user_id=user_id,
#                 session_id=session_id,
#                 force_tool_usage="custom_functions"
#             )
#             print("Response 3:", response3.output)

#             # Check conversation history
#             history = await client.get_conversation(user_id, session_id)
#             if history:
#                 print(f"\nConversation summary:")
#                 print(f"Total turns: {len(history.turns)}")
#                 for i, turn in enumerate(history.turns):
#                     print(f"Turn {i+1}:")
#                     print(f"  User: {turn.user_message[:50]}...")
#                     print(f"  Assistant: {turn.assistant_response[:50]}...")
#                     if turn.tools_used:
#                         print(f"  Tools used: {', '.join(turn.tools_used)}")

async def test_scripter():
    output_directory = BASE_DIR.joinpath('static', 'generated_audio')
    output_directory.mkdir(parents=True, exist_ok=True)
    quarterly_report = """
Q2 2025 Financial Report for Innovate Corp.
Revenue reached $5.2M, a 15% increase quarter-over-quarter, driven primarily by the successful launch of our 'Project Nova' AI platform which accounted for 60% of new sales.
However, profit margins decreased from 25% to 22% due to increased R&D spending on 'Project Chimera', our next-gen quantum computing initiative.
User engagement is up 30%, with daily active users hitting a record 500,000.
Market expansion into Europe has been slower than projected, with only a 5% market penetration against a target of 15%.
"""
    memory = GoogleGenAIClient.create_conversation_memory("memory")
    user_id = "user123"
    session_id = "google_session_010"
    async with GoogleGenAIClient(conversation_memory=memory) as client:
        # 2. Define the script configuration
        script_config = ConversationalScriptConfig(
            context="A detailed analysis of Innovate Corp's Q2 2025 financial performance, focusing on revenue growth, profit margins, and market expansion.",
            speakers=[
                FictionalSpeaker(
                    name="Analyst", role="interviewer", characteristic="Mature", gender="female"
                ),
                FictionalSpeaker(
                    name="CEO", role="interviewee", characteristic="Smooth", gender="male"
                )
            ],
            report_text=quarterly_report,
            system_prompt="You are an expert financial analyst conducting a detailed review of Innovate Corp's quarterly performance."
        )

        # 3. Generate the conversational script
        response = await client.create_conversation_script(
            report_data=script_config,
            user_id=user_id,
            session_id=session_id,
            max_lines=10,  # Limit to 10 lines for brevity,
            use_structured_output=True  # Use structured output for TTS
        )
        print("Conversational Script Generated:")
        print(response.output)
        voice_prompt = response.output

        speech_result = await client.generate_speech(
            prompt_data=voice_prompt,
            output_directory=output_directory,
        )

        if speech_result and speech_result.files:
            print(f"✅ Multi-voice speech saved to: {speech_result.files[0]}")
        else:
            print("❌ Failed to generate multi-voice speech.")

async def create_image(prompt):
    print(' --- Image Features --- ')
    async with GoogleGenAIClient() as client:
        # Image Generation:
        prompt_data = ImageGenerationPrompt(
            prompt=prompt,
            styles=["photorealistic", "vibrant"],
            model=GoogleModel.IMAGEN_4,
            aspect_ratio="16:9",
            negative_prompt="no buildings"
        )
        output_directory = BASE_DIR.joinpath('static', 'generated_images')
        output_directory.mkdir(parents=True, exist_ok=True)

        response = await client.generate_images(
            prompt_data=prompt_data,
            output_directory=output_directory,
            # output_mime_type="image/jpeg",
            number_of_images=1,  # Generate 1 image
            user_id="user123",
            session_id="session001"
        )
        print("Generated images:")
        for img in response.images:
            print(f"- {img}")

if __name__ == "__main__":
    # asyncio.run(main())
    # asyncio.run(test_scripter())
    prompt = """
Generate an image of a TROC-GLOBAL brand ambassador at a Best Buy retail environment wearing smart glasses with a prominent Best Buy logo in the background.
    """
    asyncio.run(create_image(prompt))
