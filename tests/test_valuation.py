from datetime import date, timedelta

from credit_approver.valuation import (
    Listing,
    _estimate_from_listings,
    _extract_plausible_prices,
    _iqr_filter,
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


def test_iqr_filter_removes_outlier():
    prices = [45000, 47000, 46500, 120000, 44000, 48000]  # 120000 is an outlier
    kept, removed = _iqr_filter(prices)
    assert 120000 not in kept
    assert removed == 1


def test_iqr_filter_leaves_small_samples_untouched():
    prices = [45000, 47000, 46500]  # fewer than 4 points, IQR not meaningful
    kept, removed = _iqr_filter(prices)
    assert kept == prices
    assert removed == 0


def test_estimate_from_listings_computes_median_with_buffer_and_confidence():
    listings = [
        Listing(title="A", price=45000, reg_year=2019),
        Listing(title="B", price=47000, reg_year=2019),
        Listing(title="C", price=46500, reg_year=2019),
        Listing(title="D", price=120000, reg_year=2019),  # outlier
        Listing(title="E", price=44000, reg_year=2019),
        Listing(title="F", price=48000, reg_year=2019),
    ]
    result = _estimate_from_listings(listings, target_year=2019, source="sgcarmart_scrape")

    assert result.source == "sgcarmart_scrape"
    assert result.sample_size == 6
    assert result.outliers_removed == 1
    assert result.low < result.estimated_value < result.high
    assert result.confidence in ("low", "medium", "high")


def test_estimate_from_listings_prefers_same_year_subset():
    listings = [
        Listing(title="A", price=40000, reg_year=2015),
        Listing(title="B", price=42000, reg_year=2015),
        Listing(title="C", price=60000, reg_year=2019),
        Listing(title="D", price=61000, reg_year=2019),
        Listing(title="E", price=62000, reg_year=2019),
    ]
    result = _estimate_from_listings(listings, target_year=2019, source="sgcarmart_scrape")
    assert result.estimated_value == 61000  # median of the three 2019 listings
    assert any("2019" in note for note in result.notes)


def test_estimate_from_listings_low_confidence_for_small_sample():
    listings = [Listing(title="A", price=45000, reg_year=2019)]
    result = _estimate_from_listings(listings, target_year=2019, source="sgcarmart_scrape")
    assert result.confidence == "low"
