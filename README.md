# RFV Foreclosure Aggregator

Pre-sale foreclosure data for Eagle, Garfield, and Pitkin Counties. Auto-updates weekly via GitHub Actions → GitHub Pages.

## Output

| File | Description |
|------|-------------|
| `output/index.html` | Searchable dashboard (served via GitHub Pages) |
| `output/foreclosures.csv` | Flat CSV |
| `output/foreclosures.json` | JSON |
| `output/*_debug.png` | Browser screenshots (Playwright scrapers) |

## Repo structure

```
main.py                          # Orchestrator
scrapers/
  eagle_county.py                # requests + pdfplumber
  garfield_county.py             # Playwright → GTS database
  pitkin_county.py               # Playwright → CivicPlus table
output/
  .gitkeep
.github/workflows/weekly_sync.yml
```

## Quick start

```bash
pip install playwright pdfplumber pandas requests beautifulsoup4
playwright install chromium

python main.py                 # All counties
python main.py --county eagle  # Eagle only (no browser required)
python main.py --no-browser    # Eagle only, skip Playwright scrapers
```

## GitHub Pages setup (one-time)

1. Go to repo **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `/output`
4. Save — your dashboard will be live at `https://<you>.github.io/<repo>/`

## Data sources

| County | Source | Method | Notes |
|--------|--------|--------|-------|
| Eagle | Static weekly PDFs | `requests` + `pdfplumber` | Most reliable. URLs are stable. |
| Garfield | GTS database (`foreclosures.garfieldcountyco.gov`) | Playwright | Weekly PDFs only contain FC#, no address data. Full data in GTS. |
| Pitkin | CivicPlus table (`pitkincounty.com/325/Foreclosure-Search`) | Playwright | Server-rendered HTML table. Active cases only. |

## Debugging

If a Playwright scraper returns 0 records:
1. Check **Actions → Run → Artifacts** for `debug-screenshots`
2. `garfield_debug.png` / `pitkin_debug.png` show what the browser actually rendered
3. Common causes: access gate, CAPTCHA, page structure change

### Garfield

`foreclosures.garfieldcountyco.gov` is a GTS public database. If it starts redirecting to a login page, check the debug screenshot. The county may have changed the URL — look for a "Foreclosure Database" link on `garfieldcountyco.gov/public-trustee/`.

### Eagle

PDFs are overwritten weekly. If parsing fails, run:
```python
import pdfplumber, requests, io
r = requests.get("https://www.eaglecounty.us/Departments/Treasurer%20and%20Public%20Trustee/Documents/Public%20Trustee/Pre-sale.pdf",
    headers={"Referer": "https://www.eaglecounty.us/..."})
with pdfplumber.open(io.BytesIO(r.content)) as pdf:
    print(pdf.pages[0].extract_tables())
    print(pdf.pages[0].extract_text())
```

### Pitkin

If the search form changes, inspect the form action/inputs at `pitkincounty.com/325/Foreclosure-Search` and update `pitkin_county.py` accordingly.
