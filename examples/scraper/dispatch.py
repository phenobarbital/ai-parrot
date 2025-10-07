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


class Provider(BaseModel):
    """A service provider from Dispatch.me"""
    zipcode: Optional[str] = None
    name: Optional[str] = None
    engagement_level: Optional[str] = None
    distance: Optional[str] = None
    rating: Optional[float] = Field(default=None)
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    joined: Optional[str] = None
    trades: List[str] = Field(default_factory=list)


# ---------- Helpers ----------
def _norm_text(s: str | None) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s or None

def _direct_child_divs(tag: Tag) -> List[Tag]:
    return [c for c in tag.children if isinstance(c, Tag) and c.name == "div"]

def _first_text(tag: Tag, predicate) -> Optional[str]:
    for t in tag.stripped_strings:
        if predicate(t):
            return t
    return None

def _find_heading(root: Tag, text_re: re.Pattern) -> Optional[Tag]:
    """
    Find a heading DIV whose text matches `text_re`. Returns the container that
    *contains* that heading (so we can look at its sibling rows).
    """
    for div in root.find_all("div"):
        # grab only the direct text (ignore children) to avoid matching rows
        direct_text = "".join(
            s for s in div.contents if isinstance(s, NavigableString)
        ).strip()
        if text_re.search(direct_text or ""):
            return div.parent if div.parent and div.parent.name == "div" else div
    return None

def _row_texts_under(container: Tag) -> List[str]:
    """
    Collect the text from immediate child rows (divs) under a container,
    skipping the first heading-like row. Stops when a new heading appears.
    """
    out = []
    rows = _direct_child_divs(container)
    # if this container nests another div with rows, flatten once
    if len(rows) == 1 and _direct_child_divs(rows[0]):
        rows = _direct_child_divs(rows[0])

    for i, row in enumerate(rows):
        # skip empty/heading-like lines that are short and Title Case
        text = _norm_text(" ".join(row.stripped_strings))
        if not text:
            continue
        if i == 0 and re.match(r"^[A-Z][A-Za-z ]+$", text):  # likely "Contact Information"
            continue
        out.append(text)
    return out


# ---------- Core parser ----------
def parse_provider_div(card: Tag) -> Provider:
    """
    Parse a provider card <div id="..."> relying on structure/positions,
    not on volatile class names.
    """
    # The outer card typically has: [header_div, (button?), company_div]
    direct_divs = _direct_child_divs(card)
    header_div = direct_divs[0] if direct_divs else card

    # --- HEADER: name / engagement / distance / rating ---
    # Name: first non-metric, non-label text chunk in header
    name = _first_text(
        header_div,
        lambda t: (
            len(t) > 2
            and "engaged" not in t.lower()
            and not t.lower().endswith("mi")
            and not re.fullmatch(r"\d+(\.\d+)?", t)  # avoid bare rating numbers
        ),
    )
    name = _norm_text(name)

    # Engagement: any text containing 'Engaged'
    engagement = _first_text(header_div, lambda t: "engaged" in t.lower())
    engagement = _norm_text(engagement)

    # Distance: ends with 'mi'
    distance = _first_text(header_div, lambda t: t.lower().endswith("mi"))
    distance = _norm_text(distance)

    # Rating: prefer a bare number <= 5 near the stars
    rating_val = None
    rating_txt = _first_text(header_div, lambda t: re.fullmatch(r"\d+(\.\d+)?", t or "") is not None)
    if rating_txt:
        try:
            rv = float(rating_txt)
            if 0.0 <= rv <= 5.0:
                rating_val = rv
        except ValueError:
            pass
    if rating_val is None:
        # Fallback: look for a title="X / 5"
        star = header_div.find(attrs={"title": re.compile(r"\d+(\.\d+)?\s*/\s*5")})
        if star and star.has_attr("title"):
            m = re.match(r"(\d+(\.\d+)?)", star["title"])
            if m:
                try:
                    rating_val = float(m.group(1))
                except ValueError:
                    pass

    # --- COMPANY INFO WRAPPER (2nd big block on card) ---
    company_div = None
    # pick the next sibling big div after header (skipping buttons)
    for d in direct_divs[1:]:
        company_div = d
        break
    if company_div is None:
        company_div = card

    # Contact Information
    contact_container = _find_heading(company_div, re.compile(r"\bContact Information\b", re.I))
    address = phone = email = website = None
    if contact_container:
        rows = _row_texts_under(contact_container)
        # By position: address, phone, email, website
        if len(rows) >= 1:
            address = rows[0]
        if len(rows) >= 2:
            phone   = rows[1]
        if len(rows) >= 3:
            email   = rows[2]
        if len(rows) >= 4:
            website = rows[3]
        if website and website.lower() in {"no website yet", "no website"}:
            website = "No website yet"

    # Provider Stats (Joined, Trades)
    stats_container = _find_heading(company_div, re.compile(r"\bProvider Stats\b", re.I))
    joined = None
    trades: List[str] = []
    if stats_container:
        # Joined Dispatch Network: prefer bold text if present
        joined_el = stats_container.find(string=re.compile(r"Joined Dispatch Network:", re.I))
        if joined_el:
            bold = getattr(joined_el.parent, "find", lambda *_: None)("b")
            joined = _norm_text(bold.get_text()) if bold else _norm_text(
                re.sub(r".*Joined Dispatch Network:\s*", "", joined_el.strip(), flags=re.I)
            )

        # Trades list: find the line "Trades" and gather the labels after it
        trades_anchor = stats_container.find(string=re.compile(r"\bTrades\b", re.I))
        if trades_anchor:
            # collect chip/label texts in the next container
            next_block = trades_anchor.parent.find_next("div")
            if next_block:
                labels = [ _norm_text(x.get_text()) for x in next_block.find_all(["span","div"]) ]
                trades = [t for t in labels if t and t.lower() != "trades"]

    return Provider(
        name=name,
        engagement_level=engagement,
        distance=distance,
        rating=rating_val,
        address=_norm_text(address),
        phone=_norm_text(phone),
        email=_norm_text(email),
        website=_norm_text(website),
        joined=_norm_text(joined),
        trades=[t for t in trades if t],
    )

async def test_dispatch(output_path: Path, zipcodes: List[str]):
    print("\n🛍️ Dispatch Test")
    print("=" * 40)

    tool = WebScrapingTool(
        headless=False,
        user_data_dir=str(Path.home() / ".selenium/profiles/myshop"),
        # detach=True,                     # keep window open; humans can click/type
        debugger_address="127.0.0.1:9222",
    )

    # Dispatch Steps:
    # go to login: https://manage.dispatch.me/
    # Authenticate with Username + Click on Username + Password + Click on Login
    # Go to providers list:
    # https://manage.dispatch.me/providers/list
    # Go to Recruiters Page:
    # https://manage.dispatch.me/recruit/out-of-network/list
    # Click on Filters button
    # select 5 stars or 4 stars recruiters:
    # click on radio button value last month:

    # Dispatch Scraping Test:
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
                "values": zipcodes,  # zipcodes
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
        result = await tool._execute(**test_args)
        print('Quantity of results: ', result.get('status'))
        results = []

        if result['status']:

            for r in result['result']:
                card = r.get('bs')
                more_data = r.get('metadata', {}).get('data', {})
                try:
                    provider = parse_provider_div(card)
                    if provider.name:
                        provider.zipcode = more_data.get('zipcode', None)
                        results.append(provider.model_dump())
                except Exception as e:
                    print(f"Error parsing provider div: {str(e)}")
        else:
            print("❌ Test failed")
        if results:
            df = pd.DataFrame(results)
            print("\nExtracted Providers DataFrame:")
            print(df)
            # Save to CSV
            output_file = output_path.joinpath("dispatch_providers.csv")
            df.to_csv(output_file, index=False, sep='|')
            print(f"\nData saved to {output_file.resolve()}")
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
        await test_dispatch(output_path, zipcodes)

    print("\n" + "=" * 50)
    print("🎉 Quick tests completed!")
    print("💡 If tests passed, your WebScrapingTool is working correctly")


if __name__ == "__main__":
    # Run the quick tests
    asyncio.run(main())
