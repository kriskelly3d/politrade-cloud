# PoliTrade Cloud 🏛️📊

**Automated congressional trading dashboard — free, self-updating, live URL.**

Built on:
- **GitHub Actions** — scrapes Capitol Trades every 4 hours for free
- **GitHub repo** — stores all trade data in `data/trades.csv`
- **Streamlit Community Cloud** — serves the live dashboard for free

---

## Directory Structure

```
politrade-cloud/
├── .github/
│   └── workflows/
│       └── scrape.yml          ← GitHub Actions cron job
├── data/
│   ├── trades.csv              ← Auto-updated trade history (committed by Actions)
│   ├── last_run.json           ← Run metadata (timestamp, record count, source status)
│   └── run_log.txt             ← Human-readable run history
├── app.py                      ← Streamlit dashboard
├── scrape.py                   ← Data pipeline (runs in GitHub Actions)
├── requirements.txt            ← Python dependencies
└── .gitignore
```

---

## Complete Setup Guide

### STEP 1 — Create a GitHub Repository

1. Go to **github.com** → click **"New"** (green button, top left)
2. Name it: `politrade-cloud` (or anything you like)
3. Set it to **Public** ← Required for free Streamlit Cloud deployment
4. Check **"Add a README file"**
5. Click **"Create repository"**

### STEP 2 — Upload the Files

**Option A — GitHub web interface (easiest, no git knowledge needed):**

1. Open your new repository on GitHub
2. Click **"Add file"** → **"Upload files"**
3. Upload these files:
   - `app.py`
   - `scrape.py`
   - `requirements.txt`
   - `.gitignore`
4. Click **"Commit changes"**

For the nested files (.github folder):

5. Click **"Add file"** → **"Create new file"**
6. In the filename box, type: `.github/workflows/scrape.yml`
   (GitHub will auto-create the folders as you type the slashes)
7. Paste the contents of `scrape.yml` into the editor
8. Click **"Commit new file"**

For the data directory:

9. Click **"Add file"** → **"Create new file"**
10. Type: `data/trades.csv`
11. Paste just the header line (first line of the file):
    ```
    disclosure_id,scraped_at,politician,chamber,ticker,issuer,transaction_type,transaction_date,disclosure_date,amount_range,amount_lower,amount_upper,amount_mid,source
    ```
12. Commit it

**Option B — Git command line:**
```bash
git clone https://github.com/YOUR_USERNAME/politrade-cloud.git
cd politrade-cloud
# Copy all files into this folder, then:
git add .
git commit -m "Initial commit"
git push
```

### STEP 3 — Trigger the First Scrape

The scraper runs automatically on schedule, but you can trigger it immediately:

1. In your GitHub repo, click the **"Actions"** tab
2. Click **"Scrape Congressional Trades"** in the left panel
3. Click **"Run workflow"** → **"Run workflow"** (green button)
4. Watch it run — takes about 2-3 minutes
5. When done, click the run to see logs
6. Go to your repo's **"Code"** tab → open `data/trades.csv`
   You should now see thousands of rows

### STEP 4 — Deploy to Streamlit Community Cloud (Free Live URL)

1. Go to **share.streamlit.io**
2. Click **"Sign in with GitHub"**
3. Authorize Streamlit to access your GitHub account
4. Click **"New app"**
5. Fill in:
   - **Repository:** `YOUR_USERNAME/politrade-cloud`
   - **Branch:** `main`
   - **Main file path:** `app.py`
6. Click **"Deploy!"**
7. Wait 2-3 minutes for it to build
8. You'll get a permanent URL like:
   `https://your-username-politrade-cloud-app-abc123.streamlit.app`

**That's it.** Your dashboard is now live and updates automatically every 4 hours.

---

## How the Auto-Update Cycle Works

```
GitHub Actions cron (every 4 hours)
         │
         ▼
scrape.py runs
  ├── Capitol Trades HTML → new trades
  └── Senate GitHub JSON  → new trades
         │
         ▼
Deduplication check against data/trades.csv
         │
         ▼
Append new rows to data/trades.csv
         │
         ▼
git commit + git push (automatic)
         │
         ▼
Streamlit Cloud detects new commit
         │
         ▼
Dashboard auto-refreshes (next page load)
```

---

## Free Tier Limits

| Service | Free Allowance | Our Usage |
|---|---|---|
| GitHub Actions | 2,000 min/month (public repos: unlimited) | ~360 min/month |
| GitHub Storage | 1 GB per repo | ~5 MB/year for trades.csv |
| Streamlit Cloud | 1 free app, unlimited traffic | 1 app |

**Everything is free as long as your repo is public.**

---

## Customizing What Gets Scraped

Edit `scrape.py` and change the `days_back` default, or pass `--days 90` when triggering manually in GitHub Actions.

To filter specific politicians, add a filter in `scrape.py` after the records are fetched:

```python
# Filter to only tracked politicians (add near bottom of main())
TRACKED = ["Nancy Pelosi", "Dan Crenshaw", "Tommy Tuberville"]
if TRACKED:
    deduped = [r for r in deduped if r["politician"] in TRACKED]
```

---

## Troubleshooting

**GitHub Actions workflow not showing up:**
→ The `.github/workflows/scrape.yml` file path must be exact. Check capitalization.

**"No data found" on dashboard:**
→ Trigger a manual run in GitHub Actions first (Step 3 above).

**Streamlit app says "trades.csv not found":**
→ Make sure `data/trades.csv` exists in your repo with at least the header row.

**Scraper getting 0 records:**
→ Capitol Trades may be temporarily rate-limiting. Wait 30 minutes and re-run.

**Streamlit deployment fails:**
→ Check that `requirements.txt` is in the root of the repo (not in a subfolder).

---

## Disclaimer

This project tracks publicly available STOCK Act financial disclosures.
It is for informational and educational purposes only.
Nothing here constitutes investment advice.
