#!/usr/bin/env python3
"""
Quick Start Test for WebScrapingTool
===================================

Minimal test script to quickly verify the tool works.
"""

import asyncio

# You'll need to adjust these imports based on your actual AI-Parrot structure
# For testing, you can copy the WebScrapingTool class here or import it
from parrot.tools.scraping import WebScrapingTool


async def quick_test():
    """Quick test of WebScrapingTool functionality"""

    print("🚀 Quick WebScrapingTool Test")
    print("=" * 40)

    # Initialize the tool
    tool = WebScrapingTool(headless=False, overlay_housekeeping=False)

    # Simple test: scrape Hacker News titles
    test_args = {
        "steps": [
            {
                "action": "navigate",
                "target": "https://news.ycombinator.com",
                "description": "Go to Hacker News"
            },
            {
                "action": "wait",
                "target": ".athing",
                "timeout": 10,
                "description": "Wait for stories to load"
            }
        ],
        "selectors": [
            {
                "name": "titles",
                "selector": ".titleline > a",
                "extract_type": "text",
                "multiple": True
            }
        ]
    }

    try:
        print("🔄 Running scraping test...")
        result = await tool._execute(**test_args)

        if result['status']:
            titles = result['result'][0]['extracted_data']['titles']
            print(f"✅ Success! Scraped {len(titles)} news titles")
            print("\n📰 First 3 headlines:")
            for i, title in enumerate(titles[:3], 1):
                print(f"  {i}. {title}")
        else:
            print("❌ Test failed")
            print(f"Error: {result.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"❌ Exception occurred: {str(e)}")

    print("\n✨ Test completed!")


async def test_product_scraping():
    """Test product scraping simulation"""

    print("\n🛒 Product Scraping Test")
    print("=" * 40)

    tool = WebScrapingTool(headless=True, overlay_housekeeping=False)

    # Test with a scraping-friendly site
    test_args = {
        "steps": [
            {
                "action": "navigate",
                "target": "http://quotes.toscrape.com",
                "description": "Navigate to quotes site"
            },
            {
                "action": "wait",
                "target": ".quote",
                "timeout": 10,
                "description": "Wait for quotes"
            }
        ],
        "selectors": [
            {
                "name": "quotes",
                "selector": ".quote .text",
                "extract_type": "text",
                "multiple": True
            },
            {
                "name": "authors",
                "selector": ".quote .author",
                "extract_type": "text",
                "multiple": True
            }
        ]
    }

    try:
        print("🔄 Testing quote extraction...")
        result = await tool._execute(**test_args)

        if result['status']:
            data = result['result'][0]['extracted_data']
            quotes = data['quotes']
            authors = data['authors']

            print(f"✅ Success! Found {len(quotes)} quotes")
            print("\n💭 Sample quote:")
            if quotes and authors:
                print(f"Quote: {quotes[0]}")
                print(f"Author: {authors[0]}")
        else:
            print("❌ Test failed")

    except Exception as e:
        print(f"❌ Exception: {str(e)}")


async def main():
    """Run all quick tests"""
    await quick_test()
    await test_product_scraping()

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
