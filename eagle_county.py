"""
Eagle County Foreclosure Scraper
Data source: Static PDFs updated weekly by the Public Trustee office.
URLs are stable; files are overwritten each week.
"""

import requests
import pdfplumber
import pandas as pd
import re
import io
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
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    # Required: some county servers block direct PDF access without a Referer
    "Referer": "https://www.eaglecounty.us/departments___services/treasurer___public_trustee_office/public_trustee/auction_sales_list.php",
    "Accept": "application/pdf,*/*",
}


def fetch_pdf(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        print(f"[Eagle] Failed to fetch {url}: {e}")
        return None


def parse_pdf(pdf_bytes: bytes, list_type: str = "presale") -> list[dict]:
    """
    Parse Eagle County PDF. The PDFs are tabular but vary in layout year to year.
    We extract all text and use regex to capture key fields.
    Returns a list of record dicts.
    """
    records = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if not row or all(c is None or str(c).strip() == "" for c in row):
                                continue
                            # Try to map columns by position; Eagle County typically has:
                            # Case #, Borrower, Property Address, Sale Date, Lender, Original Amount
                            row_clean = [str(c).strip() if c else "" for c in row]
                            if len(row_clean) >= 3:
                                # Skip header rows
                                if any(
                                    kw in row_clean[0].lower()
                                    for kw in ["case", "file", "#", "no."]
                                ):
                                    continue
                                record = extract_fields_from_row(row_clean, list_type)
                                if record:
                                    records.append(record)
                else:
                    # Fallback: raw text parsing
                    text = page.extract_text() or ""
                    records.extend(parse_raw_text(text, list_type))
    except Exception as e:
        print(f"[Eagle] PDF parse error: {e}")
    return records


def extract_fields_from_row(row: list[str], list_type: str) -> dict | None:
    """Map a table row to a standardized record. Eagle County column order varies."""
    if not row[0] or not re.search(r"\d{2}[-/]\d{4}", row[0]):
        return None  # Not a case number pattern

    record = {
        "county": "Eagle",
        "list_type": list_type,
        "case_number": row[0] if len(row) > 0 else "",
        "borrower": row[1] if len(row) > 1 else "",
        "property_address": row[2] if len(row) > 2 else "",
        "sale_date": row[3] if len(row) > 3 else "",
        "lender": row[4] if len(row) > 4 else "",
        "original_amount": row[5] if len(row) > 5 else "",
        "scraped_at": datetime.utcnow().isoformat(),
        "source_url": PRESALE_URL if list_type == "presale" else CONTINUANCE_URL,
    }
    return record


def parse_raw_text(text: str, list_type: str) -> list[dict]:
    """
    Fallback text parser. Looks for lines that start with a case number pattern
    like '24-0012' or '2024-00123'.
    """
    records = []
    lines = text.split("\n")
    case_pattern = re.compile(r"^\d{2,4}[-/]\d{3,6}")

    for line in lines:
        line = line.strip()
        if not case_pattern.match(line):
            continue
        parts = re.split(r"\s{2,}", line)
        record = {
            "county": "Eagle",
            "list_type": list_type,
            "case_number": parts[0] if len(parts) > 0 else "",
            "borrower": parts[1] if len(parts) > 1 else "",
            "property_address": parts[2] if len(parts) > 2 else "",
            "sale_date": parts[3] if len(parts) > 3 else "",
            "lender": parts[4] if len(parts) > 4 else "",
            "original_amount": parts[5] if len(parts) > 5 else "",
            "scraped_at": datetime.utcnow().isoformat(),
            "source_url": PRESALE_URL if list_type == "presale" else CONTINUANCE_URL,
        }
        records.append(record)
    return records


def scrape() -> pd.DataFrame:
    print("[Eagle County] Fetching presale PDF...")
    presale_bytes = fetch_pdf(PRESALE_URL)
    presale_records = parse_pdf(presale_bytes, "presale") if presale_bytes else []

    print("[Eagle County] Fetching continuance PDF...")
    cont_bytes = fetch_pdf(CONTINUANCE_URL)
    cont_records = parse_pdf(cont_bytes, "continuance") if cont_bytes else []

    all_records = presale_records + cont_records
    print(f"[Eagle County] Found {len(all_records)} records.")
    return pd.DataFrame(all_records)


if __name__ == "__main__":
    df = scrape()
    print(df.to_string())
