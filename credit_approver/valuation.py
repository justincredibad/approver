"""Vehicle collateral valuation.

Three estimation paths, in priority order:

1. `comparables` — real listings (found manually on sgcarmart/carro/etc, or
   by a future scraper that extracts per-listing COE) are combined with a
   COE-remaining adjustment: each comparable's price already bakes in its
   own remaining COE, so with enough comparables spanning different
   remaining-COE ratios we fit value = floor + slope * remaining_ratio and
   evaluate it at the target car's own ratio. This is the most accurate
   path when real data is available.
2. Live Selenium scrape of sgcarmart for the make/model/year, used as a
   flat median (no per-listing COE data extracted yet).
3. COE-depreciation estimate off the user-entered purchase price, as a
   last resort when no market data is available at all. This is a rough
   approximation, not a substitute for a real valuation, and is weaker
   for low-volume/enthusiast models where price is driven more by
   condition/mods/rarity than by COE remaining.
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


def _coe_depreciation_estimate(
    purchase_price: float,
    coe_expiry: Optional[date],
    today: Optional[date] = None,
) -> ValuationResult:
    """Straight-line depreciation of the COE-dependent portion of value.

    Singapore-registered vehicles lose their right to be on the road when
    COE expires, so value trends toward a PARF/de-registration floor as
    COE runs down.
    """
    ratio = _remaining_coe_ratio(coe_expiry, today)
    if ratio <= 0:
        return ValuationResult(estimated_value=round(purchase_price * 0.1, 2), source="coe_depreciation_estimate")

    parf_floor = purchase_price * 0.15
    depreciating_component = purchase_price - parf_floor
    estimated = parf_floor + depreciating_component * ratio
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


def _scrape_sgcarmart_prices(make: str, model: str, year: int) -> list[float]:
    """Best-effort Selenium scrape of sgcarmart used-car listings.

    Returns an empty list on any failure (missing driver, changed page
    structure, network block) so callers can fall back gracefully. CSS
    selectors here are approximate and may need updating if the site
    changes.
    """
    prices: list[float] = []
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
            query = f"{make} {model} {year}".replace(" ", "+")
            driver.get(f"https://www.sgcarmart.com/used_cars/listing.php?BRSR=0&AVL=2&q={query}")
            elements = driver.find_elements(By.CSS_SELECTOR, ".sgcm-listing__price, .price")
            for el in elements:
                match = re.search(r"[\d,]+", el.text)
                if match:
                    prices.append(float(match.group().replace(",", "")))
        finally:
            driver.quit()
    except Exception:
        return []
    return prices


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
    return _coe_depreciation_estimate(purchase_price, coe_expiry)
