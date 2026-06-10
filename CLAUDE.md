# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user **mortgage what-if explorer**. You describe a loan as it stands
*today* (current balance, rate, remaining term — not a fresh loan), build a few
scenarios (extra monthly payments, one-off lump-sum principal payments, and
optional mortgage recast), and compare payoff date and total interest side by
side. Built with Streamlit so it can be used on an iPhone via Safari → "Add to
Home Screen".

Two ways a lump sum can behave, chosen per scenario via `Scenario.recast_on_lump`:
keep the payment and finish early (default), or **recast** — re-amortize over the
remaining original term so the payment drops and the payoff date is unchanged.

## Commands

All commands assume the project virtualenv in `.venv/`.

- Run the app:        `.venv/bin/streamlit run app.py`
- Run the tests:      `.venv/bin/python test_mortgage.py`
- Headless boot check: `.venv/bin/streamlit run app.py --server.headless true`
- Install deps:       `.venv/bin/pip install -r requirements.txt`

There is no test framework — `test_mortgage.py` is a plain script with
assert-based checks and a `__main__` runner. Add new checks as `test_*`
functions; they're auto-discovered by the runner.

## Architecture

Deliberately split into a pure engine and a thin UI:

- **`mortgage.py`** — the amortization engine. Pure Python, no Streamlit and no
  pandas, so it's unit-testable in isolation. The whole model is one monthly
  loop in `amortize()`. Key types: `Loan` (current state + `standard_payment()`),
  `Scenario` (extra monthly + list of `LumpSum`), `Schedule` (result rows +
  summary, with `balance_at(month_index)`). Time is tracked as a 0-based
  `month_index` from the first payment; `add_months()` maps that to calendar
  year/month.
- **`app.py`** — the Streamlit UI. Reads loan inputs from the sidebar, builds
  N `Scenario`s from tabs (lump sums entered via `st.data_editor`, with calendar
  year/month converted to `month_index` relative to the loan start), runs each
  through `amortize()`, and renders a comparison table, an Altair balance-over-
  time chart, a point-in-time balance lookup, and a full schedule expander.

When changing the math, edit `mortgage.py` and keep `app.py` UI-only. Verify
engine changes with `test_mortgage.py`; verify the UI runs end-to-end with
Streamlit's `AppTest` (`from streamlit.testing.v1 import AppTest`).

## Conventions

- Streamlit deprecated `use_container_width`; this project uses `width="stretch"`.
- Lump sums dated before the loan start are ignored with a warning, not an error.
- `max_months` in `amortize()` caps runaway loops (e.g. negative amortization
  when the payment doesn't cover interest); such cases set
  `Schedule.negative_amortization` and surface a warning in the UI.
