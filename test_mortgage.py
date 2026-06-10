"""Quick sanity checks for the amortization engine. Run: python test_mortgage.py"""

from mortgage import Loan, Scenario, LumpSum, amortize, monthly_payment, add_months


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def test_standard_payment():
    # $300k, 6% annual, 30 years (360 months) -> well-known ~$1798.65
    pmt = monthly_payment(300_000, 0.06, 360)
    assert approx(pmt, 1798.65, 0.5), pmt


def test_pays_off_on_schedule():
    loan = Loan(balance=300_000, annual_rate=0.06, remaining_months=360,
                start_year=2026, start_month=1)
    sched = amortize(loan)  # uses standard payment
    assert sched.paid_off
    assert sched.months_to_payoff == 360, sched.months_to_payoff
    # Total interest on a 30yr 6% $300k loan is ~$347,515
    assert approx(sched.total_interest, 347_514.57, 5.0), sched.total_interest


def test_placed_midway():
    # Not a fresh loan: 200k left, 20 years remaining.
    loan = Loan(balance=200_000, annual_rate=0.05, remaining_months=240,
                start_year=2026, start_month=6)
    sched = amortize(loan)
    assert sched.paid_off and sched.months_to_payoff == 240
    # First payment lands on the start date.
    assert (sched.rows[0].year, sched.rows[0].month) == (2026, 6)


def test_extra_monthly_shortens_loan():
    loan = Loan(balance=300_000, annual_rate=0.06, remaining_months=360,
                start_year=2026, start_month=1)
    base = amortize(loan)
    faster = amortize(loan, Scenario("Extra $200", extra_monthly=200))
    assert faster.months_to_payoff < base.months_to_payoff
    assert faster.total_interest < base.total_interest


def test_lump_sum_reduces_balance():
    loan = Loan(balance=300_000, annual_rate=0.06, remaining_months=360,
                start_year=2026, start_month=1)
    base = amortize(loan)
    lump = amortize(loan, Scenario("10k @ yr1", lump_sums=[LumpSum(12, 10_000)]))
    # Balance right after the lump (month index 12) should be ~10k lower.
    assert lump.balance_at(12) < base.balance_at(12) - 9_000
    assert lump.months_to_payoff < base.months_to_payoff


def test_recast_keeps_term_lowers_payment():
    loan = Loan(balance=300_000, annual_rate=0.06, remaining_months=360,
                start_year=2026, start_month=1)
    base = amortize(loan)
    lump = [LumpSum(12, 50_000)]
    recast = amortize(loan, Scenario("recast", lump_sums=lump, recast_on_lump=True))
    pay_early = amortize(loan, Scenario("early", lump_sums=lump))  # default: no recast

    # Recast leaves the payoff date on the original schedule...
    assert recast.months_to_payoff == 360, recast.months_to_payoff
    # ...while the pay-early strategy finishes sooner.
    assert pay_early.months_to_payoff < 360

    # The payment drops after the recast (month index 13 = first full month after
    # the lump), versus the unchanged baseline payment.
    base_pmt = base.rows[0].payment            # P&I only (no extra/lump)
    after_pmt = recast.rows[13].payment
    assert after_pmt < base_pmt, (after_pmt, base_pmt)

    # Interest saved by recast is real but smaller than keeping the high payment.
    assert recast.total_interest < base.total_interest
    assert recast.total_interest > pay_early.total_interest


def test_add_months():
    assert add_months(2026, 6, 8) == (2027, 2)
    assert add_months(2026, 12, 1) == (2027, 1)
    assert add_months(2026, 1, 0) == (2026, 1)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
