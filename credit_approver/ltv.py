"""Loan-to-Value (LTV) policy rule and calculation."""
from __future__ import annotations

from .models import VehicleLoanApplication


def ltv_threshold(open_market_value: float) -> float:
    """LTV ceiling: 70% when OMV < $20,000, tightened to 60% for pricier vehicles."""
    return 0.70 if open_market_value < 20000 else 0.60


def compute_ltv(loan: VehicleLoanApplication) -> float:
    """LTV = loan amount / min(purchase price, vehicle valuation)."""
    collateral_value = min(loan.purchase_price, loan.vehicle_valuation)
    if collateral_value <= 0:
        return float("inf")
    return loan.loan_amount / collateral_value
