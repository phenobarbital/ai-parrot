import asyncio
from pathlib import Path
from parrot.bots.scraper import ScrapingAgent
from parrot.models.google import GoogleModel

async def check_scrapping_agent():
    """Example of using the ScrapingAgent with adaptive configuration"""
    agent = ScrapingAgent(
        browser='chrome',  # Use undetected-chromedriver
        headless=False,        # For debugging
        mobile=False,           # For mobile testing
        driver_type='selenium', # Using Selenium
        max_tokens=8192,
        temperature=0,
        model=GoogleModel.GEMINI_2_5_FLASH_PREVIEW,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        debugger_address="127.0.0.1:9222",
    )
    await agent.configure()

    # Get recommendations for a site
    # recommendations = await agent.get_site_recommendations('https://www.bestbuy.com/?intl=nosplash')
    # print('Site Recommendations:', recommendations)

    # Execute intelligent scraping with adaptive configuration
    request = {
        'target_url': 'https://www.bestbuy.com/?intl=nosplash',
        'objective': 'Extract Product Price and product URL for Google Pixel 10 Pro 128GB',
        'constraints': 'Respect rate limits',
        'use_template': True,
        # 'steps': [
        #     'write the product into <textarea> with placeholder "Search Best Buy"',
        #     'click on button "autocomplete-search-button"',
        #     'on results page, search for any <div> "sku-block" to extract product URL and price'
        # ]
    }

    results = await agent.execute_intelligent_scraping(
        request,
        adaptive_config=False  # Allow browser config changes
    )

if __name__ == "__main__":
    asyncio.run(check_scrapping_agent())
