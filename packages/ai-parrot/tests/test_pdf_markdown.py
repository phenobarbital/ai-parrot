"""
Test script to reproduce and debug PDFPrintTool markdown rendering issues.
"""
import asyncio
from pathlib import Path

# The problematic markdown content from the user report
SAMPLE_MARKDOWN = """
# 1. Basic Employee Information
**Employee ID:** srose@trocglobal.com
**Employee Name:** Sollie Rose
**Total Stores Visited:** 4
**Most Recent Visit Date:** 2026-01-10
**Most Recent Store Visited:** Best Buy 896 Atlanta GA
**Average Duration of Visits:** 256.67
**Total Visits:** 4
**Total Unique Stores Visited:** 4
**Median Duration of Visits:** 273.73
**Visited Retailers**: {'Best Buy': 4}

## Sales Summary
 **Current Units Sold:** No sales data available.
 **Previous Week:** No sales data available.
 **Week over Week comparison:** No sales data available.

# 2. Visits Summary

**Top-3 Longest Duration Visits:**
| Store ID | Visit Date | visit length (min) |
|---|---|---|
| BBY0890 | 2026-01-08 | 359.32 |
| BBY0504 | 2026-01-10 | 351.50 |
| BBY0896 | 2026-01-06 | 273.73 |

**Top-3 Shortest Duration Visits:**
| Store ID | Visit Date | visit length (min) |
|---|---|---|
| BBY0503 | 2026-01-09 | 42.12 |
| BBY0896 | 2026-01-06 | 273.73 |
| BBY0504 | 2026-01-10 | 351.50 |

**Most Frequent Store visited:** All stores (BBY0896, BBY0890, BBY0503, BBY0504) were visited once.
**Variance in Average Visit Length:** 21943.12
**Median Per-Store Visits:** 1

## Visit Frequency
  - Daily: 1.00
  - most frequent hour: 12
  - most frequent day: 1
  - Time Range: 02:22/23:53

# 4. Visit Performance Metrics

## 10755: What were the key wins or successes from today's visit?
• **Top Phrases:** sales, bose ultra headphones, brand awareness
• **Themes:** Bose, headphones, sales, training
• **Key Issues:**
  * sales (1)
  * brand awareness (1)
• **Sentiment Counts:**
  - Positive: 3, Negative: 0, Neutral: 1
"""


async def test_markdown_detection():
    """Test that markdown is properly detected."""
    from parrot.tools.pdfprint import PDFPrintTool
    
    pdf_tool = PDFPrintTool()
    
    # Test if markdown detection works
    is_markdown = pdf_tool._is_markdown(SAMPLE_MARKDOWN)
    print(f"[TEST] Markdown detection: {is_markdown}")
    assert is_markdown, "Should detect as markdown"
    
    print("[PASS] Markdown detection works")


async def test_markdown_preprocessing():
    """Test markdown table preprocessing."""
    from parrot.tools.pdfprint import PDFPrintTool
    
    pdf_tool = PDFPrintTool()
    
    # Test table preprocessing
    preprocessed = pdf_tool._preprocess_markdown_tables(SAMPLE_MARKDOWN)
    
    print(f"[TEST] Original length: {len(SAMPLE_MARKDOWN)}")
    print(f"[TEST] Preprocessed length: {len(preprocessed)}")
    
    # Check if table structure is preserved
    has_table_rows = '|' in preprocessed
    has_separator = '|---' in preprocessed or '---|' in preprocessed
    
    print(f"[TEST] Has table rows: {has_table_rows}")
    print(f"[TEST] Has separator: {has_separator}")
    
    print("\n=== First 2000 chars of preprocessed output ===\n")
    print(preprocessed[:2000])
    
    print("\n[PASS] Preprocessing complete")


async def test_html_conversion():
    """Test full Markdown to HTML conversion."""
    from parrot.tools.pdfprint import PDFPrintTool
    import markdown
    
    pdf_tool = PDFPrintTool()
    
    # Preprocess tables
    preprocessed = pdf_tool._preprocess_markdown_tables(SAMPLE_MARKDOWN)
    
    # Convert to HTML using the same settings as PDFPrintTool
    # NOTE: nl2br is intentionally excluded as it interferes with table parsing
    md = markdown.Markdown(
        extensions=[
            'tables',
            'fenced_code',
            'attr_list',
            'def_list',
            'footnotes',
            'toc',
            'codehilite',
            'extra'
        ],
        extension_configs={
            'tables': {'use_align_attribute': True},
            'codehilite': {'css_class': 'highlight', 'use_pygments': False}
        },
        output_format='html5'
    )
    
    html_output = md.convert(preprocessed)
    
    # Check for expected HTML elements
    has_h1 = '<h1>' in html_output or '<h1' in html_output
    has_h2 = '<h2>' in html_output or '<h2' in html_output
    has_table = '<table>' in html_output or '<table' in html_output
    has_strong = '<strong>' in html_output
    has_ul = '<ul>' in html_output
    
    print(f"[TEST] Has H1: {has_h1}")
    print(f"[TEST] Has H2: {has_h2}")
    print(f"[TEST] Has Table: {has_table}")
    print(f"[TEST] Has Strong: {has_strong}")
    print(f"[TEST] Has UL: {has_ul}")
    
    print("\n=== First 3000 chars of HTML output ===\n")
    print(html_output[:3000])
    
    if not has_table:
        print("\n[WARNING] Tables not converted! Checking raw input...")
        # Look for table patterns in input
        lines = preprocessed.split('\n')
        for i, line in enumerate(lines):
            if '|' in line:
                print(f"  Line {i}: {line[:80]}...")
    
    print("\n[TEST] HTML conversion complete")


async def test_process_content():
    """Test the full _process_content method."""
    from parrot.tools.pdfprint import PDFPrintTool
    
    pdf_tool = PDFPrintTool()
    
    # Use the full _process_content method
    html_content = pdf_tool._process_content(
        text=SAMPLE_MARKDOWN,
        auto_detect_markdown=True,
        template_name=None,
        template_vars=None
    )
    
    # Save to file for inspection
    output_path = Path("/tmp/pdf_debug_output.html")
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"[TEST] Full HTML output saved to: {output_path}")
    print(f"[TEST] HTML size: {len(html_content)} bytes")
    
    # Check for expected elements
    has_table = '<table' in html_content
    table_count = html_content.count('<table')
    
    print(f"[TEST] Tables found: {table_count}")
    
    if not has_table:
        print("\n[ERROR] No tables in output! This is the bug.")
    else:
        print(f"\n[PASS] Found {table_count} table(s) in HTML output")


async def test_pdf_generation():
    """Test actual PDF generation."""
    from parrot.tools.pdfprint import PDFPrintTool
    
    pdf_tool = PDFPrintTool()
    
    result = await pdf_tool._execute(
        text=SAMPLE_MARKDOWN,
        file_prefix="test_markdown_report",
        auto_detect_markdown=True
    )
    
    print(f"\n[TEST] PDF Generation Result:")
    print(f"  - File: {result['file_path']}")
    print(f"  - Size: {result['file_size']} bytes")
    print(f"  - Tables detected: {result['content_stats']['tables_detected']}")
    print(f"  - Was markdown: {result['content_stats']['was_markdown']}")
    
    if result['content_stats']['tables_detected'] == 0:
        print("\n[ERROR] No tables detected in PDF generation!")
    else:
        print(f"\n[PASS] Successfully detected {result['content_stats']['tables_detected']} tables")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("PDFPrintTool Markdown Rendering Debug Tests")
    print("=" * 60)
    
    print("\n--- Test 1: Markdown Detection ---")
    await test_markdown_detection()
    
    print("\n--- Test 2: Markdown Table Preprocessing ---")
    await test_markdown_preprocessing()
    
    print("\n--- Test 3: HTML Conversion ---")
    await test_html_conversion()
    
    print("\n--- Test 4: Process Content ---")
    await test_process_content()
    
    print("\n--- Test 5: PDF Generation ---")
    await test_pdf_generation()
    
    print("\n" + "=" * 60)
    print("All tests complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
