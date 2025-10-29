# CompanyInfoToolkit

A comprehensive toolkit for scraping company information from multiple business intelligence platforms. Built as an extension of AI-Parrot's `AbstractToolkit`, this toolkit provides unified access to company data from ZoomInfo, LeadIQ, Explorium, RocketReach, and SICCode.

## 🌟 Features

- **Multi-Platform Support**: Scrape from 5 major business intelligence platforms
- **Unified Data Model**: Homogenized company information across all sources
- **Async/Await**: Full async support for efficient parallel scraping
- **Automatic Tool Generation**: All public methods become AI-Parrot tools automatically
- **Google Site Search Integration**: Smart search to find company pages
- **Selenium Web Scraping**: Robust browser automation with configurable options
- **Structured Outputs**: Pydantic models with JSON serialization
- **Error Handling**: Comprehensive error handling and status tracking
- **Proxy Support**: Built-in proxy configuration for enterprise use

## 📋 Supported Platforms

| Platform | Features | Data Quality |
|----------|----------|--------------|
| **ZoomInfo** | Executives, revenue, NAICS/SIC codes | ⭐⭐⭐⭐⭐ |
| **LeadIQ** | Contact info, similar companies | ⭐⭐⭐⭐ |
| **Explorium** | Industry data, NAICS/SIC codes | ⭐⭐⭐⭐ |
| **RocketReach** | Comprehensive company profiles | ⭐⭐⭐⭐ |
| **SICCode** | SIC/NAICS classification, location | ⭐⭐⭐⭐ |

## 🚀 Quick Start

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install ChromeDriver (if not already installed)
# On macOS:
brew install chromedriver

# On Linux:
sudo apt-get install chromium-chromedriver

# Or use webdriver-manager (recommended)
pip install webdriver-manager
```

### Basic Usage

```python
import asyncio
from company_info_toolkit import CompanyInfoToolkit

async def main():
    # Initialize toolkit
    toolkit = CompanyInfoToolkit(
        google_api_key="YOUR_GOOGLE_API_KEY",
        google_cse_id="YOUR_GOOGLE_CSE_ID",
        headless=True
    )

    # Scrape from a single platform
    result = await toolkit.scrape_zoominfo("Tesla")
    print(f"Company: {result.company_name}")
    print(f"Revenue: {result.revenue_range}")

    # Scrape from all platforms
    all_results = await toolkit.scrape_all_sources("Tesla")
    for r in all_results:
        print(f"{r.source_platform}: {r.company_name}")

asyncio.run(main())
```

## 📖 Documentation

### CompanyInfoToolkit Class

#### Initialization Parameters

```python
CompanyInfoToolkit(
    google_api_key: str = None,        # Google Custom Search API key
    google_cse_id: str = None,         # Google Custom Search Engine ID
    use_proxy: bool = False,           # Enable proxy usage
    proxy_url: str = None,             # Proxy server URL
    headless: bool = True,             # Run browser in headless mode
    timeout: int = 30                  # Page load timeout (seconds)
)
```

### Available Methods (Tools)

All public async methods automatically become tools when using AbstractToolkit.

#### 1. `scrape_zoominfo(company_name, return_json=False)`

Scrape company information from ZoomInfo.

**Returns:**
- Company name, headquarters, phone, website
- Revenue range, stock symbol
- NAICS/SIC codes, industry
- Company description
- Executive team with profiles

**Example:**
```python
result = await toolkit.scrape_zoominfo("Microsoft")
print(result.executives)  # List of executives
```

#### 2. `scrape_leadiq(company_name, return_json=False)`

Scrape company information from LeadIQ.

**Returns:**
- Company name, logo, description
- Contact information
- Revenue range, employee count
- Location details
- Similar companies

**Example:**
```python
result = await toolkit.scrape_leadiq("Apple")
print(result.similar_companies)  # JSON string of similar companies
```

#### 3. `scrape_explorium(company_name, return_json=False)`

Scrape company information from Explorium.ai.

**Returns:**
- Company name, logo, description
- Headquarters and location
- NAICS/SIC codes with descriptions
- Industry classification

**Example:**
```python
result = await toolkit.scrape_explorium("Amazon")
print(f"NAICS: {result.naics_code}")
print(f"Industry: {result.industry}")
```

#### 4. `scrape_rocketreach(company_name, return_json=False)`

Scrape company information from RocketReach.

**Returns:**
- Company name, logo, description
- Contact information
- Revenue, funding, employee count
- Industry and keywords
- Multiple NAICS/SIC codes

**Example:**
```python
result = await toolkit.scrape_rocketreach("Netflix")
print(f"Founded: {result.founded}")
print(f"Keywords: {result.keywords}")
```

#### 5. `scrape_siccode(company_name, return_json=False)`

Scrape company information from SICCode.com.

**Returns:**
- Company name and description
- SIC/NAICS codes with classifications
- Detailed location (city, state, zip, country, metro area)
- Industry category

**Example:**
```python
result = await toolkit.scrape_siccode("Google")
print(f"SIC Code: {result.sic_code}")
print(f"Category: {result.category}")
```

#### 6. `scrape_all_sources(company_name, return_json=False)`

Scrape from ALL platforms in parallel.

**Returns:**
- List of CompanyInfo objects from all platforms
- Automatic error handling per platform
- Aggregated results

**Example:**
```python
results = await toolkit.scrape_all_sources("IBM")
for r in results:
    if r.scrape_status == 'success':
        print(f"{r.source_platform}: {r.company_name}")
```

### CompanyInfo Data Model

The `CompanyInfo` Pydantic model provides a unified structure for all scraped data:

```python
class CompanyInfo(BaseModel):
    # Search metadata
    search_term: Optional[str]
    search_url: Optional[str]
    source_platform: Optional[str]
    scrape_status: str  # 'pending', 'success', 'no_data', 'error'

    # Company basics
    company_name: Optional[str]
    logo_url: Optional[str]
    company_description: Optional[str]

    # Location
    headquarters: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]
    country: Optional[str]
    metro_area: Optional[str]

    # Contact
    phone_number: Optional[str]
    website: Optional[str]

    # Classification
    industry: Optional[Union[str, List[str]]]
    industry_category: Optional[str]
    category: Optional[str]
    keywords: Optional[List[str]]
    naics_code: Optional[str]
    sic_code: Optional[str]

    # Financial & size
    stock_symbol: Optional[str]
    revenue_range: Optional[str]
    employee_count: Optional[str]
    number_employees: Optional[str]
    company_size: Optional[str]
    founded: Optional[str]
    funding: Optional[str]

    # Additional
    executives: Optional[List[Dict[str, str]]]
    similar_companies: Optional[Union[str, List[Dict]]]
    social_media: Optional[Dict[str, str]]

    # Metadata
    timestamp: Optional[str]
    error_message: Optional[str]
```

## 🔧 Configuration

### Google Custom Search Setup

1. **Get API Key:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable "Custom Search API"
   - Create credentials (API Key)

2. **Create Custom Search Engine:**
   - Go to [Programmable Search Engine](https://programmablesearchengine.google.com/)
   - Create new search engine
   - Select "Search the entire web"
   - Get your Search Engine ID (CSE ID)

3. **Set Environment Variables:**
```bash
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_CSE_ID="your-cse-id"
```

### Selenium Configuration

The toolkit uses Chrome by default. You can customize browser options:

```python
toolkit = CompanyInfoToolkit(
    google_api_key="...",
    google_cse_id="...",
    headless=False,      # Show browser (useful for debugging)
    use_proxy=True,      # Use proxy
    proxy_url="http://proxy.example.com:8080",
    timeout=60           # Longer timeout for slow pages
)
```

### Using with Undetected Chrome

For better bot detection evasion, install `undetected-chromedriver`:

```bash
pip install undetected-chromedriver
```

Then modify the toolkit to use it (requires code modification).

## 🎯 Advanced Usage

### Parallel Scraping Multiple Companies

```python
async def scrape_multiple(companies):
    toolkit = CompanyInfoToolkit(
        google_api_key="...",
        google_cse_id="..."
    )

    tasks = [
        toolkit.scrape_zoominfo(company)
        for company in companies
    ]

    results = await asyncio.gather(*tasks)
    return results

# Usage
companies = ["Tesla", "Apple", "Microsoft", "Google", "Amazon"]
results = await scrape_multiple(companies)
```

### Data Aggregation

```python
async def aggregate_company_data(company_name):
    toolkit = CompanyInfoToolkit(...)

    # Get all sources
    results = await toolkit.scrape_all_sources(company_name)

    # Aggregate unique values
    aggregated = {
        'name': None,
        'websites': set(),
        'phones': set(),
        'industries': set(),
        'codes': {'naics': set(), 'sic': set()}
    }

    for r in results:
        if r.scrape_status == 'success':
            if r.company_name:
                aggregated['name'] = r.company_name
            if r.website:
                aggregated['websites'].add(r.website)
            if r.phone_number:
                aggregated['phones'].add(r.phone_number)
            if r.industry:
                if isinstance(r.industry, list):
                    aggregated['industries'].update(r.industry)
                else:
                    aggregated['industries'].add(r.industry)
            if r.naics_code:
                aggregated['codes']['naics'].add(r.naics_code)
            if r.sic_code:
                aggregated['codes']['sic'].add(r.sic_code)

    return aggregated
```

### Integration with AI-Parrot Agents

```python
from parrot.bots import Agent
from company_info_toolkit import CompanyInfoToolkit

# Create toolkit
company_toolkit = CompanyInfoToolkit(
    google_api_key="...",
    google_cse_id="..."
)

# Create agent with company scraping tools
agent = Agent(
    name="CompanyResearchAgent",
    model="gpt-4",
    tools=company_toolkit.get_tools(),
    system_prompt="""You are a company research assistant.
    Use the available tools to gather comprehensive information
    about companies from multiple sources."""
)

# Use the agent
response = await agent.execute(
    "Find detailed information about Tesla, including their "
    "revenue, executive team, and industry classification."
)
```

## ⚠️ Important Notes

### Rate Limiting

- Google Custom Search API: 100 queries/day (free tier)
- Consider implementing caching for frequently searched companies
- Add delays between requests to avoid being rate-limited

### Legal Considerations

- Respect robots.txt and terms of service
- This tool is for educational/research purposes
- Commercial use may require agreements with data providers
- Some sites may block automated scraping

### Error Handling

The toolkit provides detailed status tracking:

```python
result = await toolkit.scrape_zoominfo("CompanyName")

if result.scrape_status == 'success':
    # Data successfully scraped
    print(result.company_name)
elif result.scrape_status == 'no_data':
    # No results found
    print(f"No data: {result.error_message}")
elif result.scrape_status == 'error':
    # Error occurred
    print(f"Error: {result.error_message}")
```

## 🧪 Testing

Run the example file to test all features:

```bash
python example_usage.py
```

## 📝 TODO / Roadmap

- [ ] Add support for more platforms (Crunchbase, LinkedIn)
- [ ] Implement caching layer (Redis/SQLite)
- [ ] Add retry logic with exponential backoff
- [ ] Support for batch CSV processing
- [ ] Add data validation and cleaning
- [ ] Implement rate limiting
- [ ] Add support for authenticated sessions
- [ ] Create web UI for manual testing
- [ ] Add unit tests with pytest
- [ ] Add logging to file
- [ ] Support for custom selectors via config

## 🤝 Contributing

Contributions are welcome! Areas for improvement:

1. **New Platforms**: Add scrapers for additional sources
2. **Data Quality**: Improve parsing accuracy
3. **Performance**: Optimize Selenium usage
4. **Documentation**: Add more examples
5. **Testing**: Add comprehensive test suite

## 📄 License

This project is part of the AI-Parrot framework. Please refer to the main project license.

## 🔗 Related Projects

- [AI-Parrot](https://github.com/your-org/ai-parrot) - Main framework
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [Selenium](https://www.selenium.dev/) - Browser automation
- [Pydantic](https://docs.pydantic.dev/) - Data validation

## 📞 Support

For issues, questions, or contributions:
- Open an issue on GitHub
- Contact the AI-Parrot team
- Check the documentation

## 🎓 Examples Gallery

Check the `example_usage.py` file for comprehensive examples including:
- Basic single-platform scraping
- Parallel multi-platform scraping
- JSON output handling
- Error handling patterns
- Data aggregation strategies
- Agent integration examples

---

**Built with ❤️ for the AI-Parrot framework**
