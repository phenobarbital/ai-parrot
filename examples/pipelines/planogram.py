import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.clients.gpt import OpenAIClient, OpenAIModel
from parrot.clients.google import (
    GoogleGenAIClient,
    GoogleModel
)

async def main():
    """Example usage of the 3-step pipeline"""
    # llm = OpenAIClient(model=OpenAIModel.GPT_4O_MINI)
    llm = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_PRO)
    # llm = ClaudeClient(model=ClaudeModel.SONNET_4)  # Uncomment to use Claude

    # Reference images for product identification
    reference_images = {
        "ET-3950 BOX": BASE_DIR / "examples" / "pipelines" / "ET-3950-BOX.jpg",
        "ET-4950 BOX": BASE_DIR / "examples" / "pipelines" / "ET-4950-BOX.jpg",
        "ET-2980 Printer": BASE_DIR / "examples" / "pipelines" / "ET-2980.jpg",
        "ET-3950 Printer": BASE_DIR / "examples" / "pipelines" / "ET-3950.jpg",
        "ET-4950 Printer": BASE_DIR / "examples" / "pipelines" / "ET-4950.jpg"
    }
    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        # detection_model="yolov9m.pt"  # or "yolov8s", "yolov8m", etc.
        detection_model="yolo11l.pt",
        reference_images=reference_images,
        confidence_threshold=0.15,
    )

    planogram_config = {
        "brand": "Epson",
        "category": "Printers",
        "aisle": {
            "name": "Electronics > Printers & Printer Boxes and Supplies",
            "lighting_conditions": "bright"
        },
        "text_tokens": [
            "retail promotional poster lightbox",
            "Printer device",
            "Epson Product cardboard box",
            "Price Tag",
            "Cartridge ink bottle"
        ],
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.34,  # 33% of ROI height
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
                "level": "middle",
                "height_ratio": 0.25,  # 30% of ROI height
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
                "level": "bottom", # No height_ratio = remaining space
                "products": [
                    {
                        "name": "ET-2980",
                        "product_type": "product_box",
                        "quantity_range": [1, 2]
                    },
                    {
                        "name": "ET-3950",
                        "product_type": "product_box",
                        "quantity_range": [1, 2]
                    },
                    {
                        "name": "ET-4950",
                        "product_type": "product_box",
                        "quantity_range": [1, 2]
                    }
                ],
                "compliance_threshold": 0.8, # More flexibility for boxes
                "allow_extra_products": True
            }
        ],
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "backlit_graphic",
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
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
            ],
            # NEW: endcap geometry priors
            "size_constraints": {
                "backlit_height_ratio": 0.25,  # 25% of ROI height
            }
        }
    }

    # planogram_config = {
    #     "brand": "Hisense",
    #     "category": "TVs",
    #     "aisle": {
    #         "name": "Electronics > TVs & Home Theater",
    #         "lighting_conditions": "dim"
    #     },
    #     "shelves": [
    #         {
    #             "level": "header",
    #             "height_ratio": 0.15,
    #             "products": [
    #                 {
    #                     "name": "Hisense Header Advertisement",
    #                     "product_type": "promotional_graphic",
    #                     "mandatory": True
    #                 }
    #             ],
    #             "allow_extra_products": True,
    #             "compliance_threshold": 0.95
    #         },
    #         {
    #             "level": "top_tv",
    #             "height_ratio": 0.25,
    #             "products": [
    #                 {
    #                     "name": "Hisense TV",
    #                     "product_type": "tv",
    #                     "quantity_range": [1, 1],
    #                     "position_preference": "center"
    #                 }
    #             ],
    #             "compliance_threshold": 0.9
    #         },
    #         {
    #             "level": "middle_tv",
    #             "height_ratio": 0.25,
    #             "products": [
    #                 {
    #                     "name": "Hisense TV",
    #                     "product_type": "tv",
    #                     "quantity_range": [1, 1],
    #                     "position_preference": "center"
    #                 }
    #             ],
    #             "compliance_threshold": 0.9
    #         },
    #         {
    #             "level": "bottom_tv",
    #             "height_ratio": 0.25,
    #             "products": [
    #                 {
    #                     "name": "Hisense TV",
    #                     "product_type": "tv",
    #                     "quantity_range": [1, 1],
    #                     "position_preference": "center"
    #                 }
    #             ],
    #             "compliance_threshold": 0.9
    #         },
    #         {
    #             "level": "bottom_promo",
    #             "height_ratio": 0.10,
    #             "products": [
    #                 {
    #                     "name": "Hisense Bottom Advertisement",
    #                     "product_type": "promotional_graphic",
    #                     "mandatory": True
    #                 }
    #             ],
    #             "allow_extra_products": True,
    #             "compliance_threshold": 0.9
    #         }
    #     ],
    #     "advertisement_endcap": {
    #         "enabled": True,
    #         "promotional_type": "endcap_poster",
    #         "position": "header",
    #         "product_weight": 0.8,
    #         "text_weight": 0.2,
    #         "side_margin_percent": 0.05,
    #         "text_requirements": [
    #             {
    #                 "required_text": "Hisense",
    #                 "match_type": "contains",
    #                 "mandatory": True
    #             },
    #             {
    #                 "required_text": "OFFICIAL PARTNER",
    #                 "match_type": "contains",
    #                 "mandatory": True
    #             }
    #         ],
    #         "size_constraints": {
    #             "backlit_height_ratio": 0.25
    #         }
    #     }
    # }

    planogram = pipeline.create_planogram_description(
        config=planogram_config
    )

    # Endcap photo:
    image_path = BASE_DIR / "examples" / "pipelines" / "250714 BBY 501 Kennesaw GA.jpg"
    # image_path = BASE_DIR / "examples" / "pipelines" / "original_0.jpg"
    # image_path = BASE_DIR / "examples" / "pipelines" / "06668994-c27e-44d9-8d59-f1f65559c2e1-recap.jpeg"
    # image_path = BASE_DIR / "examples" / "pipelines" / "eb04d624-a180-4e5c-b592-ab0d40b558f9-recap.jpeg"
    # new test:
    # image_path = BASE_DIR / "examples" / "pipelines" / "356e053c-d630-4930-a2fd-cba4ab8f5e2b-recap.jpeg"
    # for evaluate wrong ROI:
    # image_path = BASE_DIR / "examples" / "pipelines" / "f7b45f4c-c33f-4312-9afb-e01af138e6f8-recap.jpeg"
    # check if compliance:
    # image_path = BASE_DIR / "examples" / "pipelines" / "check-compliance.jpeg"
    # Other Brand?
    # image_path = BASE_DIR / "examples" / "pipelines" / "hisense-2.jpg"

    # Run complete pipeline
    results = await pipeline.run(
        image=image_path,
        planogram_description=planogram,
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
