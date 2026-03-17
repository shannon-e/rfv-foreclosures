"""
Garfield County Foreclosure Scraper
Data source: foreclosures.garfieldcountyco.gov (iframe-embedded JS app)
Uses Playwright to render and extract data.

The iframe app appears to be a custom or vendor-hosted foreclosure database.
This scraper handles both table-based and search-form interfaces.
"""

import time
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = "https://foreclosures.garfieldcountyco.gov/"
PARENT_URL = "https://www.garfieldcountyco.gov/public-trustee/foreclosures/"

SCHEMA = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]


def extract_table_records(page) -> list[dict]:
    """
    Attempt to extract records from a visible HTML table on the page.
    """
    records = []
    try:
        # Wait for either a table or a list of foreclosure items
        page.wait_for_selector("table, .foreclosure-list, .result-row, [class*='foreclos']", timeout=15000)
    except PlaywrightTimeout:
        print("[Garfield] No table/list selector found within timeout.")
        return records

    # Try table rows
    rows = page.query_selector_all("table tbody tr")
    if rows:
        headers = []
        header_cells = page.query_selector_all("table thead th, table thead td")
        headers = [h.inner_text().strip().lower() for h in header_cells]
        print(f"[Garfield] Table headers: {headers}")

        for row in rows:
            cells = row.query_selector_all("td")
            cell_values = [c.inner_text().strip() for c in cells]
            if not cell_values or all(v == "" for v in cell_values):
                continue

            record = map_to_schema(cell_values, headers)
            if record:
                records.append(record)

    # Fallback: try list-style items
    if not records:
        items = page.query_selector_all("[class*='foreclos'], [class*='case'], [class*='result']")
        for item in items:
            text = item.inner_text().strip()
            if text:
                records.append({
                    "county": "Garfield",
                    "list_type": "presale",
                    "case_number": extract_case_number(text),
                    "borrower": "",
                    "property_address": extract_address(text),
                    "sale_date": extract_date(text),
                    "lender": "",
                    "original_amount": "",
                    "status": "",
                    "scraped_at": datetime.utcnow().isoformat(),
                    "source_url": BASE_URL,
                })

    return records


def map_to_schema(cell_values: list[str], headers: list[str]) -> dict | None:
    """Map table row values to standard schema using header names."""
    if not cell_values:
        return None

    def get(keywords):
        for kw in keywords:
            for i, h in enumerate(headers):
                if kw in h and i < len(cell_values):
                    return cell_values[i]
        # Fall back to positional
        return ""

    # If no headers, use positional guessing (common Garfield layout)
    if not headers and len(cell_values) >= 4:
        return {
            "county": "Garfield",
            "list_type": "presale",
            "case_number": cell_values[0],
            "borrower": cell_values[1] if len(cell_values) > 1 else "",
            "property_address": cell_values[2] if len(cell_values) > 2 else "",
            "sale_date": cell_values[3] if len(cell_values) > 3 else "",
            "lender": cell_values[4] if len(cell_values) > 4 else "",
            "original_amount": cell_values[5] if len(cell_values) > 5 else "",
            "status": cell_values[6] if len(cell_values) > 6 else "",
            "scraped_at": datetime.utcnow().isoformat(),
            "source_url": BASE_URL,
        }

    return {
        "county": "Garfield",
        "list_type": "presale",
        "case_number": get(["case", "file", "number", "no"]),
        "borrower": get(["borrower", "owner", "grantor", "name"]),
        "property_address": get(["address", "property", "legal"]),
        "sale_date": get(["sale date", "date", "auction"]),
        "lender": get(["lender", "beneficiary", "bank"]),
        "original_amount": get(["amount", "balance", "bid", "loan"]),
        "status": get(["status"]),
        "scraped_at": datetime.utcnow().isoformat(),
        "source_url": BASE_URL,
    }


def extract_case_number(text: str) -> str:
    import re
    m = re.search(r"\b\d{2,4}[-/]\d{2,6}\b", text)
    return m.group(0) if m else ""


def extract_address(text: str) -> str:
    import re
    m = re.search(r"\d+\s+[A-Za-z][\w\s,\.]+(?:CO|Colorado|Glenwood|Rifle|Carbondale|Basalt)\b[^$]*", text)
    return m.group(0).strip() if m else ""


def extract_date(text: str) -> str:
    import re
    m = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    return m.group(0) if m else ""


def try_intercept_api(page, context) -> list[dict]:
    """
    Set up network interception to capture XHR/fetch responses that
    contain JSON foreclosure data (common in vendor database systems).
    """
    captured = []

    def handle_response(response):
        if response.request.resource_type in ("xhr", "fetch"):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        captured.extend(data)
                    elif isinstance(data, dict):
                        # Look for a list inside the response
                        for v in data.values():
                            if isinstance(v, list) and len(v) > 0:
                                captured.extend(v)
            except Exception:
                pass

    page.on("response", handle_response)
    return captured


def scrape() -> pd.DataFrame:
    print("[Garfield County] Launching browser...")
    records = []

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
        intercepted_json = try_intercept_api(page, context)

        print(f"[Garfield County] Loading {BASE_URL}")
        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("[Garfield] Page load timed out — attempting partial scrape.")

        time.sleep(3)  # allow JS to fully render

        # Check for anti-bot / auth gate
        try:
            page_text = page.inner_text("body", timeout=10000)
        except PlaywrightTimeout:
            page_text = ""
            print("[Garfield] body text timed out — page may be blocked or empty.")
        if any(kw in page_text.lower() for kw in ["captcha", "access denied", "login required"]):
            print("[Garfield] Access gate detected. Manual inspection required.")
            browser.close()
            return pd.DataFrame(columns=SCHEMA)

        # Log page title & URL for debugging
        print(f"[Garfield] Final URL: {page.url}")
        print(f"[Garfield] Page title: {page.title()}")
        print(f"[Garfield] Page text preview: {page_text[:500]}")

        # Save screenshot for debugging
        page.screenshot(path="/home/claude/foreclosure-aggregator/output/garfield_debug.png")

        # Try table extraction
        records = extract_table_records(page)

        # If API was intercepted, map those records too
        if intercepted_json and not records:
            print(f"[Garfield] Intercepted {len(intercepted_json)} JSON records from API.")
            for item in intercepted_json:
                if isinstance(item, dict):
                    record = map_to_schema(list(item.values()), list(item.keys()))
                    if record:
                        records.append(record)

        # If we still have nothing, try clicking "Search" or "View All" button
        if not records:
            for selector in ["button", "input[type='submit']", "a[href*='search']", "a[href*='list']"]:
                btns = page.query_selector_all(selector)
                for btn in btns:
                    text = btn.inner_text().strip().lower()
                    if any(kw in text for kw in ["search", "view all", "list", "show"]):
                        print(f"[Garfield] Clicking '{btn.inner_text().strip()}'")
                        btn.click()
                        time.sleep(3)
                        records = extract_table_records(page)
                        if records:
                            break
                if records:
                    break

        browser.close()

    print(f"[Garfield County] Found {len(records)} records.")
    return pd.DataFrame(records) if records else pd.DataFrame(columns=SCHEMA)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
