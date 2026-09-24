from datetime import date

from dateutil.relativedelta import relativedelta
from orcaset import Context, Period, formatter, ops, period_union, stmt

from rev_model.contracts import clients
from rev_model.revenue import (
    lost_revenue,
    revenue,
    total_lost_revenue,
    total_revenue,
)

ctx = Context()
periods = Period.list(date(2025, 12, 31), relativedelta(years=1), date(2028, 12, 31))

# Client statistics
print("\nClient statistics")
print(f"Total clients: {len(clients)}")
print(
    f"Avg in-place ACV: {sum(c.opening_annual_contract_value for c in clients) / len(clients):,.0f}"
)
print(
    f"In-place contract end dates: {min(c.opening_term.end for c in clients)} to {max(c.opening_term.end for c in clients)}"
)

# Print revenue for each client
for client in clients:
    client_revenue = revenue[client.id]
    print(
        formatter.fixed_width_table(stmt.Stmt(client_revenue).values(ctx, periods)),
        "\n",
    )

# Print revenue by client cohort
cohort_years = range(
    min(c.first_contract_start for c in clients),
    max(c.first_contract_start for c in clients),
)

cohort_clients = {
    cohort_year: [c for c in clients if c.first_contract_start == cohort_year]
    for cohort_year in cohort_years
}
cohorts = {
    cohort_year: ops.add(
        f"{cohort_year} cohort",
        *[revenue[c.id] for c in cohort],
        fill=0.0,
        merge_keys=period_union,
    )
    for cohort_year, cohort in cohort_clients.items()
    if cohort
}

print(
    "\nRevenue by client cohort\n",
    formatter.fixed_width_table(
        stmt.Stmt(stmt.Total(total_revenue, list(cohorts.values()))).values(
            ctx, periods
        )
    ),
)


# Print cumulative revenue churn by termination reason
print(
    "\nCumulative revenue churn by termination reason\n",
    formatter.fixed_width_table(
        stmt.Stmt(stmt.Total(total_lost_revenue, list(lost_revenue.values()))).values(
            ctx, periods
        )
    ),
)
