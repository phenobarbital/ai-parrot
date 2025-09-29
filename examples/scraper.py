#!/usr/bin/env python3
"""
Quick Start Test for WebScrapingTool
===================================

Minimal test script to quickly verify the tool works.
"""
from pathlib import Path
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

async def test_human_interaction():
    """Test human interaction simulation"""

    print("\n🧑‍🤝‍🧑 Human Interaction Test")
    print("=" * 40)

    # Remember to start Chrome with --remote-debugging-port=9222 for this test

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Test with a scraping-friendly site
    test_args = {
        "steps": [
            {
                "action": "navigate",
                "target": "https://navigator.trocglobal.com/login",
                "description": "Navigate to login page"
            },
            {
                "action": "await_human",
                "timeout": 600,
                "wait_condition": {
                    "selector": "#content-area",
                    "url_contains": "trocglobal.com"
                },
                "description": "Finish SSO/MFA; resume on dashboard"
            },
            {
                "action": "await_browser_event",
                "timeout": 600,
                "wait_condition": {
                    "key_combo": "ctrl_enter",
                    "show_overlay_button": True,         # optional floating “Resume” button
                    "local_storage_key": "__scrapeResume",       # optional; defaults to this
                    # Optional custom predicate (any truthy JS result resumes):
                    # "predicate_js": "return !!document.querySelector('.app-shell')",
                    # Optional custom DOM event name:
                    # "custom_event_name": "scrape-resume"
                },
                "description": "User completes SSO/MFA in the open browser; press Ctrl+Enter or click Resume."
            },
            {
                "action": "wait",
                "target": "#content-area",
                "timeout": 10,
                "description": "Ensure app is loaded"
            }
        ],
        "selectors": [
            {
                "name": "program",
                "selector": ".item-details",
                "extract_type": "text",
                "multiple": True
            }
        ]
    }

    try:
        print("🔄 Testing program extraction...")
        result = await tool._execute(**test_args)

        if result['status']:
            data = result['result'][0]['extracted_data']
            programs = data['program']

            print(f"✅ Success! Found {len(programs)} programs")
            print("\n💭 Sample program:")
            if programs:
                print(f"Program: {programs[0]}")
        else:
            print("❌ Test failed")

    except Exception as e:
        print(f"❌ Exception: {str(e)}")

async def test_bestbuy_scraping():
    print("\n🛍️ BestBuy Scraping Test")
    print("=" * 40)

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Best Buy Scraping Test:
    test_args = {
        "steps": [
            {
                'action': 'navigate',
                'target': 'https://www.bestbuy.com/?intl=nosplash',
                'description': 'Best Buy home'
            },
            {
                'action': 'wait',
                'target': 'presence_of_element_located:textarea[id="autocomplete-search-bar"], input[aria-label*="Search"]',
                'timeout': 5,
                'description': 'Wait for Text Area input to be present'
            },
            {
                'action': 'fill',
                'target': 'textarea[id="autocomplete-search-bar"], input[aria-label*="Search"]',
                'value': 'Google Pixel Pro 128GB',
                'description': 'Type product'
            },
            {
                'action': 'click',
                'target': 'button[id="autocomplete-search-button"], button[aria-label="Search-Button"]',
                'description': 'Submit search'
            },
            {
                'action': 'wait',
                'target': 'div[id="main-results"]',
                'timeout': 10,
                'description': 'Wait For Results'
            }
        ],
        'selectors': [
            {
                'name':'product_title',
                'selector': 'h2.product-title',
                'extract_type':'text',
                'multiple':True
            },
            {
                'name':'product_price',
                'selector': 'div[data-testid="price-block-customer-price"], span',
                'extract_type':'text',
                'multiple':True
            },
            {
                'name':'product_link',
                'selector': '.sku-block-content-title a.product-list-item-link',
                'extract_type':'attribute',
                'attribute':'href',
                'multiple':True
            }
        ]
    }

    try:
        print("🔄 Testing Best Buy extraction...")
        result = await tool._execute(**test_args)

        if result['status']:
            data = result['result'][0]['extracted_data']
            product_titles = data['product_title']
            product_prices = data['product_price']
            product_links = data['product_link']

            print(f"✅ Success! Found {len(product_titles)} products")
            print("\n💭 Sample product:")
            if product_titles:
                print(f"Product Title: {product_titles[0]}")
                print(f"Product Price: {product_prices[0]}")
                print(f"Product Link: {product_links[0]}")
        else:
            print("❌ Test failed")

    except Exception as e:
        print(f"❌ Exception: {str(e)}")

async def main():
    """Run all quick tests"""
    # await quick_test()
    # await test_product_scraping()
    # await test_human_interaction()
    await test_bestbuy_scraping()

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
