"""Vehicle collateral valuation.

The primary path scrapes used-car listing sites (sgcarmart) with Selenium
for comparable market prices, keyed by make/model/year. Because live
scraping depends on third-party site structure that changes without
notice and may be unreachable from this environment, every call falls
back to a COE-depreciation estimate whenever scraping fails or returns no
results, so the rest of the pipeline stays usable offline.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class ValuationResult:
    estimated_value: float
    source: str
    sample_size: int = 0


def _coe_depreciation_estimate(
    purchase_price: float,
    coe_expiry: Optional[date],
    today: Optional[date] = None,
) -> ValuationResult:
    """Straight-line depreciation of the COE-dependent portion of value.

    Singapore-registered vehicles lose their right to be on the road when
    COE expires, so value trends toward a PARF/de-registration floor as
    COE runs down. This is a rough approximation for when live comparables
    aren't available, not a substitute for a real valuation.
    """
    today = today or date.today()
    if coe_expiry is None or coe_expiry <= today:
        return ValuationResult(estimated_value=round(purchase_price * 0.1, 2), source="coe_depreciation_estimate")

    standard_coe_tenure_days = 10 * 365
    remaining_days = max(0, (coe_expiry - today).days)
    remaining_ratio = min(1.0, remaining_days / standard_coe_tenure_days)

    parf_floor = purchase_price * 0.15
    depreciating_component = purchase_price - parf_floor
    estimated = parf_floor + depreciating_component * remaining_ratio
    return ValuationResult(estimated_value=round(estimated, 2), source="coe_depreciation_estimate")


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
) -> ValuationResult:
    if use_live_scraping:
        prices = _scrape_sgcarmart_prices(make, model, year)
        if prices:
            return ValuationResult(
                estimated_value=round(statistics.median(prices), 2),
                source="sgcarmart_scrape",
                sample_size=len(prices),
            )
    return _coe_depreciation_estimate(purchase_price, coe_expiry)
