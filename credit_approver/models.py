"""Data model for applicants, loan applications, and scoring results."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class EmploymentSector(str, Enum):
    GOVERNMENT = "government"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    FINANCE = "finance"
    TECH = "tech"
    PROFESSIONAL_SERVICES = "professional_services"
    MANUFACTURING = "manufacturing"
    CONSTRUCTION = "construction"
    RETAIL = "retail"
    FOOD_AND_BEVERAGE = "food_and_beverage"
    GIG_ECONOMY = "gig_economy"
    UNEMPLOYED = "unemployed"
    OTHER = "other"


class RelationshipStatus(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


@dataclass
class CbesRecord:
    """Credit-bureau-style record (payment punctuality and outstanding balances)."""

    on_time_payment_ratio: float  # 0.0-1.0 over the lookback period
    num_defaults: int = 0
    secured_outstanding_balance: float = 0.0
    secured_monthly_obligation: float = 0.0
    unsecured_outstanding_balance: float = 0.0
    unsecured_monthly_obligation: Optional[float] = None  # estimated from balance if omitted

    def estimated_unsecured_monthly_obligation(self, min_payment_rate: float = 0.03) -> float:
        if self.unsecured_monthly_obligation is not None:
            return self.unsecured_monthly_obligation
        return self.unsecured_outstanding_balance * min_payment_rate

    @property
    def existing_monthly_obligations(self) -> float:
        return self.secured_monthly_obligation + self.estimated_unsecured_monthly_obligation()


@dataclass
class Applicant:
    full_name: str
    age: int
    gender: str
    relationship_status: RelationshipStatus
    employment_sector: EmploymentSector
    annual_income: float
    has_acra_litigation: bool
    cbes: CbesRecord


@dataclass
class VehicleLoanApplication:
    vehicle_make: str
    vehicle_model: str
    vehicle_year: int
    coe_expiry: Optional[date]
    open_market_value: float  # OMV, in SGD
    purchase_price: float
    vehicle_valuation: float  # independent/estimated valuation, in SGD
    loan_amount: float
    tenure_years: float
    interest_rate_pa: float  # flat rate p.a., e.g. 0.025 for 2.5%

    @property
    def monthly_installment(self) -> float:
        total_interest = self.loan_amount * self.interest_rate_pa * self.tenure_years
        return (self.loan_amount + total_interest) / (self.tenure_years * 12)


@dataclass
class ScoreBreakdown:
    dsr: float
    dsr_threshold: float
    dsr_points: float
    ltv: float
    ltv_threshold: float
    ltv_points: float
    cbes_points: float
    acra_points: float
    employment_points: float
    age_points: float
    relationship_points: float
    total_score: int
    decision: str
    reasons: list[str] = field(default_factory=list)
