from datetime import date

from dateutil.relativedelta import relativedelta
from orcaset import (
    YF,
    Chain,
    Cons,
    Effect,
    Fn,
    Maybe,
    Period,
    Rule,
    Series,
    Thunk,
    Val,
    date_union,
    get,
    map_cells,
    ops,
    period_union,
    query,
)

from rev_model.clients import Client
from rev_model.contracts import ContractState, EndedContract, clients, contracts
from rev_model.jev import TerminationReason

type RevenueSeries = Series[Period, float, Maybe[float]]
type LostRevenueSeries = Series[date, float, Maybe[float]]


def build_revenue(client: Client) -> RevenueSeries:
    source = contracts[client.id]
    source_cells = source.cells

    def map_cells(cells: Chain[date, ContractState]) -> Chain[Period, float]:
        def compute() -> Effect[Cons[Period, float] | None]:
            cons = yield from get(cells)
            if cons is None:
                return None
            held = yield from get(cons.value)
            if isinstance(held, EndedContract):
                return None
            return Cons(
                held.term,
                Val("Revenue", held.annual_contract_value * YF.cmonthly(*held.term)),
                map_cells(cons.tail),
            )

        return Fn("Revenue cells", compute)

    return Series(
        f"{client.name} revenue", map_cells(source_cells), query.accrue(YF.cmonthly)
    )


revenue: dict[str, RevenueSeries] = {
    client.id: build_revenue(client) for client in clients
}

total_revenue = ops.add(
    "Total revenue",
    *revenue.values(),
    merge_keys=period_union,
    fill=0.0,
)


def build_lost_revenue(client: Client, reason: TerminationReason) -> LostRevenueSeries:
    """Cumulative churned ACV for ``reason``, stepping up on the final term end.

    Keys stay on the contract dates. The amount is a thunk, so ``query.last`` can
    read the next date and stop without judging that renewal.
    """

    def amount(_on: date, state: Rule[ContractState]) -> Thunk[float]:
        def compute() -> Effect[float]:
            held = yield from get(state)
            if isinstance(held, EndedContract) and held.termination_reason == reason:
                return held.annual_contract_value
            return 0.0

        return Thunk(compute)

    return Series(
        f"{client.name} lost revenue ({reason.value})",
        map_cells(
            f"{client.name} lost revenue cells ({reason.value})",
            contracts[client.id].cells,
            amount,
        ),
        query.last,
    )


lost_revenue = {
    reason: ops.add(
        f"{reason.value}",
        *[build_lost_revenue(client, reason) for client in clients],
        merge_keys=date_union,
        fill=0.0,
    )
    for reason in TerminationReason
}

total_lost_revenue = ops.add(
    "Total cumulative lost revenue",
    *lost_revenue.values(),
    merge_keys=date_union,
    fill=0.0,
)


if __name__ == "__main__":
    from orcaset import Context, formatter, stmt

    revenue_stmt = stmt.Stmt(stmt.Total(total_revenue, list(revenue.values())))

    periods = Period.list(
        date(2025, 12, 31), relativedelta(months=3), date(2030, 12, 31)
    )
    ctx = Context()
    print(formatter.fixed_width_table(revenue_stmt.values(ctx, periods)))
