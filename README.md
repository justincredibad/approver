# Credit Approver

A prototype credit-scoring agent for bank hire-purchase (vehicle) loans.
The design spec this was built from is in [PROMPTS.md](PROMPTS.md).

Given an applicant's profile and a proposed loan, the agent:

1. Computes **DSR** (debt servicing ratio) and **LTV** (loan-to-value) against
   hard policy limits.
2. Estimates the vehicle's collateral value (Selenium scrape of sgcarmart
   listings, with a COE-depreciation fallback when scraping isn't
   available).
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
- **Vehicle valuation** (`credit_approver/valuation.py`): attempts a
  Selenium scrape of sgcarmart listings for comparable prices; falls back
  to a COE-depreciation estimate if scraping is disabled, unreachable, or
  the site structure has changed. Selectors are best-effort and may need
  updating.

## Note on scoring factors

`relationship_status` is included as a scoring input because the original
spec calls for it, but marital-status-based credit decisions are
restricted or prohibited in some jurisdictions. It's weighted low (5/100
points) here; review with legal/compliance before using this in any real
lending decision.
