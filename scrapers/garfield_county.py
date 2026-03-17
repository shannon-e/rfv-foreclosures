"""
Garfield County Foreclosure Scraper
Data source: foreclosures.garfieldcountyco.gov (GTS public database)

The weekly pre-sale PDFs from garfieldcountyco.gov contain ONLY case numbers —
no borrower names, addresses, or amounts. Full data is in the GTS database.

This scraper navigates the GTS database, searches for active records,
and extracts the full table.
"""

import time
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = "https://foreclosures.garfieldcountyco.gov/"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SCHEMA = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]


def extract_table(page) -> list[dict]:
    """Extract all rows from the visible table on the current page."""
    records = []

    # Gather headers
    headers = []
    for sel in ["table thead th", "table thead td", "table tr:first-child th", "table tr:first-child td"]:
        header_els = page.query_selector_all(sel)
        if header_els:
            headers = [h.inner_text().strip().lower() for h in header_els]
            break

    print(f"[Garfield] Table headers found: {headers}")

    rows = page.query_selector_all("table tbody tr")
    if not rows:
        # Some GTS deployments have no tbody
        rows = page.query_selector_all("table tr")[1:]  # skip header row

    for row in rows:
        cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
        if not cells or all(c == "" for c in cells):
            continue

        # Map by header name if available, else by position
        def get(keywords, fallback_idx=None):
            for kw in keywords:
                for i, h in enumerate(headers):
                    if kw in h and i < len(cells):
                        return cells[i]
            if fallback_idx is not None and fallback_idx < len(cells):
                return cells[fallback_idx]
            return ""

        if headers:
            rec = {
                "county": "Garfield",
                "list_type": "presale",
                "case_number": get(["fc #", "fc#", "case", "file", "number", "foreclosure #"], 0),
                "borrower": get(["grantor", "borrower", "owner", "name"], 1),
                "property_address": get(["street", "address", "property"], 2),
                "sale_date": get(["sale date", "sale", "auction", "date"], 4),
                "lender": get(["lender", "beneficiary", "bank"], 5),
                "original_amount": get(["balance", "amount", "bid"], 6),
                "status": get(["status"], 7),
                "scraped_at": datetime.utcnow().isoformat(),
                "source_url": BASE_URL,
            }
        else:
            # No headers — positional guess for GTS layout:
            # FC# | Grantor | Street | Zip | Subdivision | Sale Date | Balance | Status
            rec = {
                "county": "Garfield",
                "list_type": "presale",
                "case_number": cells[0] if len(cells) > 0 else "",
                "borrower": cells[1] if len(cells) > 1 else "",
                "property_address": " ".join(filter(None, [
                    cells[2] if len(cells) > 2 else "",
                    cells[3] if len(cells) > 3 else "",
                ])),
                "sale_date": cells[5] if len(cells) > 5 else "",
                "lender": "",
                "original_amount": cells[6] if len(cells) > 6 else "",
                "status": cells[7] if len(cells) > 7 else "",
                "scraped_at": datetime.utcnow().isoformat(),
                "source_url": BASE_URL,
            }

        # Only include records that have at least a case number
        if rec["case_number"]:
            records.append(rec)

    return records


def scrape() -> pd.DataFrame:
    print("[Garfield County] Launching browser...")
    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print(f"[Garfield] Navigating to {BASE_URL}")
        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("[Garfield] Networkidle timeout — page may still be usable")

        time.sleep(3)
        print(f"[Garfield] Final URL: {page.url}")
        print(f"[Garfield] Page title: {page.title()}")

        try:
            page.screenshot(path=str(OUTPUT_DIR / "garfield_debug.png"))
            print("[Garfield] Screenshot saved to output/garfield_debug.png")
        except Exception as e:
            print(f"[Garfield] Screenshot error: {e}")

        # Print first 1000 chars of body text for diagnostics
        try:
            body_text = page.inner_text("body", timeout=5000)
            print(f"[Garfield] Page body preview:\n{body_text[:1000]}\n---")
        except Exception:
            pass

        # Check for access gates
        try:
            body_lower = page.inner_text("body", timeout=5000).lower()
            if any(kw in body_lower for kw in ["captcha", "access denied", "login required", "sign in"]):
                print("[Garfield] ⚠️  Access gate detected. Check output/garfield_debug.png")
                browser.close()
                return pd.DataFrame(columns=SCHEMA)
        except Exception:
            pass

        # Try submitting a search if there's a form
        submitted = False
        for selector in [
            "input[type='submit']",
            "button[type='submit']",
            "input[value='Search']",
            "button:has-text('Search')",
        ]:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                print(f"[Garfield] Submitting search via: {selector}")
                btn.click()
                time.sleep(3)
                submitted = True
                break

        if not submitted:
            print("[Garfield] No search form found — attempting to read current page table")

        # Extract table from first page
        records = extract_table(page)
        print(f"[Garfield] Page 1: {len(records)} records")

        # Paginate
        page_num = 1
        while page_num < 30:
            next_btn = None
            for sel in [
                "a:has-text('Next')",
                "input[value='Next']",
                "a[aria-label='Next']",
                ".pager-next a",
                "a.next",
            ]:
                candidate = page.query_selector(sel)
                if candidate and candidate.is_visible():
                    next_btn = candidate
                    break

            if not next_btn:
                break

            print(f"[Garfield] Paginating to page {page_num + 1}...")
            next_btn.click()
            time.sleep(2)
            new_recs = extract_table(page)
            if not new_recs:
                break
            records.extend(new_recs)
            page_num += 1
            print(f"[Garfield] Running total: {len(records)} records")

        browser.close()

    if not records:
        print("[Garfield County] ⚠️  0 records found. Check output/garfield_debug.png for page state.")
    else:
        print(f"[Garfield County] ✓ {len(records)} records")

    return pd.DataFrame(records) if records else pd.DataFrame(columns=SCHEMA)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
