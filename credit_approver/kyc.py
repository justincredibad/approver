"""MyInfo / CPF-style KYC and employment verification.

Real MyInfo integration requires a registered SingPass/MyInfo application,
client certificates, and a government-approved sandbox/production
onboarding process that can't be provisioned in this environment. This
module defines the interface the scoring app expects and ships a mock
implementation so the rest of the pipeline can be developed and tested
end-to-end. Swap in a real client (implementing the same `MyInfoClient`
protocol) once MyInfo credentials are available.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class MyInfoVerification:
    verified: bool
    full_name: Optional[str] = None
    employer: Optional[str] = None
    latest_cpf_contribution: Optional[float] = None
    notes: str = ""


class MyInfoClient(Protocol):
    def verify(self, nric_or_fin: str) -> MyInfoVerification: ...


class MockMyInfoClient:
    """Deterministic stand-in for the MyInfo Person API, for local dev/testing."""

    def verify(self, nric_or_fin: str) -> MyInfoVerification:
        if not nric_or_fin or len(nric_or_fin) < 9:
            return MyInfoVerification(verified=False, notes="Invalid NRIC/FIN format")
        return MyInfoVerification(
            verified=True,
            employer="(mock) not connected to real MyInfo API",
            notes="Mock verification only — configure a real MyInfoClient for production use.",
        )
