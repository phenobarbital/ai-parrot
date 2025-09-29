BESTBUY_TEMPLATE = {
    'search_steps': [
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
        'value': '{search_term}',
        'description': 'Type product'
    },
    {
        'action': 'click',
        'target': 'button[id="autocomplete-search-button"], button[aria-label="Search-Button"]',
        'description': 'Submit search'
    },
    {
        'action': 'wait',
        'target': '.sku-block',
        'timeout': 15,
        'description': 'Wait For Results'
    }
    ],
    'product_selectors': [
    {
        'name':'product_titles',
        'selector': 'h2.product-title',
        'extract_type':'text',
        'multiple':True
    },
    {
        'name':'product_prices',
        'selector': 'div[data-testid="price-block-customer-price"], span',
        'extract_type':'text',
        'multiple':True
    },
    {
        'name':'product_links',
        'selector': '.sku-block-content-title a.product-list-item-link',
        'extract_type':'attribute',
        'attribute':'href',
        'multiple':True
    }
    ],
    'guidance': 'Best Buy uses dynamic loading and specific CSS classes for products. Search results appear in .sku-item-list containers.'
}

AMAZON_TEMPLATE = {
    'search_steps': [
    {'action':'navigate','target':'https://www.amazon.com','description':'Amazon home'},
    {'action':'wait','target':'#twotabsearchtextbox','timeout':15,'description':'Wait for search box'},
    {'action':'fill','target':'#twotabsearchtextbox','value':'{search_term}','description':'Type product'},
    {'action':'click','target':'#nav-search-submit-button','description':'Search'},
    {'action':'wait','target':'[data-component-type="s-search-result"]','timeout':20,'description':'Wait results'}
    ],
    'product_selectors': [
        {
            'name': 'product_titles',
            'selector': '[data-component-type="s-search-result"] h2 a span',
            'extract_type': 'text',
            'multiple': True
        },
        {
            'name': 'product_prices',
            'selector': '.a-price-whole, .a-price .a-offscreen',
            'extract_type': 'text',
            'multiple': True
        }
    ],
    'guidance': 'Amazon uses data-component-type attributes for search results. Prices can be in different formats.'
}

EBAY_TEMPLATE = {
    'search_steps': [
        {
            'action': 'navigate',
            'target': 'https://www.ebay.com',
            'description': 'Navigate to eBay homepage'
        },
        {
            'action': 'fill',
            'target': '#gh-search-input',
            'value': '{search_term}',
            'description': 'Fill search input'
        },
        {
            'action': 'click',
            'target': '#gh-search-btn',
            'description': 'Click search button'
        }
    ],
    'product_selectors': [
        {
            'name': 'product_titles',
            'selector': '.it-title-lnk',
            'extract_type': 'text',
            'multiple': True
        },
        {
            'name': 'product_prices',
            'selector': '.notranslate',
            'extract_type': 'text',
            'multiple': True
        }
    ],
    'guidance': 'eBay search results use .it-title-lnk for titles and .notranslate for prices.'
}
