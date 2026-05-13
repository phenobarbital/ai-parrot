"""Example: Using InspectorToolkit to inspect Amazon Inspector v2 findings.

This example demonstrates:
1. Basic toolkit instantiation
2. Listing findings with severity filter
3. Getting ECR image findings with summary
4. Getting the account security posture (composite operation)
5. Starting an async SBOM export and polling its status

Prerequisites:
- AWS credentials configured (via profile, environment variables, or IAM role)
- Amazon Inspector v2 must be enabled in the target AWS region
- Required IAM permissions: see packages/ai-parrot-tools/src/parrot_tools/aws/policies/inspector_toolkit_policy.json

Pagination note:
    Each tool call returns ONE PAGE of results plus a `next_token`.
    The caller (agent or orchestration layer) is responsible for
    deciding whether to continue paginating. Auto-pagination is
    intentionally disabled to avoid ballooning LLM context windows.

    Example pagination loop (outside this script):
        token = None
        while True:
            result = await toolkit.aws_inspector_list_findings(next_token=token)
            process(result["findings"])
            token = result["next_token"]
            if not token:
                break
"""
from __future__ import annotations

import asyncio
import os

from parrot_tools.aws import InspectorToolkit


async def main() -> None:
    """Demonstrate InspectorToolkit operations."""
    # ----------------------------------------------------------------
    # 1. Instantiate the toolkit
    # ----------------------------------------------------------------
    # Use the default AWS profile and region from the environment.
    # Override with aws_id and region_name as needed.
    toolkit = InspectorToolkit(
        aws_id=os.environ.get("AWS_PROFILE", "default"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    print("=" * 60)
    print("InspectorToolkit — available operations")
    print("=" * 60)
    tools = toolkit.get_tools()
    for tool in tools:
        print(f"  • {tool.name}")
    print()

    # ----------------------------------------------------------------
    # 2. List CRITICAL findings (first page only)
    # ----------------------------------------------------------------
    print("Listing CRITICAL findings (first page)...")
    try:
        findings_result = await toolkit.aws_inspector_list_findings(
            severity="CRITICAL",
            status="ACTIVE",
            limit=10,
        )
        print(f"  Found {findings_result['count']} findings on this page.")
        if findings_result["next_token"]:
            print(f"  More pages available (next_token: {findings_result['next_token'][:20]}...)")
        for f in findings_result["findings"][:3]:
            print(
                f"  [{f['severity']}] {f['vulnerability_id']} — {f['title'][:60]}"
            )
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

    # ----------------------------------------------------------------
    # 3. Get findings for a specific ECR image
    # ----------------------------------------------------------------
    ecr_repo = os.environ.get("ECR_REPO", "my-app")
    print(f"Getting ECR image findings for repo '{ecr_repo}'...")
    try:
        ecr_result = await toolkit.aws_inspector_get_ecr_image_findings(
            repository_name=ecr_repo,
            severity="ALL",
            limit=20,
        )
        print(f"  Image: {ecr_result['image']}")
        print(f"  Summary: {ecr_result['summary']}")
        print(f"  Findings: {ecr_result['count']}")
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

    # ----------------------------------------------------------------
    # 4. Get account security posture (composite call)
    # ----------------------------------------------------------------
    print("Computing account security posture...")
    try:
        posture = await toolkit.aws_inspector_get_security_posture()
        print(f"  Security Score: {posture['security_score']}/100")
        print(f"  Severity Counts: {posture['severity_counts']}")
        print(f"  Coverage: {posture['coverage']}")
        print(f"  Scan Types Enabled: {posture['enabled_scan_types']}")
        print(f"  Weights Used: {posture['weights_used']}")
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

    # ----------------------------------------------------------------
    # 5. List top 5 most vulnerable resources
    # ----------------------------------------------------------------
    print("Finding top 5 most vulnerable resources...")
    try:
        top_resources = await toolkit.aws_inspector_list_top_vulnerable_resources(
            limit=5,
        )
        for i, r in enumerate(top_resources["resources"], 1):
            print(
                f"  #{i} {r['resource_id'][:60]} "
                f"(score: {r['weighted_score']}, "
                f"CRITICAL: {r['severity_counts']['CRITICAL']})"
            )
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

    # ----------------------------------------------------------------
    # 6. Start an async SBOM export (requires S3 bucket + KMS key)
    # ----------------------------------------------------------------
    s3_bucket = os.environ.get("SBOM_S3_BUCKET", "")
    kms_key_arn = os.environ.get("SBOM_KMS_KEY_ARN", "")

    if s3_bucket and kms_key_arn:
        print("Starting SBOM export to S3...")
        try:
            export = await toolkit.aws_inspector_create_sbom_export(
                s3_bucket=s3_bucket,
                s3_key_prefix="inspector-sboms/example/",
                kms_key_arn=kms_key_arn,
                report_format="CYCLONEDX_1_4",
            )
            report_id = export["report_id"]
            print(f"  Export started. Report ID: {report_id}")
            print("  Polling status (single call — no auto-poll loop)...")
            status = await toolkit.aws_inspector_get_sbom_export(
                report_id=report_id
            )
            print(f"  Status: {status['status']}")
        except RuntimeError as e:
            print(f"  Error: {e}")
        print()
    else:
        print("Skipping SBOM export (set SBOM_S3_BUCKET and SBOM_KMS_KEY_ARN env vars).")
        print()

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
