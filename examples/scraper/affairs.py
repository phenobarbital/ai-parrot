from typing import Optional
from pathlib import Path
import asyncio
import pandas as pd
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup, Tag
from navconfig import BASE_DIR
from parrot.tools.scraping import WebScrapingTool


class Review(BaseModel):
    """Structured review data from ConsumerAffairs"""
    itemtype: Optional[str] = Field(None, description="Schema.org itemtype for author")
    reviewer_name: Optional[str] = Field(None, description="Name of the reviewer")
    reviewer_location: Optional[str] = Field(None, description="Location of the reviewer")
    rating: Optional[int] = Field(None, description="Rating value (1-5)")
    verified_purchase: bool = Field(False, description="Whether purchase was verified")
    review_date: Optional[str] = Field(None, description="Date of the review")
    review_content: Optional[str] = Field(None, description="Main review text content")
    review_id: Optional[str] = Field(None, description="Unique review ID")


def parse_review(card: Tag) -> Optional[Review]:
    """
    Parse a BeautifulSoup Tag object containing a ConsumerAffairs review.

    Args:
        card: BeautifulSoup Tag object with the review HTML

    Returns:
        Review object with extracted data, or None if parsing fails
    """
    if not card or not isinstance(card, Tag):
        return None

    try:
        # Extract review ID
        review_id = card.get('data-id') or card.get('id', '').replace('review-', '')

        # Extract author itemtype
        author_div = card.find('div', {'itemprop': 'author', 'itemscope': True})
        itemtype = None
        if author_div:
            itemtype = author_div.get('itemtype')

        # Extract reviewer name
        reviewer_name = None
        name_span = card.find('span', class_='rvw__inf-nm')
        if name_span:
            reviewer_name = name_span.get_text(strip=True)

        # Extract reviewer location
        reviewer_location = None
        location_span = card.find('span', class_='rvw__inf-lctn')
        if location_span:
            reviewer_location = location_span.get_text(strip=True)

        # Extract rating
        rating = None
        rating_meta = card.find('meta', {'itemprop': 'ratingValue'})
        if rating_meta:
            try:
                rating = int(rating_meta.get('content', 0))
            except (ValueError, TypeError):
                rating = None

        # Check if purchase was verified
        verified_purchase = False
        verified_span = card.find('span', class_='rvw__inf-ver')
        if verified_span and 'Verified purchase' in verified_span.get_text():
            verified_purchase = True

        # Extract review date
        review_date = None
        date_p = card.find('p', class_='rvw__rvd-dt')
        if date_p:
            review_date = date_p.get_text(strip=True).replace('Reviewed', '').strip()

        # Extract review content
        review_content = None
        content_div = card.find('div', class_='rvw__bd')
        if content_div:
            # Get the main review text from rvw__top-text
            top_text = content_div.find('div', class_='rvw__top-text')
            if top_text:
                # Extract all paragraph text
                paragraphs = top_text.find_all('p')
                review_content = ' '.join(p.get_text(strip=True) for p in paragraphs)

        return Review(
            itemtype=itemtype,
            reviewer_name=reviewer_name,
            reviewer_location=reviewer_location,
            rating=rating,
            verified_purchase=verified_purchase,
            review_date=review_date,
            review_content=review_content,
            review_id=review_id
        )

    except Exception as e:
        print(f"Error in parse_review: {str(e)}")
        return None

async def test_consumer_scraping(output_path: Path):
    print("\n🛍️ Consumer Affairs Scraping Test")
    print("=" * 40)

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Consumer Affairs Scraping Test:
    # test_args = {
    #     "steps": [
    #         {
    #             'action': 'navigate',
    #             'url': 'https://www.consumeraffairs.com/homeowners/service-protection-advantage.html',
    #             'description': 'Consumer Affairs home'
    #         },
    #         {
    #             "action": "await_browser_event",
    #             "timeout": 600,
    #             "wait_condition": {
    #                 "key_combo": "ctrl_enter",
    #                 "show_overlay_button": True,
    #                 "local_storage_key": "__scrapeResume",
    #             },
    #             "description": "User completes SSO/MFA in the open browser; press Ctrl+Enter or click Resume."
    #         },
    #         {
    #             "action": "loop",
    #             "iterations": 2,
    #             "break_on_error": False,
    #             "description": "Iterate through 2 pages",
    #             "actions": [
    #                 {
    #                     'action': 'wait',
    #                     'selector': "#reviews-container",
    #                     'timeout': 5,
    #                     'description': 'Wait for reviews to load'
    #                 },
    #                 {
    #                     'action': 'get_html',
    #                     'selector': '#reviews-container [itemprop="reviews"]',
    #                     'selector_type': 'css',
    #                     'multiple': True,
    #                     'description': 'Extract all review divs'
    #                 },
    #                 {
    #                     "action": "click",
    #                     "selector": "a[rel='next'], .js-pager-next",
    #                     "wait_after_click": "#reviews-container",
    #                     "wait_timeout": 5,
    #                     "description": "Click next page button"
    #                 },
    #             ]
    #         }
    #     ],
    #     'selectors': []
    # }

    test_args = {
        "steps": [
            {
                "action": "loop",
                "iterations": 10,
                "break_on_error": False,
                "description": "Iterate through 50 pages",
                "actions": [
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
                        'action': 'get_html',
                        'selector': '#reviews-container [itemprop="reviews"]',
                        'selector_type': 'css',
                        'multiple': True,
                        'description': 'Extract all review divs'
                    }
                ]
            }
        ],
        'selectors': []
    }

    try:
        print("🔄 Testing Consumer Affairs extraction...")
        result = await tool._execute(**test_args)
        results = []
        if result['status']:
            for r in result['result']:
                card = r.get('bs')
                try:
                    review = parse_review(card)
                    if review:
                        results.append(review.model_dump())
                except Exception as e:
                    print(f"Error parsing provider div: {str(e)}")
        if results:
            df = pd.DataFrame(results)
            print("\nExtracted Providers DataFrame:")
            print(df)
            # Save to CSV
            output_file = output_path.joinpath("reviews.csv")
            df.to_csv(output_file, index=False, sep='|')
            print(f"\nData saved to {output_file.resolve()}")

    except Exception as e:
        print(f"❌ Exception: {str(e)}")

async def main():
    """Run all quick tests"""
    output_path = BASE_DIR / "examples" / "scraper"
    await test_consumer_scraping(output_path)

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
