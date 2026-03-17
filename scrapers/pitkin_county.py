"""
Pitkin County Foreclosure Scraper
Data source: pitkincounty.com/325/Foreclosure-Search (CivicPlus)

The page renders a full HTML table — confirmed from live screenshot.
Columns: FC #, Grantor, Street, Zip, Subdivision, Balance Due, Status

We scrape all pages and filter for active / pre-sale records
(excluding completed, withdrawn, and cured cases).
"""

import time
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

SEARCH_URL = "https://www.pitkincounty.com/325/Foreclosure-Search"
OUTPUT_DIR = Path(__file__).parent.parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)

SCHEMA = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]

# Statuses that mean the foreclosure is closed/resolved — exclude these
CLOSED_STATUSES = {
    "sale completed", "withdrawn", "cured", "redeemed", "completed",
    "dismissed", "deed issued", "certificate issued",
}

# Statuses that indicate an upcoming or active sale
ACTIVE_STATUSES = {
    "ned recorded", "pre-sale", "presale", "sale scheduled",
    "notice of sale", "combined notice", "active",
}


def extract_table_page(page) -> tuple[list[dict], bool]:
    """
    Extract records from the current page.
    Returns (records, has_more_pages).
    """
    records = []

    # Wait for a table to appear
    try:
        page.wait_for_selector("table", timeout=15000)
    except PlaywrightTimeout:
        print("[Pitkin] No table found within timeout")
        return records, False

    # Get headers
    headers = []
    for sel in ["table thead th", "table thead td", "table tr:first-child th"]:
        els = page.query_selector_all(sel)
        if els:
            headers = [el.inner_text().strip().lower() for el in els]
            break

    print(f"[Pitkin] Table headers: {headers}")

    # Get data rows
    rows = page.query_selector_all("table tbody tr")
    if not rows:
        rows = page.query_selector_all("table tr")[1:]

    for row in rows:
        cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
        if not cells or all(c == "" for c in cells):
            continue

        def get(keywords, fallback_idx=None):
            for kw in keywords:
                for i, h in enumerate(headers):
                    if kw in h and i < len(cells):
                        return cells[i]
            if fallback_idx is not None and fallback_idx < len(cells):
                return cells[fallback_idx]
            return ""

        if headers:
            status = get(["status"], 7)
            case_num = get(["fc #", "fc#", "case", "foreclosure"], 0)
            # Build address from street + zip
            street = get(["street", "address"], 2)
            zipcode = get(["zip"], 3)
            subdivision = get(["subdivision"], 4)
            address_parts = [p for p in [street, zipcode] if p]
            if subdivision:
                address_parts.append(f"({subdivision})")
            rec = {
                "county": "Pitkin",
                "list_type": "presale",
                "case_number": case_num,
                "borrower": get(["grantor", "borrower", "owner", "name"], 1),
                "property_address": " ".join(address_parts),
                "sale_date": get(["sale date", "sale", "auction", "date"], 5),
                "lender": get(["lender", "beneficiary", "bank"], 6),
                "original_amount": get(["balance", "amount", "bid"], 6),
                "status": status,
                "scraped_at": datetime.utcnow().isoformat(),
                "source_url": SEARCH_URL,
            }
        else:
            # Positional fallback — from confirmed screenshot layout:
            # FC# | Grantor | Street | Zip | Subdivision | Balance Due | Status
            street = cells[2] if len(cells) > 2 else ""
            zipcode = cells[3] if len(cells) > 3 else ""
            subdivision = cells[4] if len(cells) > 4 else ""
            address_parts = [p for p in [street, zipcode] if p]
            if subdivision:
                address_parts.append(f"({subdivision})")
            rec = {
                "county": "Pitkin",
                "list_type": "presale",
                "case_number": cells[0] if len(cells) > 0 else "",
                "borrower": cells[1] if len(cells) > 1 else "",
                "property_address": " ".join(address_parts),
                "sale_date": "",
                "lender": "",
                "original_amount": cells[5] if len(cells) > 5 else "",
                "status": cells[6] if len(cells) > 6 else "",
                "scraped_at": datetime.utcnow().isoformat(),
                "source_url": SEARCH_URL,
            }

        if rec["case_number"]:
            records.append(rec)

    # Check for next page
    has_next = False
    for sel in ["a:has-text('Next')", "input[value='Next']", ".next a", "[aria-label='Next']"]:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            has_next = True
            break

    return records, has_next


def click_next_page(page) -> bool:
    """Click the Next button. Returns True if successful."""
    for sel in ["a:has-text('Next')", "input[value='Next']", ".next a", "[aria-label='Next']"]:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            btn.click()
            time.sleep(2)
            return True
    return False


def scrape() -> pd.DataFrame:
    print("[Pitkin County] Launching browser...")
    all_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print(f"[Pitkin] Navigating to {SEARCH_URL}")
        try:
            page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            print("[Pitkin] Networkidle timeout — continuing")

        time.sleep(3)
        print(f"[Pitkin] Final URL: {page.url}")
        print(f"[Pitkin] Page title: {page.title()}")

        try:
            page.screenshot(path=str(OUTPUT_DIR / "pitkin_debug.png"))
            print("[Pitkin] Screenshot saved to output/pitkin_debug.png")
        except Exception as e:
            print(f"[Pitkin] Screenshot error: {e}")

        # Print body preview for diagnostics
        try:
            body_preview = page.inner_text("body", timeout=5000)[:1500]
            print(f"[Pitkin] Body preview:\n{body_preview}\n---")
        except Exception:
            pass

        # Look for a Search button and click it to trigger results
        for sel in [
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Search')",
            "input[value='Search']",
        ]:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                print(f"[Pitkin] Clicking search: {sel}")
                btn.click()
                time.sleep(3)
                break

        # Paginate through all results
        page_num = 1
        while page_num <= 50:  # safety cap — 729 records / ~75 per page ≈ 10 pages
            print(f"[Pitkin] Extracting page {page_num}...")
            recs, has_next = extract_table_page(page)
            all_records.extend(recs)
            print(f"[Pitkin] Page {page_num}: {len(recs)} records (total: {len(all_records)})")

            if not has_next or not recs:
                break

            if not click_next_page(page):
                break
            page_num += 1

        browser.close()

    if not all_records:
        print("[Pitkin] ⚠️  0 records found. Check output/pitkin_debug.png")
        return pd.DataFrame(columns=SCHEMA)

    df = pd.DataFrame(all_records)

    # Filter to active / pre-sale cases only
    # Keep anything that isn't clearly closed
    def is_active(status: str) -> bool:
        s = (status or "").lower().strip()
        if not s:
            return True  # unknown status — keep it
        if any(closed in s for closed in CLOSED_STATUSES):
            return False
        return True

    active_df = df[df["status"].apply(is_active)].copy()
    print(f"[Pitkin] {len(df)} total → {len(active_df)} active/scheduled records")
    return active_df if not active_df.empty else pd.DataFrame(columns=SCHEMA)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
