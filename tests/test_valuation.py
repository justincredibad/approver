import asyncio
from unittest.mock import patch

from credit_approver.valuation import (
    Listing,
    _estimate_from_listings,
    _extract_engine_cc,
    _extract_plausible_prices,
    _iqr_filter,
    _run_in_thread,
    estimate_vehicle_value,
    estimate_vehicle_value_by_engine_cc,
)


def test_no_data_when_scraping_disabled():
    result = estimate_vehicle_value("Toyota", "Corolla", 2024, use_live_scraping=False)
    assert result.estimated_value is None
    assert result.source == "no_data"
    assert result.notes


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def test_run_in_thread_escapes_a_running_event_loop():
    # Reproduces the real-world failure: Streamlit's script-execution
    # thread can have a running asyncio loop, which Playwright's sync API
    # refuses to run inside. A plain function call from that context would
    # still see the loop; _run_in_thread must not.
    async def check_from_main_thread():
        return _has_running_loop(), _run_in_thread(_has_running_loop)

    direct_sees_loop, via_thread_sees_loop = asyncio.run(check_from_main_thread())
    assert direct_sees_loop is True
    assert via_thread_sees_loop is False


def test_run_in_thread_propagates_return_value():
    assert _run_in_thread(lambda a, b: a + b, 2, 3) == 5


def test_run_in_thread_propagates_exceptions():
    def boom():
        raise ValueError("expected failure")

    try:
        _run_in_thread(boom)
        assert False, "expected ValueError"
    except ValueError as e:
        assert str(e) == "expected failure"


def test_no_data_when_scraping_finds_nothing():
    with patch("credit_approver.valuation._search_sgcarmart", return_value=[]), patch(
        "credit_approver.valuation._scrape_carro_prices", return_value=[]
    ):
        result = estimate_vehicle_value("Lotus", "Elise", 2010, use_live_scraping=True)
    assert result.estimated_value is None
    assert result.source == "no_data"


def test_sgcarmart_listings_take_priority_over_carro():
    fake_listings = [
        Listing(title="A", price=45000, reg_year=2019),
        Listing(title="B", price=46000, reg_year=2019),
        Listing(title="C", price=47000, reg_year=2019),
    ]
    with patch("credit_approver.valuation._search_sgcarmart", return_value=fake_listings), patch(
        "credit_approver.valuation._scrape_carro_prices", return_value=[999999]
    ) as carro_mock:
        result = estimate_vehicle_value("Toyota", "Corolla", 2019, use_live_scraping=True)
    assert result.source == "sgcarmart_scrape"
    assert result.estimated_value == 46000
    carro_mock.assert_not_called()


def test_carro_used_when_sgcarmart_finds_nothing():
    with patch("credit_approver.valuation._search_sgcarmart", return_value=[]), patch(
        "credit_approver.valuation._scrape_carro_prices", return_value=[50000, 52000, 51000]
    ):
        result = estimate_vehicle_value("Toyota", "Corolla", 2019, use_live_scraping=True)
    assert result.source == "carro_scrape"
    assert result.estimated_value == 51000


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


def test_extract_engine_cc_finds_plausible_value():
    assert _extract_engine_cc("Engine Capacity: 1,798cc, Manual") == 1798.0


def test_extract_engine_cc_ignores_out_of_range():
    # 50cc reads like a moped spec sheet artifact, not a car engine
    assert _extract_engine_cc("Something 50cc unrelated") is None


def test_extract_engine_cc_handles_no_match():
    assert _extract_engine_cc("No engine spec here.") is None


def test_estimate_vehicle_value_by_engine_cc_no_data_when_nothing_found():
    with patch("credit_approver.valuation._search_sgcarmart_by_engine_cc", return_value=[]):
        result = estimate_vehicle_value_by_engine_cc(1800, 2010)
    assert result.estimated_value is None
    assert result.source == "no_data"


def test_estimate_vehicle_value_by_engine_cc_uses_similar_cc_listings():
    fake_listings = [
        Listing(title="Honda Civic", price=45000, reg_year=2011, engine_cc=1800),
        Listing(title="Toyota Corolla", price=47000, reg_year=2009, engine_cc=1800),
        Listing(title="Mazda 3", price=46000, reg_year=2010, engine_cc=1800),
    ]
    with patch(
        "credit_approver.valuation._search_sgcarmart_by_engine_cc", return_value=fake_listings
    ):
        result = estimate_vehicle_value_by_engine_cc(1800, 2010)
    assert result.source == "sgcarmart_engine_cc_scrape"
    assert result.estimated_value == 46000
    assert any("similar engine capacity" in note for note in result.notes)
