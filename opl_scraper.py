"""
Export the used-car list from opl.co.il to Excel.

Setup (once):
    python -m pip install playwright pandas openpyxl

Run:
    python opl_scraper.py            # headless
    python opl_scraper.py --show     # watch the browser

Uses the Edge/Chrome already installed on your PC (no browser download).
Output: opl_cars.xlsx
"""
import argparse
import re
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

URL = ("https://www.opl.co.il/%D7%9E%D7%9B%D7%99%D7%A8%D7%AA_%D7%A8%D7%9B%D7%91/"
       "%D7%9E%D7%A6%D7%90_%D7%A8%D7%9B%D7%91?manufacturer=&model="
       "&year%5B0%5D=&year%5B1%5D=&price%5B0%5D=&price%5B1%5D=&gear=")
OUTPUT = "opl_cars.xlsx"

# Each car is an <li role="row"> whose cells are <div role="gridcell" aria-label="COLUMN NAME">
EXTRACT_JS = """
() => {
  const out = [];
  document.querySelectorAll('li[role="row"]').forEach(li => {
    const cells = li.querySelectorAll('[role="gridcell"]');
    if (!cells.length) return;                       // header row / other lists
    const rec = {};
    cells.forEach(c => {
      // label is on the cell itself, or (manufacturer) on the link inside it
      const inner = c.querySelector('[aria-label]');
      const label = c.getAttribute('aria-label') || (inner && inner.getAttribute('aria-label'));
      if (!label || label.includes('פופאפ') || label.includes('תמונה')) return;
      rec[label] = c.innerText.trim().replace(/\\s+/g, ' ');
    });
    if (!rec['דגם']) return;
    const offer = li.querySelector('a[data-licence]');
    rec['מספר רישוי'] = offer ? offer.getAttribute('data-licence') : '';
    rec['יש תמונה'] = li.querySelector('img[aria-label="לרכב יש תמונה"]') ? 'כן' : '';
    out.push(rec);
  });
  return out;
}
"""


def launch(p, show):
    for channel in ("msedge", "chrome"):
        try:
            b = p.chromium.launch(channel=channel, headless=not show)
            print(f"Using {channel}")
            return b
        except Exception as e:
            print(f"Could not start {channel}: {str(e).splitlines()[0]}")
    raise SystemExit("Neither Edge nor Chrome could be started.")


def scrape(show=False):
    with sync_playwright() as p:
        browser = launch(p, show)
        page = browser.new_page(
            locale="he-IL", timezone_id="Asia/Jerusalem",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        print("HTTP status:", resp.status if resp else "none")
        try:
            page.wait_for_selector('li[role="row"] [role="gridcell"]', timeout=60000)
        except Exception:
            print("Page title:", page.title())
            print("Page text start:", page.inner_text("body")[:300].replace("\n", " "))
            raise

        # The heading says how many cars to expect, e.g. "נמצאו 517 רכבים"
        m = re.search(r"נמצאו\s+([\d,]+)\s+רכבים", page.inner_text("body"))
        expected = int(m.group(1).replace(",", "")) if m else None

        # The list fills in gradually / lazily: scroll and wait until every car is
        # loaded (or the count stops growing for ~15 seconds).
        count_js = "() => document.querySelectorAll('li[role=\"row\"] [aria-label=\"דגם\"]').length"
        last, stable = -1, 0
        for _ in range(240):                          # up to ~2 minutes
            n = page.evaluate(count_js)
            if expected and n >= expected:
                break
            stable = stable + 1 if n == last else 0
            if stable >= 30:
                break
            last = n
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(500)
        print(f"Loaded {n} rows")
        page.evaluate("window.scrollTo(0, 0)")

        rows = page.evaluate(EXTRACT_JS)
        browser.close()

    print(f"Found {len(rows)} cars (site says {expected})")
    if expected and len(rows) != expected:
        print("WARNING: count differs from the number shown on the site.")
    return rows


def to_dataframe(rows):
    df = pd.DataFrame(rows)
    order = ["יצרן", "דגם", "שנה", "ק״מ", "הילוכים", "צבע", "מחיר מכירה", "מספר רישוי", "יש תמונה"]
    df = df[[c for c in order if c in df.columns] + [c for c in df.columns if c not in order]]

    # numeric columns so Excel can sort/filter them properly
    for c in ("שנה", "ק״מ", "מחיר מכירה"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(r"[^\d.]", "", regex=True),
                                  errors="coerce")
    return df


def save_excel(df, path=OUTPUT):
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Cars")
        ws = xw.sheets["Cars"]
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"
        ws.sheet_view.rightToLeft = True
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(width + 3, 60)
        for col_name, fmt in (("מחיר מכירה", '"₪"#,##0'), ("ק״מ", "#,##0")):
            if col_name in df.columns:
                idx = list(df.columns).index(col_name) + 1
                for cell in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                    cell[0].number_format = fmt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="show the browser window")
    args = ap.parse_args()

    rows = scrape(args.show)
    if not rows:
        raise SystemExit("No cars found.")
    df = to_dataframe(rows)
    df["נאסף בתאריך"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_excel(df)
    print(f"Saved {len(df)} cars to {OUTPUT}")


if __name__ == "__main__":
    main()
