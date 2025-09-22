import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.pipelines.models import PlanogramConfig
from parrot.clients.google import (
    GoogleGenAIClient,
    GoogleModel
)

async def main():
    """Example usage of the 3-step pipeline"""
    llm = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_PRO)
    # Reference images for product identification
    reference_images = {
        "ET-3950 BOX": BASE_DIR / "examples" / "pipelines" / "ET-3950-BOX.jpg",
        "ET-4950 BOX": BASE_DIR / "examples" / "pipelines" / "ET-4950-BOX.jpg",
        "ET-2980 Printer": BASE_DIR / "examples" / "pipelines" / "ET-2980.jpg",
        "ET-3950 Printer": BASE_DIR / "examples" / "pipelines" / "ET-3950.jpg",
        "ET-4950 Printer": BASE_DIR / "examples" / "pipelines" / "ET-4950.jpg"
    }
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

    planogram = PlanogramConfig(
        config_name="Epson EcoTank Printers Planogram",
        planogram_config=planogram_config,
        reference_images=reference_images,
        detection_model="yolo11l.pt",
        confidence_threshold=0.15,
        roi_detection_prompt="""
Analyze the image to identify the entire retail endcap display and its key components.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' with any detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

Useful phrases to look for inside the lightbox: {tag_hint}

Return all detections with the following strict criteria:

1. **'brand_logo'**: A bounding box for the '{brand}' brand logo at the top of the sign.

2. **'poster_text'**: A bounding box for the main marketing text on the sign, must include phrases like {tag_hint}.

3. **'promotional_graphic'**: A bounding box for the main promotional graphic on the sign, which may include images of products and other marketing visuals. The box should tightly enclose the graphic area without cutting off any important elements.

4. **'poster_panel'**: A bounding box that **tightly encloses the entire backlit sign, The box must **tightly enclose the sign's outer silver/gray frame on all four sides.** For this detection, 'content' should be null.

5. **'endcap'**: A bounding box for the entire retail endcap display structure. It must start at the top of the sign and extend down to the **base of the lowest shelf**, including price tags and products boxes. The box must be wide enough to **include all products and product boxes on all shelves without cropping.** For this detection, 'content' should be null.

""",
        object_identification_prompt="""
---
**!! IMPORTANT VISUAL GUIDE FOR PRINTERS !!**
You MUST use the control panel or size of screen to tell the printer models apart. This is the most important rule.
* **ET-2980:** Has a **simple control panel** with a tiny screen and arrow buttons.
* **ET-3950:** Has a **larger control panel LED screen and several buttons (11 buttons)**.
* **ET-4950:** Has a **large color TOUCHSCREEN** with no more than 3 physical buttons.

---
**!! CRITICAL IDENTIFICATION RULES !!**

1.  **ANALYZE EACH PRINTER INDEPENDENTLY:** DO NOT assume all printers are the same model. You must analyze the control panel of EACH printer individually.

2. **CONSOLIDATION (To Avoid Duplicates):**
   - If multiple detection IDs refer to the same single object, provide **only ONE entry** for that object. Choose the ID that best represents the entire object.

3. **PRODUCT TYPES & PLACEMENT HEURISTICS:**
   - **PRINTERS (Devices):** White/gray devices, typically on 'middle' shelves.
   - **BOXES (Packaging):** Blue packaging, typically on 'bottom' shelves.
   - **PROMOTIONAL GRAPHICS:** Large signs/posters, typically on the 'header'.

4. **UNREADABLE MODELS:**
   - If a model number on a box is obscured, set `product_model` to **'Unreadable Box'**.

5. **NEWLY FOUND OBJECTS (MANDATORY):**
   - If you identify a prominent product that was NOT pre-detected (e.g., a large box missed by the first pass), set its `detection_id` to `null`.
   - For these newly found items, you **MUST** also provide an estimated `detection_box` field with an array of four pixel coordinates `[x1, y1, x2, y2]`. **This field is NOT optional for new items.**
""",
    )

    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        planogram_config=planogram,
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
