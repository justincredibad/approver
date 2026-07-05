"""Vehicle collateral valuation.

Purely market-data-driven, following the approach in a companion project
(github.com/justincredibad/vehicle-valuator): a live scrape of sgcarmart,
then carro, for the make/model/year, reduced to a statistical estimate —
Tukey IQR outlier filtering, then median, with a +/-10% buffer band and a
sample-size-based confidence label. When enough listings share the
vehicle's exact manufacture year, those are used in preference to the
full (wider-year) blend.

Deliberately does NOT derive a value from the user-entered purchase
price. An earlier version had a purchase-price-based COE-depreciation
formula as a fallback, but that's circular for the LTV check this feeds:
an inflated purchase price would inflate the "independent" valuation
right along with it, defeating the point of an independent check. If no
comparable listings can be found, this returns an explicit "no data"
result rather than fabricating a number — the caller decides how to
handle that (e.g. block the assessment until a valuation is available).

If an exact make/model search finds nothing, `estimate_vehicle_value_by_
engine_cc` is a secondary, more speculative fallback: it browses general
listings and compares against other vehicles of a similar engine capacity
and manufacture year instead of the exact model. Engine-cc detail-page
selectors have not been verified at all (unlike the search-results-page
selectors below), so treat this path with more skepticism.

The sgcarmart URL/selectors/approach here are ported from
vehicle-valuator's config.py, which documents verifying them against a
real rendered search on 2026-07-02: sgcarmart is a Next.js app that only
server-renders loading skeletons, so a plain `requests` GET never sees
real data — it requires a real browser (Playwright) to render
client-side first. That verification has NOT been independently
re-confirmed from this codebase — this development environment's network
policy blocks sgcarmart.com and carro.sg outright, so only the
fails-gracefully path has been exercised here, not successful extraction.
Re-verify periodically: sgcarmart's CSS-module class names embed a build
hash (e.g. "styles_price__PoUIK") that changes on redeploy even with no
visible page change.
"""
from __future__ import annotations

import os
import re
import shutil
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode


def _run_in_thread(fn, *args, **kwargs):
    """Run fn in a fresh OS thread and wait for the result.

    Playwright's sync API raises if called from a thread that already has
    a running asyncio event loop — which is the case for Streamlit's
    script-execution thread (and other async-hosting frameworks). A scrape
    that works fine as a standalone script can silently produce nothing
    when called from inside Streamlit, because the broad
    `except Exception: return []` around each scraper swallows that error
    the same as a genuine network failure. Running in a plain new thread
    has no event loop of its own, sidestepping the conflict regardless of
    the caller's context.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(fn, *args, **kwargs).result()

# On hosts where Playwright's own bundled Chromium isn't available (e.g. a
# `playwright install chromium` was never run, or can't be — Streamlit
# Community Cloud has no way to run that post-install step), fall back to
# an apt-installed system Chromium if `packages.txt` requested one. Checked
# in order: an explicit override, then common Debian/Ubuntu binary names.
SYSTEM_CHROMIUM_ENV_VAR = "CHROMIUM_EXECUTABLE_PATH"
SYSTEM_CHROMIUM_CANDIDATES = ["chromium", "chromium-browser"]


def _resolve_chromium_executable() -> Optional[str]:
    """Return a system Chromium path to launch with, or None to let
    Playwright use its own bundled browser (the normal local-dev path
    after `playwright install chromium`)."""
    override = os.environ.get(SYSTEM_CHROMIUM_ENV_VAR)
    if override:
        return override
    for name in SYSTEM_CHROMIUM_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


@dataclass
class ValuationResult:
    estimated_value: Optional[float]
    source: str
    sample_size: int = 0
    low: Optional[float] = None
    high: Optional[float] = None
    outliers_removed: int = 0
    confidence: str = ""
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Live scrape: sgcarmart (primary) — approach ported from a companion
# project that documents having verified it against a real rendered page.
# ---------------------------------------------------------------------------

SGCARMART_BASE_URL = "https://www.sgcarmart.com"
SGCARMART_LISTING_PATH = "/used-cars/listing"
MAX_PAGES_PER_SEARCH = 2
YEAR_SEARCH_WINDOW = 2  # search target_year +/- this many years

SGCARMART_SELECTORS = {
    "listing_card": "div.styles_listing_box__eDRd3, div.listing_item, "
                    "div.card_used_listing, article.listing",
    "price": ".styles_price_container__rI4oV .styles_price__PoUIK, "
             ".price, .listing_price, .car_price",
    "title": ".styles_model_name__ZaHTI, .car_title, .listing_title, h3 a, h2 a",
    "model_year": ".styles_reg_date_text__g7iO_, .reg_date, .year, .car_year",
    "link": "a.styles_text_link__wBaHL, a",
}

PRICE_BUFFER_PCT = 0.10
MIN_SAMPLE_SIZE = 5
IQR_OUTLIER_MULTIPLIER = 1.5


@dataclass
class Listing:
    title: str
    price: float
    reg_year: Optional[int] = None
    url: str = ""
    engine_cc: Optional[float] = None


def _clean_int(text: str) -> Optional[float]:
    """Extract a number from messy text like '$45,800' or '12.3k'."""
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)(k)?(?!m)", text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= 1000
    return value


def _extract_year(text: str) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None


# Plausible engine displacement range (cc) — filters stray numbers that
# happen to be followed by "cc" without being an engine spec.
MIN_PLAUSIBLE_ENGINE_CC = 600
MAX_PLAUSIBLE_ENGINE_CC = 8_000
_ENGINE_CC_PATTERN = re.compile(r"([\d,]{3,5})\s*cc\b", re.IGNORECASE)


def _extract_engine_cc(text: str) -> Optional[float]:
    """Pull an engine displacement figure (e.g. "1,798cc") out of raw page
    text. Unlike the search-results-page selectors above (which
    vehicle-valuator's config.py documents verifying against a real
    render), this has NOT been verified against any real sgcarmart detail
    page — it's a speculative regex scan, used only for the engine-capacity
    cross-model fallback search."""
    if not text:
        return None
    for match in _ENGINE_CC_PATTERN.finditer(text):
        value = float(match.group(1).replace(",", ""))
        if MIN_PLAUSIBLE_ENGINE_CC <= value <= MAX_PLAUSIBLE_ENGINE_CC:
            return value
    return None


def _try_select(card, selector_key: str) -> str:
    selectors = [s.strip() for s in SGCARMART_SELECTORS[selector_key].split(",")]
    for sel in selectors:
        el = card.select_one(sel)
        if el:
            return el.get_text(strip=True)
    return ""


def _try_select_href(card) -> str:
    selectors = [s.strip() for s in SGCARMART_SELECTORS["link"].split(",")]
    for sel in selectors:
        el = card.select_one(sel)
        if el and el.get("href"):
            href = el["href"]
            return href if href.startswith("http") else SGCARMART_BASE_URL + href
    return ""


def _parse_sgcarmart_listing_page(html: str) -> list[Listing]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(SGCARMART_SELECTORS["listing_card"])

    results = []
    for card in cards:
        try:
            title = _try_select(card, "title")
            price = _clean_int(_try_select(card, "price"))
            reg_year = _extract_year(_try_select(card, "model_year"))
            url = _try_select_href(card)
            if price is None or not title:
                continue
            results.append(Listing(title=title, price=price, reg_year=reg_year, url=url))
        except Exception:
            continue
    return results


def _fetch_sgcarmart_html_playwright(url: str, page) -> str:
    page.goto(url, timeout=15_000)
    try:
        page.wait_for_selector(SGCARMART_SELECTORS["listing_card"].split(",")[0].strip(), timeout=15_000)
    except Exception:
        pass  # fall through with whatever rendered; parse step handles empty results
    return page.content()


def _launch_chromium(p):
    """Launch headless Chromium, preferring an apt-installed system browser
    over Playwright's own bundled one when the latter isn't available (see
    _resolve_chromium_executable). --no-sandbox/--disable-dev-shm-usage are
    standard requirements for running headless Chrome as root in a
    container, which is the common case for cloud hosts."""
    launch_args = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    }
    executable_path = _resolve_chromium_executable()
    if executable_path:
        launch_args["executable_path"] = executable_path
    return p.chromium.launch(**launch_args)


def _search_sgcarmart(make: str, model: str, year: int) -> list[Listing]:
    return _run_in_thread(_search_sgcarmart_impl, make, model, year)


def _search_sgcarmart_impl(make: str, model: str, year: int) -> list[Listing]:
    """Best-effort Playwright fetch + parse of sgcarmart search results.

    Returns an empty list on any failure (missing playwright, network
    block, no matching results) so callers can fall back gracefully. See
    the module docstring re: verification status of the selectors below.
    """
    all_listings: list[Listing] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = _launch_chromium(p)
            try:
                browser_page = browser.new_page()
                for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):
                    params = {"q": f"{make} {model}", "avl": "", "page": page_num}
                    url = f"{SGCARMART_BASE_URL}{SGCARMART_LISTING_PATH}?{urlencode(params)}"
                    html = _fetch_sgcarmart_html_playwright(url, browser_page)
                    page_listings = _parse_sgcarmart_listing_page(html)
                    if not page_listings:
                        break
                    page_listings = [
                        listing
                        for listing in page_listings
                        if listing.reg_year is None
                        or abs(listing.reg_year - year) <= YEAR_SEARCH_WINDOW
                    ]
                    all_listings.extend(page_listings)
            finally:
                browser.close()
    except Exception:
        return []
    return all_listings


ENGINE_CC_SEARCH_TOLERANCE_PCT = 0.15  # +/- 15% of the given engine capacity
ENGINE_CC_YEAR_WINDOW = 3  # wider than YEAR_SEARCH_WINDOW: cross-model, so allow more spread
# Bounds worst-case runtime (one detail-page fetch each, up to 15s timeout
# per fetch) to a few minutes rather than potentially five-plus.
MAX_ENGINE_CC_CANDIDATES = 10


def _search_sgcarmart_by_engine_cc(engine_cc: float, year: int) -> list[Listing]:
    return _run_in_thread(_search_sgcarmart_by_engine_cc_impl, engine_cc, year)


def _search_sgcarmart_by_engine_cc_impl(engine_cc: float, year: int) -> list[Listing]:
    """Cross-model fallback: when an exact make/model search finds nothing,
    browse sgcarmart's general used-car listings and keep only ones whose
    engine capacity (read from each candidate's own detail page) falls
    within ENGINE_CC_SEARCH_TOLERANCE_PCT of the given cc, as a rough proxy
    for "similarly-sized/valued vehicle" when no direct comparable exists.

    This is considerably more speculative than _search_sgcarmart: it visits
    a generic listing URL whose exact behavior with no make/model filter is
    unconfirmed, and engine-cc detail-page selectors have never been
    verified at all (see _extract_engine_cc). Treat results from this path
    with more skepticism than a direct make/model match.
    """
    matches: list[Listing] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = _launch_chromium(p)
            try:
                browser_page = browser.new_page()
                params = {"avl": "", "page": 1}
                url = f"{SGCARMART_BASE_URL}{SGCARMART_LISTING_PATH}?{urlencode(params)}"
                html = _fetch_sgcarmart_html_playwright(url, browser_page)
                candidates = _parse_sgcarmart_listing_page(html)[:MAX_ENGINE_CC_CANDIDATES]

                low_cc = engine_cc * (1 - ENGINE_CC_SEARCH_TOLERANCE_PCT)
                high_cc = engine_cc * (1 + ENGINE_CC_SEARCH_TOLERANCE_PCT)

                for candidate in candidates:
                    if not candidate.url:
                        continue
                    if candidate.reg_year is not None and abs(candidate.reg_year - year) > ENGINE_CC_YEAR_WINDOW:
                        continue  # cheap pre-filter before spending a detail-page fetch
                    try:
                        detail_html = _fetch_sgcarmart_html_playwright(candidate.url, browser_page)
                    except Exception:
                        continue
                    cc = _extract_engine_cc(detail_html)
                    if cc is not None and low_cc <= cc <= high_cc:
                        matches.append(
                            Listing(
                                title=candidate.title,
                                price=candidate.price,
                                reg_year=candidate.reg_year,
                                url=candidate.url,
                                engine_cc=cc,
                            )
                        )
            finally:
                browser.close()
    except Exception:
        return []
    return matches


def _iqr_filter(prices: list[float]) -> tuple[list[float], int]:
    """Remove outliers using the Tukey IQR method. Returns (kept, num_removed)."""
    if len(prices) < 4:
        return prices, 0

    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    q1 = sorted_prices[n // 4]
    q3 = sorted_prices[(3 * n) // 4]
    iqr = q3 - q1
    lower_fence = q1 - IQR_OUTLIER_MULTIPLIER * iqr
    upper_fence = q3 + IQR_OUTLIER_MULTIPLIER * iqr

    kept = [p for p in prices if lower_fence <= p <= upper_fence]
    return kept, len(prices) - len(kept)


def _estimate_from_listings(listings: list[Listing], target_year: Optional[int], source: str) -> ValuationResult:
    """Turn scraped listings into a price estimate: IQR-filtered median with
    a +/-10% buffer band, preferring same-year listings when there are
    enough of them, and a sample-size-based confidence label."""
    notes: list[str] = []
    prices = [listing.price for listing in listings]
    raw_count = len(prices)

    filtered_prices, removed = _iqr_filter(prices)
    if not filtered_prices:
        filtered_prices = prices
        removed = 0
        notes.append("Outlier filter was too aggressive; used raw data instead.")

    median_price = statistics.median(filtered_prices)

    if target_year:
        same_year_prices = [listing.price for listing in listings if listing.reg_year == target_year]
        if len(same_year_prices) >= 3:
            same_year_filtered, _ = _iqr_filter(same_year_prices)
            if same_year_filtered:
                median_price = statistics.median(same_year_filtered)
                notes.append(
                    f"Used {len(same_year_filtered)} listing(s) specifically from "
                    f"{target_year} rather than the full year-range blend."
                )

    low = median_price * (1 - PRICE_BUFFER_PCT)
    high = median_price * (1 + PRICE_BUFFER_PCT)

    if raw_count >= 15:
        confidence = "high"
    elif raw_count >= MIN_SAMPLE_SIZE:
        confidence = "medium"
    else:
        confidence = "low"
        notes.append(f"Only {raw_count} listing(s) found — estimate may be unreliable.")

    if removed:
        notes.append(f"Removed {removed} outlier listing(s) before computing the median.")

    return ValuationResult(
        estimated_value=round(median_price, 2),
        source=source,
        sample_size=raw_count,
        low=round(low, 2),
        high=round(high, 2),
        outliers_removed=removed,
        confidence=confidence,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Live scrape: carro (secondary, unverified) — falls back to this only if
# sgcarmart returns nothing. No CSS selectors have ever been confirmed
# against carro.sg's real markup, so this stays a broad, class-agnostic
# price scan rather than pretending to a precision it doesn't have.
# ---------------------------------------------------------------------------

MIN_PLAUSIBLE_CAR_PRICE = 5_000
MAX_PLAUSIBLE_CAR_PRICE = 800_000
_PRICE_PATTERN = re.compile(r"\$\s?([\d,]{4,9})")


def _extract_plausible_prices(text: str) -> list[float]:
    prices = []
    for match in _PRICE_PATTERN.finditer(text):
        value = float(match.group(1).replace(",", ""))
        if MIN_PLAUSIBLE_CAR_PRICE <= value <= MAX_PLAUSIBLE_CAR_PRICE:
            prices.append(value)
    return prices


def _scrape_carro_prices(make: str, model: str, year: int) -> list[float]:
    return _run_in_thread(_scrape_carro_prices_impl, make, model, year)


def _scrape_carro_prices_impl(make: str, model: str, year: int) -> list[float]:
    try:
        from playwright.sync_api import sync_playwright

        query = f"{make}-{model}-{year}".replace(" ", "-").lower()
        url = f"https://www.carro.sg/buy-used-car/{query}"
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            try:
                page = browser.new_page()
                page.goto(url, timeout=15_000)
                return _extract_plausible_prices(page.content())
            finally:
                browser.close()
    except Exception:
        return []


def estimate_vehicle_value(make: str, model: str, year: int, use_live_scraping: bool = True) -> ValuationResult:
    if use_live_scraping:
        listings = _search_sgcarmart(make, model, year)
        if listings:
            return _estimate_from_listings(listings, target_year=year, source="sgcarmart_scrape")
        prices = _scrape_carro_prices(make, model, year)
        if prices:
            return ValuationResult(
                estimated_value=round(statistics.median(prices), 2),
                source="carro_scrape",
                sample_size=len(prices),
            )
    if use_live_scraping:
        note = (
            "No comparable listings found on sgcarmart or carro for this make/model/year — "
            "a vehicle valuation is required before this application can be assessed. Try "
            "widening the search (different model spelling) or check back later."
        )
    else:
        note = (
            "Live scraping is disabled, so no vehicle valuation was produced — enable it "
            "and run this from an environment with real network access and a real "
            "Chrome/Chromium browser (this does not work on Streamlit Community Cloud, "
            "which has no browser installed)."
        )
    return ValuationResult(estimated_value=None, source="no_data", notes=[note])


def estimate_vehicle_value_by_engine_cc(engine_cc: float, year: int) -> ValuationResult:
    """Fallback estimate when the exact make/model has no comparable
    listings: compare against other vehicles of a similar engine capacity
    and manufacture year instead. Considerably more speculative than
    `estimate_vehicle_value` — see `_search_sgcarmart_by_engine_cc`."""
    listings = _search_sgcarmart_by_engine_cc(engine_cc, year)
    if not listings:
        return ValuationResult(
            estimated_value=None,
            source="no_data",
            notes=[
                f"No comparable listings found within {ENGINE_CC_SEARCH_TOLERANCE_PCT:.0%} of "
                f"{engine_cc:.0f}cc for vehicles from around {year}. A vehicle valuation is "
                "required before this application can be assessed."
            ],
        )
    result = _estimate_from_listings(listings, target_year=year, source="sgcarmart_engine_cc_scrape")
    result.notes.append(
        f"Estimated from {result.sample_size} vehicle(s) of similar engine capacity "
        f"(~{engine_cc:.0f}cc +/-{ENGINE_CC_SEARCH_TOLERANCE_PCT:.0%}), not the exact make/model — "
        "treat this as a rougher proxy than a direct match."
    )
    return result
