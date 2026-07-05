# Credit Approver

A prototype credit-scoring agent for bank hire-purchase (vehicle) loans.
The design spec this was built from is in [PROMPTS.md](PROMPTS.md).

Given an applicant's profile and a proposed loan, the agent:

1. Computes **DSR** (debt servicing ratio) and **LTV** (loan-to-value) against
   hard policy limits.
2. Estimates the vehicle's collateral value: manually-entered comparable
   listings (most accurate) take priority, then a best-effort Selenium
   scrape of sgcarmart/carro, falling back to a COE-depreciation estimate
   off the purchase price if neither is available.
3. Produces a **1-100 creditworthiness score** from DSR/LTV headroom, CBES
   credit bureau record, ACRA litigation history, employment sector, age,
   and relationship status.
4. Returns a decision: `AUTO-APPROVED` (score ≥ 80, no policy breach),
   `REFER FOR MANUAL REVIEW` (score 60-79), or `REJECTED` (score < 60, or a
   DSR/LTV policy breach — which forces rejection regardless of score).

## Policy rules

- **DSR** must be ≤ 60%, relaxed to ≤ 80% when annual income exceeds
  $72,000.
- **LTV** (loan amount / lower of purchase price or valuation) must be
  ≤ 70% when the vehicle's Open Market Value (OMV) is below $20,000, or
  ≤ 60% when OMV is $20,000 or above.

See `credit_approver/dsr.py`, `credit_approver/ltv.py`, and
`credit_approver/scoring.py` for the implementation and weighting.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the GUI

```bash
streamlit run credit_approver/app.py
```

Fill in the applicant, CBES, and vehicle/loan fields and submit to get the
score, decision, and a per-factor points breakdown.

## Run the tests

```bash
pytest
```

## What's mocked / stubbed

This is a prototype and does **not** connect to real government or bureau
systems:

- **MyInfo / CPF KYC** (`credit_approver/kyc.py`): real integration
  requires a registered SingPass/MyInfo application, client certificates,
  and government onboarding that can't be provisioned here.
  `MockMyInfoClient` stands in behind the same `MyInfoClient` interface a
  real client would implement.
- **CBES credit bureau records**: entered manually in the GUI (on-time
  payment ratio, defaults, secured/unsecured balances) rather than pulled
  from a live bureau feed.
- **Vehicle valuation** (`credit_approver/valuation.py`): prioritizes
  manually-entered comparable listings (with a COE-remaining adjustment —
  see `estimate_from_comparables`), then attempts a Selenium scrape of
  sgcarmart and carro for comparable prices, falling back to a
  COE-depreciation estimate off the purchase price if neither is
  available. **The live scrape has not been verified against real
  markup** — this was developed in a sandboxed environment whose network
  policy blocks both sgcarmart.com and carro.sg outright, so only the
  fails-gracefully path has been exercised. Test it against the real
  sites (from an environment with normal network access) before relying
  on it; the manual-comparables input is the reliable path in the
  meantime, especially for low-volume/enthusiast models where live
  listings are sparse anyway.

## Note on scoring factors

`relationship_status` is included as a scoring input because the original
spec calls for it, but marital-status-based credit decisions are
restricted or prohibited in some jurisdictions. It's weighted low (5/100
points) here; review with legal/compliance before using this in any real
lending decision.
