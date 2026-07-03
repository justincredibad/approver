"""Debt Servicing Ratio (DSR) policy rule and calculation."""
from __future__ import annotations

from .models import Applicant, VehicleLoanApplication


def dsr_threshold(annual_income: float) -> float:
    """DSR ceiling per bank policy: 60%, relaxed to 80% for higher earners."""
    return 0.80 if annual_income > 72000 else 0.60


def compute_dsr(applicant: Applicant, loan: VehicleLoanApplication) -> float:
    """DSR = (existing monthly debt obligations + new loan installment) / monthly income."""
    monthly_income = applicant.annual_income / 12
    if monthly_income <= 0:
        return float("inf")
    existing = applicant.cbes.existing_monthly_obligations
    new_installment = loan.monthly_installment
    return (existing + new_installment) / monthly_income
