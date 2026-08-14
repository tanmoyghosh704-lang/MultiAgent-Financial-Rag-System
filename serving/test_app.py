"""Standalone tests for the FastAPI serving layer. Slow where they touch
/research (real graph, real Ollama calls) - same tradeoff as every other
end-to-end test in this repo, kept deliberately few in number here since
graph/test_orchestrator.py already covers the routing matrix in detail;
these just confirm the HTTP layer wraps that correctly.
"""

from fastapi.testclient import TestClient

from serving.app import app, resolve_ticker

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_resolve_ticker_direct_ticker():
    assert resolve_ticker("aapl") == "AAPL"


def test_resolve_ticker_by_company_name():
    assert resolve_ticker("Apple") == "AAPL"


def test_resolve_ticker_unrecognized_falls_through_unchanged():
    assert resolve_ticker("notarealcompany") == "NOTAREALCOMPANY"


def test_research_endpoint_resolves_company_name_and_returns_metadata():
    response = client.post("/research", json={"query": "Apple", "parallel": True})
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["ok"] is True
    assert body["report"] is not None
    assert body["market_agent"]["ok"] is True
    assert body["filings_agent"]["ok"] is True
    assert body["execution_mode"] == "parallel"
    assert len(body["filings_questions_asked"]) == 2


def test_research_endpoint_invalid_ticker_returns_structured_error():
    response = client.post("/research", json={"query": "NOTAREALTICKER123"})
    assert response.status_code == 200  # a "no data" result is a valid response, not a server error
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "no_data_available"
    assert body["report"] is None
