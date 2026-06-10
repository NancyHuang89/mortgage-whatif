"""Mortgage what-if explorer — a Streamlit app.

Run locally:   streamlit run app.py
On iPhone:     open the deployed URL in Safari -> Share -> Add to Home Screen.

You describe your loan as it is *today* (current balance, rate, remaining
term), then build a few scenarios — extra monthly payments, one-off lump sums,
and optional recast — and compare them side by side.

Layout note: everything lives in the main page (no sidebar) so the inputs stay
visible on a phone, and numeric inputs use number fields (not an editable
table) so the iPhone keyboard appears reliably.
"""

import calendar

import altair as alt
import pandas as pd
import streamlit as st

from mortgage import Loan, Scenario, LumpSum, amortize, add_months

st.set_page_config(page_title="Mortgage What-If", page_icon="🏠", layout="centered")

MONTHS = list(calendar.month_name)[1:]  # ["January", ..., "December"]
MAX_LUMPS = 4


def money(x: float) -> str:
    return f"${x:,.0f}"


st.title("🏠 Mortgage What-If Explorer")

# --------------------------------------------------------------------------- #
# Your loan today (main page, always visible)
# --------------------------------------------------------------------------- #
with st.expander("⚙️  Your loan today", expanded=True):
    st.caption("Enter the loan as it stands right now — not as a brand-new loan.")

    c1, c2 = st.columns(2)
    balance = c1.number_input("Current balance ($)", min_value=0.0,
                              value=400_000.0, step=1_000.0)
    rate_pct = c2.number_input("Interest rate (% / year)", min_value=0.0,
                               max_value=30.0, value=6.0, step=0.125, format="%.3f")

    c3, c4 = st.columns(2)
    years = c3.number_input("Years remaining", min_value=0, max_value=40, value=25, step=1)
    extra_term_months = c4.number_input("+ Months", min_value=0, max_value=11, value=0, step=1)
    remaining_months = int(years) * 12 + int(extra_term_months)

    c5, c6 = st.columns(2)
    start_month = c5.selectbox("Next payment month", range(1, 13),
                               index=5, format_func=lambda m: MONTHS[m - 1])
    start_year = c6.number_input("Year", min_value=2000, max_value=2100, value=2026, step=1)

    auto_payment = st.checkbox("Compute my payment automatically", value=True,
                               help="Off = type in your actual statement payment.")

    loan = Loan(
        balance=balance,
        annual_rate=rate_pct / 100.0,
        remaining_months=remaining_months,
        start_year=int(start_year),
        start_month=int(start_month),
    )

    std_pmt = loan.standard_payment() if remaining_months > 0 else 0.0
    if auto_payment:
        payment_override = None
        st.metric("Monthly payment (P&I)", money(std_pmt))
    else:
        payment_override = st.number_input("Your monthly payment (P&I, $)",
                                           min_value=0.0, value=float(round(std_pmt, 2)), step=10.0)

if remaining_months <= 0:
    st.warning("Set 'Years remaining' (or months) greater than zero to begin.")
    st.stop()

# --------------------------------------------------------------------------- #
# Scenario builder
# --------------------------------------------------------------------------- #
st.write(
    "Compare how extra monthly payments and one-time lump sums change your "
    "payoff date and total interest. The first scenario is your baseline."
)

n_scenarios = st.slider("How many scenarios to compare?", 1, 4, 2)

default_names = ["Baseline", "Extra monthly", "Lump sum", "Both"]
scenarios: list[Scenario] = []

tabs = st.tabs([f"Scenario {i + 1}" for i in range(n_scenarios)])
for i, tab in enumerate(tabs):
    with tab:
        name = st.text_input("Name", value=default_names[i], key=f"name_{i}")
        extra = st.number_input(
            "Extra principal each month ($)", min_value=0.0, value=0.0, step=50.0,
            key=f"extra_{i}",
            help="Added to principal every month on top of your regular payment.",
        )

        recast = st.checkbox(
            "Recast after lump sums", value=False, key=f"recast_{i}",
            help="On: a lump sum lowers your monthly payment but keeps the same "
                 "payoff date (re-amortized over the remaining term). "
                 "Off: payment stays the same and the loan finishes earlier.",
        )

        n_lumps = st.number_input("How many lump-sum payments?", min_value=0,
                                  max_value=MAX_LUMPS, value=0, step=1, key=f"nlumps_{i}")

        lump_sums: list[LumpSum] = []
        for j in range(int(n_lumps)):
            st.markdown(f"**Lump sum {j + 1}**")
            lc1, lc2, lc3 = st.columns(3)
            ly = lc1.number_input("Year", min_value=loan.start_year,
                                  max_value=loan.start_year + 40, value=loan.start_year,
                                  step=1, key=f"ly_{i}_{j}")
            lm = lc2.selectbox("Month", range(1, 13), index=loan.start_month - 1,
                               format_func=lambda m: MONTHS[m - 1], key=f"lm_{i}_{j}")
            la = lc3.number_input("Amount ($)", min_value=0.0, value=10_000.0,
                                  step=500.0, key=f"la_{i}_{j}")

            month_index = (int(ly) - loan.start_year) * 12 + (int(lm) - loan.start_month)
            if month_index < 0:
                st.warning(f"Lump sum {j + 1} is dated before your start date — ignored.")
            elif la > 0:
                lump_sums.append(LumpSum(month_index=month_index, amount=float(la)))

        scenarios.append(Scenario(name=name or f"Scenario {i + 1}", extra_monthly=extra,
                                  lump_sums=lump_sums, recast_on_lump=recast))

# Run every scenario through the engine.
schedules = [amortize(loan, sc, payment_override=payment_override) for sc in scenarios]
baseline = schedules[0]

if any(s.negative_amortization for s in schedules):
    st.warning("⚠️ For at least one scenario the payment doesn't fully cover the monthly "
               "interest, so that part of the balance isn't shrinking. Check your inputs.")

# --------------------------------------------------------------------------- #
# Results: summary comparison
# --------------------------------------------------------------------------- #
st.header("Comparison")

summary_rows = []
for sc, sch in zip(scenarios, schedules):
    if sch.paid_off:
        payoff = f"{MONTHS[sch.payoff_month - 1][:3]} {sch.payoff_year}"
        yrs, mos = divmod(sch.months_to_payoff, 12)
        length = f"{yrs}y {mos}m"
    else:
        payoff, length = "not within 100y", "—"
    summary_rows.append({
        "Scenario": sc.name,
        "Payoff date": payoff,
        "Time to payoff": length,
        "Total interest": sch.total_interest,
        "Interest saved": baseline.total_interest - sch.total_interest,
        "Months saved": baseline.months_to_payoff - sch.months_to_payoff,
    })

summary = pd.DataFrame(summary_rows)
st.dataframe(
    summary,
    hide_index=True,
    width="stretch",
    column_config={
        "Total interest": st.column_config.NumberColumn(format="$%,d"),
        "Interest saved": st.column_config.NumberColumn(format="$%,d"),
    },
)

# --------------------------------------------------------------------------- #
# Results: balance-over-time chart
# --------------------------------------------------------------------------- #
st.subheader("Balance over time")

chart_data = []
for sc, sch in zip(scenarios, schedules):
    for row in sch.rows:
        chart_data.append({
            "date": pd.Timestamp(year=row.year, month=row.month, day=1),
            "Balance": row.end_balance,
            "Scenario": sc.name,
        })
chart_df = pd.DataFrame(chart_data)

line = (
    alt.Chart(chart_df)
    .mark_line()
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("Balance:Q", title="Remaining balance", axis=alt.Axis(format="$,.0f")),
        color=alt.Color("Scenario:N", title="Scenario"),
        tooltip=[alt.Tooltip("date:T", title="Date"),
                 alt.Tooltip("Balance:Q", format="$,.0f"),
                 "Scenario:N"],
    )
    .properties(height=360)
    .interactive()
)
st.altair_chart(line, width="stretch")

# --------------------------------------------------------------------------- #
# Results: balance at a chosen point in time
# --------------------------------------------------------------------------- #
st.subheader("Balance at a specific time")
st.caption("Pick any year and month to see where each scenario stands then.")

c7, c8 = st.columns(2)
look_month = c7.selectbox("Month", range(1, 13), index=loan.start_month - 1,
                          format_func=lambda m: MONTHS[m - 1], key="look_month")
default_year = add_months(loan.start_year, loan.start_month, 60)[0]  # ~5 years out
look_year = c8.number_input("Year", min_value=loan.start_year, max_value=loan.start_year + 100,
                            value=default_year, step=1, key="look_year")

target_index = (int(look_year) - loan.start_year) * 12 + (int(look_month) - loan.start_month)
point_rows = [{
    "Scenario": sc.name,
    "Balance then": (0.0 if sch.paid_off and target_index >= sch.months_to_payoff
                     else sch.balance_at(target_index)),
    "Status": ("paid off" if sch.paid_off and target_index >= sch.months_to_payoff else "active"),
} for sc, sch in zip(scenarios, schedules)]
st.dataframe(
    pd.DataFrame(point_rows),
    hide_index=True,
    width="stretch",
    column_config={"Balance then": st.column_config.NumberColumn(format="$%,d")},
)

# --------------------------------------------------------------------------- #
# Optional: full amortization table for one scenario
# --------------------------------------------------------------------------- #
with st.expander("See the full month-by-month schedule"):
    pick = st.selectbox("Scenario", [sc.name for sc in scenarios], key="pick_schedule")
    sch = schedules[[sc.name for sc in scenarios].index(pick)]
    table = pd.DataFrame([{
        "Date": f"{MONTHS[r.month - 1][:3]} {r.year}",
        "Start balance": r.start_balance,
        "Interest": r.interest,
        "Principal": r.principal,
        "Extra": r.extra,
        "Lump sum": r.lump,
        "Total paid": r.payment,
        "End balance": r.end_balance,
    } for r in sch.rows])
    st.dataframe(
        table, hide_index=True, width="stretch",
        column_config={c: st.column_config.NumberColumn(format="$%,.0f")
                       for c in table.columns if c != "Date"},
    )
