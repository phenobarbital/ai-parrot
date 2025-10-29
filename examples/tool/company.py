"""
Example usage of CompanyInfoToolkit - demonstrating all features.

This example shows:
1. Basic initialization
2. Using individual scraping methods
3. Using all sources at once
4. Working with structured outputs
5. Error handling
6. Integration with AI-Parrot agents
"""
import asyncio
import json
import traceback
from parrot.bots import Agent
from parrot.tools.company_info import CompanyInfoToolkit, CompanyInfo


async def example_basic_usage():
    """Example 1: Basic usage with a single platform."""
    print("=" * 60)
    print("Example 1: Basic Usage - Single Platform")
    print("=" * 60)

    # Initialize the toolkit
    toolkit = CompanyInfoToolkit(
        headless=True,
        timeout=30
    )

    # Scrape from LeadIQ
    print("\n1. Scraping PetSmart from LeadIQ...")
    result = await toolkit.scrape_leadiq("PetSmart")

    print(f"\nCompany: {result.company_name}")
    print(f"Status: {result.scrape_status}")
    print(f"Headquarters: {result.headquarters}")
    print(f"Phone: {result.phone_number}")
    print(f"Website: {result.website}")
    print(f"Revenue: {result.revenue_range}")
    print(f"Industry: {result.industry}")
    print(f"NAICS: {result.naics_code}")
    print(f"SIC: {result.sic_code}")


async def example_all_sources():
    """Example 2: Scrape from all sources simultaneously."""
    print("\n" + "=" * 60)
    print("Example 2: All Sources - Parallel Scraping")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        headless=True
    )

    # Scrape from all sources
    print("\nScraping 'Tesla' from all sources...")
    results = await toolkit.scrape_all_sources("Tesla")

    print(f"\nTotal sources scraped: {len(results)}")
    print("\nResults by platform:")
    print("-" * 60)

    for result in results:
        print(f"\n{result.source_platform.upper()}:")
        print(f"  Status: {result.scrape_status}")
        print(f"  Company: {result.company_name}")
        print(f"  Website: {result.website}")
        print(f"  Revenue: {result.revenue_range}")
        print(f"  Employees: {result.employee_count}")

        if result.scrape_status == 'error':
            print(f"  Error: {result.error_message}")


async def example_json_output():
    """Example 3: Getting JSON output instead of objects."""
    print("\n" + "=" * 60)
    print("Example 3: JSON Output Format")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        headless=True
    )

    # Get JSON output
    print("\nScraping 'Microsoft' from LeadIQ (JSON output)...")
    json_result = await toolkit.scrape_leadiq("Microsoft", return_json=True)

    # Parse and pretty print
    data = json.loads(json_result)
    print("\nJSON Result:")
    print(json.dumps(data, indent=2))

    # Convert back to object if needed
    company_info = CompanyInfo.from_dict(data)
    print(f"\nConverted back to object: {company_info.company_name}")


async def example_multiple_companies():
    """Example 4: Scraping multiple companies."""
    print("\n" + "=" * 60)
    print("Example 4: Multiple Companies")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        headless=True
    )

    companies = ["Apple", "Google", "Amazon", "Netflix", "Meta"]

    print(f"\nScraping {len(companies)} companies from RocketReach...")

    # Create tasks
    tasks = [
        toolkit.scrape_rocketreach(company)
        for company in companies
    ]

    # Run in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Display summary
    print("\n" + "-" * 60)
    print(f"{'Company':<20} {'Status':<15} {'Revenue':<20}")
    print("-" * 60)

    for company, result in zip(companies, results):
        if isinstance(result, Exception):
            print(f"{company:<20} {'ERROR':<15} {str(result)[:20]}")
        else:
            print(f"{company:<20} {result.scrape_status:<15} {result.revenue_range or 'N/A':<20}")


async def example_error_handling():
    """Example 5: Proper error handling."""
    print("\n" + "=" * 60)
    print("Example 5: Error Handling")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        headless=True,
        timeout=10  # Short timeout for testing
    )

    # Try to scrape a non-existent or difficult company
    print("\nAttempting to scrape 'NonExistentCompanyXYZ123'...")

    try:
        result = await toolkit.scrape_zoominfo("NonExistentCompanyXYZ123")

        if result.scrape_status == 'no_data':
            print("\n❌ No data found for this company")
            print(f"   Reason: {result.error_message}")
        elif result.scrape_status == 'error':
            print("\n❌ Error occurred during scraping")
            print(f"   Error: {result.error_message}")
        elif result.scrape_status == 'success':
            print("\n✅ Success!")
            print(f"   Company: {result.company_name}")

    except Exception as e:
        print(f"\n❌ Exception caught: {type(e).__name__}")
        print(f"   Message: {str(e)}")


async def example_with_proxy():
    """Example 6: Using proxy configuration."""
    print("\n" + "=" * 60)
    print("Example 6: Proxy Configuration")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        use_proxy=True,
        proxy_url="http://proxy.example.com:8080",
        headless=True
    )

    print("\nScraping with proxy enabled...")
    result = await toolkit.scrape_explorium("IBM")

    print(f"\nStatus: {result.scrape_status}")
    print(f"Company: {result.company_name}")


async def example_data_aggregation():
    """Example 7: Aggregating data from multiple sources."""
    print("\n" + "=" * 60)
    print("Example 7: Data Aggregation")
    print("=" * 60)

    toolkit = CompanyInfoToolkit(
        headless=True
    )

    company = "Walmart"
    print(f"\nAggregating data for '{company}' from all sources...")

    # Get all results
    all_results = await toolkit.scrape_all_sources(company)

    # Aggregate data
    aggregated = {
        'company_name': None,
        'websites': set(),
        'phone_numbers': set(),
        'headquarters': set(),
        'revenue_ranges': set(),
        'industries': set(),
        'naics_codes': set(),
        'sic_codes': set(),
        'sources': []
    }

    for result in all_results:
        if result.scrape_status == 'success':
            aggregated['sources'].append(result.source_platform)

            if result.company_name:
                aggregated['company_name'] = result.company_name
            if result.website:
                aggregated['websites'].add(result.website)
            if result.phone_number:
                aggregated['phone_numbers'].add(result.phone_number)
            if result.headquarters:
                aggregated['headquarters'].add(result.headquarters)
            if result.revenue_range:
                aggregated['revenue_ranges'].add(result.revenue_range)
            if result.industry:
                if isinstance(result.industry, list):
                    aggregated['industries'].update(result.industry)
                else:
                    aggregated['industries'].add(result.industry)
            if result.naics_code:
                aggregated['naics_codes'].add(result.naics_code)
            if result.sic_code:
                aggregated['sic_codes'].add(result.sic_code)

    # Display aggregated data
    print(f"\n{'='*60}")
    print(f"AGGREGATED DATA FOR: {aggregated['company_name']}")
    print(f"{'='*60}")
    print(f"\nData sources: {', '.join(aggregated['sources'])}")
    print(f"\nWebsites found: {len(aggregated['websites'])}")
    for website in aggregated['websites']:
        print(f"  - {website}")

    print(f"\nPhone numbers found: {len(aggregated['phone_numbers'])}")
    for phone in aggregated['phone_numbers']:
        print(f"  - {phone}")

    print(f"\nRevenue ranges found: {len(aggregated['revenue_ranges'])}")
    for revenue in aggregated['revenue_ranges']:
        print(f"  - {revenue}")

    print(f"\nIndustries found: {len(aggregated['industries'])}")
    for industry in list(aggregated['industries'])[:5]:  # Show first 5
        print(f"  - {industry}")


async def example_integration_with_agent():
    """Example 8: Integration with AI-Parrot Agent."""
    print("\n" + "=" * 60)
    print("Example 8: Integration with AI-Parrot Agent")
    print("=" * 60)

    # Initialize toolkit
    toolkit = CompanyInfoToolkit(
        headless=True
    )

    # Get all tools
    tools = toolkit.get_tools()

    print(f"\nAvailable tools: {len(tools)}")
    for tool in tools:
        print(f"  - {tool.name}")

    # Create agent with company scraping tools
    agent = Agent(
        name="CompanyResearchAgent",
        model="gpt-4",
        tools=tools
    )
    # Now the agent can use any scraping tool!
    response = await agent.ask(
        "Find me information about Tesla from all available sources"
    )
    print("\nAgent Response:")
    print(response)


async def main():
    """Run all examples."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  CompanyInfoToolkit - Complete Usage Examples".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")

    try:
        # Run examples (comment out ones you don't want to run)

        await example_basic_usage()
        # await example_all_sources()
        # await example_json_output()
        # await example_multiple_companies()
        # await example_error_handling()
        # await example_with_proxy()
        # await example_data_aggregation()
        # await example_integration_with_agent()

        print("\n" + "=" * 60)
        print("All examples completed!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️  Examples interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error running examples: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    # Note: You need to set your Google API credentials before running
    print("\n⚠️  Remember to set your Google API credentials!")
    print("   - GOOGLE_API_KEY")
    print("   - GOOGLE_CSE_ID")
    print("\n")

    # Uncomment to run all examples
    asyncio.run(main())
