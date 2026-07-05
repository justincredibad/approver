from datetime import date

from credit_approver.dsr import compute_dsr, dsr_threshold
from credit_approver.models import (
    Applicant,
    CbesRecord,
    EmploymentSector,
    RelationshipStatus,
    VehicleLoanApplication,
)


def make_applicant(annual_income=60000, **cbes_kwargs):
    cbes = CbesRecord(on_time_payment_ratio=1.0, **cbes_kwargs)
    return Applicant(
        full_name="Test",
        age=30,
        gender="M",
        relationship_status=RelationshipStatus.SINGLE,
        employment_sector=EmploymentSector.TECH,
        annual_income=annual_income,
        has_acra_litigation=False,
        cbes=cbes,
    )


def make_loan(loan_amount=20000, tenure_years=5, interest_rate_pa=0.03):
    return VehicleLoanApplication(
        vehicle_make="Toyota",
        vehicle_model="Corolla",
        vehicle_year=2024,
        coe_expiry=date(2034, 1, 1),
        open_market_value=18000,
        purchase_price=90000,
        vehicle_valuation=90000,
        loan_amount=loan_amount,
        tenure_years=tenure_years,
        interest_rate_pa=interest_rate_pa,
    )


def test_dsr_threshold_standard():
    assert dsr_threshold(60000) == 0.60


def test_dsr_threshold_high_income():
    assert dsr_threshold(80000) == 0.80


def test_dsr_threshold_boundary_not_relaxed():
    assert dsr_threshold(72000) == 0.60


def test_compute_dsr_basic():
    applicant = make_applicant(annual_income=60000)
    loan = make_loan(loan_amount=20000, tenure_years=5, interest_rate_pa=0.03)
    dsr = compute_dsr(applicant, loan)
    monthly_income = 5000
    expected_installment = (20000 + 20000 * 0.03 * 5) / 60
    assert abs(dsr - expected_installment / monthly_income) < 1e-9


def test_compute_dsr_includes_existing_obligations():
    applicant = make_applicant(annual_income=60000, secured_monthly_obligation=500)
    loan = make_loan(loan_amount=0, tenure_years=5, interest_rate_pa=0.0)
    dsr = compute_dsr(applicant, loan)
    assert abs(dsr - 500 / 5000) < 1e-9


def test_compute_dsr_estimates_unsecured_obligation_from_balance():
    applicant = make_applicant(annual_income=60000, unsecured_outstanding_balance=10000)
    loan = make_loan(loan_amount=0, tenure_years=5, interest_rate_pa=0.0)
    dsr = compute_dsr(applicant, loan)
    assert abs(dsr - (10000 * 0.03) / 5000) < 1e-9
