"""
app.py — PoliTrade Streamlit Dashboard
Live at: https://your-app.streamlit.app (after deployment)

Reads data/trades.csv from the same GitHub repo.
GitHub Actions updates the CSV every 4 hours.
Streamlit Cloud auto-pulls the latest commit.

Run locally: streamlit run app.py
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ── Page config — MUST be first Streamlit call ─────────────────────────────
st.set_page_config(
    page_title="PoliTrade — Congressional Trading Dashboard",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "Tracks STOCK Act disclosures from U.S. Congress members. "
                 "Data via Capitol Trades. For informational purposes only.",
    }
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Import font */
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap');

  /* Global font */
  html, body, [class*="st-"] {
    font-family: 'DM Sans', sans-serif;
  }

  /* Dark metric cards */
  [data-testid="metric-container"] {
    background: #1a1f2e;
    border: 1px solid #252d42;
    border-radius: 8px;
    padding: 16px !important;
  }
  [data-testid="metric-container"] label {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #6b7594;
  }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 28px;
    font-weight: 600;
  }

  /* Hide default Streamlit branding */
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }

  /* Sidebar */
  [data-testid="stSidebar"] {
    background: #111520;
    border-right: 1px solid #1e2740;
  }

  /* Table header */
  thead tr th {
    background: #1a1f2e !important;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }

  /* Status badges */
  .badge-buy {
    display: inline-block;
    background: rgba(61,188,126,0.15);
    color: #3dbc7e;
    border: 1px solid rgba(61,188,126,0.3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: 'DM Mono', monospace;
    font-weight: 500;
  }
  .badge-sell {
    display: inline-block;
    background: rgba(224,92,92,0.15);
    color: #e05c5c;
    border: 1px solid rgba(224,92,92,0.3);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: 'DM Mono', monospace;
    font-weight: 500;
  }

  /* Alert box */
  .stAlert { border-radius: 8px; }

  /* Section titles */
  h2, h3 { letter-spacing: -0.5px; }

  div[data-testid="stDataFrame"] {
    border: 1px solid #1e2740;
    border-radius: 8px;
    overflow: hidden;
  }
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────
TRADES_CSV    = Path("data/trades.csv")
LAST_RUN_JSON = Path("data/last_run.json")

BUY_COLOR  = "#3dbc7e"
SELL_COLOR = "#e05c5c"
GOLD_COLOR = "#c9a84c"
BLUE_COLOR = "#4c8ec9"
BG_COLOR   = "#0b0e14"
SURFACE    = "#111520"


# ── Data loading ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)   # Cache for 5 minutes; refreshes when file changes
def load_trades() -> pd.DataFrame:
    """Load and pre-process trades.csv."""
    if not TRADES_CSV.exists():
        return pd.DataFrame()

    df = pd.read_csv(TRADES_CSV, dtype=str)

    # Parse dates
    for col in ("transaction_date", "disclosure_date", "scraped_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Parse numerics
    for col in ("amount_lower", "amount_upper", "amount_mid"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Normalize transaction type display
    if "transaction_type" in df.columns:
        df["tx_display"] = df["transaction_type"].str.lower().map(
            lambda x: "Buy" if "purchase" in str(x) or "buy" in str(x)
                      else "Sell" if "sale" in str(x) or "sell" in str(x)
                      else x.title()
        )

    # Ensure politician / ticker columns exist
    df["politician"] = df.get("politician", pd.Series(dtype=str)).fillna("Unknown")
    df["ticker"]     = df.get("ticker",     pd.Series(dtype=str)).fillna("???")
    df["chamber"]    = df.get("chamber",    pd.Series(dtype=str)).fillna("Unknown")

    # Sort newest first
    if "transaction_date" in df.columns:
        df = df.sort_values("transaction_date", ascending=False)

    return df


@st.cache_data(ttl=300)
def load_run_meta() -> dict:
    """Load last_run.json."""
    if not LAST_RUN_JSON.exists():
        return {}
    try:
        return json.loads(LAST_RUN_JSON.read_text())
    except Exception:
        return {}


# ── Helpers ────────────────────────────────────────────────────────────────
def fmt_money(n: float) -> str:
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"


def plotly_theme():
    """Return a dark theme layout dict for Plotly charts."""
    return dict(
        plot_bgcolor  = "rgba(0,0,0,0)",
        paper_bgcolor = "rgba(0,0,0,0)",
        font          = dict(family="DM Sans, sans-serif", color="#8892a4", size=12),
        xaxis=dict(gridcolor="#1e2740", linecolor="#1e2740", tickfont=dict(size=11)),
        yaxis=dict(gridcolor="#1e2740", linecolor="#1e2740", tickfont=dict(size=11)),
        margin=dict(l=8, r=8, t=32, b=8),
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════

def main():
    df   = load_trades()
    meta = load_run_meta()

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 🏛️ PoliTrade")
        st.markdown("*Congressional Trading Monitor*")
        st.divider()

        # -- Data health
        if meta:
            last_run = meta.get("last_run_utc", "Unknown")
            try:
                lr_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                age   = datetime.utcnow().replace(tzinfo=None) - lr_dt.replace(tzinfo=None)
                age_h = age.total_seconds() / 3600
                status_color = "🟢" if age_h < 5 else "🟡" if age_h < 10 else "🔴"
                st.markdown(f"**Data status:** {status_color}")
                st.caption(f"Last updated {age_h:.1f}h ago")
            except Exception:
                st.caption(f"Last run: {last_run}")

            sources = meta.get("sources", {})
            for src, info in sources.items():
                ok = info.get("status") == "ok"
                st.caption(f"{'✅' if ok else '❌'} {src}: {info.get('records', '?')} records")
        else:
            st.warning("No run metadata found.\nRun `python scrape.py` first.")

        st.divider()

        # -- Filters
        st.markdown("### Filters")

        if df.empty:
            st.info("No data loaded yet.")
            return

        # Date range
        min_date = df["transaction_date"].min()
        max_date = df["transaction_date"].max()
        today    = pd.Timestamp.now()

        date_options = {
            "Last 30 days":  today - timedelta(days=30),
            "Last 90 days":  today - timedelta(days=90),
            "Last 6 months": today - timedelta(days=180),
            "Last year":     today - timedelta(days=365),
            "All time":      min_date,
        }
        date_label = st.selectbox("Date range", list(date_options.keys()), index=0)
        date_from  = date_options[date_label]

        # Chamber filter
        chambers = ["All"] + sorted(df["chamber"].dropna().unique().tolist())
        sel_chamber = st.selectbox("Chamber", chambers)

        # Transaction type
        tx_options = ["All", "Buy", "Sell"]
        sel_tx = st.selectbox("Transaction type", tx_options)

        # Politician multi-select
        all_pols = sorted(df["politician"].dropna().unique().tolist())
        sel_pols = st.multiselect(
            "Politician (leave blank = all)",
            options=all_pols,
            default=[],
            placeholder="All politicians..."
        )

        # Ticker search
        ticker_search = st.text_input("Ticker search", placeholder="e.g. NVDA, AAPL").upper().strip()

        st.divider()
        st.caption("Data: Capitol Trades · Senate disclosure repo")
        st.caption("Refreshes every 4 hours via GitHub Actions")

    # ── Apply filters ─────────────────────────────────────────────────────
    fdf = df.copy()
    fdf = fdf[fdf["transaction_date"] >= date_from]

    if sel_chamber != "All":
        fdf = fdf[fdf["chamber"].str.lower() == sel_chamber.lower()]

    if sel_tx != "All":
        fdf = fdf[fdf["tx_display"] == sel_tx]

    if sel_pols:
        fdf = fdf[fdf["politician"].isin(sel_pols)]

    if ticker_search:
        fdf = fdf[fdf["ticker"].str.contains(ticker_search, case=False, na=False)]

    # ── Header ────────────────────────────────────────────────────────────
    col_title, col_ts = st.columns([3, 1])
    with col_title:
        st.markdown("## Congressional Trading Dashboard")
    with col_ts:
        if meta.get("last_run_utc"):
            st.markdown(
                f"<div style='text-align:right;color:#6b7594;font-size:12px;"
                f"font-family:DM Mono,monospace;padding-top:12px'>"
                f"⏱ Updated {meta['last_run_utc'][:16].replace('T',' ')} UTC</div>",
                unsafe_allow_html=True
            )

    st.caption(
        f"Showing **{len(fdf):,}** of **{len(df):,}** total disclosures · "
        f"STOCK Act filings, 45-day lag applies · Estimates only"
    )

    if df.empty:
        st.error(
            "**No data found.** Run `python scrape.py` to generate `data/trades.csv`."
        )
        st.code("python scrape.py --days 90", language="bash")
        return

    # ── KPI Metrics ───────────────────────────────────────────────────────
    st.markdown("---")

    buys  = fdf[fdf["tx_display"] == "Buy"]
    sells = fdf[fdf["tx_display"] == "Sell"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Disclosures",  f"{len(fdf):,}")
    m2.metric("Unique Politicians", f"{fdf['politician'].nunique()}")
    m3.metric("Unique Tickers",     f"{fdf['ticker'].nunique()}")
    m4.metric(
        "Est. Buy Volume",
        fmt_money(buys["amount_mid"].sum()),
        delta=f"{len(buys):,} trades"
    )
    m5.metric(
        "Est. Sell Volume",
        fmt_money(sells["amount_mid"].sum()),
        delta=f"{len(sells):,} trades",
        delta_color="inverse"
    )

    st.markdown("---")

    # ── Charts ────────────────────────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

    # Chart 1: Top tickers by trade count (last 30 days)
    with chart_col1:
        st.markdown("#### Most Traded Tickers")

        top_n = fdf.groupby(["ticker", "tx_display"]).size().reset_index(name="count")
        top_tickers = (
            top_n.groupby("ticker")["count"].sum()
            .sort_values(ascending=False)
            .head(15).index
        )
        chart_data = top_n[top_n["ticker"].isin(top_tickers)]

        if not chart_data.empty:
            fig = px.bar(
                chart_data,
                x="ticker",
                y="count",
                color="tx_display",
                color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
                labels={"count": "# Trades", "ticker": "Ticker", "tx_display": "Type"},
                barmode="stack",
            )
            fig.update_layout(
                **plotly_theme(),
                legend=dict(
                    orientation="h", y=1.05, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"
                ),
                title_text="",
                xaxis_title="",
                yaxis_title="Number of Disclosures",
                height=340,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No chart data for current filters.")

    # Chart 2: Trade volume over time
    with chart_col2:
        st.markdown("#### Trade Activity Over Time")

        if "transaction_date" in fdf.columns and len(fdf) > 0:
            daily = (
                fdf.groupby([fdf["transaction_date"].dt.to_period("W"), "tx_display"])
                .size().reset_index(name="count")
            )
            daily["transaction_date"] = daily["transaction_date"].astype(str)

            fig2 = px.area(
                daily,
                x="transaction_date",
                y="count",
                color="tx_display",
                color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
                labels={"transaction_date": "Week", "count": "Trades", "tx_display": "Type"},
            )
            fig2.update_layout(
                **plotly_theme(),
                legend=dict(
                    orientation="h", y=1.05, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"
                ),
                height=340,
                xaxis_title="",
                yaxis_title="Weekly Disclosures",
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Not enough data for timeline chart.")

    # Chart 3: Top politicians by estimated dollar volume
    st.markdown("#### Politician Activity (Estimated $ Volume)")

    pol_vol = (
        fdf.groupby(["politician", "tx_display"])["amount_mid"]
        .sum().reset_index()
    )
    top_pols = (
        pol_vol.groupby("politician")["amount_mid"].sum()
        .sort_values(ascending=False).head(12).index
    )
    pol_chart_data = pol_vol[pol_vol["politician"].isin(top_pols)]

    if not pol_chart_data.empty:
        fig3 = px.bar(
            pol_chart_data,
            x="amount_mid",
            y="politician",
            color="tx_display",
            color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
            labels={
                "amount_mid":  "Est. $ Volume",
                "politician":  "",
                "tx_display":  "Type"
            },
            orientation="h",
            barmode="group",
        )
        fig3.update_layout(
            **plotly_theme(),
            height=400,
            legend=dict(
                orientation="h", y=1.02, x=0,
                font=dict(size=11), bgcolor="rgba(0,0,0,0)"
            ),
            xaxis=dict(
                tickformat="$,.0f",
                gridcolor="#1e2740",
                linecolor="#1e2740",
            ),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", categoryorder="total ascending"),
        )
        st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # ── Searchable Trade Table ─────────────────────────────────────────────
    st.markdown("#### Trade Disclosures")

    # Column search bar (above table)
    table_search = st.text_input(
        "🔍 Search table by politician, ticker, or issuer",
        placeholder="Type to filter rows...",
        key="table_search"
    )

    display_df = fdf.copy()
    if table_search:
        mask = (
            display_df["politician"].str.contains(table_search, case=False, na=False) |
            display_df["ticker"].str.contains(table_search, case=False, na=False) |
            display_df.get("issuer", pd.Series(dtype=str)).str.contains(
                table_search, case=False, na=False
            )
        )
        display_df = display_df[mask]

    # Select and rename columns for display
    show_cols = {
        "transaction_date": "Trade Date",
        "disclosure_date":  "Filed Date",
        "politician":       "Politician",
        "chamber":          "Chamber",
        "ticker":           "Ticker",
        "tx_display":       "Action",
        "amount_range":     "Amount Range",
        "amount_mid":       "Est. Midpoint",
        "source":           "Source",
    }
    avail = {k: v for k, v in show_cols.items() if k in display_df.columns}
    table = display_df[list(avail.keys())].rename(columns=avail)

    # Format date columns
    for col in ("Trade Date", "Filed Date"):
        if col in table.columns:
            table[col] = table[col].dt.strftime("%Y-%m-%d").fillna("—")

    # Format midpoint
    if "Est. Midpoint" in table.columns:
        table["Est. Midpoint"] = table["Est. Midpoint"].apply(
            lambda x: fmt_money(x) if x > 0 else "—"
        )

    # Capitalize chamber
    if "Chamber" in table.columns:
        table["Chamber"] = table["Chamber"].str.title()

    st.dataframe(
        table.head(500),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn(width="small"),
            "Action": st.column_config.TextColumn(width="small"),
            "Chamber": st.column_config.TextColumn(width="small"),
            "Est. Midpoint": st.column_config.TextColumn(width="medium"),
        }
    )

    if len(display_df) > 500:
        st.caption(f"Showing first 500 of {len(display_df):,} rows. Use filters to narrow results.")

    # ── Download ──────────────────────────────────────────────────────────
    st.markdown("---")
    dl_col1, dl_col2 = st.columns([1, 3])
    with dl_col1:
        csv_bytes = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download filtered CSV",
            data=csv_bytes,
            file_name=f"politrade_export_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
    with dl_col2:
        st.caption(
            f"Exporting **{len(display_df):,}** rows with current filters applied."
        )

    # ── Disclaimer ────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "⚠️ **Disclaimer:** This tool tracks publicly available STOCK Act disclosures. "
        "Data is for informational purposes only and does not constitute investment advice. "
        "Disclosures may be filed up to 45 days after the actual trade. "
        "Dollar amounts are estimates based on mandated disclosure ranges."
    )


if __name__ == "__main__":
    main()
