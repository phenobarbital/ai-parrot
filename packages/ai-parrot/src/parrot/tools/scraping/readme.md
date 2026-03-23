# ScrapingAgent for AI-Parrot

An intelligent web scraping agent that uses natural language to control web scraping operations with LLM-powered planning and execution.

## Overview

The ScrapingAgent combines the power of large language models with browser automation to create a natural language interface for web scraping. It analyzes web pages, generates optimal scraping strategies, and executes complex scraping workflows with minimal manual configuration.

### Key Features

- **Natural Language Control**: Describe what you want to scrape in plain English
- **Intelligent Analysis**: Automatically analyzes page structure and complexity
- **Strategic Planning**: Generates step-by-step navigation and extraction plans
- **Structured Output**: Uses Pydantic models for validation and type safety
- **Multiple Browser Support**: Selenium and Playwright, regular and undetected modes
- **Mobile Emulation**: Scrape mobile versions of websites
- **Authentication Handling**: Built-in support for login workflows
- **Plan Refinement**: Iteratively improve plans based on execution results
- **RESTful API**: Full HTTP API for integration with other services

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  ScrapingAgent                       │
│  (Inherits from BasicAgent → AbstractBot)           │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐  ┌────────────────┐              │
│  │   Analysis   │  │  Plan Generation│              │
│  │   Module     │  │    & Validation │              │
│  └──────┬───────┘  └────────┬────────┘              │
│         │                   │                        │
│         └────────┬──────────┘                        │
│                  │                                   │
│         ┌────────▼────────┐                          │
│         │  Execution      │                          │
│         │  Orchestrator   │                          │
│         └────────┬────────┘                          │
│                  │                                   │
│         ┌────────▼────────┐                          │
│         │ WebScrapingTool │                          │
│         └────────┬────────┘                          │
│                  │                                   │
│    ┌─────────────┴─────────────┐                    │
│    │                            │                    │
│ ┌──▼────────┐          ┌───────▼────┐               │
│ │ Selenium  │          │ Playwright │               │
│ │  Driver   │          │   Driver   │               │
│ └───────────┘          └────────────┘               │
└─────────────────────────────────────────────────────┘
```

## Installation

```bash
# Install AI-parrot with scraping dependencies
pip install ai-parrot[scraping]

# Or install individual dependencies
pip install selenium playwright undetected-chromedriver
pip install beautifulsoup4 lxml

# Install playwright browsers
playwright install
```

## Quick Start

### Basic Usage

```python
import asyncio
from parrot.agents.scraping_agent import ScrapingAgent

async def main():
    # Create agent
    agent = ScrapingAgent(
        name="MyScraper",
        llm="openai",
        model="gpt-4"
    )

    # Configure agent
    await agent.configure()

    # Scrape with natural language
    result = await agent.scrape(
        "Extract all article titles and authors from https://news.ycombinator.com"
    )

    print(f"Status: {result['status']}")
    print(f"Pages scraped: {result['metadata']['total_pages_scraped']}")

    # Access extracted data
    for page_result in result['result']:
        if page_result['success']:
            print(f"\nURL: {page_result['url']}")
            print(f"Data: {page_result['extracted_data']}")

asyncio.run(main())
```

### Advanced Usage with Plan Control

```python
async def advanced_scraping():
    agent = ScrapingAgent(
        name="AdvancedScraper",
        llm="anthropic",
        model="claude-sonnet-4"
    )
    await agent.configure()

    # Step 1: Generate plan
    plan = await agent.generate_scraping_plan(
        objective="Search for Python jobs and extract job titles, companies, and locations",
        url="https://jobs.example.com",
        context={
            "search_query": "Python Developer",
            "location": "Remote"
        }
    )

    # Step 2: Review and modify plan if needed
    print(f"Generated {len(plan.steps)} steps")
    print(f"Using {len(plan.selectors)} selectors")

    # Optionally modify the plan
    plan.browser_config.headless = False  # Show browser

    # Step 3: Execute the plan
    result = await agent.execute_plan(plan)

    # Step 4: Refine if needed
    if not result['status']:
        refined_plan = await agent.refine_plan(
            plan,
            feedback="The search button selector was incorrect. Try '#search-btn' instead."
        )
        result = await agent.execute_plan(refined_plan)

    return result
```

## Structured Output Schemas

### ScrapingPlanSchema

The complete plan for a scraping operation:

```python
from parrot.agents.scraping_agent import (
    ScrapingPlanSchema,
    BrowserConfigSchema,
    NavigationStepSchema,
    SelectorSchema,
    PageAnalysisSchema
)

# Create a manual plan
plan = ScrapingPlanSchema(
    objective="Extract product information",
    analysis=PageAnalysisSchema(
        url="https://shop.example.com",
        page_type="product listing",
        complexity="moderate",
        requires_javascript=True,
        has_pagination=True,
        has_authentication=False,
        key_elements=["product cards", "prices"],
        potential_challenges=["lazy loading"],
        recommended_approach="Use browser with scroll"
    ),
    browser_config=BrowserConfigSchema(
        browser="chrome",
        headless=True,
        mobile=False
    ),
    steps=[
        NavigationStepSchema(
            action="navigate",
            description="Go to products page",
            target="https://shop.example.com/products"
        ),
        NavigationStepSchema(
            action="wait",
            description="Wait for products",
            target=".product-card",
            timeout=10
        )
    ],
    selectors=[
        SelectorSchema(
            name="titles",
            selector=".product-title",
            extract_type="text",
            multiple=True
        )
    ]
)
```

### BrowserConfigSchema

Browser configuration options:

```python
config = BrowserConfigSchema(
    browser="chrome",          # or "firefox", "edge", "safari", "undetected"
    headless=True,              # Run without UI
    mobile=False,               # Emulate mobile device
    mobile_device="iPhone 12",  # Specific device to emulate
    driver_type="selenium",     # or "playwright"
    auto_install=True          # Auto-install drivers
)
```

### NavigationStepSchema

Individual scraping steps:

```python
# Navigate to URL
step1 = NavigationStepSchema(
    action="navigate",
    description="Go to homepage",
    target="https://example.com"
)

# Click element
step2 = NavigationStepSchema(
    action="click",
    description="Click search button",
    target="#search-btn",
    wait_after=2.0
)

# Fill form
step3 = NavigationStepSchema(
    action="fill",
    description="Enter search query",
    target="input[name='q']",
    value="web scraping"
)

# Wait for element
step4 = NavigationStepSchema(
    action="wait",
    description="Wait for results",
    target=".search-result",
    timeout=10
)

# Scroll
step5 = NavigationStepSchema(
    action="scroll",
    description="Scroll to bottom",
    target="bottom"
)
```

### SelectorSchema

Content extraction selectors:

```python
# Extract text
selector1 = SelectorSchema(
    name="product_titles",
    selector=".product h2",
    selector_type="css",
    extract_type="text",
    multiple=True
)

# Extract attribute
selector2 = SelectorSchema(
    name="product_images",
    selector=".product img",
    selector_type="css",
    extract_type="attribute",
    attribute="src",
    multiple=True
)

# Extract HTML
selector3 = SelectorSchema(
    name="product_descriptions",
    selector=".description",
    extract_type="html",
    multiple=False
)
```

## Integration Patterns

### With BotManager

```python
from parrot.manager import BotManager
from parrot.agents.scraping_agent import ScrapingAgent

async def with_manager():
    manager = BotManager()

    # Create through manager
    agent = await manager.create_agent(
        class_name=ScrapingAgent,
        name="ManagedScraper",
        llm={"name": "openai", "model": "gpt-4"}
    )

    # Use the agent
    result = await agent.scrape(
        "Extract news headlines from BBC"
    )

    return result
```

### With Agent Registry

```python
from parrot.registry import agent_registry
from parrot.agents.scraping_agent import ScrapingAgent

# Register at startup
@agent_registry.register_agent(
    name="ScrapingAgent",
    singleton=True,
    at_startup=True,
    startup_config={
        "llm": "anthropic",
        "model": "claude-sonnet-4"
    },
    tags={"scraping", "automation"},
    priority=100
)
class MyScrapingAgent(ScrapingAgent):
    pass

# Later, get the agent
agent = await agent_registry.get_instance("ScrapingAgent")
```

### RESTful API

```python
from aiohttp import web
from parrot.handlers.scraping_agent_handler import create_scraping_api

async def run_api():
    app = await create_scraping_api(
        llm="openai",
        model="gpt-4"
    )
    web.run_app(app, host="0.0.0.0", port=8080)

# API Endpoints:
# POST /api/v1/scraping/analyze       - Analyze page
# POST /api/v1/scraping/plan          - Generate plan
# POST /api/v1/scraping/execute       - Execute plan
# POST /api/v1/scraping/scrape        - Complete workflow
# GET  /api/v1/scraping/plans/{id}    - Get plan
# POST /api/v1/scraping/plans/{id}/refine - Refine plan
# GET  /api/v1/scraping/health        - Health check
```

Example API request:

```bash
curl -X POST http://localhost:8080/api/v1/scraping/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "objective": "Extract product names and prices",
    "url": "https://shop.example.com",
    "return_plan": true
  }'
```

## Common Use Cases

### 1. E-commerce Scraping

```python
result = await agent.scrape("""
Go to https://shop.example.com/laptops
Extract for each product:
- Product name
- Price
- Rating
- Availability
- Image URL
Handle pagination to get all products
""")
```

### 2. News Aggregation

```python
result = await agent.scrape("""
From https://news.example.com:
1. Get all article headlines
2. For each article, extract:
   - Title
   - Author
   - Publication date
   - Summary
   - Category tags
3. Handle "Load More" button
""")
```

### 3. Job Board Scraping

```python
result = await agent.scrape(
    objective="""
    Search for 'Python Developer' jobs
    Extract: job title, company, location, salary range
    Apply filters: Remote only, Full-time
    Get results from all pages
    """,
    url="https://jobs.example.com",
    context={
        "requires_search": True,
        "has_filters": True
    }
)
```

### 4. Social Media Scraping

```python
# Requires authentication
result = await agent.scrape(
    objective="Extract my last 10 posts with engagement metrics",
    url="https://social.example.com/profile",
    context={
        "requires_login": True,
        "credentials": {
            "username": "user@example.com",
            "password": os.getenv("PASSWORD")
        }
    }
)
```

### 5. Real Estate Listings

```python
result = await agent.scrape("""
From https://realestate.example.com:
Search for: Apartments in San Francisco, $2000-$3000
Extract:
- Address
- Price
- Bedrooms/Bathrooms
- Square footage
- Photos (URLs)
- Contact information
Navigate through all result pages
""")
```

## Advanced Features

### Mobile Scraping

```python
# Scrape mobile version
plan = await agent.generate_scraping_plan(
    objective="Extract mobile app features",
    url="https://app-store.example.com"
)

# Enable mobile mode
plan.browser_config.mobile = True
plan.browser_config.mobile_device = "iPhone 12"

result = await agent.execute_plan(plan)
```

### Anti-Bot Bypass

```python
# Use undetected browser for sites with Cloudflare
plan.browser_config.browser = "undetected"
plan.browser_config.headless = False  # Often required
```

### Authentication

```python
result = await agent.scrape(
    objective="Extract dashboard data after login",
    url="https://app.example.com",
    context={
        "requires_login": True,
        "login_url": "https://app.example.com/login",
        "credentials": {
            "username": "user@example.com",
            "password": os.getenv("PASSWORD")
        },
        "username_selector": "#email",
        "password_selector": "#password",
        "submit_selector": "button[type='submit']"
    }
)
```

### Pagination Handling

```python
# Agent automatically detects and handles pagination
result = await agent.scrape("""
Extract all products from https://shop.example.com
Handle pagination - click 'Next' until no more pages
Extract: name, price, rating for each product
""")
```

### Error Handling and Retry

```python
plan = await agent.generate_scraping_plan(
    objective="Scrape with retry logic",
    url="https://unstable-site.example.com"
)

# Configure retry behavior
plan.retry_config = {
    "max_retries": 5,
    "retry_delay": 3,
    "retry_on_failure": True
}

result = await agent.execute_plan(plan)
```

## Best Practices

### 1. Be Specific in Objectives

❌ **Bad**: "Get data from the website"

✅ **Good**: "Extract product names, prices, and ratings from all pages of https://shop.example.com/electronics"

### 2. Provide Context

```python
result = await agent.scrape(
    objective="Extract job listings",
    url="https://jobs.example.com",
    context={
        "page_type": "job board",
        "requires_search": True,
        "search_query": "Python Developer",
        "has_filters": True,
        "pagination_type": "infinite scroll"
    }
)
```

### 3. Review Plans Before Execution

```python
# Generate plan first
plan = await agent.generate_scraping_plan(objective, url)

# Review
print(f"Steps: {len(plan.steps)}")
print(f"Selectors: {len(plan.selectors)}")
for step in plan.steps:
    print(f"- {step.action}: {step.description}")

# Modify if needed
plan.browser_config.headless = False

# Then execute
result = await agent.execute_plan(plan)
```

### 4. Use Appropriate Browser Mode

```python
# For JavaScript-heavy sites
config.browser = "chrome"
config.headless = True

# For anti-bot sites
config.browser = "undetected"
config.headless = False

# For simple static sites
config.browser = "chrome"
config.headless = True
```

### 5. Handle Rate Limiting

```python
# Add delays between requests
for step in plan.steps:
    step.wait_after = 2.0  # Wait 2 seconds after each action

# Or in retry config
plan.retry_config["retry_delay"] = 5  # Wait 5 seconds between retries
```

## Troubleshooting

### Issue: Selectors not finding elements

**Solution**: Refine the plan with correct selectors

```python
refined_plan = await agent.refine_plan(
    plan,
    feedback="Selector '.title' not found. The correct selector is '.product-name'"
)
```

### Issue: Page requires JavaScript but not rendering

**Solution**: Ensure browser config allows JavaScript

```python
plan.analysis.requires_javascript = True
plan.browser_config.driver_type = "selenium"  # or "playwright"
```

### Issue: Anti-bot detection

**Solution**: Use undetected browser mode

```python
plan.browser_config.browser = "undetected"
plan.browser_config.headless = False
```

### Issue: Slow page loading

**Solution**: Increase timeouts

```python
for step in plan.steps:
    if step.action == "wait":
        step.timeout = 30  # Increase to 30 seconds
```

## Performance Considerations

### Parallel Scraping

```python
import asyncio

async def scrape_multiple_urls(urls):
    agent = ScrapingAgent()
    await agent.configure()

    tasks = [
        agent.scrape(f"Extract data from {url}")
        for url in urls
    ]

    results = await asyncio.gather(*tasks)
    return results
```

### Resource Management

```python
# Always cleanup
async def scrape_with_cleanup():
    agent = ScrapingAgent()
    try:
        await agent.configure()
        result = await agent.scrape(objective)
        return result
    finally:
        # Cleanup happens automatically via context manager
        pass
```

### Caching Plans

```python
# Store plans for reuse
plan = await agent.generate_scraping_plan(objective, url)

# Save plan
with open('scraping_plan.json', 'w') as f:
    f.write(plan.model_dump_json())

# Load and reuse later
with open('scraping_plan.json', 'r') as f:
    plan_data = json.load(f)
    plan = ScrapingPlanSchema(**plan_data)

result = await agent.execute_plan(plan)
```

## Legal and Ethical Considerations

⚠️ **Important**: Always respect website terms of service and robots.txt

- Check robots.txt before scraping
- Respect rate limits
- Don't overload servers
- Don't scrape copyrighted content without permission
- Include delays between requests
- Use appropriate user agents
- Cache results to minimize requests

## Contributing

We welcome contributions! Areas for improvement:

- Additional browser support (Safari, Edge)
- More sophisticated anti-detection techniques
- Enhanced pagination detection
- Better error recovery strategies
- Performance optimizations

## License

AI-Parrot and ScrapingAgent are open source under the MIT License.

## Support

- Documentation: https://ai-parrot.readthedocs.io
- Issues: https://github.com/your-org/ai-parrot/issues
- Discord: https://discord.gg/ai-parrot

---

Built with ❤️ by the AI-Parrot team
