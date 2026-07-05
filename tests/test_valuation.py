from datetime import date, timedelta

from credit_approver.valuation import Comparable, estimate_from_comparables, estimate_vehicle_value


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
