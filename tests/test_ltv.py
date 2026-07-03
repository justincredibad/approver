from datetime import date

from credit_approver.ltv import compute_ltv, ltv_threshold
from credit_approver.models import VehicleLoanApplication


def make_loan(loan_amount, purchase_price, valuation, omv):
    return VehicleLoanApplication(
        vehicle_make="Toyota",
        vehicle_model="Corolla",
        vehicle_year=2024,
        coe_expiry=date(2034, 1, 1),
        open_market_value=omv,
        purchase_price=purchase_price,
        vehicle_valuation=valuation,
        loan_amount=loan_amount,
        tenure_years=5,
        interest_rate_pa=0.03,
    )


def test_ltv_threshold_low_omv():
    assert ltv_threshold(15000) == 0.70


def test_ltv_threshold_high_omv():
    assert ltv_threshold(25000) == 0.60


def test_ltv_threshold_boundary_tightens_at_20000():
    assert ltv_threshold(20000) == 0.60


def test_compute_ltv_uses_lower_of_price_and_valuation():
    loan = make_loan(loan_amount=50000, purchase_price=100000, valuation=90000, omv=15000)
    assert compute_ltv(loan) == 50000 / 90000
