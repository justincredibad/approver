# Credit Approver

A prototype credit-scoring agent for bank hire-purchase (vehicle) loans.
The design spec this was built from is in [PROMPTS.md](PROMPTS.md).

Given an applicant's profile and a proposed loan, the agent:

1. Computes **DSR** (debt servicing ratio) and **LTV** (loan-to-value) against
   hard policy limits.
2. Estimates the vehicle's collateral value: a Playwright scrape of
   sgcarmart (with carro as a secondary source), reduced to an
   IQR-outlier-filtered median with a confidence label and +/-10% band. If
   the exact make/model has no listings, a popup asks for the vehicle's
   engine capacity (cc) and falls back to comparing against other
   vehicles of similar size and manufacture year instead. Deliberately
   does **not** derive a value from the purchase price the
   applicant/dealer entered — that would be circular for the LTV check
   this feeds. If no comparable listings are found through either path,
   the application cannot be assessed until one is available.
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
playwright install chromium  # required — valuation has no other data source
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
  confidence label (`high`/`medium`/`low`). If the exact make/model has no
  listings, the GUI pops up a dialog asking for the vehicle's engine
  capacity (cc) and falls back to `estimate_vehicle_value_by_engine_cc`,
  which compares against *other* vehicles of similar engine size and
  manufacture year — a rougher proxy, used only when a direct match
  fails. If neither path finds anything, the result is an explicit "no
  data" state (not a fabricated number) and the GUI blocks assessment
  until a valuation is available — this deliberately does not fall back
  to a formula based on the purchase price, since that would let an
  inflated purchase price flow straight through to an inflated
  "independent" valuation, defeating the point of the LTV check.

  The sgcarmart search-results URL/selectors are ported from a companion
  project ([vehicle-valuator](https://github.com/justincredibad/vehicle-valuator))
  whose `config.py` documents having verified them against a real
  rendered search — notably that sgcarmart is a Next.js app which only
  server-renders loading skeletons, so it requires a real browser
  (Playwright) rather than a plain HTTP GET. **That verification has not
  been independently re-confirmed from this codebase** — this development
  environment's network policy blocks both sgcarmart.com and carro.sg
  outright, so only the fails-gracefully path has been exercised here,
  not successful extraction. Re-verify periodically regardless: sgcarmart's
  CSS-module class names embed a build hash that changes on redeploy. The
  engine-cc detail-page selectors used by the cross-model fallback are
  considerably more speculative still — they've never been verified
  against real markup at all, unlike the search-results-page ones above.

  Requires `playwright install chromium` after `pip install` (see Setup
  above) — there's no formula fallback anymore, so a working scrape is
  required for any assessment to complete at all.

  **Does not work on Streamlit Community Cloud out of the box** — it has
  no Chrome/Chromium binary by default. This repo includes a
  `packages.txt` requesting the apt `chromium` package, which Streamlit
  Cloud installs automatically at build time; `valuation.py` looks for
  that system browser (via `shutil.which`) and uses it when Playwright's
  own bundled browser isn't present. This is an untested workaround —
  Streamlit Community Cloud's free tier is resource-constrained (shared
  ~1GB RAM), and a system-apt Chromium build isn't guaranteed to get along
  with whatever Playwright protocol version is installed. If it doesn't
  work in practice, run this locally or on a proper VPS/container
  platform instead (see `vehicle-valuator`'s own README for a Docker-based
  deployment example).

## Running the GUI online with scraping on your own PC

Streamlit Community Cloud's free tier has no browser (see above), so the
most reliable way to get live valuations into a hosted deployment is to
run the scraper on a machine that has real network access and Chrome —
your own PC — and have the hosted GUI call out to it over HTTP.

**1. On your PC**, run the scraper as a small local API:
```bash
pip install -e ".[server]"
playwright install chromium
python -m credit_approver.scraper_server
```
This starts a Flask server on `http://localhost:8800` with two endpoints:
`/valuation?make=...&model=...&year=...` and
`/valuation/by-cc?engine_cc=...&year=...`. Check it's alive:
`curl http://localhost:8800/health`.

**2. Expose it publicly with a tunnel**, e.g. [ngrok](https://ngrok.com):
```bash
ngrok http 8800
```
This prints a public HTTPS URL (e.g. `https://abcd1234.ngrok-free.app`).
Your PC and this tunnel need to be running whenever you want the hosted
app to produce a valuation — ngrok's free tier also gives a new random
URL each time you restart it, unless you pay for a static domain.

**3. Point the deployed app at that URL.** On Streamlit Community Cloud:
app settings → **Secrets** → add:
```toml
SCRAPER_API_URL = "https://abcd1234.ngrok-free.app"
```
(For a local run instead, `export SCRAPER_API_URL=...` works the same
way — `credit_approver/app.py` checks `st.secrets` first, then the
environment variable.) Once set, the deployed app calls your PC for
every valuation instead of trying (and failing) to scrape in-process.

**Security note**: this exposes your local scraper endpoint to anyone who
has the tunnel URL, with no authentication. Acceptable for a personal
prototype; not something to leave running unattended for a real
deployment without adding at least a shared-secret header check.

## Note on scoring factors

`relationship_status` is included as a scoring input because the original
spec calls for it, but marital-status-based credit decisions are
restricted or prohibited in some jurisdictions. It's weighted low (5/100
points) here; review with legal/compliance before using this in any real
lending decision.
