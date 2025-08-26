import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.models.detections import PlanogramConfigBuilder
from parrot.clients.gpt import OpenAIClient, OpenAIModel


async def main():
    """Example usage of the 3-step pipeline"""
    llm = OpenAIClient(model=OpenAIModel.GPT_4_1_MINI)

    builder = (PlanogramConfigBuilder()
    .set_basic_info("Pokemon", "TCG Vending", "Vending Unit")
    .set_brand_detection(target_brands=["Pokemon", "Pokémon"], confidence_threshold=0.65)
    )
    # Define shelves with slot-by-slot expectations (left→right)
    shelf_specs = {
        "s1": ["elite_trainer_box","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack"],
        "s2": ["elite_trainer_box","EMPTY","EMPTY","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack"],
        "s3": ["booster_display","EMPTY","EMPTY","EMPTY","booster_pack","booster_pack","booster_pack","booster_pack"],
        "s4": ["booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack"],
        "s5": ["mini_tin","mini_tin","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack","booster_pack"],
        "s6": ["booster_pack","EMPTY","EMPTY","EMPTY","EMPTY","EMPTY","EMPTY","EMPTY"],
    }
    for level, slots in shelf_specs.items():
        builder.add_shelf(
            level=level,
            products=[  # repeat products to represent chutes in order
                {"name": p, "product_type": p if p!="EMPTY" else "empty_slot", "quantity_range": (0,1), "mandatory": (p!="EMPTY")}
                for p in slots
            ],
            compliance_threshold=0.8  # shelf pass bar
        )

    vending_cfg = builder.build()
    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        # detection_model="yolov9m.pt"  # or "yolov8s", "yolov8m", etc.
        detection_model="yolo11m.pt",
    )

    planogram_config = {
        "brand": "Epson",
        "category": "Printers",
        "aisle": {
            "name": "Electronics > Printers & Printer Boxes and Supplies",
            "lighting_conditions": "bright"
        },
        "shelves": [
            {
                "level": "header",
                "products": [
                    {
                        "name": "Epson EcoTank Advertisement",
                        "product_type": "promotional_graphic",
                        "mandatory": True
                    }
                ],
                "allow_extra_products": True,
                "compliance_threshold": 0.95
            },
            {
                "level": "top",
                "products": [
                    {
                        "name": "ET-2980",
                        "product_type": "printer",
                        "quantity_range": [1, 1],
                        "position_preference": "left"
                    },
                    {
                        "name": "ET-3950",
                        "product_type": "printer",
                        "quantity_range": [1, 1],
                        "position_preference": "center"
                    },
                    {
                        "name": "ET-4950",
                        "product_type": "printer",
                        "quantity_range": [1, 1],
                        "position_preference": "right"
                    }
                ],
                "compliance_threshold": 0.9
            },
            {
                "level": "middle",
                "products": [
                    {
                        "name": "ET-2980 box",
                        "product_type": "printer_box",
                        "quantity_range": [1, 2]
                    },
                    {
                        "name": "ET-3950 box",
                        "product_type": "printer_box",
                        "quantity_range": [1, 2]
                    },
                    {
                        "name": "ET-4950 box",
                        "product_type": "printer_box",
                        "quantity_range": [1, 2]
                    }
                ],
                "compliance_threshold": 0.8 # More flexibility for boxes
            }
        ],
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "backlit_graphic",
            "position": "header",
            "text_requirements": [
                {
                    "required_text": "Goodbye Cartridges",
                    "match_type": "contains",
                    "mandatory": True
                },
                {
                    "required_text": "Hello Savings",
                    "match_type": "contains",
                    "mandatory": True
                }
            ]
        }
    }

    planogram = pipeline.create_planogram_description(
        config=planogram_config
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
        confidence_threshold=0.6,
        return_overlay="identified",
        overlay_save_path="/tmp/planogram_overlay.jpg",
    )

    # Print results
    print("\n" + "="*60)
    print(f"\nOVERALL COMPLIANCE: {results['overall_compliant']}")
    print(f"COMPLIANCE SCORE: {results['overall_compliance_score']:.1%}")
    print("="*60)

    # Print results will now show text compliance
    print("\nSHELF-BY-SHELF RESULTS:")
    for result in results['step3_compliance_results']:
        print(f"{result.shelf_level.upper()}: {result.compliance_status}")
        print(f"  Expected: {result.expected_products}")
        print(f"  Found: {result.found_products}")
        print(f"  Product Score: {result.compliance_score:.1%}")
        print(f"  Text Score: {result.text_compliance_score:.1%}")
        print(f"  Text Compliant: {'✅' if result.overall_text_compliant else '❌'}")

        # Show text compliance details
        if result.text_compliance_results:
            print("  Text Requirements:")
            for text_result in result.text_compliance_results:
                status = "✅" if text_result.found else "❌"
                print(f"    {status} '{text_result.required_text}' (confidence: {text_result.confidence:.2f})")
                if text_result.matched_features:
                    print(f"        Matched: {text_result.matched_features}")
        print()

    # Render the Image:
    print(results['overlay_path'])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
