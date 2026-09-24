from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from orcaset import Context, Period, formatter, ops, period_union, stmt

from rev_model.contracts import clients
from rev_model.revenue import lost_revenue, revenue, total_lost_revenue, total_revenue

REPORT_YEARS = 3
REPORT_START = date(2026, 10, 1)

cohort_years = tuple(sorted({c.first_contract_start for c in clients}))
cohort_revenue = {
    year: ops.add(
        f"{year} cohort",
        *[revenue[c.id] for c in clients if c.first_contract_start == year],
        fill=0.0,
        merge_keys=period_union,
    )
    for year in cohort_years
}


def quarters(model_start: date, years: int) -> list[Period]:
    """Calendar quarters from ``model_start``, each running from the prior quarter end."""
    end = model_start - timedelta(days=1)
    periods: list[Period] = []
    for _ in range(4 * years):
        start, end = end, end + relativedelta(months=3, day=31)
        periods.append(Period(start, end))
    return periods


def revenue_statement() -> stmt.Stmt:
    return stmt.Stmt(
        stmt.Total(
            total_revenue,
            [cohort_revenue[year] for year in cohort_years],
        ),
        stmt.Total(
            total_lost_revenue,
            list(lost_revenue.values()),
        ),
    )


def render(ctx: Context, periods: list[Period]) -> str:
    result = revenue_statement().values_for_periods(ctx, periods)
    return formatter.markdown_table(result)


if __name__ == "__main__":
    print(render(Context(), quarters(REPORT_START, REPORT_YEARS)))
