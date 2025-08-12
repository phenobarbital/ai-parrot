import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.models.detections import PlanogramDescription
from parrot.clients.gpt import OpenAIClient, OpenAIModel
from parrot.clients.claude import (
    ClaudeClient,
    ClaudeModel
)

async def main():
    """Example usage of the 3-step pipeline"""
    # llm = OpenAIClient(model=OpenAIModel.GPT5_MINI)
    llm = ClaudeClient(model=ClaudeModel.SONNET_4)  # Uncomment to use Claude

    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        detection_model="yolov8n"  # or "yolov8s", "yolov8m", etc.
    )

    # Define expected planogram
    planogram = PlanogramDescription(
        shelves={
            "header": ["epson ecotank advertisement"],
            "top": ["ET-2980", "ET-3950", "ET-4950"],
            "middle": ["fact_tag", "fact_tag", "fact_tag"],
            "bottom": ["ET-2980 box", "ET-3950 box", "ET-4950 box"],
        }
    )

    # Reference images for product identification
    reference_images = [
        BASE_DIR / "examples" / "pipelines" / "ET-2980.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-3950.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-4950.jpg"
    ]

    # Endcap photo:
    image_path = BASE_DIR / "examples" / "pipelines" / "250714 BBY 501 Kennesaw GA.jpg"

    # Run complete pipeline
    results = await pipeline.run(
        image=image_path,
        reference_images=reference_images,
        planogram_description=planogram,
        confidence_threshold=0.6
    )

    # Print results
    print(f"\nOVERALL COMPLIANCE: {results['overall_compliant']}")
    print(f"COMPLIANCE SCORE: {results['overall_compliance_score']:.1%}")

    print("\nSHELF-BY-SHELF RESULTS:")
    for result in results['step3_compliance_results']:
        print(f"{result.shelf_level.upper()}: {result.compliance_status.value}")
        print(f"  Expected: {result.expected_products}")
        print(f"  Found: {result.found_products}")
        if result.missing_products:
            print(f"  Missing: {result.missing_products}")
        if result.unexpected_products:
            print(f"  Unexpected: {result.unexpected_products}")
        print(f"  Score: {result.compliance_score:.1%}")
        print()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
