from datetime import date, timedelta

from credit_approver.valuation import (
    Comparable,
    _extract_plausible_prices,
    estimate_from_comparables,
    estimate_vehicle_value,
)


def test_fallback_valuation_no_network():
    result = estimate_vehicle_value(
        "Toyota",
        "Corolla",
        2024,
        purchase_price=100000,
        coe_expiry=date.today() + timedelta(days=365 * 5),
        use_live_scraping=False,
    )
    assert result.source == "coe_depreciation_estimate"
    assert 0 < result.estimated_value < 100000


def test_fallback_valuation_expired_coe():
    result = estimate_vehicle_value(
        "Toyota",
        "Corolla",
        2010,
        purchase_price=100000,
        coe_expiry=date.today() - timedelta(days=1),
        use_live_scraping=False,
    )
    assert result.estimated_value == 10000
    assert result.source == "coe_depreciation_estimate"


def test_fallback_valuation_older_car_is_worth_less_than_newer_at_same_coe():
    coe_expiry = date.today() + timedelta(days=365 * 5)
    newer = estimate_vehicle_value(
        "Toyota", "Corolla", date.today().year, purchase_price=100000,
        coe_expiry=coe_expiry, use_live_scraping=False,
    )
    older = estimate_vehicle_value(
        "Toyota", "Corolla", date.today().year - 15, purchase_price=100000,
        coe_expiry=coe_expiry, use_live_scraping=False,
    )
    assert older.estimated_value < newer.estimated_value


def test_fallback_valuation_age_discount_is_capped():
    coe_expiry = date.today() + timedelta(days=365 * 5)
    ancient = estimate_vehicle_value(
        "Toyota", "Corolla", date.today().year - 100, purchase_price=100000,
        coe_expiry=coe_expiry, use_live_scraping=False,
    )
    very_old = estimate_vehicle_value(
        "Toyota", "Corolla", date.today().year - 30, purchase_price=100000,
        coe_expiry=coe_expiry, use_live_scraping=False,
    )
    # Both are past the 50%-floor cutoff (25 years), so they should be equal,
    # not scaling down indefinitely with age.
    assert ancient.estimated_value == very_old.estimated_value


def test_fallback_valuation_no_coe_expiry_given():
    result = estimate_vehicle_value(
        "Toyota", "Corolla", 2024, purchase_price=100000, coe_expiry=None, use_live_scraping=False
    )
    assert result.estimated_value == 10000


def test_comparables_take_priority_over_scraping_and_fallback():
    today = date(2026, 7, 5)
    comparables = [
        Comparable(price=60000, coe_expiry=today + timedelta(days=365 * 2)),
        Comparable(price=90000, coe_expiry=today + timedelta(days=365 * 8)),
    ]
    result = estimate_vehicle_value(
        "Lotus",
        "Elise",
        2010,
        purchase_price=999999,  # should be ignored entirely once comparables are given
        coe_expiry=today + timedelta(days=365 * 5),
        use_live_scraping=False,
        comparables=comparables,
    )
    assert result.source in ("comparable_regression", "comparable_average")
    assert 60000 <= result.estimated_value <= 90000


def test_comparables_regression_extrapolates_with_clean_data():
    today = date(2026, 7, 5)
    comparables = [
        Comparable(price=20000, coe_expiry=today + timedelta(days=365 * 1)),
        Comparable(price=80000, coe_expiry=today + timedelta(days=365 * 9)),
    ]
    result = estimate_from_comparables(comparables, today + timedelta(days=365 * 5), today=today)
    assert result.source == "comparable_regression"
    assert result.sample_size == 2
    # roughly midway between the two comps' remaining-COE ratios
    assert 40000 < result.estimated_value < 60000


def test_comparables_fall_back_to_average_on_noisy_real_world_data():
    # Real Lotus Elise comps found on the market don't show a clean COE/price
    # relationship (condition/mods dominate for enthusiast cars) — the fit
    # comes out with a negative slope, which should be rejected in favor of
    # a flat average rather than extrapolated.
    today = date(2026, 7, 5)
    comparables = [
        Comparable(price=72800, coe_expiry=date(2029, 10, 31)),
        Comparable(price=74800, coe_expiry=date(2028, 7, 2)),
    ]
    result = estimate_from_comparables(comparables, date(2031, 1, 1), today=today)
    assert result.source == "comparable_average"
    assert result.estimated_value == 73800.0


def test_estimate_from_comparables_requires_at_least_one():
    try:
        estimate_from_comparables([], date(2030, 1, 1))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_extract_plausible_prices_finds_listing_prices():
    # Loosely mimics the visible text of a listing search results page:
    # real prices mixed with unrelated small dollar figures (rebates,
    # instalment teasers) that shouldn't be picked up.
    page_text = """
    Lotus Elise SC 1.8 (2010)
    $72,800
    Depreciation: $12,500/yr
    From $88/month*

    Lotus Elise S (2011)
    $74,800
    Cashback $500 with this listing
    """
    prices = _extract_plausible_prices(page_text)
    assert 72800.0 in prices
    assert 74800.0 in prices
    assert 88.0 not in prices
    assert 500.0 not in prices


def test_extract_plausible_prices_ignores_out_of_range_figures():
    page_text = "$1,000,000,000 jackpot! Car priced at $45,000 today. Fee: $50."
    prices = _extract_plausible_prices(page_text)
    assert prices == [45000.0]


def test_extract_plausible_prices_handles_no_matches():
    assert _extract_plausible_prices("No prices mentioned here at all.") == []
