from datetime import date, timedelta

from credit_approver.valuation import estimate_vehicle_value


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
