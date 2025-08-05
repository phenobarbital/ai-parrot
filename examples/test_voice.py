import asyncio
from pathlib import Path
from parrot.tools.gvoice import GoogleVoiceTool


# --- Sample Input ---
SAMPLE_MARKDOWN_SUMMARY = """
# Weekly Tech Summary

This week saw major advancements in AI and sustainable tech.

## Artificial Intelligence Updates
A new large language model claims state-of-the-art results in code generation. Ethical discussions continue around AI bias mitigation techniques presented at the AI conference.

## Sustainable Technology
Solar panel efficiency hit a new record in lab tests. Investment in green hydrogen projects surged globally.

## Quick Mention
Quantum computing researchers demonstrated improved qubit stability.

# Conclusion
A busy week signaling rapid innovation across key technology sectors. Stay tuned for more updates next week.
"""
async def test_voice_tool():
    print("\nInstantiating GoogleVoiceTool...")
    voice_tool = GoogleVoiceTool(
        name="podcast_generator_tool", # Langchain tools require a name
        # You can override defaults here if needed:
        # voice_model="en-GB-News-K",
        # output_format="MP3",
    )
    print(
        f"  > Using Voice Model: {voice_tool.voice_model}"
    )
    print(
        f"  > Using Output Format: {voice_tool.output_format}"
    )
    print(
        f"  > Using Language Code: {voice_tool.language_code}"
    )
    # 4. Run the Tool's Async Method
    print(
        f"\nRunning tool with markdown summary..."
    )
    # Pass the markdown text as the 'query' argument to _arun
    result = await voice_tool._arun(query=SAMPLE_MARKDOWN_SUMMARY)
    # 5. Evaluate the Result
    print("\n--- Tool Result ---")
    print(result)
    print("-------------------")
    file_path = Path(result["file_path"])
    print(f"  > File Path Returned: {file_path}")

if __name__ == "__main__":
    asyncio.run(test_voice_tool())
