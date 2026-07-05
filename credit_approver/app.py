"""Streamlit GUI for the credit approver agent.

Run with: streamlit run credit_approver/app.py
"""
from __future__ import annotations

import os
from datetime import date

import streamlit as st

from credit_approver.kyc import MockMyInfoClient
from credit_approver.models import (
    Applicant,
    CbesRecord,
    EmploymentSector,
    RelationshipStatus,
    VehicleLoanApplication,
)
from credit_approver.remote_scraper_client import (
    fetch_remote_valuation,
    fetch_remote_valuation_by_engine_cc,
)
from credit_approver.scoring import assess_application
from credit_approver.valuation import (
    ValuationResult,
    estimate_vehicle_value,
    estimate_vehicle_value_by_engine_cc,
)

st.set_page_config(page_title="Credit Approver", layout="wide")
st.title("Hire Purchase Credit Approver")
st.caption(
    "Prototype credit-scoring agent for vehicle hire-purchase loans. "
    "MyInfo and CBES data are mocked/user-entered — see README for details."
)


def _scraper_api_url() -> str | None:
    """A configured remote scraper (see credit_approver/scraper_server.py
    and README) takes priority over in-process scraping — this is how a
    Chrome-less host like Streamlit Community Cloud gets live valuations
    from a machine that actually has a browser."""
    try:
        url = st.secrets.get("SCRAPER_API_URL")
        if url:
            return url
    except Exception:
        pass
    return os.environ.get("SCRAPER_API_URL")


def _unreachable_remote_result(base_url: str) -> ValuationResult:
    return ValuationResult(
        estimated_value=None,
        source="no_data",
        notes=[
            f"Could not reach the remote scraper API at {base_url} — check that it's "
            "running locally and the tunnel exposing it is still up."
        ],
    )


def _get_valuation(make: str, model: str, year: int) -> ValuationResult:
    base_url = _scraper_api_url()
    if base_url:
        result = fetch_remote_valuation(base_url, make, model, year)
        return result if result is not None else _unreachable_remote_result(base_url)
    return estimate_vehicle_value(make, model, year, use_live_scraping=True)


def _get_valuation_by_engine_cc(engine_cc: float, year: int) -> ValuationResult:
    base_url = _scraper_api_url()
    if base_url:
        result = fetch_remote_valuation_by_engine_cc(base_url, engine_cc, year)
        return result if result is not None else _unreachable_remote_result(base_url)
    return estimate_vehicle_value_by_engine_cc(engine_cc, year)


@st.dialog("Add engine capacity")
def _prompt_for_engine_cc():
    st.write(
        "No comparable listings were found for this exact make/model/year. "
        "Enter the vehicle's engine capacity (cc) to estimate a value by "
        "comparing against similarly-sized vehicles instead."
    )
    cc = st.number_input("Engine capacity (cc)", min_value=600, max_value=8000, value=1600, step=50)
    if st.button("Search by engine capacity"):
        st.session_state["engine_cc"] = cc
        st.rerun()


def _render_valuation(valuation) -> None:
    msg = f"Vehicle valuation: SGD {valuation.estimated_value:,.2f} (source: {valuation.source}"
    if valuation.sample_size:
        msg += f", n={valuation.sample_size}"
    if valuation.confidence:
        msg += f", confidence={valuation.confidence}"
    msg += ")"
    st.info(msg)
    if valuation.low is not None and valuation.high is not None:
        st.caption(f"Range: SGD {valuation.low:,.2f} – {valuation.high:,.2f}")
    for note in valuation.notes:
        st.caption(note)


with st.form("applicant_form"):
    st.subheader("Applicant")
    col1, col2, col3 = st.columns(3)
    with col1:
        full_name = st.text_input("Full name")
        nric = st.text_input("NRIC/FIN (for MyInfo KYC, mock)")
        age = st.number_input("Age", min_value=18, max_value=100, value=35)
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    with col2:
        relationship_status = st.selectbox(
            "Relationship status", [s.value for s in RelationshipStatus]
        )
        employment_sector = st.selectbox(
            "Employment sector", [s.value for s in EmploymentSector]
        )
        annual_income = st.number_input(
            "Annual income (SGD)", min_value=0.0, value=60000.0, step=1000.0
        )
    with col3:
        has_acra_litigation = st.checkbox("Has ACRA litigation on record")
        on_time_ratio = st.slider("CBES on-time payment ratio", 0.0, 1.0, 0.95)
        num_defaults = st.number_input("CBES recorded defaults", min_value=0, value=0)

    st.subheader("Existing obligations (from CBES)")
    col4, col5 = st.columns(2)
    with col4:
        secured_balance = st.number_input(
            "Secured loans outstanding balance (SGD)", min_value=0.0, value=0.0
        )
        secured_monthly = st.number_input(
            "Secured loans monthly obligation (SGD)", min_value=0.0, value=0.0
        )
    with col5:
        unsecured_balance = st.number_input(
            "Unsecured loans outstanding balance (SGD)", min_value=0.0, value=0.0
        )
        unsecured_monthly = st.number_input(
            "Unsecured loans monthly obligation (SGD, 0 = auto-estimate at 3% of balance)",
            min_value=0.0,
            value=0.0,
        )

    st.subheader("Vehicle & loan")
    col6, col7, col8 = st.columns(3)
    with col6:
        vehicle_make = st.text_input("Make", value="Toyota")
        vehicle_model = st.text_input("Model", value="Corolla Altis")
        vehicle_year = st.number_input(
            "Year", min_value=1990, max_value=date.today().year, value=date.today().year
        )
    with col7:
        omv = st.number_input("Open Market Value / OMV (SGD)", min_value=0.0, value=18000.0)
        purchase_price = st.number_input("Purchase price (SGD)", min_value=0.0, value=90000.0)
        coe_expiry = st.date_input(
            "COE expiry date", value=date(date.today().year + 5, 1, 1)
        )
    with col8:
        loan_amount = st.number_input("Loan amount requested (SGD)", min_value=0.0, value=60000.0)
        tenure_years = st.number_input("Tenure (years)", min_value=1.0, max_value=10.0, value=7.0)
        interest_rate_pa = (
            st.number_input("Flat interest rate p.a. (%)", min_value=0.0, value=2.78) / 100
        )

    submitted = st.form_submit_button("Assess application")

if submitted:
    # Snapshot the form inputs into session_state: if the engine-capacity
    # dialog opens below, its own submit triggers a rerun that re-executes
    # this whole script from the top, and `submitted` would be False on
    # that rerun (the button wasn't clicked again). Everything needed to
    # resume the assessment has to survive that rerun some other way.
    st.session_state["pending"] = {
        "full_name": full_name,
        "nric": nric,
        "age": age,
        "gender": gender,
        "relationship_status": relationship_status,
        "employment_sector": employment_sector,
        "annual_income": annual_income,
        "has_acra_litigation": has_acra_litigation,
        "on_time_ratio": on_time_ratio,
        "num_defaults": num_defaults,
        "secured_balance": secured_balance,
        "secured_monthly": secured_monthly,
        "unsecured_balance": unsecured_balance,
        "unsecured_monthly": unsecured_monthly,
        "vehicle_make": vehicle_make,
        "vehicle_model": vehicle_model,
        "vehicle_year": vehicle_year,
        "omv": omv,
        "purchase_price": purchase_price,
        "coe_expiry": coe_expiry,
        "loan_amount": loan_amount,
        "tenure_years": tenure_years,
        "interest_rate_pa": interest_rate_pa,
    }
    st.session_state.pop("engine_cc", None)

pending = st.session_state.get("pending")
if pending:
    kyc_result = MockMyInfoClient().verify(pending["nric"])
    if not kyc_result.verified:
        st.warning(f"KYC check: {kyc_result.notes}")
    else:
        st.caption(f"KYC check: {kyc_result.notes}")

    with st.spinner("Looking up vehicle valuation — a live scrape can take up to a minute..."):
        valuation = _get_valuation(
            pending["vehicle_make"], pending["vehicle_model"], int(pending["vehicle_year"])
        )

    if valuation.estimated_value is None:
        if "engine_cc" not in st.session_state:
            _prompt_for_engine_cc()
            st.stop()
        with st.spinner(
            "Searching similar-engine-capacity vehicles — this cross-model search "
            "checks more listings individually and can take a few minutes..."
        ):
            valuation = _get_valuation_by_engine_cc(
                st.session_state["engine_cc"], int(pending["vehicle_year"])
            )
        if valuation.estimated_value is None:
            st.error("No vehicle valuation available — cannot assess this application.")
            for note in valuation.notes:
                st.caption(note)
            st.session_state.pop("pending", None)
            st.session_state.pop("engine_cc", None)
            st.stop()

    _render_valuation(valuation)

    cbes = CbesRecord(
        on_time_payment_ratio=pending["on_time_ratio"],
        num_defaults=int(pending["num_defaults"]),
        secured_outstanding_balance=pending["secured_balance"],
        secured_monthly_obligation=pending["secured_monthly"],
        unsecured_outstanding_balance=pending["unsecured_balance"],
        unsecured_monthly_obligation=pending["unsecured_monthly"] or None,
    )
    applicant = Applicant(
        full_name=pending["full_name"],
        age=int(pending["age"]),
        gender=pending["gender"],
        relationship_status=RelationshipStatus(pending["relationship_status"]),
        employment_sector=EmploymentSector(pending["employment_sector"]),
        annual_income=pending["annual_income"],
        has_acra_litigation=pending["has_acra_litigation"],
        cbes=cbes,
    )
    loan = VehicleLoanApplication(
        vehicle_make=pending["vehicle_make"],
        vehicle_model=pending["vehicle_model"],
        vehicle_year=int(pending["vehicle_year"]),
        coe_expiry=pending["coe_expiry"],
        open_market_value=pending["omv"],
        purchase_price=pending["purchase_price"],
        vehicle_valuation=valuation.estimated_value,
        loan_amount=pending["loan_amount"],
        tenure_years=pending["tenure_years"],
        interest_rate_pa=pending["interest_rate_pa"],
    )

    assessment = assess_application(applicant, loan)
    result = assessment.score

    if assessment.ltv_adjusted:
        st.warning(assessment.adjustment_message)

    st.subheader("Result")
    st.metric("Creditworthiness score", f"{result.total_score} / 100")
    if assessment.ltv_adjusted:
        st.caption(f"Loan amount assessed: SGD {assessment.loan.loan_amount:,.2f} (adjusted)")
    if result.decision == "AUTO-APPROVED":
        st.success(result.decision)
    elif result.decision == "REFER FOR MANUAL REVIEW":
        st.warning(result.decision)
    else:
        st.error(result.decision)

    st.write(f"**DSR:** {result.dsr:.1%} (limit {result.dsr_threshold:.0%})")
    st.write(f"**LTV:** {result.ltv:.1%} (limit {result.ltv_threshold:.0%})")

    st.table(
        {
            "Component": [
                "DSR",
                "LTV",
                "CBES record",
                "ACRA litigation",
                "Employment sector",
                "Age",
                "Relationship status",
            ],
            "Points": [
                result.dsr_points,
                result.ltv_points,
                result.cbes_points,
                result.acra_points,
                result.employment_points,
                result.age_points,
                result.relationship_points,
            ],
        }
    )

    if result.reasons:
        st.subheader("Flags")
        for reason in result.reasons:
            st.write(f"- {reason}")

    st.session_state.pop("pending", None)
    st.session_state.pop("engine_cc", None)
