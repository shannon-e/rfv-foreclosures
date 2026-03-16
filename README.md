# Roaring Fork Valley Foreclosure Aggregator

Synthesizes preforeclosure data from Garfield, Eagle, and Pitkin Counties into a unified, searchable report. Auto-updates weekly via GitHub Actions.

## Output

- `output/index.html` — Searchable HTML report (open locally or host on GitHub Pages)
- `output/foreclosures.csv` — Flat CSV for Excel/Sheets
- `output/foreclosures.json` — JSON for downstream use

## Quick Start

```bash
# 1. Install dependencies
pip install playwright pdfplumber pandas requests beautifulsoup4
playwright install chromium

# 2. Run all three counties
python main.py

# 3. Eagle County only (no browser required)
python main.py --county eagle

# 4. Skip browser-based scrapers (Eagle PDF only)
python main.py --no-browser
```

## Data Sources & Scraper Strategy

| County | Source | Method | Notes |
|--------|--------|--------|-------|
| **Eagle** | Static PDFs (weekly) | `pdfplumber` + `requests` | Most reliable. Two PDFs: Pre-Sale and Continuance. |
| **Garfield** | `foreclosures.garfieldcountyco.gov` (iframe) | Playwright | JS-rendered vendor DB. May need manual inspection if layout changes. |
| **Pitkin** | CivicPlus widget | Playwright + API intercept | Attempts to capture the underlying API call before falling back to DOM. |

## Auto-Update (GitHub Actions)

Push this repo to GitHub. The workflow at `.github/workflows/weekly_sync.yml` runs every Monday at 8 AM MT, commits updated output files, and uploads artifacts.

To enable GitHub Pages hosting of the HTML report:
1. Go to repo Settings → Pages
2. Source: Deploy from branch `main`, folder `/output`
3. Your report will be live at `https://<you>.github.io/<repo>/`

## Debugging Scrapers

Each Playwright scraper saves a screenshot on load:
- `output/garfield_debug.png`
- `output/pitkin_debug.png`

If a scraper returns 0 records, check the screenshot to see what the browser actually rendered (auth gate, CAPTCHA, empty page, etc.).

## Known Limitations

### Garfield County
The iframe at `foreclosures.garfieldcountyco.gov` redirected without rendering content during initial analysis. Possible causes:
- Session/cookie requirement from the parent page
- IP filtering (may need residential proxy)
- Requires a form submission to load data

**Workaround**: Run `garfield_county.py` standalone and inspect the debug screenshot. If blocked, the scraper may need to load the parent page first to establish session cookies, then navigate to the iframe URL.

### Pitkin County
CivicPlus widgets sometimes load from a unique API endpoint per deployment. If the JSON interceptor finds nothing and DOM extraction fails, inspect the browser's Network tab on `pitkincounty.com/325/Foreclosure-Search` while manually clicking "Search" to find the actual API URL, then hardcode it in `pitkin_county.py`.

### Eagle County
Eagle County PDFs have stable URLs but no fixed column layout specification — the parser handles both table-extracted and raw-text layouts. If parsing yields empty or garbled data, print `pdfplumber`'s raw table output for one page:
```python
import pdfplumber
with pdfplumber.open("presale.pdf") as pdf:
    print(pdf.pages[0].extract_tables())
```

## Schema

All records use this unified schema:

| Field | Description |
|-------|-------------|
| `county` | Garfield / Eagle / Pitkin |
| `list_type` | presale / continuance |
| `case_number` | County case/file number |
| `borrower` | Mortgagor name |
| `property_address` | Street address |
| `sale_date` | Scheduled auction date |
| `lender` | Beneficiary/bank |
| `original_amount` | Original loan or bid amount |
| `status` | Sale status (if available) |
| `scraped_at` | ISO timestamp of scrape |
| `source_url` | Source URL for this record |
