"""AWS Bedrock Example — Amazon Nova Reel (video generation)

Generates a short MP4 from a text prompt with Amazon Nova Reel, via
``NovaClient.video_generation()``.

Usage:
    python examples/agents/aws/nova_reel_video.py
    python examples/agents/aws/nova_reel_video.py "a drone shot over a canyon"
    python examples/agents/aws/nova_reel_video.py "a drone shot over a canyon" \
        --duration 6 --s3 s3://my-bucket/nova-reel/ --out artifacts/nova-reel

Environment Variables:
    AWS_DEFAULT_REGION       AWS region (must be us-east-1, eu-west-1, or
                             ap-northeast-1 — see the note below)
    AWS_ACCESS_KEY_ID        AWS access key (or use IAM role)
    AWS_SECRET_ACCESS_KEY    AWS secret key (or use IAM role)

This is NOT an agent: Nova Reel takes no messages and supports no tools.

Nova Reel has **no synchronous API** — it is ``StartAsyncInvoke`` only, so
``video_generation()`` starts the job, polls ``GetAsyncInvoke`` until it
finishes, then downloads the MP4 from S3 into *--out*. Expect minutes, not
seconds, and note the two consequences:

1. An **S3 output location is mandatory**. Pass ``--s3 s3://bucket/prefix``,
   or configure ``bucket_name`` for your profile in
   ``parrot.conf::AWS_CREDENTIALS`` and it is resolved automatically. With
   neither, the client raises ``ValueError`` before any API call.
2. The caller needs write access to that bucket *and* read access to fetch
   the finished object back.

Note: `StartAsyncInvoke` / `GetAsyncInvoke` were added to the AWS SDK when
Nova Reel launched (Dec 2024). An older `botocore` has no such operation, so
the call fails with ``AttributeError: 'BedrockRuntime' object has no
attribute 'start_async_invoke'`` before reaching AWS. Check with::

    python -c "import botocore, gzip, json, os; \
      d=json.load(gzip.open(os.path.join(os.path.dirname(botocore.__file__), \
      'data/bedrock-runtime/2023-09-30/service-2.json.gz'))); \
      print(sorted(d['operations']))"

Note: `amazon.nova-reel-v1:0` is **in-region only** — no geo or global
inference profile, so the ID is never region-prefixed. It is available in
us-east-1, eu-west-1 and ap-northeast-1 only, and neither Converse nor the
synchronous Invoke API serves it.

⚠️  Lifecycle: AWS marks Nova Reel **Legacy with EOL 2026-09-30**. Do not
build new work on it without a migration plan.

See examples/agents/aws/README.md for full setup instructions.
"""
import argparse
import asyncio
from pathlib import Path

from parrot.clients.amazon.nova import NovaClient

DEFAULT_PROMPT = "A slow drone shot flying over a misty pine forest at dawn"
DEFAULT_OUTPUT_DIR = Path("artifacts/nova-reel")


def _parse_args() -> argparse.Namespace:
    """Parse the CLI arguments for a single Nova Reel generation."""
    parser = argparse.ArgumentParser(
        description="Generate a video with Amazon Nova Reel on AWS Bedrock.",
    )
    parser.add_argument(
        "prompt", nargs="?", default=DEFAULT_PROMPT,
        help=f"Text prompt for the video (default: {DEFAULT_PROMPT!r})",
    )
    parser.add_argument(
        "--duration", type=int, default=6,
        help="Video duration in seconds (default: 6)",
    )
    parser.add_argument(
        "--s3", default=None, metavar="S3_URI",
        help="S3 output location, e.g. s3://my-bucket/nova-reel/. Falls back "
             "to AWS_CREDENTIALS[<profile>]['bucket_name'].",
    )
    parser.add_argument(
        "--reference-image", type=Path, default=None,
        help="Optional starting-frame image for the video",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Directory the MP4 is downloaded to (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=10.0,
        help="Seconds between job-status polls (default: 10)",
    )
    parser.add_argument(
        "--timeout", type=float, default=900.0,
        help="Give up after this many seconds (default: 900)",
    )
    return parser.parse_args()


async def main() -> int:
    """Run the async generation job and report the downloaded MP4."""
    args = _parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    client = NovaClient()
    print("🎬 AWS Bedrock — Amazon Nova Reel (video generation)")
    print(f"   Region: {client._region}   Output: {args.out}")
    print(f"   Prompt: {args.prompt}")
    print(f"   This polls until the job finishes — expect several minutes.\n")

    try:
        result = await client.video_generation(
            args.prompt,
            duration=args.duration,
            reference_image=args.reference_image,
            output_directory=args.out,
            s3_output_uri=args.s3,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        print("   Nova Reel writes to S3 first: pass --s3 s3://bucket/prefix, "
              "or set bucket_name for your AWS profile.")
        return 1
    except AttributeError as exc:
        # The installed botocore predates StartAsyncInvoke (Dec 2024), so the
        # operation does not exist on the client at all — a far more confusing
        # failure than a service error unless it is named.
        print(f"❌ {exc}")
        print("   The installed botocore has no StartAsyncInvoke operation — "
              "it predates the Nova Reel launch (Dec 2024).")
        print("   Upgrade the SDK: uv pip install -U boto3 botocore aioboto3")
        return 1
    except Exception as exc:
        print(f"❌ Generation failed: {type(exc).__name__}: {exc}")
        print("   Nova Reel is in-region only (us-east-1, eu-west-1, "
              "ap-northeast-1) and must be enabled under Bedrock model access.")
        return 1

    print(f"✅ Model:    {result.model}")
    print(f"   Provider: {result.provider}")
    print(f"   Video:    {result.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
