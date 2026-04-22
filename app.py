"""
app.py — PoliTrade Cloud Dashboard (politrade-cloud)
=====================================================
Reads data/trades.csv updated by GitHub Actions scrape.py.
Deployed at Streamlit Community Cloud.

ROOT CAUSES FIXED IN THIS VERSION:
  1. plotly_theme() yaxis key collision — all update_layout() calls now use
     explicit inline dicts instead of **plotly_theme() unpacking. Python
     raises TypeError when the same key appears both in the unpacked dict
     and as an explicit kwarg. Fix: inline every layout property, no unpacking.
  2. NaN guard on pol_chart_data — the Politician Activity chart now drops
     NaN amount_mid rows and verifies numeric data exists before rendering.
     The old guard (if not pol_chart_data.empty) passed even when all values
     were NaN, causing Plotly to crash on the empty categorical axis.
  3. Shared layout constants replace the plotly_theme() function entirely.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

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

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600&display=swap');
  html, body, [class*="st-"] { font-family: 'DM Sans', sans-serif; }
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
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  [data-testid="stSidebar"] {
    background: #111520;
    border-right: 1px solid #1e2740;
  }
  thead tr th {
    background: #1a1f2e !important;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
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

# ── Shared Plotly layout values ────────────────────────────────────────────
# FIX: These are plain variables, NOT a function that returns a dict.
# Using **function() unpacking in update_layout() causes TypeError when
# the function dict and explicit kwargs share the same top-level key (e.g. yaxis).
# Every chart now uses these values inline — no dict unpacking anywhere.
PLOT_BG      = "rgba(0,0,0,0)"
GRID_COLOR   = "#1e2740"
LINE_COLOR   = "#1e2740"
FONT_COLOR   = "#8892a4"
FONT_FAMILY  = "DM Sans, sans-serif"
MARGIN       = dict(l=8, r=8, t=32, b=8)
AXIS_FONT    = dict(size=11)


# ── Data loading ───────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_trades() -> pd.DataFrame:
    if not TRADES_CSV.exists():
        return pd.DataFrame()

    df = pd.read_csv(TRADES_CSV, dtype=str)

    for col in ("transaction_date", "disclosure_date", "scraped_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in ("amount_lower", "amount_upper", "amount_mid"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "transaction_type" in df.columns:
        df["tx_display"] = df["transaction_type"].str.lower().map(
            lambda x: "Buy"  if "purchase" in str(x) or "buy"  in str(x)
                 else "Sell" if "sale"     in str(x) or "sell" in str(x)
                 else str(x).title()
        )

    df["politician"] = df.get("politician", pd.Series(dtype=str)).fillna("Unknown")
    df["ticker"]     = df.get("ticker",     pd.Series(dtype=str)).fillna("???")
    df["chamber"]    = df.get("chamber",    pd.Series(dtype=str)).fillna("Unknown")

    if "transaction_date" in df.columns:
        df = df.sort_values("transaction_date", ascending=False)

    return df


@st.cache_data(ttl=300)
def load_run_meta() -> dict:
    if not LAST_RUN_JSON.exists():
        return {}
    try:
        return json.loads(LAST_RUN_JSON.read_text())
    except Exception:
        return {}


# ── Helpers ────────────────────────────────────────────────────────────────

def fmt_money(n: float) -> str:
    n = float(n or 0)
    if n >= 1_000_000:
        return f"${n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n/1_000:.0f}K"
    return f"${n:.0f}"


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

        if meta:
            last_run = meta.get("last_run_utc", "Unknown")
            try:
                lr_dt  = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                age_h  = (datetime.utcnow() - lr_dt.replace(tzinfo=None)).total_seconds() / 3600
                dot    = "🟢" if age_h < 5 else "🟡" if age_h < 10 else "🔴"
                st.markdown(f"**Data status:** {dot}")
                st.caption(f"Last updated {age_h:.1f}h ago")
            except Exception:
                st.caption(f"Last run: {last_run}")

            for src, info in meta.get("sources", {}).items():
                ok = info.get("status") == "ok"
                st.caption(f"{'✅' if ok else '❌'} {src}: {info.get('records','?')} records")
        else:
            st.warning("No run metadata found.\nRun `python scrape.py` first.")

        st.divider()
        st.markdown("### Filters")

        if df.empty:
            st.info("No data loaded yet.")
            return

        today       = pd.Timestamp.now()
        date_options = {
            "Last 30 days":  today - timedelta(days=30),
            "Last 90 days":  today - timedelta(days=90),
            "Last 6 months": today - timedelta(days=180),
            "Last year":     today - timedelta(days=365),
            "All time":      df["transaction_date"].min(),
        }
        date_label  = st.selectbox("Date range", list(date_options.keys()), index=0)
        date_from   = date_options[date_label]

        chambers    = ["All"] + sorted(df["chamber"].dropna().unique().tolist())
        sel_chamber = st.selectbox("Chamber", chambers)

        sel_tx      = st.selectbox("Transaction type", ["All", "Buy", "Sell"])

        all_pols    = sorted(df["politician"].dropna().unique().tolist())
        sel_pols    = st.multiselect(
            "Politician (leave blank = all)", options=all_pols,
            default=[], placeholder="All politicians..."
        )

        ticker_search = st.text_input(
            "Ticker search", placeholder="e.g. NVDA, AAPL"
        ).upper().strip()

        st.divider()
        st.caption("Data: Capitol Trades · Senate disclosure repo")
        st.caption("Refreshes every 4 hours via GitHub Actions")

    # ── Apply filters ─────────────────────────────────────────────────────
    fdf = df[df["transaction_date"] >= date_from].copy()

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
        st.error("**No data found.** Run `python scrape.py` to generate `data/trades.csv`.")
        return

    # ── KPI Metrics ───────────────────────────────────────────────────────
    st.markdown("---")
    buys  = fdf[fdf["tx_display"] == "Buy"]
    sells = fdf[fdf["tx_display"] == "Sell"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Disclosures",  f"{len(fdf):,}")
    m2.metric("Unique Politicians", f"{fdf['politician'].nunique()}")
    m3.metric("Unique Tickers",     f"{fdf['ticker'].nunique()}")
    m4.metric("Est. Buy Volume",    fmt_money(buys["amount_mid"].sum()),
              delta=f"{len(buys):,} trades")
    m5.metric("Est. Sell Volume",   fmt_money(sells["amount_mid"].sum()),
              delta=f"{len(sells):,} trades", delta_color="inverse")

    st.markdown("---")

    # ── Chart 1 + 2: Side by side ─────────────────────────────────────────
    chart_col1, chart_col2 = st.columns(2)

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
            fig1 = px.bar(
                chart_data, x="ticker", y="count", color="tx_display",
                color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
                labels={"count": "# Trades", "ticker": "Ticker", "tx_display": "Type"},
                barmode="stack",
            )
            # FIX: All layout props are inline — no **dict unpacking
            fig1.update_layout(
                plot_bgcolor=PLOT_BG,
                paper_bgcolor=PLOT_BG,
                font=dict(family=FONT_FAMILY, color=FONT_COLOR, size=12),
                margin=MARGIN,
                height=340,
                legend=dict(
                    orientation="h", y=1.05, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"
                ),
                xaxis=dict(
                    gridcolor=GRID_COLOR, linecolor=LINE_COLOR,
                    tickfont=AXIS_FONT, title=""
                ),
                yaxis=dict(
                    gridcolor=GRID_COLOR, linecolor=LINE_COLOR,
                    tickfont=AXIS_FONT, title="Number of Disclosures"
                ),
            )
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("No chart data for current filters.")

    with chart_col2:
        st.markdown("#### Trade Activity Over Time")

        if "transaction_date" in fdf.columns and len(fdf) > 0:
            daily = (
                fdf.groupby(
                    [fdf["transaction_date"].dt.to_period("W"), "tx_display"]
                ).size().reset_index(name="count")
            )
            daily["transaction_date"] = daily["transaction_date"].astype(str)

            fig2 = px.area(
                daily, x="transaction_date", y="count", color="tx_display",
                color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
                labels={
                    "transaction_date": "Week",
                    "count": "Trades",
                    "tx_display": "Type",
                },
            )
            # FIX: inline layout — no **dict unpacking
            fig2.update_layout(
                plot_bgcolor=PLOT_BG,
                paper_bgcolor=PLOT_BG,
                font=dict(family=FONT_FAMILY, color=FONT_COLOR, size=12),
                margin=MARGIN,
                height=340,
                legend=dict(
                    orientation="h", y=1.05, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"
                ),
                xaxis=dict(
                    gridcolor=GRID_COLOR, linecolor=LINE_COLOR,
                    tickfont=AXIS_FONT, title=""
                ),
                yaxis=dict(
                    gridcolor=GRID_COLOR, linecolor=LINE_COLOR,
                    tickfont=AXIS_FONT, title="Weekly Disclosures"
                ),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Not enough data for timeline chart.")

    # ── Chart 3: Politician Activity ──────────────────────────────────────
    st.markdown("#### Politician Activity (Estimated $ Volume)")

    pol_vol = (
        fdf.groupby(["politician", "tx_display"])["amount_mid"]
           .sum()
           .reset_index()
    )

    # FIX: Drop rows where amount_mid is 0 or NaN BEFORE checking empty.
    # The old guard (if not pol_chart_data.empty) passed even when all
    # amount_mid values were NaN/0, causing Plotly to crash on an empty
    # categorical axis when categoryorder="total ascending" was applied.
    pol_vol = pol_vol[pol_vol["amount_mid"] > 0].dropna(subset=["amount_mid"])

    top_pols = (
        pol_vol.groupby("politician")["amount_mid"].sum()
               .sort_values(ascending=False)
               .head(12).index
    )
    pol_chart_data = pol_vol[pol_vol["politician"].isin(top_pols)]

    if pol_chart_data.empty or pol_chart_data["amount_mid"].sum() == 0:
        st.info("No dollar volume data available for current filters.")
    else:
        fig3 = px.bar(
            pol_chart_data,
            x="amount_mid",
            y="politician",
            color="tx_display",
            color_discrete_map={"Buy": BUY_COLOR, "Sell": SELL_COLOR},
            labels={
                "amount_mid": "Est. $ Volume",
                "politician": "",
                "tx_display": "Type",
            },
            orientation="h",
            barmode="group",
        )
        # FIX: yaxis has ONE definition with ALL required properties.
        # Previously: **plotly_theme() set yaxis=dict(gridcolor=...) AND
        # the explicit yaxis=dict(categoryorder=...) kwarg overwrote it,
        # dropping gridcolor. Now both are in the same dict — no conflict.
        fig3.update_layout(
            plot_bgcolor=PLOT_BG,
            paper_bgcolor=PLOT_BG,
            font=dict(family=FONT_FAMILY, color=FONT_COLOR, size=12),
            margin=MARGIN,
            height=max(350, len(pol_chart_data["politician"].unique()) * 35),
            legend=dict(
                orientation="h", y=1.02, x=0,
                font=dict(size=11), bgcolor="rgba(0,0,0,0)"
            ),
            xaxis=dict(
                tickformat="$,.0f",
                gridcolor=GRID_COLOR,
                linecolor=LINE_COLOR,
                tickfont=AXIS_FONT,
            ),
            yaxis=dict(
                gridcolor="rgba(0,0,0,0)",
                linecolor=LINE_COLOR,
                tickfont=AXIS_FONT,
                categoryorder="total ascending",    # ← Now safely in one dict
            ),
        )
        st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # ── Searchable Trade Table ─────────────────────────────────────────────
    st.markdown("#### Trade Disclosures")

    table_search = st.text_input(
        "🔍 Search by politician, ticker, or issuer",
        placeholder="Type to filter rows...",
        key="table_search"
    )

    display_df = fdf.copy()
    if table_search:
        mask = (
            display_df["politician"].str.contains(table_search, case=False, na=False) |
            display_df["ticker"].str.contains(table_search, case=False, na=False)
        )
        # issuer column is optional
        if "issuer" in display_df.columns:
            mask = mask | display_df["issuer"].str.contains(
                table_search, case=False, na=False
            )
        display_df = display_df[mask]

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
    table = display_df[list(avail.keys())].rename(columns=avail).copy()

    for col in ("Trade Date", "Filed Date"):
        if col in table.columns:
            table[col] = pd.to_datetime(table[col], errors="coerce").dt.strftime("%Y-%m-%d").fillna("—")

    if "Est. Midpoint" in table.columns:
        table["Est. Midpoint"] = table["Est. Midpoint"].apply(
            lambda x: fmt_money(float(x)) if pd.notna(x) and float(x) > 0 else "—"
        )

    if "Chamber" in table.columns:
        table["Chamber"] = table["Chamber"].str.title()

    st.dataframe(
        table.head(500),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Ticker":         st.column_config.TextColumn(width="small"),
            "Action":         st.column_config.TextColumn(width="small"),
            "Chamber":        st.column_config.TextColumn(width="small"),
            "Est. Midpoint":  st.column_config.TextColumn(width="medium"),
        }
    )

    if len(display_df) > 500:
        st.caption(
            f"Showing first 500 of {len(display_df):,} rows. "
            "Use filters to narrow results."
        )

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
        st.caption(f"Exporting **{len(display_df):,}** rows with current filters applied.")

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
