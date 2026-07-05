from datetime import date

from credit_approver.models import (
    Applicant,
    CbesRecord,
    EmploymentSector,
    RelationshipStatus,
    VehicleLoanApplication,
)
from credit_approver.ltv import compute_ltv, ltv_threshold
from credit_approver.scoring import assess_application, score_applicant


def strong_applicant():
    cbes = CbesRecord(on_time_payment_ratio=1.0, num_defaults=0)
    return Applicant(
        full_name="Strong Applicant",
        age=35,
        gender="F",
        relationship_status=RelationshipStatus.MARRIED,
        employment_sector=EmploymentSector.GOVERNMENT,
        annual_income=90000,
        has_acra_litigation=False,
        cbes=cbes,
    )


def modest_loan():
    return VehicleLoanApplication(
        vehicle_make="Toyota",
        vehicle_model="Corolla",
        vehicle_year=2024,
        coe_expiry=date(2034, 1, 1),
        open_market_value=18000,
        purchase_price=40000,
        vehicle_valuation=40000,
        loan_amount=10000,
        tenure_years=5,
        interest_rate_pa=0.025,
    )


def test_strong_applicant_auto_approved():
    result = score_applicant(strong_applicant(), modest_loan())
    assert result.total_score >= 80
    assert result.decision == "AUTO-APPROVED"


def test_dsr_breach_forces_rejection_regardless_of_score():
    applicant = strong_applicant()
    loan = modest_loan()
    loan.loan_amount = 500000  # blows past the DSR limit
    result = score_applicant(applicant, loan)
    assert result.decision.startswith("REJECTED")


def test_ltv_breach_forces_rejection():
    applicant = strong_applicant()
    loan = modest_loan()
    loan.loan_amount = 35000  # 87.5% LTV, above the 70% limit for low OMV
    result = score_applicant(applicant, loan)
    assert "REJECTED" in result.decision


def test_acra_litigation_reduces_score():
    clean = score_applicant(strong_applicant(), modest_loan())
    applicant = strong_applicant()
    applicant.has_acra_litigation = True
    dirty = score_applicant(applicant, modest_loan())
    assert dirty.total_score < clean.total_score


def test_score_bounded_between_0_and_100():
    applicant = strong_applicant()
    applicant.age = 90
    applicant.has_acra_litigation = True
    applicant.cbes = CbesRecord(on_time_payment_ratio=0.0, num_defaults=10)
    result = score_applicant(applicant, modest_loan())
    assert 0 <= result.total_score <= 100


def test_assess_application_caps_loan_on_ltv_breach_instead_of_rejecting():
    applicant = strong_applicant()
    loan = modest_loan()
    loan.loan_amount = 35000  # 87.5% LTV, above the 70% limit for low OMV
    assessment = assess_application(applicant, loan)

    assert assessment.ltv_adjusted is True
    assert "35,000.00" in assessment.adjustment_message
    assert assessment.loan.loan_amount < loan.loan_amount
    assert assessment.score.decision != "REJECTED (policy limit exceeded)"

    # The adjusted loan should sit right at (not over) the LTV limit.
    adjusted_ltv = compute_ltv(assessment.loan)
    limit = ltv_threshold(assessment.loan.open_market_value)
    assert adjusted_ltv <= limit + 1e-9


def test_assess_application_leaves_compliant_loan_unchanged():
    applicant = strong_applicant()
    loan = modest_loan()
    assessment = assess_application(applicant, loan)

    assert assessment.ltv_adjusted is False
    assert assessment.loan.loan_amount == loan.loan_amount
    assert assessment.score.total_score == score_applicant(applicant, loan).total_score


def test_assess_application_still_rejects_on_dsr_breach():
    applicant = strong_applicant()  # annual_income=90000 -> DSR limit 80%
    # High-value vehicle so a big loan still sits well within the LTV limit,
    # isolating a DSR breach that auto-adjustment can't fix by capping LTV.
    loan = VehicleLoanApplication(
        vehicle_make="Toyota",
        vehicle_model="Alphard",
        vehicle_year=2024,
        coe_expiry=date(2034, 1, 1),
        open_market_value=100000,
        purchase_price=1000000,
        vehicle_valuation=1000000,
        loan_amount=400000,  # LTV 40%, well under the 60% limit
        tenure_years=5,
        interest_rate_pa=0.025,
    )
    assert compute_ltv(loan) <= ltv_threshold(loan.open_market_value)  # sanity: not an LTV breach

    assessment = assess_application(applicant, loan)

    # DSR depends on income, not the vehicle, so there's no loan-amount fix for it.
    assert assessment.ltv_adjusted is False
    assert assessment.score.decision == "REJECTED (policy limit exceeded)"
