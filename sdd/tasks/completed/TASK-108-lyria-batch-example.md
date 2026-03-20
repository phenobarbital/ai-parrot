# TASK-108: Add Lyria Batch Usage Example

**Feature**: google-lyria-music-generation
**Spec**: `sdd/specs/google-lyria-music-generation.spec.md`
**Status**: in-progress
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-104
**Assigned-to**: ad88ddfc-fd84-406a-9983-d6470af955f8

---

## Context

This task adds a usage example demonstrating the new `generate_music_batch()` method. Examples help developers understand how to use the feature.

---

## Scope

- Create example script showing batch music generation
- Demonstrate key parameters: prompt, negative_prompt, seed, genre, mood
- Show how to handle output files

**NOT in scope**:
- Streaming example (already exists)
- Documentation updates

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/lyria_batch_example.py` | CREATE | Usage example |

---

## Implementation Notes

### Example Structure

```python
#!/usr/bin/env python
"""
Example: Generate music using Vertex AI Lyria batch API.

This example demonstrates the generate_music_batch() method which
produces complete 30-second WAV files.

Requirements:
- Vertex AI credentials (VERTEX_PROJECT_ID, VERTEX_REGION, VERTEX_CREDENTIALS_FILE)
- pip install parrot-ai

Usage:
    python lyria_batch_example.py
"""
import asyncio
from pathlib import Path

from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import MusicGenre, MusicMood


async def basic_generation():
    """Generate music with a simple prompt."""
    print("=== Basic Music Generation ===")

    client = GoogleGenAIClient(vertexai=True)

    results = await client.generate_music_batch(
        prompt="Calm acoustic guitar melody with soft strings",
        output_directory=Path("./output/music")
    )

    print(f"Generated {len(results)} file(s):")
    for path in results:
        print(f"  - {path} ({path.stat().st_size / 1024:.1f} KB)")


async def advanced_generation():
    """Generate music with all parameters."""
    print("\n=== Advanced Music Generation ===")

    client = GoogleGenAIClient(vertexai=True)

    results = await client.generate_music_batch(
        prompt="Energetic electronic track",
        negative_prompt="vocals, drums",  # Exclude these elements
        genre=MusicGenre.EDM,
        mood=MusicMood.UPBEAT,
        seed=42,  # For reproducibility
        output_directory=Path("./output/music")
    )

    print(f"Generated {len(results)} file(s):")
    for path in results:
        print(f"  - {path}")


async def multiple_variations():
    """Generate multiple variations of the same prompt."""
    print("\n=== Multiple Variations ===")

    client = GoogleGenAIClient(vertexai=True)

    results = await client.generate_music_batch(
        prompt="Jazz piano improvisation",
        genre=MusicGenre.JAZZ_FUSION,
        sample_count=3,  # Generate 3 variations
        output_directory=Path("./output/variations")
    )

    print(f"Generated {len(results)} variations:")
    for i, path in enumerate(results, 1):
        print(f"  Variation {i}: {path}")


async def compare_streaming_vs_batch():
    """Show the difference between streaming and batch APIs."""
    print("\n=== Streaming vs Batch Comparison ===")

    client = GoogleGenAIClient(vertexai=True)
    prompt = "Chill lo-fi hip hop beat"

    # Option 1: Streaming (Lyria RealTime)
    # Good for: Real-time playback, variable duration
    print("\nStreaming approach (yields PCM chunks):")
    print("  async for chunk in client.generate_music_stream(prompt):")
    print("      # Process each PCM chunk as it arrives")

    # Option 2: Batch (Vertex AI)
    # Good for: File output, reproducibility, batch processing
    print("\nBatch approach (returns WAV files):")
    results = await client.generate_music_batch(
        prompt=prompt,
        output_directory=Path("./output")
    )
    print(f"  Generated: {results[0]}")


async def main():
    """Run all examples."""
    # Create output directory
    Path("./output/music").mkdir(parents=True, exist_ok=True)
    Path("./output/variations").mkdir(parents=True, exist_ok=True)

    await basic_generation()
    await advanced_generation()
    await multiple_variations()
    await compare_streaming_vs_batch()

    print("\n=== Done! Check ./output/ for generated files ===")


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Constraints

- Example must be runnable standalone
- Include clear docstrings and comments
- Show both simple and advanced usage
- Handle output directory creation

### References in Codebase

- `examples/clients/google_client_example.py` — existing example pattern

---

## Acceptance Criteria

- [ ] Example file created at `examples/clients/lyria_batch_example.py`
- [ ] Example is runnable: `python examples/clients/lyria_batch_example.py`
- [ ] Demonstrates basic, advanced, and variation generation
- [ ] Includes comparison with streaming approach
- [ ] Has clear docstrings and comments
- [ ] No linting errors

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-lyria-music-generation.spec.md`
2. **Check dependencies** — verify TASK-104 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create** the example file
5. **Verify** syntax: `python -m py_compile examples/clients/lyria_batch_example.py`
6. **Move this file** to `sdd/tasks/completed/TASK-108-lyria-batch-example.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Antigravity (ad88ddfc-fd84-406a-9983-d6470af955f8)
**Date**: 2026-03-02
**Notes**: Created a comprehensive usage example at `examples/clients/lyria_batch_example.py` covering basic generation, advanced parameters, and multiple variations. Added comparative notes on streaming vs batch APIs.

**Deviations from spec**: None.
