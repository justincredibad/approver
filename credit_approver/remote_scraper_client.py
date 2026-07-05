"""Client for calling a locally-hosted scraper_server.py instance over HTTP.

Lets a GUI deployment without Chrome (e.g. Streamlit Community Cloud) get
live valuations from a machine that has both real network access and a
real browser, via a tunnel (ngrok, Cloudflare Tunnel, etc.) exposing that
machine's scraper_server.py publicly. See README.md for setup.

Every function here returns None on any failure (network error, timeout,
bad response) rather than raising, so callers can degrade to the same
"no data" state used when local in-process scraping finds nothing.
"""
from __future__ import annotations

from typing import Optional

import requests

from credit_approver.valuation import ValuationResult

# Real Playwright scraping is slow — multiple page loads plus (for the
# engine-cc cross-model path) up to MAX_ENGINE_CC_CANDIDATES sequential
# detail-page fetches. A too-short client timeout gives up and reports
# "no data" before the scraper ever finishes, which looks identical to a
# genuine empty result with no indication that it was actually a timeout.
VALUATION_TIMEOUT_SECONDS = 60
VALUATION_BY_CC_TIMEOUT_SECONDS = 180


def _to_valuation_result(payload: dict) -> ValuationResult:
    return ValuationResult(
        estimated_value=payload.get("estimated_value"),
        source=payload.get("source", "remote_scraper"),
        sample_size=payload.get("sample_size", 0),
        low=payload.get("low"),
        high=payload.get("high"),
        outliers_removed=payload.get("outliers_removed", 0),
        confidence=payload.get("confidence", ""),
        notes=payload.get("notes", []),
    )


def fetch_remote_valuation(
    base_url: str, make: str, model: str, year: int, timeout: int = VALUATION_TIMEOUT_SECONDS
) -> Optional[ValuationResult]:
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/valuation",
            params={"make": make, "model": model, "year": year},
            timeout=timeout,
        )
        response.raise_for_status()
        return _to_valuation_result(response.json())
    except Exception:
        return None


def fetch_remote_valuation_by_engine_cc(
    base_url: str, engine_cc: float, year: int, timeout: int = VALUATION_BY_CC_TIMEOUT_SECONDS
) -> Optional[ValuationResult]:
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/valuation/by-cc",
            params={"engine_cc": engine_cc, "year": year},
            timeout=timeout,
        )
        response.raise_for_status()
        return _to_valuation_result(response.json())
    except Exception:
        return None
