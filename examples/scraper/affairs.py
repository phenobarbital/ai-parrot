from pathlib import Path
import asyncio
from parrot.tools.scraping import WebScrapingTool

async def test_consumer_scraping():
    print("\n🛍️ Consumer Affairs Scraping Test")
    print("=" * 40)

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Consumer Affairs Scraping Test:
    test_args = {
        "steps": [
            {
                'action': 'navigate',
                'url': 'https://www.consumeraffairs.com/homeowners/service-protection-advantage.html',
                'description': 'Consumer Affairs home'
            },
            {
                "action": "await_browser_event",
                "timeout": 600,
                "wait_condition": {
                    "key_combo": "ctrl_enter",
                    "show_overlay_button": True,
                    "local_storage_key": "__scrapeResume",
                },
                "description": "User completes SSO/MFA in the open browser; press Ctrl+Enter or click Resume."
            },
            {
                "action": "loop",
                "iterations": 3,
                "break_on_error": False,
                "description": "Iterate through 3 pages",
                "actions": [
                    {
                        "action": "scroll",
                        "direction": "bottom",
                        "smooth": False,
                        "description": "Scroll to bottom of page"
                    },
                    {
                        "action": "click",
                        "selector": "a[rel='next'], .js-pager-next",
                        "wait_after_click": "#reviews-container",
                        "wait_timeout": 5,
                        "description": "Click next page button"
                    },
                    {
                        'action': 'wait',
                        'selector': "#reviews-container [itemprop='reviews'], #reviews-container .rvw",
                        'timeout': 10,
                        'description': 'Wait for reviews to load'
                    },
                    {
                        'action': 'screenshot',
                        'selector': None,  # Full page
                        'full_page': True,
                        'output_path': 'screenshots/',
                        'return_base64': False,
                        'description': 'Take full page screenshot'
                    },
                ]
            }
        ],
        'selectors': [
            {
                'name':'reviews',
                'selector': "#reviews-container [itemprop='reviews'], #reviews-container .rvw",
                'extract_type':'text',
                'multiple':True
            }
        ]
    }

    try:
        print("🔄 Testing Consumer Affairs extraction...")
        result = await tool._execute(**test_args)

        if result['status']:
            data = result['result'][0]['extracted_data']
            reviews = data['reviews']
            print(f"✅ Success! Found {len(reviews)} reviews")
            print("\n💭 Sample review:")
            if reviews:
                print(f"Review: {reviews[0]}")
        else:
            print("❌ Test failed")

    except Exception as e:
        print(f"❌ Exception: {str(e)}")

async def main():
    """Run all quick tests"""
    await test_consumer_scraping()

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
