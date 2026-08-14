"""Section-aware chunking for downloaded 10-K filings, with a documented
fallback for filings where section detection isn't confident.

## Why section-aware, not fixed-size

A fixed-size chunker (e.g. "every 1000 characters") has no idea it just
split a filing mid-sentence across, say, the Risk Factors / Properties
boundary — a retrieved chunk can end up half of one topic and half of
an unrelated one, which hurts both retrieval precision (the embedding
represents two different topics at once) and the mandatory
source-section citation the Filings Agent has to produce (Phase 3+).
10-Ks are regulatorily required to use the same ~23 "Item" sections
(Item 1 Business, Item 1A Risk Factors, Item 7 MD&A, ...) in the same
order, so splitting on those real boundaries — instead of an arbitrary
character count — keeps each chunk topically coherent and gives a real
section name to cite, not just "chunk #14."

## Why there's a fallback at all

The Item numbering is standardized by regulation, but *how a filing
agent renders the heading in HTML* is not. Testing the heading-detection
heuristic below against all 15 companies' actual downloaded filings
showed it reliably recovers the full ~21-23 section sequence for about
half of them (Workiva-style renderers: AAPL, JPM, BA, VZ, CAT, JNJ, PG)
and breaks down for the rest — either the heading pattern doesn't match
at all (MSFT: 0 raw candidates) or cross-references like "as discussed
in Item 7" throughout the MD&A section get mistaken for real headings
(F: 78 raw candidates, mostly repeated "Item 7" mentions in running
prose). See LOG.md for the specific numbers and the regex iteration
that led here — this file only keeps the version that shipped.

Rather than chase an increasingly complicated regex trying to
universally handle every filing agent's rendering quirks, this chunker
uses section detection when it's confident (a canonical-order, longest-
quiet-gap heuristic that recovers at least `MIN_CONFIDENT_SECTIONS` of
the 23 possible Items) and falls back to overlapping sliding-window
chunks otherwise. Every chunk records which method produced it
(`chunk["section_item"] is None` for fallback chunks) so retrieval
results and grounding checks downstream can see this explicitly instead
of silently pretending every chunk has a trustworthy section label.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

CANONICAL_ITEMS: list[str] = [
    "1", "1A", "1B", "1C", "2", "3", "4", "5", "6", "7", "7A", "8",
    "9", "9A", "9B", "9C", "10", "11", "12", "13", "14", "15", "16",
]

CANONICAL_TITLES: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities",
    "6": "[Reserved]",
    "7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants on Accounting and Financial Disclosure",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters",
    "13": "Certain Relationships and Related Transactions, and Director Independence",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibit and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

# Below this many recovered canonical sections, section detection is not
# trusted for this filing and the sliding-window fallback is used instead.
MIN_CONFIDENT_SECTIONS = 18

# Sized to sentence-transformers/all-MiniLM-L6-v2's effective ~256 token
# window (roughly 1000-1200 characters of English text) - a much larger
# chunk would have most of its content silently ignored by the embedding
# model, hurting retrieval precision even though the chunk "looks" fine.
MAX_CHUNK_CHARS = 1200
OVERLAP_CHARS = 150

# Any 'Item X[letter].' not immediately followed by another digit (excludes
# references like "Item 408" to SEC regulations, which aren't 10-K sections).
_ITEM_CANDIDATE_PATTERN = re.compile(r"Item\s+(\d{1,2}[A-C]?)\.(?!\d)")


def extract_text(html_path: Path) -> str:
    """Extract visible prose text, stripping the hidden inline-XBRL tagging
    layer these filings carry (see LOG.md: modern 10-Ks are "Inline XBRL" -
    every financial fact is machine-tagged, and some of that tagging lives
    in a hidden <ix:header> block BeautifulSoup's get_text() doesn't know is
    invisible, since it has no CSS engine - it happily returns hidden text
    right alongside visible prose. Left unstripped, that block's tag-name
    soup ("us-gaap:CommonStockMember", raw context IDs, dates with no
    sentence around them) polluted the first ~4.5% of every filing's
    fallback chunks, found via a real Filings Agent test on NVDA."""
    with open(html_path, encoding="utf-8", errors="ignore") as f:
        content = f.read()
    soup = BeautifulSoup(content, "lxml")

    for hidden in soup.find_all("ix:header"):
        hidden.decompose()
    for hidden in soup.find_all(style=lambda s: s and "display:none" in s.replace(" ", "")):
        hidden.decompose()

    return soup.get_text(separator="\n")


def detect_sections(text: str) -> list[tuple[str, int]]:
    """Return [(item_number, char_offset), ...] in canonical order, best-effort.

    For each canonical item in turn, among all regex candidates for that
    item number appearing after the previous accepted section, picks the
    one followed by the longest run of text before the next Item-like
    token of any number. Real section headings are followed by pages of
    genuine content; cross-references ("as discussed in Item 7") are
    typically followed shortly by more prose or another Item mention, so
    they lose out to the real heading under this heuristic in most cases.
    """
    all_matches = [(m.start(), m.group(1).upper()) for m in _ITEM_CANDIDATE_PATTERN.finditer(text)]
    all_positions = [pos for pos, _ in all_matches]

    accepted: list[tuple[str, int]] = []
    search_start = 0
    for item in CANONICAL_ITEMS:
        candidates = [pos for pos, num in all_matches if num == item and pos >= search_start]
        if not candidates:
            continue

        def gap_to_next(pos: int) -> int:
            later = [p for p in all_positions if p > pos]
            return (min(later) - pos) if later else len(text) - pos

        chosen = max(candidates, key=gap_to_next)
        accepted.append((item, chosen))
        search_start = chosen + 1

    return accepted


def _split_on_paragraphs(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split text into <= max_chars pieces on paragraph boundaries where
    possible, falling back to a hard split for any single paragraph that
    alone exceeds max_chars (common in dense financial-table text)."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            pieces.append(current)
        if len(para) <= max_chars:
            current = para
        else:
            # Word-boundary split, not a raw character-count slice - a hard
            # index cut here produced chunks starting mid-word (e.g.
            # "cally with the SEC..." from "specifically") in filings whose
            # risk-factor bullets run as one long unbroken paragraph with no
            # internal newlines. Found via a real Filings Agent test against
            # NVDA - see LOG.md.
            words = para.split(" ")
            piece_words: list[str] = []
            piece_len = 0
            for word in words:
                if piece_len + len(word) + 1 > max_chars and piece_words:
                    pieces.append(" ".join(piece_words))
                    piece_words = piece_words[-1:] if overlap_chars else []
                    piece_len = sum(len(w) + 1 for w in piece_words)
                piece_words.append(word)
                piece_len += len(word) + 1
            if piece_words:
                pieces.append(" ".join(piece_words))
            current = ""

    if current:
        pieces.append(current)

    # apply overlap between adjacent pieces so context isn't lost at a cut.
    # Word-boundary aware, same reason as the hard-split above: a raw
    # [-overlap_chars:] slice cuts mid-word just as easily as a raw forward
    # slice does (this was the actual remaining source of chunks starting
    # mid-word after the hard-split fix - the hard-split was fixed but this
    # overlap slice, found via the same NVDA test, was doing the same thing).
    overlapped = []
    for i, piece in enumerate(pieces):
        if i == 0:
            overlapped.append(piece)
        else:
            prefix = " ".join(pieces[i - 1][-overlap_chars:].split(" ")[1:])
            overlapped.append(f"{prefix}\n{piece}")
    return overlapped


def chunk_filing(ticker: str, html_path: Path) -> dict[str, Any]:
    text = extract_text(html_path)
    sections = detect_sections(text)

    chunks: list[dict[str, Any]] = []

    if len(sections) >= MIN_CONFIDENT_SECTIONS:
        method = "section_aware"
        for i, (item, start) in enumerate(sections):
            end = sections[i + 1][1] if i + 1 < len(sections) else len(text)
            section_text = text[start:end]
            pieces = _split_on_paragraphs(section_text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
            for j, piece in enumerate(pieces):
                chunks.append(
                    {
                        "ticker": ticker,
                        "section_item": item,
                        "section_title": CANONICAL_TITLES[item],
                        "chunk_index": j,
                        "text": piece,
                    }
                )
    else:
        method = "sliding_window_fallback"
        pieces = _split_on_paragraphs(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
        for j, piece in enumerate(pieces):
            chunks.append(
                {
                    "ticker": ticker,
                    "section_item": None,
                    "section_title": "unknown (sliding-window fallback)",
                    "chunk_index": j,
                    "text": piece,
                }
            )

    return {
        "ticker": ticker,
        "method": method,
        "sections_detected": len(sections),
        "num_chunks": len(chunks),
        "chunks": chunks,
    }
