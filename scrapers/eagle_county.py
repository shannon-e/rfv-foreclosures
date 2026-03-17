"""
Eagle County Foreclosure Scraper
Data source: Static PDFs updated weekly by the Public Trustee.
URLs are stable — overwritten each week, not date-stamped.

Pre-Sale list   = properties scheduled for auction this week
Continuance list = sales continued to a later date

No browser needed. requests + pdfplumber only.
"""

import io
import re
import requests
import pdfplumber
import pandas as pd
from datetime import datetime

PRESALE_URL = (
    "https://www.eaglecounty.us/Departments/Treasurer%20and%20Public%20Trustee"
    "/Documents/Public%20Trustee/Pre-sale.pdf"
)
CONTINUANCE_URL = (
    "https://www.eaglecounty.us/Departments/Treasurer%20and%20Public%20Trustee"
    "/Documents/Public%20Trustee/Continuance.pdf"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": (
        "https://www.eaglecounty.us/departments___services/"
        "treasurer___public_trustee_office/public_trustee/auction_sales_list.php"
    ),
    "Accept": "application/pdf,*/*",
}

SCHEMA = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]

# Pattern that identifies a case number row: YY-NNNN or YYYY-NNNNN
CASE_RE = re.compile(r"^\d{2,4}[-/]\d{3,6}$")


def fetch_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        if "pdf" not in r.headers.get("content-type", "").lower() and len(r.content) < 1000:
            print(f"[Eagle] Unexpected response for {url}: {r.headers.get('content-type')}")
            return None
        print(f"[Eagle] Fetched {url} ({len(r.content):,} bytes)")
        return r.content
    except requests.RequestException as e:
        print(f"[Eagle] Failed to fetch {url}: {e}")
        return None


def parse_pdf(pdf_bytes: bytes, list_type: str, source_url: str) -> list[dict]:
    """
    Parse Eagle County pre-sale/continuance PDF.
    Strategy: try structured table extraction first, fall back to raw text.
    Eagle County PDFs typically have columns:
      Case #  |  Borrower  |  Property Address  |  Sale Date  |  Lender  |  Original Amount
    """
    records = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if not row:
                                continue
                            row_clean = [str(c).strip() if c else "" for c in row]
                            # Skip header rows or blank rows
                            if not row_clean[0] or not CASE_RE.match(row_clean[0].split("\n")[0]):
                                continue
                            rec = build_record(row_clean, list_type, source_url)
                            if rec:
                                records.append(rec)
                else:
                    # Fallback: raw text
                    text = page.extract_text() or ""
                    records.extend(parse_raw_text(text, list_type, source_url))
    except Exception as e:
        print(f"[Eagle] PDF parse error: {e}")

    print(f"[Eagle] Parsed {len(records)} records from {list_type} PDF")
    return records


def build_record(row: list[str], list_type: str, source_url: str) -> dict | None:
    """Map table row to schema. Eagle County column order is typically positional."""
    # Multi-line cells get joined
    row = [c.replace("\n", " ").strip() for c in row]

    case_number = row[0] if len(row) > 0 else ""
    if not CASE_RE.match(case_number):
        return None

    return {
        "county": "Eagle",
        "list_type": list_type,
        "case_number": case_number,
        "borrower": row[1] if len(row) > 1 else "",
        "property_address": row[2] if len(row) > 2 else "",
        "sale_date": row[3] if len(row) > 3 else "",
        "lender": row[4] if len(row) > 4 else "",
        "original_amount": row[5] if len(row) > 5 else "",
        "status": "Pre-Sale" if list_type == "presale" else "Continuance",
        "scraped_at": datetime.utcnow().isoformat(),
        "source_url": source_url,
    }


def parse_raw_text(text: str, list_type: str, source_url: str) -> list[dict]:
    """
    Fallback text parser: lines starting with a case number pattern.
    Splits on 2+ spaces to separate columns.
    """
    records = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\s{2,}", line)
        if not parts or not CASE_RE.match(parts[0]):
            continue
        rec = build_record(parts, list_type, source_url)
        if rec:
            records.append(rec)
    return records


def scrape() -> pd.DataFrame:
    all_records = []

    print("[Eagle County] Fetching Pre-Sale PDF...")
    presale_bytes = fetch_pdf(PRESALE_URL)
    if presale_bytes:
        all_records.extend(parse_pdf(presale_bytes, "presale", PRESALE_URL))

    print("[Eagle County] Fetching Continuance PDF...")
    cont_bytes = fetch_pdf(CONTINUANCE_URL)
    if cont_bytes:
        all_records.extend(parse_pdf(cont_bytes, "continuance", CONTINUANCE_URL))

    print(f"[Eagle County] Total: {len(all_records)} records")
    if not all_records:
        return pd.DataFrame(columns=SCHEMA)
    return pd.DataFrame(all_records)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
