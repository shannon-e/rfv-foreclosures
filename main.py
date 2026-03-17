#!/usr/bin/env python3
"""
Roaring Fork Valley Foreclosure Aggregator
Combines Eagle, Garfield, and Pitkin County pre-sale data
into a unified CSV + searchable HTML report.

Usage:
    python main.py                    # All counties
    python main.py --county eagle     # Single county
    python main.py --no-browser       # Skip Playwright scrapers (Eagle only)
"""

import argparse
import importlib.util
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).parent
OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
SCRAPERS_DIR = ROOT_DIR / "scrapers"

SCHEMA_COLS = [
    "county", "list_type", "case_number", "borrower", "property_address",
    "sale_date", "lender", "original_amount", "status", "scraped_at", "source_url",
]


def run_scraper(name: str, script_path: Path) -> pd.DataFrame:
    try:
        spec = importlib.util.spec_from_file_location(name, script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        df = mod.scrape()
        for col in SCHEMA_COLS:
            if col not in df.columns:
                df[col] = ""
        return df[SCHEMA_COLS]
    except Exception:
        print(f"[Main] Scraper '{name}' failed:")
        traceback.print_exc()
        return pd.DataFrame(columns=SCHEMA_COLS)


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    before = len(df)
    df = df.drop_duplicates(subset=["county", "case_number"], keep="last")
    removed = before - len(df)
    if removed:
        print(f"[Main] Removed {removed} duplicate records.")
    return df


def generate_html(df: pd.DataFrame, output_path: Path) -> None:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    county_counts = df.groupby("county").size().to_dict() if not df.empty else {}
    total = len(df)

    if df.empty:
        rows_html = (
            '<tr><td colspan="9" style="text-align:center;padding:2.5rem;color:#888">'
            'No pre-sale records found this week. Check back Monday.'
            "</td></tr>"
        )
    else:
        rows_html = ""
        for _, row in df.iterrows():
            c = (row["county"] or "").lower()
            amt = row["original_amount"] or ""
            if amt and "$" not in str(amt):
                try:
                    amt = f"${float(str(amt).replace(',', '')):,.0f}"
                except Exception:
                    pass
            rows_html += f"""
            <tr class="county-{c}" data-county="{row['county']}" data-listtype="{row['list_type']}">
                <td><span class="badge badge-{c}">{row['county']}</span></td>
                <td>{row['case_number']}</td>
                <td>{row['borrower']}</td>
                <td>{row['property_address']}</td>
                <td>{row['sale_date']}</td>
                <td>{row['lender']}</td>
                <td>{amt}</td>
                <td>{row['status']}</td>
                <td><span class="lt">{row['list_type']}</span></td>
            </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RFV Foreclosures</title>
<style>
*,*::before,*::after{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f3f0;color:#2a2a2a;margin:0;padding:1.5rem}}
h1{{font-size:1.55rem;margin:0 0 .2rem;font-weight:700}}
.meta{{color:#777;font-size:.82rem;margin-bottom:1.4rem}}
.stats{{display:flex;gap:.875rem;flex-wrap:wrap;margin-bottom:1.25rem}}
.stat{{background:#fff;border-radius:8px;padding:.7rem 1.1rem;box-shadow:0 1px 3px rgba(0,0,0,.07);min-width:120px}}
.stat .n{{font-size:1.75rem;font-weight:700}}
.stat .l{{font-size:.72rem;color:#999;text-transform:uppercase;letter-spacing:.05em}}
.sg .n{{color:#c0392b}} .se .n{{color:#2980b9}} .sp .n{{color:#27ae60}}
.controls{{display:flex;gap:.7rem;flex-wrap:wrap;margin-bottom:1rem;align-items:center}}
input[type=search],select{{padding:.45rem .7rem;border:1px solid #ddd;border-radius:6px;font-size:.875rem;background:#fff}}
input[type=search]{{min-width:240px}}
input[type=search]:focus,select:focus{{outline:none;border-color:#888}}
.btn{{padding:.45rem .9rem;background:#2a2a2a;color:#fff;border:none;border-radius:6px;font-size:.82rem;cursor:pointer;margin-left:auto}}
.btn:hover{{background:#444}}
#count{{font-size:.82rem;color:#888}}
.wrap{{overflow-x:auto;background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
table{{border-collapse:collapse;width:100%;font-size:.83rem}}
th{{text-align:left;padding:.7rem .85rem;background:#fafafa;border-bottom:2px solid #eee;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;color:#666;cursor:pointer;white-space:nowrap;user-select:none}}
th:hover{{background:#f0f0f0}}
th.asc::after{{content:" ↑"}} th.desc::after{{content:" ↓"}}
td{{padding:.55rem .85rem;border-bottom:1px solid #f0f0f0;vertical-align:top}}
tr:hover td{{background:#fafbff}}
tr.hidden{{display:none}}
.badge{{display:inline-block;padding:.18em .5em;border-radius:4px;font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em}}
.badge-eagle{{background:#eaf4fb;color:#2980b9}}
.badge-garfield{{background:#fdecea;color:#c0392b}}
.badge-pitkin{{background:#eafaf1;color:#27ae60}}
.lt{{font-size:.7rem;color:#888;background:#f0f0f0;padding:.12em .4em;border-radius:3px}}
.empty{{text-align:center;padding:3rem;color:#888;display:none}}
@media(max-width:600px){{body{{padding:.75rem}}.controls{{flex-direction:column}}.btn{{margin-left:0}}}}
</style>
</head>
<body>
<h1>🏔️ Roaring Fork Valley Pre-Sale Foreclosures</h1>
<div class="meta">Updated: {now} &nbsp;·&nbsp; Eagle, Garfield &amp; Pitkin Counties &nbsp;·&nbsp; Currently scheduled for sale only</div>

<div class="stats">
  <div class="stat"><div class="n">{total}</div><div class="l">Total</div></div>
  <div class="stat se"><div class="n">{county_counts.get('Eagle', 0)}</div><div class="l">Eagle</div></div>
  <div class="stat sg"><div class="n">{county_counts.get('Garfield', 0)}</div><div class="l">Garfield</div></div>
  <div class="stat sp"><div class="n">{county_counts.get('Pitkin', 0)}</div><div class="l">Pitkin</div></div>
</div>

<div class="controls">
  <input type="search" id="q" placeholder="Search borrower, address, case #…" oninput="filter()">
  <select id="cf" onchange="filter()">
    <option value="">All Counties</option>
    <option>Eagle</option><option>Garfield</option><option>Pitkin</option>
  </select>
  <select id="tf" onchange="filter()">
    <option value="">All List Types</option>
    <option value="presale">Pre-Sale</option>
    <option value="continuance">Continuance</option>
  </select>
  <span id="count"></span>
  <button class="btn" onclick="exportCSV()">Export CSV</button>
</div>

<div class="wrap">
  <table id="t">
    <thead><tr>
      <th onclick="sort(0)">County</th>
      <th onclick="sort(1)">Case #</th>
      <th onclick="sort(2)">Borrower</th>
      <th onclick="sort(3)">Address</th>
      <th onclick="sort(4)">Sale Date</th>
      <th onclick="sort(5)">Lender</th>
      <th onclick="sort(6)">Amount</th>
      <th onclick="sort(7)">Status</th>
      <th onclick="sort(8)">Type</th>
    </tr></thead>
    <tbody id="tb">{rows_html}</tbody>
  </table>
  <div class="empty" id="empty">No matching records.</div>
</div>

<script>
function filter(){{
  const q=document.getElementById('q').value.toLowerCase();
  const cf=document.getElementById('cf').value;
  const tf=document.getElementById('tf').value;
  let v=0;
  document.querySelectorAll('#tb tr').forEach(r=>{{
    const show=(!q||r.innerText.toLowerCase().includes(q))&&
               (!cf||r.dataset.county===cf)&&
               (!tf||r.dataset.listtype===tf);
    r.classList.toggle('hidden',!show);
    if(show)v++;
  }});
  document.getElementById('count').textContent=v+' record'+(v!==1?'s':'');
  document.getElementById('empty').style.display=v===0?'block':'none';
}}
let sd={{}};
function sort(c){{
  const tb=document.getElementById('tb');
  const rows=[...tb.querySelectorAll('tr')];
  const dir=sd[c]==='asc'?'desc':'asc'; sd={{}};sd[c]=dir;
  document.querySelectorAll('th').forEach((th,i)=>{{th.classList.remove('asc','desc');if(i===c)th.classList.add(dir);}});
  rows.sort((a,b)=>{{
    const av=a.cells[c]?.innerText.trim()||'';
    const bv=b.cells[c]?.innerText.trim()||'';
    return dir==='asc'?av.localeCompare(bv):bv.localeCompare(av);
  }});
  rows.forEach(r=>tb.appendChild(r));
}}
function exportCSV(){{
  const rows=document.querySelectorAll('#tb tr:not(.hidden)');
  const hdrs=[...document.querySelectorAll('thead th')].map(th=>th.innerText.trim());
  const lines=[hdrs.join(',')];
  rows.forEach(r=>{{
    const cells=[...r.cells].map(td=>'"'+td.innerText.replace(/"/g,'""').trim()+'"');
    lines.push(cells.join(','));
  }});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([lines.join('\\n')],{{type:'text/csv'}}));
  a.download='rfv-foreclosures-{datetime.utcnow().strftime("%Y%m%d")}.csv';
  a.click();
}}
filter();
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"[Main] HTML written: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", choices=["eagle", "garfield", "pitkin", "all"], default="all")
    parser.add_argument("--no-browser", action="store_true", help="Skip Playwright scrapers")
    args = parser.parse_args()

    dfs = []

    if args.county in ("eagle", "all"):
        print("\n=== Eagle County ===")
        dfs.append(run_scraper("eagle_county", SCRAPERS_DIR / "eagle_county.py"))

    if args.county in ("garfield", "all") and not args.no_browser:
        print("\n=== Garfield County ===")
        dfs.append(run_scraper("garfield_county", SCRAPERS_DIR / "garfield_county.py"))

    if args.county in ("pitkin", "all") and not args.no_browser:
        print("\n=== Pitkin County ===")
        dfs.append(run_scraper("pitkin_county", SCRAPERS_DIR / "pitkin_county.py"))

    if not dfs:
        print("[Main] No scrapers ran.")
        sys.exit(1)

    combined = pd.concat(dfs, ignore_index=True)
    combined = deduplicate(combined)

    csv_path = OUTPUT_DIR / "foreclosures.csv"
    combined.to_csv(csv_path, index=False)
    print(f"\n[Main] CSV: {csv_path} ({len(combined)} records)")

    json_path = OUTPUT_DIR / "foreclosures.json"
    combined.to_json(json_path, orient="records", indent=2)
    print(f"[Main] JSON: {json_path}")

    # .nojekyll needed for GitHub Pages to serve files in subdirectories
    (OUTPUT_DIR / ".nojekyll").touch()

    html_path = OUTPUT_DIR / "index.html"
    generate_html(combined, html_path)

    print(f"\n✅ Done. {len(combined)} records across {combined['county'].nunique()} counties.")


if __name__ == "__main__":
    main()
