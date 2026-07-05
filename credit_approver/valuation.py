"""Vehicle collateral valuation.

Three estimation paths, in priority order:

1. `comparables` — real listings (found manually on sgcarmart/carro/etc, or
   by a future scraper that extracts per-listing COE) are combined with a
   COE-remaining adjustment: each comparable's price already bakes in its
   own remaining COE, so with enough comparables spanning different
   remaining-COE ratios we fit value = floor + slope * remaining_ratio and
   evaluate it at the target car's own ratio. This is the most accurate
   path when real data is available.
2. Live Selenium scrape of sgcarmart, then carro, for the make/model/year,
   used as a flat median (no per-listing COE data extracted yet). Price
   extraction matches on visible "$X,XXX" text within a plausible car-price
   range rather than a specific CSS class, so it degrades more gracefully
   across site redesigns than a class-based selector would — but it has
   NOT been verified against either site's live markup: this development
   environment's network policy blocks both domains outright (confirmed
   via direct request, not just a generic timeout), so only the
   fails-gracefully path has been exercised, not successful extraction.
   Test against the real sites before relying on this in production.
3. COE-depreciation estimate off the user-entered purchase price, as a
   last resort when no market data is available at all. On top of the
   COE-remaining discount, this path also applies a mild capped age-based
   haircut from the vehicle's manufacture year, since two cars with the
   same remaining COE but very different years aren't usually worth the
   same. This is a rough approximation, not a substitute for a real
   valuation, and the age assumption in particular is a bad fit for
   low-volume/enthusiast/classic models where price is driven more by
   condition/mods/rarity than by age or COE remaining — supply real
   `comparables` for those instead.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Optional

STANDARD_COE_TENURE_DAYS = 10 * 365


@dataclass
class ValuationResult:
    estimated_value: float
    source: str
    sample_size: int = 0


@dataclass
class Comparable:
    """A comparable listing found on a used-car site, with its own COE expiry."""

    price: float
    coe_expiry: date


def _remaining_coe_ratio(coe_expiry: Optional[date], today: Optional[date] = None) -> float:
    today = today or date.today()
    if coe_expiry is None or coe_expiry <= today:
        return 0.0
    remaining_days = (coe_expiry - today).days
    return min(1.0, remaining_days / STANDARD_COE_TENURE_DAYS)


# Applied only to the COE-depreciation fallback's non-PARF component, and
# only capped at a modest 50% floor: it approximates ordinary wear/mileage/
# tech-obsolescence depreciation for a typical mass-market car. It's a bad
# assumption for enthusiast/classic/appreciating models (a bigger reason
# to supply real `comparables` for those instead of relying on this
# fallback).
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


def estimate_from_comparables(
    comparables: list[Comparable],
    target_coe_expiry: Optional[date],
    today: Optional[date] = None,
) -> ValuationResult:
    """Combine real comparable listings with a COE-remaining adjustment.

    With >=2 comparables spanning a meaningfully different remaining-COE
    ratio, fit a line and evaluate it at the target's ratio. Niche/
    enthusiast cars often don't show a clean COE/price relationship over
    just a couple of comps (condition, mods, and rarity dominate) — when
    the fit comes out nonsensical (negative slope or floor), fall back to
    a flat average of the comparables instead of forcing a bad
    extrapolation.
    """
    if not comparables:
        raise ValueError("estimate_from_comparables requires at least one comparable")

    today = today or date.today()
    target_ratio = _remaining_coe_ratio(target_coe_expiry, today)
    prices = [c.price for c in comparables]
    ratios = [_remaining_coe_ratio(c.coe_expiry, today) for c in comparables]

    if len(comparables) >= 2 and (max(ratios) - min(ratios)) > 0.05:
        n = len(comparables)
        mean_r = sum(ratios) / n
        mean_p = sum(prices) / n
        numerator = sum((r - mean_r) * (p - mean_p) for r, p in zip(ratios, prices))
        denominator = sum((r - mean_r) ** 2 for r in ratios)
        if denominator > 0:
            slope = numerator / denominator
            floor = mean_p - slope * mean_r
            if slope >= 0 and floor >= 0:
                estimated = floor + slope * target_ratio
                return ValuationResult(
                    estimated_value=round(estimated, 2),
                    source="comparable_regression",
                    sample_size=n,
                )

    return ValuationResult(
        estimated_value=round(statistics.mean(prices), 2),
        source="comparable_average",
        sample_size=len(comparables),
    )


# Plausible SGD range for a used-car listing price. Filters out unrelated
# dollar amounts on the page (rebates, monthly instalment teasers, ads)
# without depending on any particular CSS class name.
MIN_PLAUSIBLE_CAR_PRICE = 5_000
MAX_PLAUSIBLE_CAR_PRICE = 800_000

_PRICE_PATTERN = re.compile(r"\$\s?([\d,]{4,9})")


def _extract_plausible_prices(text: str) -> list[float]:
    """Pull "$X,XXX"-style figures out of raw page text and keep only the
    ones in a plausible used-car price range.

    This is intentionally not tied to any specific CSS class or DOM
    structure — those change whenever a site redesigns, silently breaking
    a selector-based scrape. Matching on the page's visible price
    formatting instead is more resilient, at the cost of occasionally
    picking up an unrelated figure (mitigated by the plausibility filter).
    """
    prices = []
    for match in _PRICE_PATTERN.finditer(text):
        value = float(match.group(1).replace(",", ""))
        if MIN_PLAUSIBLE_CAR_PRICE <= value <= MAX_PLAUSIBLE_CAR_PRICE:
            prices.append(value)
    return prices


def _scrape_listing_site(url: str) -> list[float]:
    """Best-effort Selenium fetch of a used-car listing search page.

    Returns an empty list on any failure (missing driver, network block,
    no matching results) so callers can fall back gracefully. Not verified
    against live sgcarmart/carro markup — this development environment's
    network policy blocks both domains, so this has only been tested for
    graceful failure, not for successful extraction. Test against the real
    site before relying on it.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            body_text = driver.find_element(By.TAG_NAME, "body").text
            return _extract_plausible_prices(body_text)
        finally:
            driver.quit()
    except Exception:
        return []


def _scrape_sgcarmart_prices(make: str, model: str, year: int) -> list[float]:
    query = f"{make} {model} {year}".replace(" ", "+")
    url = f"https://www.sgcarmart.com/used_cars/listing.php?BRSR=0&AVL=2&q={query}"
    return _scrape_listing_site(url)


def _scrape_carro_prices(make: str, model: str, year: int) -> list[float]:
    query = f"{make}-{model}-{year}".replace(" ", "-").lower()
    url = f"https://www.carro.sg/buy-used-car/{query}"
    return _scrape_listing_site(url)


def estimate_vehicle_value(
    make: str,
    model: str,
    year: int,
    purchase_price: float,
    coe_expiry: Optional[date] = None,
    use_live_scraping: bool = True,
    comparables: Optional[list[Comparable]] = None,
) -> ValuationResult:
    if comparables:
        return estimate_from_comparables(comparables, coe_expiry)
    if use_live_scraping:
        prices = _scrape_sgcarmart_prices(make, model, year)
        if prices:
            return ValuationResult(
                estimated_value=round(statistics.median(prices), 2),
                source="sgcarmart_scrape",
                sample_size=len(prices),
            )
        prices = _scrape_carro_prices(make, model, year)
        if prices:
            return ValuationResult(
                estimated_value=round(statistics.median(prices), 2),
                source="carro_scrape",
                sample_size=len(prices),
            )
    return _coe_depreciation_estimate(purchase_price, coe_expiry, vehicle_year=year)
