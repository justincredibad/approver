from unittest.mock import Mock, patch

from credit_approver.remote_scraper_client import (
    fetch_remote_valuation,
    fetch_remote_valuation_by_engine_cc,
)


def _fake_response(json_payload, status_ok=True):
    response = Mock()
    response.json.return_value = json_payload
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = Exception("HTTP error")
    return response


def test_fetch_remote_valuation_parses_successful_response():
    payload = {
        "estimated_value": 46000.0,
        "source": "sgcarmart_scrape",
        "sample_size": 5,
        "low": 41400.0,
        "high": 50600.0,
        "outliers_removed": 1,
        "confidence": "medium",
        "notes": ["some note"],
    }
    with patch("credit_approver.remote_scraper_client.requests.get", return_value=_fake_response(payload)):
        result = fetch_remote_valuation("http://localhost:8800", "Toyota", "Corolla", 2019)
    assert result is not None
    assert result.estimated_value == 46000.0
    assert result.source == "sgcarmart_scrape"
    assert result.confidence == "medium"
    assert result.notes == ["some note"]


def test_fetch_remote_valuation_returns_none_on_connection_error():
    with patch("credit_approver.remote_scraper_client.requests.get", side_effect=ConnectionError("down")):
        result = fetch_remote_valuation("http://localhost:8800", "Toyota", "Corolla", 2019)
    assert result is None


def test_fetch_remote_valuation_returns_none_on_http_error():
    with patch(
        "credit_approver.remote_scraper_client.requests.get",
        return_value=_fake_response({}, status_ok=False),
    ):
        result = fetch_remote_valuation("http://localhost:8800", "Toyota", "Corolla", 2019)
    assert result is None


def test_fetch_remote_valuation_by_engine_cc_parses_successful_response():
    payload = {
        "estimated_value": 46000.0,
        "source": "sgcarmart_engine_cc_scrape",
        "sample_size": 3,
        "low": None,
        "high": None,
        "outliers_removed": 0,
        "confidence": "",
        "notes": [],
    }
    with patch("credit_approver.remote_scraper_client.requests.get", return_value=_fake_response(payload)):
        result = fetch_remote_valuation_by_engine_cc("http://localhost:8800", 1800, 2010)
    assert result is not None
    assert result.estimated_value == 46000.0
    assert result.source == "sgcarmart_engine_cc_scrape"


def test_fetch_remote_valuation_by_engine_cc_returns_none_on_timeout():
    with patch("credit_approver.remote_scraper_client.requests.get", side_effect=TimeoutError("slow")):
        result = fetch_remote_valuation_by_engine_cc("http://localhost:8800", 1800, 2010)
    assert result is None
