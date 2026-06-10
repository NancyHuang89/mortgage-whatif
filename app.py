"""Mortgage what-if explorer — a Streamlit app.

Run locally:   streamlit run app.py
On iPhone:     open the deployed URL in Safari -> Share -> Add to Home Screen.

You describe your loan as it is *today* (current balance, rate, remaining
term), then build a few scenarios — extra monthly payments and one-off lump
sums — and compare them side by side.
"""

import calendar

import altair as alt
import pandas as pd
import streamlit as st

from mortgage import Loan, Scenario, LumpSum, amortize, add_months

st.set_page_config(page_title="Mortgage What-If", page_icon="🏠", layout="wide")

MONTHS = list(calendar.month_name)[1:]  # ["January", ..., "December"]


def money(x: float) -> str:
    return f"${x:,.0f}"


# --------------------------------------------------------------------------- #
# Sidebar: your loan today
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Your loan today")
    st.caption("Enter the loan as it stands right now — not as a brand-new loan.")

    balance = st.number_input(
        "Current balance ($)", min_value=0.0, value=400_000.0, step=1_000.0,
        help="The principal you still owe today.",
    )
    rate_pct = st.number_input(
        "Interest rate (% per year)", min_value=0.0, max_value=30.0,
        value=6.0, step=0.125, format="%.3f",
    )

    st.markdown("**Remaining term**")
    c1, c2 = st.columns(2)
    years = c1.number_input("Years", min_value=0, max_value=40, value=25, step=1)
    extra_term_months = c2.number_input("+ Months", min_value=0, max_value=11, value=0, step=1)
    remaining_months = int(years) * 12 + int(extra_term_months)

    st.markdown("**Next payment date**")
    c3, c4 = st.columns(2)
    start_month = c3.selectbox("Month", range(1, 13),
                               index=5, format_func=lambda m: MONTHS[m - 1])
    start_year = c4.number_input("Year", min_value=2000, max_value=2100, value=2026, step=1)

    st.divider()
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
        payment_override = st.number_input(
            "Your monthly payment (P&I, $)", min_value=0.0,
            value=float(round(std_pmt, 2)), step=10.0,
        )


# --------------------------------------------------------------------------- #
# Main: scenario builder
# --------------------------------------------------------------------------- #
st.title("🏠 Mortgage What-If Explorer")
st.write(
    "Compare how extra monthly payments and one-time lump sums change your "
    "payoff date and total interest. The first scenario is your baseline."
)

if remaining_months <= 0:
    st.warning("Set a remaining term greater than zero in the sidebar to begin.")
    st.stop()

n_scenarios = st.slider("How many scenarios to compare?", 1, 4, 2)

# Build a config UI for each scenario inside tabs.
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

        st.caption("One-time lump-sum principal payments (leave empty for none):")
        lump_df = st.data_editor(
            pd.DataFrame({"Year": pd.Series(dtype="Int64"),
                          "Month": pd.Series(dtype="Int64"),
                          "Amount ($)": pd.Series(dtype="float")}),
            num_rows="dynamic",
            key=f"lumps_{i}",
            hide_index=True,
            column_config={
                "Year": st.column_config.NumberColumn(min_value=2000, max_value=2100, step=1),
                "Month": st.column_config.NumberColumn(min_value=1, max_value=12, step=1),
                "Amount ($)": st.column_config.NumberColumn(min_value=0.0, step=500.0, format="$%d"),
            },
            width="stretch",
        )

        lump_sums: list[LumpSum] = []
        for _, r in lump_df.iterrows():
            if pd.isna(r["Year"]) or pd.isna(r["Month"]) or pd.isna(r["Amount ($)"]):
                continue
            month_index = (int(r["Year"]) - loan.start_year) * 12 + (int(r["Month"]) - loan.start_month)
            if month_index < 0:
                st.warning(f"Lump sum dated {int(r['Month'])}/{int(r['Year'])} is before "
                           "your start date and was ignored.")
                continue
            lump_sums.append(LumpSum(month_index=month_index, amount=float(r["Amount ($)"])))

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
        # Use day 1 of each month as the plotted date.
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
    .properties(height=380)
    .interactive()
)
st.altair_chart(line, width="stretch")

# --------------------------------------------------------------------------- #
# Results: balance at a chosen point in time
# --------------------------------------------------------------------------- #
st.subheader("Balance at a specific time")
st.caption("Pick any year and month to see where each scenario stands then.")

c5, c6 = st.columns(2)
look_month = c5.selectbox("Month", range(1, 13), index=loan.start_month - 1,
                          format_func=lambda m: MONTHS[m - 1], key="look_month")
default_year = add_months(loan.start_year, loan.start_month, 60)[0]  # ~5 years out
look_year = c6.number_input("Year", min_value=loan.start_year, max_value=loan.start_year + 100,
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
