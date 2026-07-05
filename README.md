# Credit Approver

A prototype credit-scoring agent for bank hire-purchase (vehicle) loans.
The design spec this was built from is in [PROMPTS.md](PROMPTS.md).

Given an applicant's profile and a proposed loan, the agent:

1. Computes **DSR** (debt servicing ratio) and **LTV** (loan-to-value) against
   hard policy limits.
2. Estimates the vehicle's collateral value: a Playwright scrape of
   sgcarmart (with carro as a secondary source), reduced to an
   IQR-outlier-filtered median with a confidence label and +/-10% band,
   falling back to a COE-depreciation estimate off the purchase price if
   no listings are found.
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
playwright install chromium  # only needed for live valuation scraping
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
- **Vehicle valuation** (`credit_approver/valuation.py`): scrapes
  sgcarmart with Playwright (carro as a secondary source if sgcarmart
  returns nothing), then reduces the listings to a price estimate: Tukey
  IQR outlier filtering, median, a same-manufacture-year preference when
  enough listings share it, a +/-10% buffer band, and a sample-size-based
  confidence label (`high`/`medium`/`low`). Falls back to a
  COE-depreciation estimate off the purchase price if no listings are
  found at all.

  The sgcarmart URL/selectors are ported from a companion project
  ([vehicle-valuator](https://github.com/justincredibad/vehicle-valuator))
  whose `config.py` documents having verified them against a real
  rendered search — notably that sgcarmart is a Next.js app which only
  server-renders loading skeletons, so it requires a real browser
  (Playwright) rather than a plain HTTP GET. **That verification has not
  been independently re-confirmed from this codebase** — this development
  environment's network policy blocks both sgcarmart.com and carro.sg
  outright, so only the fails-gracefully path has been exercised here,
  not successful extraction. Re-verify periodically regardless: sgcarmart's
  CSS-module class names embed a build hash that changes on redeploy.

  Requires `playwright install chromium` after `pip install`. **Does not
  work on Streamlit Community Cloud** — it has no Chrome/Chromium binary
  at all, so live scraping will silently fall through to the
  COE-depreciation estimate there regardless of selector correctness; it
  only actually runs somewhere with a real browser available (your own
  machine, a VPS, etc).

## Note on scoring factors

`relationship_status` is included as a scoring input because the original
spec calls for it, but marital-status-based credit decisions are
restricted or prohibited in some jurisdictions. It's weighted low (5/100
points) here; review with legal/compliance before using this in any real
lending decision.
