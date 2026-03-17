#!/usr/bin/env python3
"""
Roaring Fork Valley Foreclosure Aggregator
Combines Garfield, Eagle, and Pitkin County preforeclosure data
into a unified CSV + searchable HTML report.

Usage:
    python main.py                  # Run all scrapers
    python main.py --county eagle   # Single county
    python main.py --no-browser     # Skip Playwright scrapers (Eagle only)
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)

SCHEMA_COLS = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]


def run_scraper(name: str, module_path: str) -> pd.DataFrame:
    """Dynamically import and run a scraper module."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(name, module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        df = mod.scrape()
        # Ensure all schema columns exist
        for col in SCHEMA_COLS:
            if col not in df.columns:
                df[col] = ""
        return df[SCHEMA_COLS]
    except Exception:
        print(f"[Main] Scraper '{name}' failed:")
        traceback.print_exc()
        return pd.DataFrame(columns=SCHEMA_COLS)


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate records across counties by case number."""
    if df.empty:
        return df
    before = len(df)
    df = df.drop_duplicates(subset=["county", "case_number"], keep="last")
    after = len(df)
    if before != after:
        print(f"[Main] Removed {before - after} duplicate records.")
    return df


def generate_html_report(df: pd.DataFrame, output_path: Path) -> None:
    """Generate a searchable, filterable HTML report."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    county_counts = df.groupby("county").size().to_dict() if not df.empty else {}
    total = len(df)

    # Build table rows
    if df.empty:
        rows_html = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#888">No records found. Check scraper debug screenshots in /output/</td></tr>'
    else:
        rows_html = ""
        for _, row in df.iterrows():
            county_class = row["county"].lower() if row["county"] else "unknown"
            amount = row["original_amount"]
            if amount and "$" not in str(amount) and str(amount).replace(",", "").replace(".", "").isdigit():
                try:
                    amount = f"${float(str(amount).replace(',', '')):,.0f}"
                except Exception:
                    pass
            rows_html += f"""
            <tr class="county-{county_class}" data-county="{row['county']}" data-listtype="{row['list_type']}">
                <td><span class="badge badge-{county_class}">{row['county']}</span></td>
                <td>{row['case_number']}</td>
                <td>{row['borrower']}</td>
                <td>{row['property_address']}</td>
                <td>{row['sale_date']}</td>
                <td>{row['lender']}</td>
                <td>{amount}</td>
                <td>{row['status']}</td>
                <td><span class="list-type">{row['list_type']}</span></td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Roaring Fork Valley Foreclosures</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f4f3f0;
    color: #2a2a2a;
    margin: 0;
    padding: 1.5rem;
  }}
  h1 {{ font-size: 1.6rem; margin: 0 0 0.25rem; font-weight: 700; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .stats {{
    display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.25rem;
  }}
  .stat-card {{
    background: white; border-radius: 8px; padding: 0.75rem 1.25rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); min-width: 130px;
  }}
  .stat-card .num {{ font-size: 1.8rem; font-weight: 700; }}
  .stat-card .label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-garfield .num {{ color: #c0392b; }}
  .stat-eagle .num {{ color: #2980b9; }}
  .stat-pitkin .num {{ color: #27ae60; }}
  .controls {{
    display: flex; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 1rem;
    align-items: center;
  }}
  input[type=search] {{
    padding: 0.5rem 0.75rem; border: 1px solid #ddd; border-radius: 6px;
    font-size: 0.9rem; min-width: 260px; outline: none;
  }}
  input[type=search]:focus {{ border-color: #888; }}
  select {{
    padding: 0.5rem 0.75rem; border: 1px solid #ddd; border-radius: 6px;
    font-size: 0.9rem; background: white; cursor: pointer;
  }}
  .btn-export {{
    margin-left: auto; padding: 0.5rem 1rem; background: #2a2a2a; color: white;
    border: none; border-radius: 6px; font-size: 0.85rem; cursor: pointer;
  }}
  .btn-export:hover {{ background: #444; }}
  .table-wrap {{ overflow-x: auto; background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th {{
    text-align: left; padding: 0.75rem 0.875rem;
    background: #fafafa; border-bottom: 2px solid #eee;
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: #666; cursor: pointer; white-space: nowrap; user-select: none;
  }}
  th:hover {{ background: #f0f0f0; }}
  th.sorted-asc::after {{ content: " ↑"; }}
  th.sorted-desc::after {{ content: " ↓"; }}
  td {{ padding: 0.6rem 0.875rem; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
  tr:hover td {{ background: #fafbff; }}
  tr.hidden {{ display: none; }}
  .badge {{
    display: inline-block; padding: 0.2em 0.55em; border-radius: 4px;
    font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
  }}
  .badge-garfield {{ background: #fdecea; color: #c0392b; }}
  .badge-eagle {{ background: #eaf4fb; color: #2980b9; }}
  .badge-pitkin {{ background: #eafaf1; color: #27ae60; }}
  .list-type {{
    font-size: 0.72rem; color: #888; background: #f0f0f0;
    padding: 0.15em 0.45em; border-radius: 3px;
  }}
  .no-results {{
    text-align: center; padding: 3rem; color: #888;
    display: none;
  }}
  #count-label {{ font-size: 0.85rem; color: #888; }}
  @media (max-width: 600px) {{
    body {{ padding: 0.75rem; }}
    .controls {{ flex-direction: column; }}
    .btn-export {{ margin-left: 0; }}
  }}
</style>
</head>
<body>
<h1>🏔️ Roaring Fork Valley Preforeclosures</h1>
<div class="meta">Last updated: {now} &nbsp;·&nbsp; Garfield, Eagle &amp; Pitkin Counties</div>

<div class="stats">
  <div class="stat-card">
    <div class="num">{total}</div>
    <div class="label">Total Records</div>
  </div>
  <div class="stat-card stat-garfield">
    <div class="num">{county_counts.get('Garfield', 0)}</div>
    <div class="label">Garfield</div>
  </div>
  <div class="stat-card stat-eagle">
    <div class="num">{county_counts.get('Eagle', 0)}</div>
    <div class="label">Eagle</div>
  </div>
  <div class="stat-card stat-pitkin">
    <div class="num">{county_counts.get('Pitkin', 0)}</div>
    <div class="label">Pitkin</div>
  </div>
</div>

<div class="controls">
  <input type="search" id="search" placeholder="Search borrower, address, case #…" oninput="filterTable()">
  <select id="county-filter" onchange="filterTable()">
    <option value="">All Counties</option>
    <option value="Garfield">Garfield</option>
    <option value="Eagle">Eagle</option>
    <option value="Pitkin">Pitkin</option>
  </select>
  <select id="type-filter" onchange="filterTable()">
    <option value="">All List Types</option>
    <option value="presale">Pre-Sale</option>
    <option value="continuance">Continuance</option>
  </select>
  <span id="count-label"></span>
  <button class="btn-export" onclick="exportCSV()">Export CSV</button>
</div>

<div class="table-wrap">
  <table id="main-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)">County</th>
        <th onclick="sortTable(1)">Case #</th>
        <th onclick="sortTable(2)">Borrower</th>
        <th onclick="sortTable(3)">Property Address</th>
        <th onclick="sortTable(4)">Sale Date</th>
        <th onclick="sortTable(5)">Lender</th>
        <th onclick="sortTable(6)">Amount</th>
        <th onclick="sortTable(7)">Status</th>
        <th onclick="sortTable(8)">List Type</th>
      </tr>
    </thead>
    <tbody id="table-body">
      {rows_html}
    </tbody>
  </table>
  <div class="no-results" id="no-results">No matching records found.</div>
</div>

<script>
function filterTable() {{
  const search = document.getElementById('search').value.toLowerCase();
  const county = document.getElementById('county-filter').value;
  const listType = document.getElementById('type-filter').value;
  const rows = document.querySelectorAll('#table-body tr');
  let visible = 0;
  rows.forEach(row => {{
    const text = row.innerText.toLowerCase();
    const rowCounty = row.dataset.county || '';
    const rowType = row.dataset.listtype || '';
    const matchSearch = !search || text.includes(search);
    const matchCounty = !county || rowCounty === county;
    const matchType = !listType || rowType === listType;
    const show = matchSearch && matchCounty && matchType;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('count-label').textContent = visible + ' record' + (visible !== 1 ? 's' : '');
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
}}

let sortDir = {{}};
function sortTable(col) {{
  const tbody = document.getElementById('table-body');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const dir = sortDir[col] === 'asc' ? 'desc' : 'asc';
  sortDir = {{[col]: dir}};
  document.querySelectorAll('th').forEach((th, i) => {{
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (i === col) th.classList.add(dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  }});
  rows.sort((a, b) => {{
    const aVal = a.cells[col]?.innerText.trim() || '';
    const bVal = b.cells[col]?.innerText.trim() || '';
    return dir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

function exportCSV() {{
  const rows = document.querySelectorAll('#table-body tr:not(.hidden)');
  const headers = Array.from(document.querySelectorAll('thead th')).map(th => th.innerText.trim());
  const lines = [headers.join(',')];
  rows.forEach(row => {{
    const cells = Array.from(row.cells).map(td => '"' + td.innerText.replace(/"/g, '""').trim() + '"');
    lines.push(cells.join(','));
  }});
  const blob = new Blob([lines.join('\\n')], {{type: 'text/csv'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'rfv-foreclosures-{datetime.utcnow().strftime("%Y%m%d")}.csv';
  a.click();
}}

// Initial count
filterTable();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"[Main] HTML report written: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Roaring Fork Valley Foreclosure Aggregator")
    parser.add_argument("--county", choices=["eagle", "garfield", "pitkin", "all"], default="all")
    parser.add_argument("--no-browser", action="store_true", help="Skip Playwright scrapers")
    args = parser.parse_args()

    scrapers_dir = Path(__file__).parent / "scrapers"
    dfs = []

    run_eagle = args.county in ("eagle", "all")
    run_garfield = args.county in ("garfield", "all") and not args.no_browser
    run_pitkin = args.county in ("pitkin", "all") and not args.no_browser

    if run_eagle:
        print("\n=== Eagle County ===")
        df = run_scraper("eagle_county", scrapers_dir / "eagle_county.py")
        dfs.append(df)

    if run_garfield:
        print("\n=== Garfield County ===")
        df = run_scraper("garfield_county", scrapers_dir / "garfield_county.py")
        dfs.append(df)

    if run_pitkin:
        print("\n=== Pitkin County ===")
        df = run_scraper("pitkin_county", scrapers_dir / "pitkin_county.py")
        dfs.append(df)

    if not dfs:
        print("[Main] No scrapers ran.")
        sys.exit(1)

    combined = pd.concat(dfs, ignore_index=True)
    combined = deduplicate(combined)

    # Write outputs
    csv_path = OUTPUT_DIR / "foreclosures.csv"
    combined.to_csv(csv_path, index=False)
    print(f"\n[Main] CSV written: {csv_path} ({len(combined)} records)")

    json_path = OUTPUT_DIR / "foreclosures.json"
    combined.to_json(json_path, orient="records", indent=2)
    print(f"[Main] JSON written: {json_path}")

    html_path = OUTPUT_DIR / "index.html"
    generate_html_report(combined, html_path)

    print(f"\n✅ Done. {len(combined)} total records across {combined['county'].nunique()} counties.")
    return combined


if __name__ == "__main__":
    main()
