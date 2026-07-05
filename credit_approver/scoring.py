"""Creditworthiness scoring engine.

Produces a 1-100 score from: DSR headroom, LTV headroom, CBES payment
record, ACRA litigation history, employment sector, age, and relationship
status. DSR/LTV breaches are hard policy gates that force a rejection
regardless of the numeric score, since they are compliance limits rather
than soft risk signals.
"""
from __future__ import annotations

from dataclasses import replace

from .dsr import compute_dsr, dsr_threshold
from .ltv import compute_ltv, ltv_threshold
from .models import (
    Applicant,
    AssessmentResult,
    EmploymentSector,
    RelationshipStatus,
    ScoreBreakdown,
    VehicleLoanApplication,
)

WEIGHTS = {
    "dsr": 30,
    "ltv": 15,
    "cbes": 20,
    "acra": 15,
    "employment": 10,
    "age": 5,
    "relationship": 5,
}
assert sum(WEIGHTS.values()) == 100

# Coarse risk tiers by sector stability/income reliability.
EMPLOYMENT_RISK_MULTIPLIER = {
    EmploymentSector.GOVERNMENT: 1.0,
    EmploymentSector.HEALTHCARE: 1.0,
    EmploymentSector.EDUCATION: 1.0,
    EmploymentSector.FINANCE: 0.9,
    EmploymentSector.TECH: 0.9,
    EmploymentSector.PROFESSIONAL_SERVICES: 0.85,
    EmploymentSector.MANUFACTURING: 0.7,
    EmploymentSector.CONSTRUCTION: 0.6,
    EmploymentSector.RETAIL: 0.6,
    EmploymentSector.FOOD_AND_BEVERAGE: 0.55,
    EmploymentSector.GIG_ECONOMY: 0.4,
    EmploymentSector.OTHER: 0.5,
    EmploymentSector.UNEMPLOYED: 0.1,
}

# NOTE: relationship status is included because the source spec explicitly
# lists it as a scoring criterion, but marital-status-based credit scoring
# is restricted or prohibited in many jurisdictions (e.g. US ECOA). Kept as
# a low-weight (5 pt) factor here; review with legal/compliance before any
# real-world use.
RELATIONSHIP_MULTIPLIER = {
    RelationshipStatus.MARRIED: 1.0,
    RelationshipStatus.SINGLE: 0.9,
    RelationshipStatus.DIVORCED: 0.85,
    RelationshipStatus.WIDOWED: 0.85,
}


def _age_multiplier(age: int) -> float:
    if 25 <= age <= 55:
        return 1.0
    if (21 <= age < 25) or (55 < age <= 65):
        return 0.7
    return 0.3


def _linear_headroom_points(value: float, threshold: float, weight: float) -> float:
    """Full points at value=0, zero points at/above the policy threshold."""
    if threshold <= 0:
        return 0.0
    ratio = max(0.0, 1.0 - (value / threshold))
    return round(weight * ratio, 2)


def score_applicant(applicant: Applicant, loan: VehicleLoanApplication) -> ScoreBreakdown:
    reasons: list[str] = []

    dsr = compute_dsr(applicant, loan)
    dsr_limit = dsr_threshold(applicant.annual_income)
    dsr_points = _linear_headroom_points(dsr, dsr_limit, WEIGHTS["dsr"])
    dsr_breach = dsr > dsr_limit
    if dsr_breach:
        reasons.append(f"DSR {dsr:.1%} exceeds policy limit of {dsr_limit:.0%}")

    ltv = compute_ltv(loan)
    ltv_limit = ltv_threshold(loan.open_market_value)
    ltv_points = _linear_headroom_points(ltv, ltv_limit, WEIGHTS["ltv"])
    ltv_breach = ltv > ltv_limit
    if ltv_breach:
        reasons.append(f"LTV {ltv:.1%} exceeds policy limit of {ltv_limit:.0%}")

    cbes = applicant.cbes
    cbes_points = WEIGHTS["cbes"] * cbes.on_time_payment_ratio
    cbes_points -= min(cbes_points, cbes.num_defaults * 5)
    cbes_points = max(0.0, round(cbes_points, 2))
    if cbes.num_defaults > 0:
        reasons.append(f"{cbes.num_defaults} default(s) on credit bureau record")

    acra_points = 0.0 if applicant.has_acra_litigation else float(WEIGHTS["acra"])
    if applicant.has_acra_litigation:
        reasons.append("Active ACRA litigation on record")

    employment_points = WEIGHTS["employment"] * EMPLOYMENT_RISK_MULTIPLIER.get(
        applicant.employment_sector, 0.5
    )
    age_points = WEIGHTS["age"] * _age_multiplier(applicant.age)
    relationship_points = WEIGHTS["relationship"] * RELATIONSHIP_MULTIPLIER.get(
        applicant.relationship_status, 0.85
    )

    total = (
        dsr_points
        + ltv_points
        + cbes_points
        + acra_points
        + employment_points
        + age_points
        + relationship_points
    )
    total_score = max(0, min(100, round(total)))

    if dsr_breach or ltv_breach:
        decision = "REJECTED (policy limit exceeded)"
    elif total_score >= 80:
        decision = "AUTO-APPROVED"
    elif total_score >= 60:
        decision = "REFER FOR MANUAL REVIEW"
    else:
        decision = "REJECTED"

    return ScoreBreakdown(
        dsr=dsr,
        dsr_threshold=dsr_limit,
        dsr_points=dsr_points,
        ltv=ltv,
        ltv_threshold=ltv_limit,
        ltv_points=ltv_points,
        cbes_points=cbes_points,
        acra_points=acra_points,
        employment_points=round(employment_points, 2),
        age_points=round(age_points, 2),
        relationship_points=round(relationship_points, 2),
        total_score=total_score,
        decision=decision,
        reasons=reasons,
    )


def assess_application(applicant: Applicant, loan: VehicleLoanApplication) -> AssessmentResult:
    """Score the application, auto-capping the loan amount to the maximum
    the vehicle's valuation supports if the requested amount breaches LTV.

    A DSR breach still hard-rejects (that depends on the applicant's
    income, not the vehicle, so there's no analogous "adjust and retry").
    An LTV breach, however, just means the applicant asked to borrow more
    than this specific car supports — capping the request to the max
    allowed and reassessing is more useful than an outright rejection.
    """
    ltv = compute_ltv(loan)
    ltv_limit = ltv_threshold(loan.open_market_value)

    if ltv > ltv_limit:
        collateral_value = min(loan.purchase_price, loan.vehicle_valuation)
        max_loan_amount = round(collateral_value * ltv_limit, 2)
        message = (
            f"Requested loan amount of SGD {loan.loan_amount:,.2f} exceeds the maximum "
            f"loan-to-value limit ({ltv_limit:.0%}) supported by this vehicle's valuation. "
            f"Loan amount has been adjusted down to SGD {max_loan_amount:,.2f} and the "
            f"application reassessed."
        )
        adjusted_loan = replace(loan, loan_amount=max_loan_amount)
        return AssessmentResult(
            score=score_applicant(applicant, adjusted_loan),
            loan=adjusted_loan,
            ltv_adjusted=True,
            adjustment_message=message,
        )

    return AssessmentResult(
        score=score_applicant(applicant, loan),
        loan=loan,
        ltv_adjusted=False,
    )
