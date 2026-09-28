"""The benchmark's 24-month analysis window (DEV_PLAN section 5.3)."""

from __future__ import annotations

from datetime import date

from shared.settings import Settings


def window_bounds(settings: Settings) -> tuple[date, date]:
    """Return (window_start, window_end), both inclusive.

    window_end is the confirmed benchmark end date. window_start is the first day of
    the month `window_months` months before it.
    """
    end = settings.benchmark.end_date
    if end is None:
        raise ValueError("benchmark.end_date is not set in config/settings.yaml")
    months = settings.benchmark.window_months

    end_month_index = end.year * 12 + (end.month - 1)  # months since year 0, 0-indexed
    start_month_index = end_month_index - months + 1  # window_months inclusive of end's month
    start_year, start_month0 = divmod(start_month_index, 12)
    start = date(start_year, start_month0 + 1, 1)
    return start, end
