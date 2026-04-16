"""
scrape.py — Standalone data pipeline for GitHub Actions.

This script is deliberately self-contained — it does NOT import from
the other politrade modules (utils.py, database.py, etc.) so it can
run cleanly in GitHub Actions without the full project setup.

What it does:
  1. Fetches congressional trades from Capitol Trades (HTML scrape)
  2. Fetches Senate trades from the GitHub data repo (JSON)
  3. Loads the existing data/trades.csv (deduplication)
  4. Appends only genuinely new rows
  5. Saves updated trades.csv and a last_run.json status file

Output files (committed back to repo by GitHub Actions):
  data/trades.csv        — Full trade history (append-only)
  data/last_run.json     — Metadata about the last successful run
  data/run_log.txt       — Human-readable log of each run
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Logging setup ─────────────────────────────────────────────────────────
# In CI (GitHub Actions), use plain text. Locally, same.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scrape")

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR       = Path("data")
TRADES_CSV     = DATA_DIR / "trades.csv"
LAST_RUN_JSON  = DATA_DIR / "last_run.json"
RUN_LOG        = DATA_DIR / "run_log.txt"

DATA_DIR.mkdir(exist_ok=True)

# ── CSV Schema ─────────────────────────────────────────────────────────────
# These are the columns in trades.csv — order matters for csv.DictWriter
CSV_COLUMNS = [
    "disclosure_id",     # SHA-256 hash for deduplication
    "scraped_at",        # When WE fetched it (UTC ISO)
    "politician",        # Full name
    "chamber",           # 'house' or 'senate'
    "ticker",            # Stock symbol e.g. 'NVDA'
    "issuer",            # Company name
    "transaction_type",  # 'purchase' or 'sale'
    "transaction_date",  # When the trade was executed
    "disclosure_date",   # When it was filed/published
    "amount_range",      # Raw range string e.g. '$1,001 - $15,000'
    "amount_lower",      # Parsed lower bound (numeric)
    "amount_upper",      # Parsed upper bound (numeric)
    "amount_mid",        # Midpoint estimate (numeric)
    "source",            # Which source provided this record
]

# ── HTTP helper ───────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def http_get(url, params=None, retries=3, backoff=2.0):
    """GET with retry. Returns Response or None."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            log.warning(f"HTTP {status} attempt {attempt}/{retries}: {url}")
            if status == 429:
                time.sleep(backoff * attempt * 4)
            elif status >= 500:
                time.sleep(backoff * attempt)
            else:
                return None
        except Exception as e:
            log.warning(f"Request error attempt {attempt}/{retries}: {e}")
            time.sleep(backoff * attempt)
    log.error(f"All {retries} attempts failed: {url}")
    return None


# ── Amount range parser ────────────────────────────────────────────────────
KNOWN_RANGES = {
    "1k-15k":    (1001,    15000),
    "15k-50k":   (15001,   50000),
    "50k-100k":  (50001,   100000),
    "100k-250k": (100001,  250000),
    "250k-500k": (250001,  500000),
    "500k-1m":   (500001,  1000000),
    "1m-5m":     (1000001, 5000000),
    "5m+":       (5000001, 10000000),
    # Standard disclosure strings
    "$1,001 - $15,000":      (1001,   15000),
    "$15,001 - $50,000":     (15001,  50000),
    "$50,001 - $100,000":    (50001,  100000),
    "$100,001 - $250,000":   (100001, 250000),
    "$250,001 - $500,000":   (250001, 500000),
    "$500,001 - $1,000,000": (500001, 1000000),
    "over $1,000,000":       (1000001, 5000000),
    "purchase":              (1001,   15000),    # When only "Purchase" is listed
}


def parse_amount(raw: str):
    """Return (lower, upper, mid) tuple from a raw amount string."""
    if not raw:
        return (0, 0, 0)

    normalized = raw.lower().strip().replace("–", "-").replace("—", "-")

    for key, (lo, hi) in KNOWN_RANGES.items():
        if key in normalized:
            return (lo, hi, (lo + hi) / 2)

    # Fallback: extract numbers
    nums = re.findall(r"[\d,]+", raw.replace(",", ""))
    try:
        vals = [float(n) for n in nums if float(n) > 0]
        if len(vals) >= 2:
            return (vals[0], vals[1], (vals[0] + vals[1]) / 2)
        if len(vals) == 1:
            return (vals[0], vals[0], vals[0])
    except Exception:
        pass

    return (0, 0, 0)


def disclosure_id(politician, ticker, tx_type, tx_date, amount):
    """Deterministic SHA-256 ID for deduplication."""
    key = f"{politician}|{ticker}|{tx_type}|{tx_date}|{amount}"
    return hashlib.sha256(key.encode()).hexdigest()[:20]


# ── Date parsers ───────────────────────────────────────────────────────────
def parse_relative_date(text: str) -> str:
    """Convert Capitol Trades relative dates to YYYY-MM-DD strings."""
    t = text.lower().strip()
    now = datetime.utcnow()

    if "yesterday" in t:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if "today" in t or re.match(r"^\d+:\d+", t):
        return now.strftime("%Y-%m-%d")

    m = re.search(r"(\d+)\s*days?\s*ago", t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    m = re.search(r"(\d+)\s*hours?\s*ago", t)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d")

    for fmt in ("%d %b %Y", "%b %d %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(t.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return now.strftime("%Y-%m-%d")


def parse_abs_date(text: str) -> str:
    """Parse absolute date strings to YYYY-MM-DD."""
    for fmt in ("%d %b %Y", "%b %d %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text.strip()


# ── Source 1: Capitol Trades HTML ─────────────────────────────────────────
def scrape_capitol_trades(days_back: int = 30) -> list[dict]:
    """
    Scrape capitoltrades.com/trades HTML table.
    Verified working April 2026. Returns full trade list, all politicians.
    """
    log.info("Scraping Capitol Trades...")
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    records = []
    page = 1

    while page <= 15:  # Max 15 pages (1440 trades) per run
        log.info(f"  Page {page}...")
        r = http_get(
            "https://www.capitoltrades.com/trades",
            params={"page": page, "pageSize": 96},
        )
        if not r:
            log.error("Capitol Trades unreachable.")
            break

        soup  = BeautifulSoup(r.text, "lxml")
        table = soup.find("table")
        if not table:
            log.warning("No <table> found on Capitol Trades page.")
            break

        tbody = table.find("tbody")
        rows  = tbody.find_all("tr") if tbody else []
        if not rows:
            break

        found_old = False

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            try:
                # Cell 0: politician + chamber
                cell0     = cells[0].get_text(" ", strip=True)
                name_tag  = cells[0].find("a")
                name      = name_tag.get_text(strip=True) if name_tag else cell0.split()[0]
                chamber   = "senate" if "Senate" in cell0 else "house"

                # Cell 1: issuer (company + ticker like "NVDA:US")
                issuer_text = cells[1].get_text(" ", strip=True)
                tm = re.search(r'\b([A-Z]{1,5})(?::US)?\b', issuer_text)
                ticker = tm.group(1) if tm else ""
                if not ticker or ticker in ("US", "NA", "N"):
                    continue

                # Cell 2: published date (when Capitol Trades posted it)
                pub_date = parse_relative_date(cells[2].get_text(" ", strip=True))

                # Cell 3: trade date
                trade_date = parse_abs_date(cells[3].get_text(" ", strip=True))

                # Skip if older than our window
                try:
                    pub_dt = datetime.strptime(pub_date, "%Y-%m-%d")
                    if pub_dt < cutoff:
                        found_old = True
                        continue
                except ValueError:
                    pass

                # Cell 6: transaction type
                tx_raw = cells[6].get_text(strip=True).lower()
                if "buy" in tx_raw or "purchase" in tx_raw:
                    tx_type = "purchase"
                elif "sell" in tx_raw or "sale" in tx_raw:
                    tx_type = "sale"
                else:
                    tx_type = tx_raw

                # Cell 7: size / amount
                amount_raw = cells[7].get_text(strip=True)
                lo, hi, mid = parse_amount(amount_raw)

                did = disclosure_id(name, ticker, tx_type, trade_date, amount_raw)

                records.append({
                    "disclosure_id":    did,
                    "scraped_at":       datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "politician":       name,
                    "chamber":          chamber,
                    "ticker":           ticker,
                    "issuer":           issuer_text[:120],
                    "transaction_type": tx_type,
                    "transaction_date": trade_date,
                    "disclosure_date":  pub_date,
                    "amount_range":     amount_raw,
                    "amount_lower":     lo,
                    "amount_upper":     hi,
                    "amount_mid":       mid,
                    "source":           "capitol_trades",
                })

            except Exception as e:
                log.debug(f"Row parse error: {e}")
                continue

        if found_old and len(rows) < 50:
            break

        page += 1
        time.sleep(1.5)  # Polite crawl delay

    log.info(f"Capitol Trades: {len(records)} records fetched.")
    return records


# ── Source 2: Senate GitHub repo ──────────────────────────────────────────
def scrape_senate_github(days_back: int = 30) -> list[dict]:
    """
    Fetch Senate trade data from timothycarambat/senate-stock-watcher-data.
    Raw JSON on GitHub CDN — no auth, no cost.
    """
    log.info("Fetching Senate data from GitHub repo...")
    cutoff  = datetime.utcnow() - timedelta(days=days_back)
    base    = "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/data"
    records = []

    now = datetime.utcnow()
    months = []
    for delta in range(0, max(2, days_back // 28 + 1)):
        m = now.month - delta
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))

    for year, month in months:
        url = f"{base}/{year}/{month:02d}/{year}-{month:02d}.json"
        r   = http_get(url)
        if not r:
            log.debug(f"No GitHub data for {year}-{month:02d}")
            continue

        try:
            monthly = r.json()
        except Exception as e:
            log.warning(f"JSON parse error {year}-{month:02d}: {e}")
            continue

        for filing in monthly:
            try:
                first = filing.get("first_name", "").strip()
                last  = filing.get("last_name",  "").strip()
                name  = f"{first} {last}".strip() or "Unknown"
                filed = filing.get("date_recieved", "")

                for tx in filing.get("transactions", []):
                    ticker = tx.get("ticker", "").strip().upper()
                    if not ticker or ticker == "--":
                        continue
                    if not re.match(r'^[A-Z]{1,5}$', ticker):
                        continue

                    tx_date    = tx.get("transaction_date", filed)
                    tx_raw     = tx.get("type", "").lower()
                    amount_raw = tx.get("amount", "Unknown")

                    # Date filter
                    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                        try:
                            tx_dt = datetime.strptime(tx_date, fmt)
                            if tx_dt < cutoff:
                                tx_date = None
                            break
                        except ValueError:
                            continue

                    if tx_date is None:
                        continue

                    tx_type = (
                        "purchase" if "purchase" in tx_raw or "buy" in tx_raw
                        else "sale" if "sale" in tx_raw or "sell" in tx_raw
                        else tx_raw
                    )

                    lo, hi, mid = parse_amount(amount_raw)
                    did = disclosure_id(name, ticker, tx_type, tx_date, amount_raw)

                    records.append({
                        "disclosure_id":    did,
                        "scraped_at":       datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "politician":       name,
                        "chamber":          "senate",
                        "ticker":           ticker,
                        "issuer":           tx.get("asset_description", "")[:120],
                        "transaction_type": tx_type,
                        "transaction_date": tx_date,
                        "disclosure_date":  filed,
                        "amount_range":     amount_raw,
                        "amount_lower":     lo,
                        "amount_upper":     hi,
                        "amount_mid":       mid,
                        "source":           "senate_github",
                    })

            except Exception as e:
                log.debug(f"Senate filing parse error: {e}")
                continue

        time.sleep(0.5)

    log.info(f"Senate GitHub: {len(records)} records fetched.")
    return records


# ── Deduplication & CSV I/O ───────────────────────────────────────────────
def load_existing_ids() -> set:
    """Load set of disclosure_ids already in trades.csv."""
    if not TRADES_CSV.exists():
        return set()
    existing = set()
    with open(TRADES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            did = row.get("disclosure_id", "").strip()
            if did:
                existing.add(did)
    log.info(f"Loaded {len(existing)} existing trade IDs for deduplication.")
    return existing


def append_new_trades(new_records: list[dict]) -> tuple[int, int]:
    """
    Append only genuinely new records to trades.csv.
    Returns (new_count, total_count).
    """
    existing_ids = load_existing_ids()

    # Filter to new only
    fresh = [r for r in new_records if r["disclosure_id"] not in existing_ids]
    log.info(f"New records after dedup: {len(fresh)} of {len(new_records)}")

    if not fresh:
        total = len(existing_ids)
        return 0, total

    # Write header if file doesn't exist
    write_header = not TRADES_CSV.exists()

    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(fresh)

    total = len(existing_ids) + len(fresh)
    log.info(f"Appended {len(fresh)} new records. Total: {total}")
    return len(fresh), total


def save_run_metadata(new_count: int, total: int, sources_status: dict):
    """Save last_run.json so the dashboard can show run health."""
    meta = {
        "last_run_utc":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "new_records":   new_count,
        "total_records": total,
        "sources":       sources_status,
        "next_run_est":  "~4 hours (GitHub Actions cron)",
    }
    with open(LAST_RUN_JSON, "w") as f:
        json.dump(meta, f, indent=2)

    # Append to human-readable log
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(
            f"{meta['last_run_utc']} | +{new_count} new | "
            f"{total} total | "
            f"sources: {json.dumps(sources_status)}\n"
        )


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="PoliTrade scraper")
    parser.add_argument(
        "--days", type=int,
        default=int(os.environ.get("DAYS_BACK", 30)),
        help="Days of history to fetch (default: 30)"
    )
    args = parser.parse_args()

    log.info(f"=== PoliTrade Scrape Run — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} ===")
    log.info(f"Fetching last {args.days} days of disclosures.")

    all_records    = []
    sources_status = {}

    # ── Source 1: Capitol Trades ────────────────────────────
    try:
        ct_records = scrape_capitol_trades(days_back=args.days)
        all_records.extend(ct_records)
        sources_status["capitol_trades"] = {
            "status": "ok",
            "records": len(ct_records)
        }
    except Exception as e:
        log.error(f"Capitol Trades scrape failed: {e}")
        sources_status["capitol_trades"] = {"status": "error", "error": str(e)}

    # ── Source 2: Senate GitHub ─────────────────────────────
    try:
        sg_records = scrape_senate_github(days_back=args.days)
        all_records.extend(sg_records)
        sources_status["senate_github"] = {
            "status": "ok",
            "records": len(sg_records)
        }
    except Exception as e:
        log.error(f"Senate GitHub scrape failed: {e}")
        sources_status["senate_github"] = {"status": "error", "error": str(e)}

    if not all_records:
        log.warning("No records fetched from any source. Check source availability.")
        save_run_metadata(0, 0, sources_status)
        # Exit with 0 so GitHub Actions doesn't mark as failed
        # (no data is not a script error — sources may just have no new filings)
        sys.exit(0)

    # ── Cross-source dedup (same trade from both sources) ───
    seen = set()
    deduped = []
    for r in all_records:
        if r["disclosure_id"] not in seen:
            seen.add(r["disclosure_id"])
            deduped.append(r)

    log.info(f"After cross-source dedup: {len(deduped)} records")

    # ── Persist ─────────────────────────────────────────────
    new_count, total = append_new_trades(deduped)
    save_run_metadata(new_count, total, sources_status)

    log.info(f"=== Run complete: +{new_count} new, {total} total ===")


if __name__ == "__main__":
    main()
