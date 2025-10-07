from __future__ import annotations
import re
from pathlib import Path
import asyncio
from typing import List, Optional
import pandas as pd
from bs4 import Tag, NavigableString
from pydantic import BaseModel, Field
from navconfig import BASE_DIR
from parrot.tools.scraping import WebScrapingTool

async def test_nav(output_path: Path, zipcodes: List[str]):
    print("\n🛍️ Navigation Test")
    print("=" * 40)

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Navigation Scraping Test:
    test_args = {
        "steps": [
            {
                'action': 'navigate',
                'url': 'https://manage.dispatch.me/login',
                'description': 'Dispatch login page'
            },
            {
                "action": "authenticate",
                "method": "form",
                "username_selector": "input[name='email']",
                "username": "troc-assurant@trocglobal.com",
                "enter_on_username": True,  # Press Enter after filling username
                "password_selector": "input[name='password']",
                "password": "bozhip-Juvhac-kektu0",
                "submit_selector": "button[type='submit']"
            },
            {
                "action": "wait",
                "timeout": 2,
                "condition_type": "url_is",
                "condition": "https://manage.dispatch.me/providers/list",
                "description": "Wait until redirected to providers list"
            },
            {
                'action': 'navigate',
                'url': 'https://manage.dispatch.me/recruit/out-of-network/list',
                'description': 'Go to Recruiters Page'
            },
            {
                "action": "click",
                "selector": "//button[contains(., 'Filtering On')]",
                "selector_type": "xpath",
                "description": "Click Filters button"
            },
            {
                "action": "wait",
                "timeout": 2,
                "condition_type": "simple",
                "description": "Wait 5 seconds"
            },
            {
                "action": "click",
                "selector": "//button[contains(., 'Filters')]",
                "selector_type": "xpath",
                "description": "Click Filters button"
            },
            {
                "action": "await_browser_event",
                "timeout": 600,
                "wait_condition": {
                    "key_combo": "ctrl_enter",
                    "show_overlay_button": True,
                    "local_storage_key": "__scrapeResume",
                },
                "description": "Wait for Human to complete filtering criteria; press Ctrl+Enter or click Resume."
            },
            {
                "action": "loop",
                "iterations": 0,
                "break_on_error": False,
                "description": "Iterate through all zipcodes",
                "values": ['10001', '90001', '60601', '94101'],  # zipcodes
                "value_name": "zipcode",
                "actions": [
                    {
                        "action": "fill",
                        "description": "Search {i+1} of 4: Zipcode {value}",
                        "selector": "input[placeholder='Zip Code']",
                        "value": "{value}",
                    },
                    {
                        'action': 'click',
                        'selector': '//button[@data-testid="Button" and contains(text(),"Find Providers")]',
                        'selector_type': 'xpath',
                        'description': 'Click on Find Providers button'
                    },
                    {
                        "action": "wait",
                        "timeout": 2,
                        "condition_type": "simple",
                        "description": "Wait 2 seconds until search finishes"
                    },
                    {
                        "action": "conditional",
                        "description": "Check for error and retry if needed",
                        "target": "div.css-0",
                        "target_type": "css",
                        "condition_type": "text_contains",
                        "expected_value": "There was an error, please refresh the page.",
                        "timeout": 2,
                        "actions_if_true": [
                            {
                                "action": "refresh",
                                "description": "Reload page due to error"
                            },
                            {
                                "action": "wait",
                                "timeout": 3,
                                "condition_type": "simple",
                                "description": "Wait after reload"
                            }
                        ],
                        "actions_if_false": [
                            {
                                'action': 'get_html',
                                'selector': '//div[@id and translate(@id, "0123456789", "") = ""]',
                                'selector_type': 'xpath',
                                'multiple': True,
                                'extract_name': 'numeric_id_divs',
                                'description': 'Extract all divs with numeric IDs'
                            }
                        ]  # Continue normally if no error
                    }
                ]
            }
        ],
        'selectors': []
    }

    try:
        result = await tool.execute(**test_args)
        print('Quantity of results: ', result.get('status'))
    except Exception as e:
        print(f"❌ Exception: {str(e)}")

async def main():
    """Run all quick tests"""
    output_path = BASE_DIR / "examples" / "scraper"
    # load the Excel of zipcodes
    zipcodes_df = pd.read_excel(output_path.joinpath("zipcodes.xlsx"))
    # convert the column "anchor_zip" in a list of zipcodes
    zipcodes = zipcodes_df['anchor_zip'].dropna().astype(str).tolist()
    if len(zipcodes) > 1:
        await test_nav(output_path, zipcodes)

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
