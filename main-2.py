#!/usr/bin/env python3
"""
Roaring Fork Valley Foreclosure Aggregator
All scraper logic is in this single file — no imports from subdirectories.
"""

import io
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SCHEMA_COLS = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]

EAGLE_PRESALE_URL = (
    "https://www.eaglecounty.us/Departments/Treasurer%20and%20Public%20Trustee"
    "/Documents/Public%20Trustee/Pre-sale.pdf"
)
EAGLE_CONTINUANCE_URL = (
    "https://www.eaglecounty.us/Departments/Treasurer%20and%20Public%20Trustee"
    "/Documents/Public%20Trustee/Continuance.pdf"
)
EAGLE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.eaglecounty.us/departments___services/treasurer___public_trustee_office/public_trustee/auction_sales_list.php",
    "Accept": "application/pdf,*/*",
}


def eagle_fetch_pdf(url):
    try:
        r = requests.get(url, headers=EAGLE_HEADERS, timeout=30)
        r.raise_for_status()
        print(f"[Eagle] Fetched {len(r.content)} bytes from {url}")
        return r.content
    except Exception as e:
        print(f"[Eagle] Failed to fetch {url}: {e}")
        return None


def eagle_parse_pdf(pdf_bytes, list_type, source_url):
    import pdfplumber
    records = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            print(f"[Eagle] PDF has {len(pdf.pages)} pages")
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                print(f"[Eagle] Page {i+1} text preview: {text[:200]}")
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            if not row or all(c is None or str(c).strip() == "" for c in row):
                                continue
                            row_clean = [str(c).strip() if c else "" for c in row]
                            if len(row_clean) >= 3 and re.search(r"\d{2}[-/]\d{3,}", row_clean[0]):
                                records.append({
                                    "county": "Eagle",
                                    "list_type": list_type,
                                    "case_number": row_clean[0],
                                    "borrower": row_clean[1] if len(row_clean) > 1 else "",
                                    "property_address": row_clean[2] if len(row_clean) > 2 else "",
                                    "sale_date": row_clean[3] if len(row_clean) > 3 else "",
                                    "lender": row_clean[4] if len(row_clean) > 4 else "",
                                    "original_amount": row_clean[5] if len(row_clean) > 5 else "",
                                    "status": "",
                                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                                    "source_url": source_url,
                                })
                else:
                    for line in text.split("\n"):
                        line = line.strip()
                        if re.match(r"^\d{2,4}[-/]\d{3,6}", line):
                            parts = re.split(r"\s{2,}", line)
                            records.append({
                                "county": "Eagle",
                                "list_type": list_type,
                                "case_number": parts[0],
                                "borrower": parts[1] if len(parts) > 1 else "",
                                "property_address": parts[2] if len(parts) > 2 else "",
                                "sale_date": parts[3] if len(parts) > 3 else "",
                                "lender": parts[4] if len(parts) > 4 else "",
                                "original_amount": parts[5] if len(parts) > 5 else "",
                                "status": "",
                                "scraped_at": datetime.now(timezone.utc).isoformat(),
                                "source_url": source_url,
                            })
    except Exception as e:
        print(f"[Eagle] PDF parse error: {e}")
        traceback.print_exc()
    return records


def scrape_eagle():
    print("\n=== Eagle County ===")
    records = []
    for url, list_type in [(EAGLE_PRESALE_URL, "presale"), (EAGLE_CONTINUANCE_URL, "continuance")]:
        pdf_bytes = eagle_fetch_pdf(url)
        if pdf_bytes:
            records.extend(eagle_parse_pdf(pdf_bytes, list_type, url))
    print(f"[Eagle] Total records: {len(records)}")
    return records


def scrape_garfield():
    print("\n=== Garfield County ===")
    records = []
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

            intercepted = []
            def on_response(response):
                if response.request.resource_type in ("xhr", "fetch"):
                    try:
                        if "json" in response.headers.get("content-type", ""):
                            data = response.json()
                            if isinstance(data, list):
                                intercepted.extend(data)
                            elif isinstance(data, dict):
                                for v in data.values():
                                    if isinstance(v, list):
                                        intercepted.extend(v)
                    except Exception:
                        pass
            page.on("response", on_response)

            url = "https://foreclosures.garfieldcountyco.gov/"
            print(f"[Garfield] Loading {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except PWTimeout:
                print("[Garfield] Timeout on load, continuing anyway")

            time.sleep(3)
            print(f"[Garfield] Title: {page.title()}")
            print(f"[Garfield] URL: {page.url}")

            try:
                body = page.inner_text("body", timeout=5000)
                print(f"[Garfield] Body preview: {body[:300]}")
            except Exception:
                print("[Garfield] Could not get body text")

            page.screenshot(path=str(OUTPUT_DIR / "garfield_debug.png"))

            if intercepted:
                print(f"[Garfield] Intercepted {len(intercepted)} JSON records")
                for item in intercepted:
                    if isinstance(item, dict):
                        records.append({
                            "county": "Garfield",
                            "list_type": "presale",
                            "case_number": str(item.get("caseNumber", item.get("case_number", item.get("CaseNumber", "")))),
                            "borrower": str(item.get("borrower", item.get("Borrower", item.get("grantor", "")))),
                            "property_address": str(item.get("address", item.get("Address", item.get("propertyAddress", "")))),
                            "sale_date": str(item.get("saleDate", item.get("sale_date", item.get("SaleDate", "")))),
                            "lender": str(item.get("lender", item.get("Lender", item.get("beneficiary", "")))),
                            "original_amount": str(item.get("amount", item.get("Amount", item.get("originalAmount", "")))),
                            "status": str(item.get("status", item.get("Status", ""))),
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "source_url": url,
                        })
            else:
                rows = page.query_selector_all("table tbody tr")
                print(f"[Garfield] Table rows found: {len(rows)}")
                for row in rows:
                    cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                    if cells and len(cells) >= 3:
                        records.append({
                            "county": "Garfield",
                            "list_type": "presale",
                            "case_number": cells[0],
                            "borrower": cells[1] if len(cells) > 1 else "",
                            "property_address": cells[2] if len(cells) > 2 else "",
                            "sale_date": cells[3] if len(cells) > 3 else "",
                            "lender": cells[4] if len(cells) > 4 else "",
                            "original_amount": cells[5] if len(cells) > 5 else "",
                            "status": cells[6] if len(cells) > 6 else "",
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "source_url": url,
                        })
            browser.close()
    except Exception as e:
        print(f"[Garfield] Error: {e}")
        traceback.print_exc()

    print(f"[Garfield] Total records: {len(records)}")
    return records


def scrape_pitkin():
    print("\n=== Pitkin County ===")
    records = []
    url = "https://www.pitkincounty.com/325/Foreclosure-Search"
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")

            intercepted = []
            def on_response(response):
                if response.request.resource_type in ("xhr", "fetch"):
                    try:
                        if "json" in response.headers.get("content-type", ""):
                            data = response.json()
                            if isinstance(data, list):
                                intercepted.extend(data)
                            elif isinstance(data, dict):
                                for v in data.values():
                                    if isinstance(v, list):
                                        intercepted.extend(v)
                    except Exception:
                        pass
            page.on("response", on_response)

            print(f"[Pitkin] Loading {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except PWTimeout:
                print("[Pitkin] Timeout on load, continuing anyway")

            time.sleep(4)
            print(f"[Pitkin] Title: {page.title()}")
            page.screenshot(path=str(OUTPUT_DIR / "pitkin_debug.png"))

            try:
                body = page.inner_text("body", timeout=5000)
                print(f"[Pitkin] Body preview: {body[:300]}")
            except Exception:
                print("[Pitkin] Could not get body text")

            if intercepted:
                print(f"[Pitkin] Intercepted {len(intercepted)} JSON records")
                for item in intercepted:
                    if isinstance(item, dict):
                        records.append({
                            "county": "Pitkin",
                            "list_type": "presale",
                            "case_number": str(item.get("caseNumber", item.get("case_number", item.get("CaseNumber", "")))),
                            "borrower": str(item.get("borrower", item.get("Borrower", item.get("grantor", "")))),
                            "property_address": str(item.get("address", item.get("Address", item.get("propertyAddress", "")))),
                            "sale_date": str(item.get("saleDate", item.get("sale_date", item.get("SaleDate", "")))),
                            "lender": str(item.get("lender", item.get("Lender", item.get("beneficiary", "")))),
                            "original_amount": str(item.get("amount", item.get("Amount", item.get("originalAmount", "")))),
                            "status": str(item.get("status", item.get("Status", ""))),
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "source_url": url,
                        })
            else:
                rows = page.query_selector_all("table tbody tr")
                print(f"[Pitkin] Table rows found: {len(rows)}")
                for row in rows:
                    cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
                    if cells and len(cells) >= 3:
                        records.append({
                            "county": "Pitkin",
                            "list_type": "presale",
                            "case_number": cells[0],
                            "borrower": cells[1] if len(cells) > 1 else "",
                            "property_address": cells[2] if len(cells) > 2 else "",
                            "sale_date": cells[3] if len(cells) > 3 else "",
                            "lender": cells[4] if len(cells) > 4 else "",
                            "original_amount": cells[5] if len(cells) > 5 else "",
                            "status": cells[6] if len(cells) > 6 else "",
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "source_url": url,
                        })
            browser.close()
    except Exception as e:
        print(f"[Pitkin] Error: {e}")
        traceback.print_exc()

    print(f"[Pitkin] Total records: {len(records)}")
    return records


def generate_html(df, output_path):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    county_counts = df.groupby("county").size().to_dict() if not df.empty else {}
    total = len(df)

    rows_html = ""
    if df.empty:
        rows_html = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#888">No records found.</td></tr>'
    else:
        for _, row in df.iterrows():
            cc = row["county"].lower() if row["county"] else "unknown"
            rows_html += f'<tr data-county="{row["county"]}" data-listtype="{row["list_type"]}"><td><span class="badge badge-{cc}">{row["county"]}</span></td><td>{row["case_number"]}</td><td>{row["borrower"]}</td><td>{row["property_address"]}</td><td>{row["sale_date"]}</td><td>{row["lender"]}</td><td>{row["original_amount"]}</td><td>{row["status"]}</td><td>{row["list_type"]}</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Roaring Fork Valley Foreclosures</title>
<style>
*,*::before,*::after{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f4f3f0;color:#2a2a2a;margin:0;padding:1.5rem}}
h1{{font-size:1.6rem;margin:0 0 .25rem;font-weight:700}}
.meta{{color:#666;font-size:.85rem;margin-bottom:1.5rem}}
.stats{{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.25rem}}
.stat-card{{background:white;border-radius:8px;padding:.75rem 1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.08);min-width:130px}}
.stat-card .num{{font-size:1.8rem;font-weight:700}}
.stat-card .label{{font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.05em}}
.stat-garfield .num{{color:#c0392b}}.stat-eagle .num{{color:#2980b9}}.stat-pitkin .num{{color:#27ae60}}
.controls{{display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1rem;align-items:center}}
input[type=search]{{padding:.5rem .75rem;border:1px solid #ddd;border-radius:6px;font-size:.9rem;min-width:260px}}
select{{padding:.5rem .75rem;border:1px solid #ddd;border-radius:6px;font-size:.9rem;background:white}}
.btn{{margin-left:auto;padding:.5rem 1rem;background:#2a2a2a;color:white;border:none;border-radius:6px;font-size:.85rem;cursor:pointer}}
.table-wrap{{overflow-x:auto;background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}
th{{text-align:left;padding:.75rem .875rem;background:#fafafa;border-bottom:2px solid #eee;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#666;white-space:nowrap}}
td{{padding:.6rem .875rem;border-bottom:1px solid #f0f0f0;vertical-align:top}}
tr:hover td{{background:#fafbff}}
tr.hidden{{display:none}}
.badge{{display:inline-block;padding:.2em .55em;border-radius:4px;font-size:.72rem;font-weight:600;text-transform:uppercase}}
.badge-garfield{{background:#fdecea;color:#c0392b}}.badge-eagle{{background:#eaf4fb;color:#2980b9}}.badge-pitkin{{background:#eafaf1;color:#27ae60}}
</style>
</head>
<body>
<h1>🏔️ Roaring Fork Valley Preforeclosures</h1>
<div class="meta">Last updated: {now} · Garfield, Eagle & Pitkin Counties</div>
<div class="stats">
<div class="stat-card"><div class="num">{total}</div><div class="label">Total</div></div>
<div class="stat-card stat-garfield"><div class="num">{county_counts.get('Garfield',0)}</div><div class="label">Garfield</div></div>
<div class="stat-card stat-eagle"><div class="num">{county_counts.get('Eagle',0)}</div><div class="label">Eagle</div></div>
<div class="stat-card stat-pitkin"><div class="num">{county_counts.get('Pitkin',0)}</div><div class="label">Pitkin</div></div>
</div>
<div class="controls">
<input type="search" id="s" placeholder="Search borrower, address, case #…" oninput="f()">
<select id="c" onchange="f()"><option value="">All Counties</option><option>Garfield</option><option>Eagle</option><option>Pitkin</option></select>
<select id="t" onchange="f()"><option value="">All Types</option><option value="presale">Pre-Sale</option><option value="continuance">Continuance</option></select>
<span id="n"></span>
<button class="btn" onclick="ex()">Export CSV</button>
</div>
<div class="table-wrap"><table>
<thead><tr><th>County</th><th>Case #</th><th>Borrower</th><th>Property Address</th><th>Sale Date</th><th>Lender</th><th>Amount</th><th>Status</th><th>Type</th></tr></thead>
<tbody id="tb">{rows_html}</tbody>
</table></div>
<script>
function f(){{const s=document.getElementById('s').value.toLowerCase(),c=document.getElementById('c').value,t=document.getElementById('t').value,rows=document.querySelectorAll('#tb tr');let v=0;rows.forEach(r=>{{const show=(!s||r.innerText.toLowerCase().includes(s))&&(!c||r.dataset.county===c)&&(!t||r.dataset.listtype===t);r.classList.toggle('hidden',!show);if(show)v++}});document.getElementById('n').textContent=v+' record'+(v!==1?'s':'')}}
function ex(){{const rows=document.querySelectorAll('#tb tr:not(.hidden)'),h=['County','Case #','Borrower','Address','Sale Date','Lender','Amount','Status','Type'],lines=[h.join(',')];rows.forEach(r=>{{lines.push(Array.from(r.cells).map(td=>'"'+td.innerText.replace(/"/g,'""').trim()+'"').join(','))}});const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\\n')],{{type:'text/csv'}}));a.download='rfv-foreclosures.csv';a.click()}}
f();
</script>
</body></html>"""
    output_path.write_text(html, encoding="utf-8")
    print(f"[Main] HTML written: {output_path}")


if __name__ == "__main__":
    print(f"[Main] Working directory: {Path(__file__).parent}")
    print(f"[Main] Output directory: {OUTPUT_DIR}")

    all_records = []
    all_records.extend(scrape_eagle())
    all_records.extend(scrape_garfield())
    all_records.extend(scrape_pitkin())

    df = pd.DataFrame(all_records)
    for col in SCHEMA_COLS:
        if col not in df.columns:
            df[col] = ""
    if not df.empty:
        df = df[SCHEMA_COLS]

    df.to_csv(OUTPUT_DIR / "foreclosures.csv", index=False)
    df.to_json(OUTPUT_DIR / "foreclosures.json", orient="records", indent=2)
    generate_html(df, OUTPUT_DIR / "index.html")

    print(f"\n✅ Done. {len(df)} total records.")
