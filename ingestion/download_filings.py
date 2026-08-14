"""Download each company's latest 10-K from SEC EDGAR, ahead of time.

Run once (`python -m ingestion.download_filings`), not at query time — the
graph/agents only ever read from `data/filings/` on disk. This matches the
project doc's requirement to not depend on live scraping/API calls during
actual research queries; hitting SEC's API here is a one-time ingestion
step, not a runtime dependency.

Ticker -> CIK -> latest 10-K is fully resolved via SEC's own free APIs, so
no filing URLs are hardcoded anywhere:
  1. www.sec.gov/files/company_tickers.json  -> ticker to CIK
  2. data.sec.gov/submissions/CIK{cik}.json  -> filing history, find most
     recent form == "10-K"
  3. the primary document URL is then deterministic from the CIK and
     accession number

SEC's fair-access policy requires every request to carry a descriptive
User-Agent with contact info (an anonymous/generic User-Agent gets
rate-limited or blocked) - see USER_AGENT below.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
import yaml

USER_AGENT = "MultiAgent-Financial-RAG-Research tanmoyghosh704@gmail.com"
HEADERS = {"User-Agent": USER_AGENT}

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}"

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_YAML = REPO_ROOT / "ingestion" / "sources.yaml"
FILINGS_DIR = REPO_ROOT / "data" / "filings"

# SEC asks for no more than ~10 requests/sec; staying well under that since
# this is a one-time ingestion script, not a latency-sensitive path.
REQUEST_DELAY_SECONDS = 0.3


def _load_company_universe() -> dict[str, dict[str, Any]]:
    with open(SOURCES_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fetch_ticker_to_cik_map() -> dict[str, int]:
    resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    raw = resp.json()  # {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    return {entry["ticker"]: entry["cik_str"] for entry in raw.values()}


def _latest_10k_filing(cik: int) -> dict[str, str] | None:
    resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]

    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return {
                "accession_number": recent["accessionNumber"][i],
                "primary_document": recent["primaryDocument"][i],
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
            }
    return None


def download_filing(ticker: str, cik: int) -> dict[str, Any]:
    """Download `ticker`'s latest 10-K to data/filings/{ticker}_10K.htm.

    Returns a result dict recording what happened (success + metadata, or
    a structured failure reason) rather than raising, so a batch run over
    all 15 companies can report a clean summary at the end instead of
    dying on the first miss.
    """
    filing = _latest_10k_filing(cik)
    if filing is None:
        return {"ticker": ticker, "ok": False, "error": "no_10k_found", "cik": cik}

    accession_no_dashes = filing["accession_number"].replace("-", "")
    url = FILING_URL.format(
        cik=cik,
        accession_no_dashes=accession_no_dashes,
        primary_document=filing["primary_document"],
    )

    resp = requests.get(url, headers=HEADERS, timeout=60)
    if resp.status_code != 200:
        return {
            "ticker": ticker,
            "ok": False,
            "error": "download_failed",
            "status_code": resp.status_code,
            "url": url,
        }

    FILINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FILINGS_DIR / f"{ticker}_10K.htm"
    out_path.write_bytes(resp.content)

    return {
        "ticker": ticker,
        "ok": True,
        "cik": cik,
        "report_date": filing["report_date"],
        "filing_date": filing["filing_date"],
        "url": url,
        "path": str(out_path),
        "size_bytes": len(resp.content),
    }


def download_all() -> list[dict[str, Any]]:
    universe = _load_company_universe()
    ticker_to_cik = _fetch_ticker_to_cik_map()

    results = []
    for ticker in universe:
        cik = ticker_to_cik.get(ticker)
        if cik is None:
            results.append({"ticker": ticker, "ok": False, "error": "ticker_not_in_sec_database"})
            continue

        result = download_filing(ticker, cik)
        results.append(result)
        time.sleep(REQUEST_DELAY_SECONDS)

    return results


if __name__ == "__main__":
    results = download_all()

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    print(f"Downloaded {len(ok)}/{len(results)} filings successfully.")
    for r in ok:
        print(f"  {r['ticker']}: {r['report_date']} ({r['size_bytes']:,} bytes) -> {r['path']}")
    if failed:
        print("\nFailed:")
        for r in failed:
            print(f"  {r['ticker']}: {r['error']}")

    manifest_path = FILINGS_DIR / "download_manifest.json"
    FILINGS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")
