USER_AGENTS = [
    # Chrome - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    # Chrome - Desktop (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",  # noqa
    # Safari - Desktop (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",  # noqa
    # Firefox - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    # Edge - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.46",  # noqa
    # Chrome - Mobile (Android)
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36",  # noqa
    # Safari - Mobile (iOS)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",  # noqa
    # Samsung Internet - Mobile (Android)
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/21.0 Chrome/118.0.0.0 Mobile Safari/537.36",  # noqa
    # Firefox - Mobile (Android)
    "Mozilla/5.0 (Android 13; Mobile; rv:118.0) Gecko/118.0 Firefox/118.0",
    # Opera - Desktop (Windows)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0"  # noqa
    # Firefox - Desktop (Linux)
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Chrome - Desktop (Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Other:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa
]  # noqa


DESKTOP_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
]

MOBILE_USER_AGENTS = [
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
]

MOBILE_DEVICES = [
    'iPhone X',
    'iPhone 12 Pro',
    'iPhone 14 Pro Max',
    'Google Nexus 7',
    'Pixel 2',
    'Pixel 5',
    'Samsung Galaxy S21',
    'Samsung Galaxy Tab',
    'iPad Pro'
]

# Browser options configurations
CHROME_OPTIONS = [
    "--disable-gpu",
    "--no-sandbox",
    "--enable-automation",
    "--lang=en",
    "--disable-dev-shm-usage",
    "--disable-features=VizDisplayCompositor",
    "--disable-features=IsolateOrigins",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--window-size=1920,1080"
]

UNDETECTED_OPTIONS = [
    "--disable-gpu",
    "--no-sandbox",
    "--enable-automation",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=NetworkService,NetworkServiceInProcess",
    "--disable-dev-shm-usage",
]

FIREFOX_OPTIONS = [
    "--no-sandbox",
    "--disable-gpu",
    "--width=1920",
    "--height=1080"
]
