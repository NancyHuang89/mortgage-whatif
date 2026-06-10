"""Mortgage amortization engine.

Pure Python, no UI and no pandas — so it's easy to read and test on its own.

The whole model is one monthly loop. You are NOT assumed to start from a fresh
loan: you give the *current* state of your mortgage (balance, rate, remaining
term) and the engine runs forward from there.

Each month:
    interest   = balance * (annual_rate / 12)
    principal  = monthly_payment - interest        # the regular payment's split
    balance    = balance - principal - extra_monthly - (any lump sum this month)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Small calendar helper
# --------------------------------------------------------------------------- #
def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    """Return the (year, month) that is `n` months after the given year/month.

    `month` is 1-12. Example: add_months(2026, 6, 8) -> (2027, 2).
    """
    total = (year * 12 + (month - 1)) + n
    return total // 12, total % 12 + 1


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass
class LumpSum:
    """A one-time extra principal payment applied in a specific month."""
    month_index: int   # 0-based offset from the first payment (0 = first month)
    amount: float


@dataclass
class Loan:
    """The current state of your mortgage — where you are *today*."""
    balance: float            # current outstanding principal
    annual_rate: float        # e.g. 0.06 for 6%
    remaining_months: int     # payments left under the original schedule
    start_year: int           # calendar year of the next payment
    start_month: int          # calendar month (1-12) of the next payment

    def standard_payment(self) -> float:
        """The level principal+interest payment that pays this loan off
        exactly over `remaining_months` (the normal amortizing payment)."""
        return monthly_payment(self.balance, self.annual_rate, self.remaining_months)


@dataclass
class Scenario:
    """A what-if overlaid on the base loan."""
    name: str
    extra_monthly: float = 0.0
    lump_sums: list[LumpSum] = field(default_factory=list)
    recast_on_lump: bool = False
    # When True, each lump sum triggers a recast: the monthly payment is
    # recalculated over the months still left in the ORIGINAL term, so the
    # payment drops and the payoff date stays put (instead of the default
    # behavior, where the payment is unchanged and the loan finishes early).


# --------------------------------------------------------------------------- #
# Core math
# --------------------------------------------------------------------------- #
def monthly_payment(balance: float, annual_rate: float, n_months: int) -> float:
    """Standard amortizing payment for `balance` over `n_months`."""
    if n_months <= 0:
        return balance
    r = annual_rate / 12.0
    if r == 0:
        return balance / n_months
    return balance * r / (1 - (1 + r) ** -n_months)


@dataclass
class Row:
    """One month of the schedule."""
    month_index: int
    year: int
    month: int
    start_balance: float
    interest: float
    principal: float        # principal from the regular payment
    extra: float            # extra recurring principal this month
    lump: float             # one-time principal this month
    payment: float          # total cash paid this month (P&I + extra + lump)
    end_balance: float
    cumulative_interest: float


@dataclass
class Schedule:
    rows: list[Row]
    paid_off: bool                  # did it reach zero within the cap?
    months_to_payoff: int
    total_interest: float
    payoff_year: int | None
    payoff_month: int | None
    negative_amortization: bool     # payment didn't even cover interest

    def balance_at(self, month_index: int) -> float:
        """Outstanding balance at the end of the given month index.

        If the loan is already paid off by then, returns 0.0.
        """
        if not self.rows or month_index < 0:
            return self.rows[0].start_balance if self.rows else 0.0
        if month_index >= len(self.rows):
            return 0.0 if self.paid_off else self.rows[-1].end_balance
        return self.rows[month_index].end_balance


def amortize(
    loan: Loan,
    scenario: Scenario | None = None,
    *,
    payment_override: float | None = None,
    max_months: int = 1200,
) -> Schedule:
    """Run the monthly schedule until the loan is paid off (or max_months).

    `payment_override` lets you pin the regular P&I payment (e.g. your actual
    statement amount); otherwise the standard amortizing payment is used.
    """
    scenario = scenario or Scenario(name="Baseline")
    payment = payment_override if payment_override is not None else loan.standard_payment()
    r = loan.annual_rate / 12.0

    # Collapse lump sums into {month_index: total_amount}.
    lumps: dict[int, float] = {}
    for ls in scenario.lump_sums:
        lumps[ls.month_index] = lumps.get(ls.month_index, 0.0) + ls.amount

    rows: list[Row] = []
    bal = loan.balance
    cumulative_interest = 0.0
    neg_am = False
    m = 0

    while bal > 0.005 and m < max_months:
        interest = bal * r
        scheduled_principal = payment - interest
        if scheduled_principal <= 0:
            neg_am = True  # payment doesn't cover interest on its own

        extra = scenario.extra_monthly
        lump = lumps.get(m, 0.0)

        # Total principal we intend to knock off this month.
        intended = scheduled_principal + extra + lump

        year, month = add_months(loan.start_year, loan.start_month, m)

        if intended >= bal:
            # Final month: pay exactly what's left (plus this month's interest).
            principal = min(scheduled_principal, bal)
            remaining_after_regular = bal - principal
            extra_applied = min(extra, max(remaining_after_regular, 0.0))
            remaining_after_extra = remaining_after_regular - extra_applied
            lump_applied = min(lump, max(remaining_after_extra, 0.0))
            end_balance = 0.0
        else:
            principal = scheduled_principal
            extra_applied = extra
            lump_applied = lump
            end_balance = bal - intended

        cumulative_interest += interest
        rows.append(
            Row(
                month_index=m,
                year=year,
                month=month,
                start_balance=bal,
                interest=interest,
                principal=principal,
                extra=extra_applied,
                lump=lump_applied,
                payment=interest + principal + extra_applied + lump_applied,
                end_balance=end_balance,
                cumulative_interest=cumulative_interest,
            )
        )
        bal = end_balance

        # Mortgage recast: a lump sum re-amortizes the remaining balance over
        # the months still left in the ORIGINAL term, lowering future payments
        # while leaving the payoff date unchanged.
        if scenario.recast_on_lump and lump_applied > 0 and bal > 0.005:
            term_months_left = loan.remaining_months - (m + 1)
            if term_months_left > 0:
                payment = monthly_payment(bal, loan.annual_rate, term_months_left)

        m += 1

    paid_off = bal <= 0.005
    payoff_year = rows[-1].year if (rows and paid_off) else None
    payoff_month = rows[-1].month if (rows and paid_off) else None

    return Schedule(
        rows=rows,
        paid_off=paid_off,
        months_to_payoff=len(rows) if paid_off else max_months,
        total_interest=cumulative_interest,
        payoff_year=payoff_year,
        payoff_month=payoff_month,
        negative_amortization=neg_am,
    )
