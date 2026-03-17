"""
Pitkin County Foreclosure Scraper
Data source: pitkincounty.com/325/Foreclosure-Search (CivicPlus JS widget)

CivicPlus widgets typically load data via an internal API call.
This scraper intercepts that API call; if it fails, falls back to DOM extraction.
"""

import time
import json
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SEARCH_URL = "https://www.pitkincounty.com/325/Foreclosure-Search"

SCHEMA = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]

# Known CivicPlus API patterns — these are common across CivicPlus deployments
CIVICPLUS_API_PATTERNS = [
    "/api/", "/WebAPI/", "/data/", "/search", "/foreclosures",
    "civicplus", "civicengage",
]


def normalize_record(raw: dict) -> dict:
    """
    Normalize a raw dict from any source into the standard schema.
    Key names vary by CivicPlus config — we try common variants.
    """
    def get(*keys):
        for k in keys:
            for rk in raw:
                if k.lower() in rk.lower():
                    val = raw[rk]
                    if val is not None:
                        return str(val).strip()
        return ""

    return {
        "county": "Pitkin",
        "list_type": "presale",
        "case_number": get("case", "file", "number", "id", "no"),
        "borrower": get("borrower", "owner", "grantor", "name", "mortgagor"),
        "property_address": get("address", "property", "location", "legal"),
        "sale_date": get("sale", "date", "auction", "scheduled"),
        "lender": get("lender", "beneficiary", "bank", "mortgagee"),
        "original_amount": get("amount", "balance", "bid", "loan", "principal"),
        "status": get("status", "stage", "type"),
        "scraped_at": datetime.utcnow().isoformat(),
        "source_url": SEARCH_URL,
    }


def extract_from_dom(page) -> list[dict]:
    """Parse the rendered DOM for foreclosure data."""
    records = []

    # Wait for content to load
    try:
        page.wait_for_selector(
            "table, .fr-list, .foreclosure, [class*='result'], [class*='case']",
            timeout=20000,
        )
    except PlaywrightTimeout:
        print("[Pitkin] No recognizable content selector found.")
        return records

    # Try tables
    rows = page.query_selector_all("table tbody tr")
    if rows:
        headers = [
            h.inner_text().strip().lower()
            for h in page.query_selector_all("table thead th, table thead td")
        ]
        print(f"[Pitkin] Table headers: {headers}")
        for row in rows:
            cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            raw = dict(zip(headers, cells)) if headers else {str(i): v for i, v in enumerate(cells)}
            records.append(normalize_record(raw))

    # Try CivicPlus structured divs
    if not records:
        items = page.query_selector_all(
            ".fr-list-item, .listItem, .foreclosureItem, [class*='listRow']"
        )
        for item in items:
            text = item.inner_text().strip()
            if text:
                # Try to parse labeled fields like "Case Number: 24-0001\nBorrower: Smith, John"
                raw = {}
                for line in text.split("\n"):
                    if ":" in line:
                        k, _, v = line.partition(":")
                        raw[k.strip().lower()] = v.strip()
                if raw:
                    records.append(normalize_record(raw))

    return records


def scrape() -> pd.DataFrame:
    print("[Pitkin County] Launching browser...")
    records = []
    intercepted_json: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # Network interceptor — capture API responses
        def handle_response(response):
            url = response.url
            if any(pat in url for pat in CIVICPLUS_API_PATTERNS):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        data = response.json()
                        if isinstance(data, list):
                            intercepted_json.extend(data)
                        elif isinstance(data, dict):
                            for v in data.values():
                                if isinstance(v, list):
                                    intercepted_json.extend(v)
                        print(f"[Pitkin] Intercepted API: {url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"[Pitkin County] Loading {SEARCH_URL}")
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("[Pitkin] Page load timed out — attempting partial scrape.")

        time.sleep(4)

        print(f"[Pitkin] Final URL: {page.url}")
        print(f"[Pitkin] Page title: {page.title()}")
        page.screenshot(path="/home/claude/foreclosure-aggregator/output/pitkin_debug.png")

        # Use intercepted JSON first
        if intercepted_json:
            print(f"[Pitkin] Processing {len(intercepted_json)} intercepted JSON records.")
            for item in intercepted_json:
                if isinstance(item, dict):
                    records.append(normalize_record(item))
        else:
            # Fall back to DOM extraction
            records = extract_from_dom(page)

        # If still nothing — try clicking a "Search All" / "View" button
        if not records:
            for selector in ["button[type='submit']", "input[type='submit']", "a"]:
                for el in page.query_selector_all(selector):
                    el_text = el.inner_text().strip().lower()
                    if any(kw in el_text for kw in ["search", "all", "view", "list", "show"]):
                        print(f"[Pitkin] Clicking '{el.inner_text().strip()}'")
                        el.click()
                        time.sleep(4)
                        records = extract_from_dom(page)
                        if records:
                            break
                if records:
                    break

        # Pagination: if there's a "Next" button, iterate
        page_count = 1
        while page_count < 20:  # safety cap
            next_btn = page.query_selector("a[aria-label='Next'], .next, a:has-text('Next')")
            if not next_btn or not next_btn.is_visible():
                break
            next_btn.click()
            time.sleep(3)
            new_records = extract_from_dom(page)
            if not new_records:
                break
            records.extend(new_records)
            page_count += 1
            print(f"[Pitkin] Paginated to page {page_count}, total records: {len(records)}")

        browser.close()

    print(f"[Pitkin County] Found {len(records)} records.")
    return pd.DataFrame(records) if records else pd.DataFrame(columns=SCHEMA)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
