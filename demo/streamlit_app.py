"""Minimal Streamlit demo for the FastAPI /research endpoint.

Calls the API over HTTP rather than importing the graph directly - this
demos the actual deployable interface, not a shortcut around it. The
whole point of this file (per the project doc) is making the multi-agent
architecture visible: which agents produced usable data, which didn't,
and how long each took, laid out so an interviewer can see it at a
glance instead of taking "it's multi-agent" on faith from the code.

Run alongside the API:
    uvicorn serving.app:app --port 8000
    streamlit run demo/streamlit_app.py
"""

import requests
import streamlit as st

st.set_page_config(page_title="Multi-Agent Financial Research Assistant", layout="centered")
st.title("Multi-Agent Financial Research Assistant")
st.caption("Descriptive research summaries only - not investment advice.")

api_url = st.sidebar.text_input("API URL", "http://localhost:8000")
query = st.text_input("Company name or ticker", "Apple")
parallel = st.checkbox("Run Market + Filings agents in parallel", value=True)

if st.button("Run Research", type="primary"):
    with st.spinner("Running Market Agent + Filings Agent + Synthesis Agent..."):
        try:
            response = requests.post(
                f"{api_url}/research", json={"query": query, "parallel": parallel}, timeout=300
            )
        except requests.exceptions.ConnectionError:
            st.error(f"Could not reach the API at {api_url} - is `uvicorn serving.app:app` running?")
            st.stop()

    if response.status_code != 200:
        st.error(f"Request failed: HTTP {response.status_code}")
        st.stop()

    data = response.json()
    st.subheader(f"Ticker: {data['ticker']}")

    def _agent_status(meta: dict) -> str:
        return "✅ used" if meta["ok"] and meta["used_in_synthesis"] else ("⚠️ unavailable" if not meta["ok"] else "⬜ not used")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Market Agent", _agent_status(data["market_agent"]), f"{data['market_agent']['latency_seconds']}s")
    col2.metric("Filings Agent", _agent_status(data["filings_agent"]), f"{data['filings_agent']['latency_seconds']}s")
    col3.metric("Synthesis Agent", "✅ ok" if data["synthesis_agent"]["ok"] else "❌ failed", f"{data['synthesis_agent']['latency_seconds']}s")
    col4.metric(f"Total ({data['execution_mode']})", "", f"{data['total_latency_seconds']}s")

    if data["filings_questions_asked"]:
        st.caption("Filings Agent was asked: " + " | ".join(data["filings_questions_asked"]))

    if data["ok"]:
        st.markdown(data["report"])
    else:
        st.error(f"No report generated: {data['error']}")

    with st.expander("Raw API response"):
        st.json(data)
