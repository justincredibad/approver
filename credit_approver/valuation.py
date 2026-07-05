"""Vehicle collateral valuation.

Two estimation paths, in priority order:

1. Live scrape of sgcarmart, then carro, for the make/model/year, reduced
   to a statistical estimate: Tukey IQR outlier filtering, then median,
   with a +/-10% buffer band and a sample-size-based confidence label.
   When enough listings share the vehicle's exact manufacture year, those
   are used in preference to the full (wider-year) blend. This is the
   most accurate path when real listings are found.

   The sgcarmart URL/selectors/approach here are ported from a companion
   project (github.com/justincredibad/vehicle-valuator) whose config.py
   documents verifying them against a real rendered search on 2026-07-02:
   sgcarmart is a Next.js app that only server-renders loading skeletons,
   so a plain `requests` GET never sees real data — it requires a real
   browser (Playwright) to render client-side first. That verification
   has NOT been independently re-confirmed from this codebase — this
   development environment's network policy blocks sgcarmart.com and
   carro.sg outright, so only the fails-gracefully path has been
   exercised here, not successful extraction. Re-verify periodically:
   sgcarmart's CSS-module class names embed a build hash
   (e.g. "styles_price__PoUIK") that changes on redeploy even with no
   visible page change.
2. COE-depreciation estimate off the user-entered purchase price, as a
   last resort when no market data is available at all. On top of the
   COE-remaining discount, this path also applies a mild capped age-based
   haircut from the vehicle's manufacture year. This is a rough
   approximation, not a substitute for a real valuation, and is weaker
   for low-volume/enthusiast/classic models where price is driven more by
   condition/mods/rarity than by age or COE remaining.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from urllib.parse import urlencode

STANDARD_COE_TENURE_DAYS = 10 * 365


@dataclass
class ValuationResult:
    estimated_value: float
    source: str
    sample_size: int = 0
    low: Optional[float] = None
    high: Optional[float] = None
    outliers_removed: int = 0
    confidence: str = ""
    notes: list[str] = field(default_factory=list)


def _remaining_coe_ratio(coe_expiry: Optional[date], today: Optional[date] = None) -> float:
    today = today or date.today()
    if coe_expiry is None or coe_expiry <= today:
        return 0.0
    remaining_days = (coe_expiry - today).days
    return min(1.0, remaining_days / STANDARD_COE_TENURE_DAYS)


# Applied only to the COE-depreciation fallback's non-PARF component, and
# only capped at a modest 50% floor: it approximates ordinary wear/mileage/
# tech-obsolescence depreciation for a typical mass-market car. It's a bad
# assumption for enthusiast/classic/appreciating models (a bigger reason to
# trust real scraped listings over this fallback for those).
AGE_DEPRECIATION_PER_YEAR = 0.02
MIN_AGE_MULTIPLIER = 0.5


def _age_multiplier(vehicle_year: Optional[int], today: Optional[date] = None) -> float:
    if vehicle_year is None:
        return 1.0
    today = today or date.today()
    age_years = max(0, today.year - vehicle_year)
    return max(MIN_AGE_MULTIPLIER, 1 - AGE_DEPRECIATION_PER_YEAR * age_years)


def _coe_depreciation_estimate(
    purchase_price: float,
    coe_expiry: Optional[date],
    vehicle_year: Optional[int] = None,
    today: Optional[date] = None,
) -> ValuationResult:
    """Straight-line depreciation of the COE-dependent portion of value,
    with a mild additional discount for vehicle age.

    Singapore-registered vehicles lose their right to be on the road when
    COE expires, so value trends toward a PARF/de-registration floor as
    COE runs down. On top of that, the non-PARF component gets a capped
    age-based haircut, since two cars with the same remaining COE but very
    different manufacture years aren't usually worth the same.
    """
    ratio = _remaining_coe_ratio(coe_expiry, today)
    if ratio <= 0:
        return ValuationResult(estimated_value=round(purchase_price * 0.1, 2), source="coe_depreciation_estimate")

    parf_floor = purchase_price * 0.15
    depreciating_component = purchase_price - parf_floor
    age_multiplier = _age_multiplier(vehicle_year, today)
    estimated = parf_floor + depreciating_component * ratio * age_multiplier
    return ValuationResult(estimated_value=round(estimated, 2), source="coe_depreciation_estimate")


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


def _search_sgcarmart(make: str, model: str, year: int) -> list[Listing]:
    """Best-effort Playwright fetch + parse of sgcarmart search results.

    Returns an empty list on any failure (missing playwright, network
    block, no matching results) so callers can fall back gracefully. See
    the module docstring re: verification status of the selectors below.
    """
    all_listings: list[Listing] = []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
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
    try:
        from playwright.sync_api import sync_playwright

        query = f"{make}-{model}-{year}".replace(" ", "-").lower()
        url = f"https://www.carro.sg/buy-used-car/{query}"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=15_000)
                return _extract_plausible_prices(page.content())
            finally:
                browser.close()
    except Exception:
        return []


def estimate_vehicle_value(
    make: str,
    model: str,
    year: int,
    purchase_price: float,
    coe_expiry: Optional[date] = None,
    use_live_scraping: bool = True,
) -> ValuationResult:
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
    return _coe_depreciation_estimate(purchase_price, coe_expiry, vehicle_year=year)
