from pathlib import Path

# Function to create the PowerPoint template programmatically
def create_powerpoint_template():
    """Create a custom PowerPoint template with proper styling."""
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    # Create new presentation
    prs = Presentation()

    # Define slide layouts we'll customize
    # Layout 0: Title Slide
    title_slide_layout = prs.slide_layouts[0]

    # Layout 1: Title and Content
    content_slide_layout = prs.slide_layouts[1]

    # Customize master slide properties (this is simplified - in practice you'd
    # want to use PowerPoint's design tools or an existing template file)

    # You could also load an existing template and modify it:
    # prs = Presentation('base_template.pptx')

    # Save as template
    template_path = Path("templates/corporate_template.pptx")
    template_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(template_path))

    print(f"✅ PowerPoint template created: {template_path}")
    return str(template_path)

# Usage example
if __name__ == "__main__":
    import asyncio

    # Create the PowerPoint template first
    create_powerpoint_template()
