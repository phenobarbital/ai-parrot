"""AWS Bedrock Example — Amazon Nova Canvas (image generation)

Generates PNG images from a text prompt with Amazon Nova Canvas, via
``NovaClient.generate_image()``.

Usage:
    python examples/agents/aws/nova_canvas_image.py
    python examples/agents/aws/nova_canvas_image.py "a red bicycle on a beach"
    python examples/agents/aws/nova_canvas_image.py "a red bicycle" \
        --negative "blurry, text" --count 2 --width 1280 --height 720 --seed 42

Environment Variables:
    AWS_DEFAULT_REGION       AWS region (must be us-east-1, eu-west-1, or
                             ap-northeast-1 — see the note below)
    AWS_ACCESS_KEY_ID        AWS access key (or use IAM role)
    AWS_SECRET_ACCESS_KEY    AWS secret key (or use IAM role)

This is NOT an agent: Nova Canvas takes no messages and supports no tools.
It is invoked through the synchronous ``invoke_model`` API with
``taskType: "TEXT_IMAGE"`` and returns base64 images, so the sample is a
plain one-shot CLI rather than a `BasicAgent` conversation loop.

Note: `amazon.nova-canvas-v1:0` is **in-region only** — it has no geo or
global inference profile, so the ID is never region-prefixed (that is what
``NovaGeneration._translate_in_region_model()`` exists for, as opposed to
the text path's ``_translate_model()``). It is available in us-east-1,
eu-west-1 and ap-northeast-1 only, and the Converse API does NOT serve it.

⚠️  Lifecycle: AWS marks Nova Canvas **Legacy with EOL 2026-09-30**. Do not
build new work on it without a migration plan.

See examples/agents/aws/README.md for full setup instructions.
"""
import argparse
import asyncio
from pathlib import Path

from parrot.clients.amazon.nova import NovaClient

DEFAULT_PROMPT = "A futuristic city skyline at sunset, digital art style"
DEFAULT_OUTPUT_DIR = Path("artifacts/nova-canvas")


def _parse_args() -> argparse.Namespace:
    """Parse the CLI arguments for a single Nova Canvas generation."""
    parser = argparse.ArgumentParser(
        description="Generate images with Amazon Nova Canvas on AWS Bedrock.",
    )
    parser.add_argument(
        "prompt", nargs="?", default=DEFAULT_PROMPT,
        help=f"Text prompt for the image (default: {DEFAULT_PROMPT!r})",
    )
    parser.add_argument(
        "--negative", default=None,
        help="Negative prompt describing what to avoid",
    )
    parser.add_argument(
        "--count", type=int, default=1,
        help="Number of candidate images to request (default: 1)",
    )
    parser.add_argument("--width", type=int, default=1024, help="Width in pixels")
    parser.add_argument("--height", type=int, default=1024, help="Height in pixels")
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Generation seed, for reproducible output",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Directory the PNGs are written to (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


async def main() -> int:
    """Generate the image(s) and report where they were saved."""
    args = _parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    client = NovaClient()
    print("🎨 AWS Bedrock — Amazon Nova Canvas (image generation)")
    print(f"   Region: {client._region}   Output: {args.out}")
    print(f"   Prompt: {args.prompt}\n")

    try:
        result = await client.generate_image(
            args.prompt,
            negative_prompt=args.negative,
            number_of_images=args.count,
            width=args.width,
            height=args.height,
            seed=args.seed,
            output_directory=args.out,
        )
    except Exception as exc:
        print(f"❌ Generation failed: {type(exc).__name__}: {exc}")
        print("   Nova Canvas is in-region only (us-east-1, eu-west-1, "
              "ap-northeast-1) and must be enabled under Bedrock model access.")
        return 1

    print(f"✅ Model:    {result.model}")
    print(f"   Provider: {result.provider}")
    for path in result.images or []:
        print(f"   Saved:    {path}")
    if not result.images:
        print("   (no image paths returned — check the response payload)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
