"""
dashboard.py — temporary Streamlit debug UI.
Development/monitoring tool only. Not a permanent product.
Run with: streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import httpx

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Forex Alert Debug", layout="wide")
st.title("🔍 Forex Alert Service — Debug Monitor")


def get(path: str):
    try:
        r = httpx.get(f"{API_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"API error [{path}]: {e}")
        return None


# ── Service Health ─────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    health = get("/health")
    if health:
        st.metric("Service", health["status"].upper())
        st.caption(f"Uptime: {health['uptime_seconds']}s")

with col2:
    provider = get("/providers/status")
    if provider:
        st.metric("Twelve Data", provider["status"].upper())
        if provider.get("error"):
            st.error(provider["error"])
        else:
            st.caption(f"Last fetch: {provider.get('last_fetch_utc', 'n/a')}")

st.divider()

# ── Pairs Summary ──────────────────────────────────────────────────────────
st.subheader("📊 Pairs — Latest Signal")
summary = get("/signals/summary")
if summary:
    df = pd.DataFrame(summary)
    st.dataframe(df, use_container_width=True)

st.divider()

# ── Alert Stats ────────────────────────────────────────────────────────────
st.subheader("📈 Alert Stats")
stats = get("/alerts/stats")
if stats:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Signals", stats["total"])
    c2.metric("BUY", stats["buy"])
    c3.metric("SELL", stats["sell"])
    c4.metric("Telegram Sent", stats["telegram_sent"])

st.divider()

# ── Recent Signals ─────────────────────────────────────────────────────────
st.subheader("🕐 Recent Signals")
limit = st.slider("Show last N signals", 10, 200, 50)
recent = get(f"/signals/recent?limit={limit}")
if recent:
    df = pd.DataFrame(recent)
    if not df.empty:
        df["signal_color"] = df["signal"].map({"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"})
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No signals logged yet.")

if st.button("🔄 Refresh"):
    st.rerun()
