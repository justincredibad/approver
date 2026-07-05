"""Streamlit GUI for the credit approver agent.

Run with: streamlit run credit_approver/app.py
"""
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
from credit_approver.scoring import assess_application
from credit_approver.valuation import Comparable, estimate_vehicle_value

st.set_page_config(page_title="Credit Approver", layout="wide")
st.title("Hire Purchase Credit Approver")
st.caption(
    "Prototype credit-scoring agent for vehicle hire-purchase loans. "
    "MyInfo and CBES data are mocked/user-entered — see README for details."
)

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

    use_live_scraping = st.checkbox(
        "Attempt live valuation scrape (sgcarmart, requires network + Selenium)", value=False
    )

    with st.expander("Manual comparable listings (optional, most accurate)"):
        st.caption(
            "For niche/low-volume models the live scrape may find nothing and the COE "
            "depreciation fallback is a rough approximation. If you've found real listings "
            "yourself (sgcarmart, carro, etc.), enter up to 3 here — each comparable's own "
            "COE expiry is used to adjust for the difference vs. this application's vehicle."
        )
        comp_rows = []
        for i in range(3):
            ccol1, ccol2 = st.columns(2)
            with ccol1:
                comp_price = st.number_input(
                    f"Comparable #{i + 1} price (SGD)", min_value=0.0, value=0.0, key=f"comp_price_{i}"
                )
            with ccol2:
                comp_coe = st.date_input(
                    f"Comparable #{i + 1} COE expiry", value=None, key=f"comp_coe_{i}"
                )
            comp_rows.append((comp_price, comp_coe))

    submitted = st.form_submit_button("Assess application")

if submitted:
    kyc_result = MockMyInfoClient().verify(nric)
    if not kyc_result.verified:
        st.warning(f"KYC check: {kyc_result.notes}")
    else:
        st.caption(f"KYC check: {kyc_result.notes}")

    comparables = [
        Comparable(price=price, coe_expiry=comp_coe)
        for price, comp_coe in comp_rows
        if price > 0 and comp_coe is not None
    ]

    valuation = estimate_vehicle_value(
        vehicle_make,
        vehicle_model,
        int(vehicle_year),
        purchase_price,
        coe_expiry=coe_expiry,
        use_live_scraping=use_live_scraping,
        comparables=comparables or None,
    )
    st.info(
        f"Vehicle valuation: SGD {valuation.estimated_value:,.2f} "
        f"(source: {valuation.source}, n={valuation.sample_size})"
        if valuation.sample_size
        else f"Vehicle valuation: SGD {valuation.estimated_value:,.2f} (source: {valuation.source})"
    )

    cbes = CbesRecord(
        on_time_payment_ratio=on_time_ratio,
        num_defaults=int(num_defaults),
        secured_outstanding_balance=secured_balance,
        secured_monthly_obligation=secured_monthly,
        unsecured_outstanding_balance=unsecured_balance,
        unsecured_monthly_obligation=unsecured_monthly or None,
    )
    applicant = Applicant(
        full_name=full_name,
        age=int(age),
        gender=gender,
        relationship_status=RelationshipStatus(relationship_status),
        employment_sector=EmploymentSector(employment_sector),
        annual_income=annual_income,
        has_acra_litigation=has_acra_litigation,
        cbes=cbes,
    )
    loan = VehicleLoanApplication(
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=int(vehicle_year),
        coe_expiry=coe_expiry,
        open_market_value=omv,
        purchase_price=purchase_price,
        vehicle_valuation=valuation.estimated_value,
        loan_amount=loan_amount,
        tenure_years=tenure_years,
        interest_rate_pa=interest_rate_pa,
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
