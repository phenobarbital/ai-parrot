"""Example: Generate a PlanogramConfig JSON for the product_counter type.

This script generates a complete planogram configuration JSON payload for
a product-on-counter display (e.g. an Epson EcoTank printer on a promotional
counter/podium) and prints it ready for insertion into
``troc.planograms_configurations`` in PostgreSQL.

Usage::

    python product_counter_config.py

The output JSON can be inserted into the database with:

    INSERT INTO troc.planograms_configurations
        (config_name, planogram_type, planogram_config,
         roi_detection_prompt, object_identification_prompt,
         confidence_threshold)
    VALUES
        (%(config_name)s, %(planogram_type)s, %(planogram_config)s::jsonb,
         %(roi_detection_prompt)s, %(object_identification_prompt)s,
         %(confidence_threshold)s);
"""
import json
import sys


def build_config() -> dict:
    """Build the PlanogramConfig dict for an Epson EcoTank counter display.

    Returns:
        Dict matching the ``PlanogramConfig`` model schema, ready for JSON
        serialisation and database insertion.
    """
    return {
        "config_name": "epson_ecotank_counter",
        "planogram_type": "product_counter",
        "planogram_config": {
            "brand": "Epson",
            "expected_elements": [
                "product",
                "promotional_background",
                "information_label",
            ],
            "scoring_weights": {
                "product": 1.0,
                "promotional_background": 0.5,
                "information_label": 0.3,
            },
        },
        "roi_detection_prompt": (
            "Identify the product counter or podium display area in this Epson "
            "retail image.  The counter is a raised surface (podium or table) "
            "holding one or more Epson EcoTank printers.  Return a single bounding "
            "box labeled 'counter' that covers the full counter surface, including "
            "any promotional backdrop behind the product and any information label "
            "attached to the counter."
        ),
        "object_identification_prompt": (
            "Within this Epson EcoTank counter/podium display, identify the "
            "following elements and return their bounding boxes:\n"
            "1) 'product' — the main Epson EcoTank printer placed on the counter.  "
            "   It is the primary product unit, typically centred on the surface.\n"
            "2) 'promotional_background' — any Epson-branded backdrop panel, side "
            "   banner, or rear graphic behind or around the product.  It usually "
            "   features the EcoTank logo and brand colours (black, red, white).\n"
            "3) 'information_label' — any price tag, specification card, product "
            "   fact tag, or informational placard placed in front of or beside "
            "   the printer on the counter surface.\n"
            "Return each detected element with its label and normalised bounding box."
        ),
        "reference_images": {},
        "confidence_threshold": 0.25,
        "detection_model": "yolo11l.pt",
    }


def print_sql(cfg: dict) -> None:
    """Print an example SQL INSERT statement for the config.

    Args:
        cfg: The config dict to embed in the SQL.
    """
    pc = json.dumps(cfg["planogram_config"], ensure_ascii=False, indent=2)
    print("\n-- Example SQL INSERT (use parameterised queries in production):")
    print("INSERT INTO troc.planograms_configurations")
    print("    (config_name, planogram_type, planogram_config,")
    print("     roi_detection_prompt, object_identification_prompt,")
    print("     confidence_threshold)")
    print("VALUES (")
    print(f"    '{cfg['config_name']}',")
    print(f"    '{cfg['planogram_type']}',")
    print(f"    '{pc}'::jsonb,")
    print(f"    '{cfg['roi_detection_prompt'][:60]}...',")
    print(f"    '{cfg['object_identification_prompt'][:60]}...',")
    print(f"    {cfg['confidence_threshold']}")
    print(");")


def main() -> None:
    """Entry point: build config, print JSON, and print example SQL."""
    cfg = build_config()
    print("=== PlanogramConfig JSON for product_counter ===")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    print_sql(cfg)

    # Validate JSON round-trip
    serialised = json.dumps(cfg)
    parsed = json.loads(serialised)
    assert parsed["planogram_type"] == "product_counter", "planogram_type mismatch"
    assert "scoring_weights" in parsed["planogram_config"], "scoring_weights missing"
    print("\n✅  JSON valid and parseable.")


if __name__ == "__main__":
    main()
