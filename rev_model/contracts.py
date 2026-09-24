from datetime import date, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from orcaset import (
    Effect,
    Fn,
    Maybe,
    Period,
    Series,
    Thunk,
    Val,
    get,
    get_at,
    query,
)
from pydantic import BaseModel, ConfigDict

from rev_model.clients import Client, JsonPeriod, load_clients
from rev_model.jev import Renewal, RenewalForecaster, TerminationReason

DATA_PATH = Path(__file__).parent.parent / "data" / "clients.json"
clients = load_clients(DATA_PATH)

# Whole years, so each client renews at most once per calendar year.
RENEWAL_YEARS = 3
forecaster: Val[RenewalForecaster] = Val("Renewal forecaster", RenewalForecaster())


class RenewalTerm(BaseModel):
    model_config = ConfigDict(frozen=True)

    term: JsonPeriod
    annual_contract_value: float
    value_step_up: float


class ActiveContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    client: Client
    term: JsonPeriod
    annual_contract_value: float
    prior_renewals: tuple[RenewalTerm, ...]


class EndedContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    client: Client
    termination_date: date
    termination_reason: TerminationReason
    prior_renewals: tuple[RenewalTerm, ...]

    @property
    def annual_contract_value(self) -> float:
        if self.prior_renewals:
            return self.prior_renewals[-1].annual_contract_value
        return self.client.opening_annual_contract_value


type ContractState = ActiveContract | EndedContract
type ContractSeries = Series[date, ContractState, Maybe[ContractState]]


def initial_contract(client: Client) -> ActiveContract:
    return ActiveContract(
        client=client,
        term=client.opening_term,
        annual_contract_value=client.opening_annual_contract_value,
        prior_renewals=(),
    )


def next_renewal(client: Client, on: date) -> date:
    """Term end after a renewal on ``on``, measured from the opening end."""
    elapsed = on.year - client.opening_term.end.year
    return client.opening_term.end + relativedelta(years=elapsed + RENEWAL_YEARS)


def apply_renewal(state: ActiveContract, judgment: Renewal) -> ContractState:
    if judgment.value_step_up <= -1.0:
        if judgment.termination is None:
            raise ValueError(
                f"Non-renewal for {state.client.name} did not include a termination reason"
            )
        return EndedContract(
            client=state.client,
            termination_date=state.term.end,
            termination_reason=judgment.termination.reason,
            prior_renewals=state.prior_renewals,
        )
    start = state.term.end
    step_up = judgment.value_step_up
    term = Period(start, next_renewal(state.client, start))
    annual_contract_value = state.annual_contract_value * (1.0 + step_up)
    renewal = RenewalTerm(
        term=term,
        annual_contract_value=annual_contract_value,
        value_step_up=step_up,
    )
    return ActiveContract(
        client=state.client,
        term=term,
        annual_contract_value=annual_contract_value,
        prior_renewals=(*state.prior_renewals, renewal),
    )


class ContractBook:
    """Contracts in force, and the renewals decided through the date ``through``."""

    def __init__(self, through: date) -> None:
        self.contracts: dict[str, ContractState] = {
            client.id: initial_contract(client) for client in clients
        }
        self.through = through
        self._renewals: dict[tuple[str, date], Renewal] = {}

    def renewal(self, client_id: str, on: date) -> Effect[Renewal]:
        while on > self.through:
            yield from self._advance()
        try:
            return self._renewals[client_id, on]
        except KeyError:
            raise ValueError(
                f"No renewal for {client_id} on {on.isoformat()}"
            ) from None

    def _advance(self) -> Effect[None]:
        nxt = self.through + relativedelta(years=1)
        due: list[ActiveContract] = []
        for client in clients:
            state = self.contracts[client.id]
            if (
                isinstance(state, ActiveContract)
                and self.through < state.term.end <= nxt
            ):
                due.append(state)
        if due:
            judge = yield from get(forecaster)
            judged = judge.forecast_many(due)
            decided = {
                (state.client.id, state.term.end): judged[state.client.id]
                for state in due
            }
            renewed = {
                state.client.id: apply_renewal(
                    state, decided[state.client.id, state.term.end]
                )
                for state in due
            }
            self._renewals.update(decided)
            self.contracts.update(renewed)
        self.through = nxt


@Fn.define("Contract book")
def book() -> ContractBook:
    first_year = min(client.opening_term.end.year for client in clients)
    return ContractBook(date(first_year - 1, 12, 31))


def build_contract(client: Client) -> ContractSeries:
    opening = client.opening_term

    def step(on: date) -> tuple[date, ContractState | Thunk[ContractState], date]:
        if on == opening.start:
            return on, initial_contract(client), opening.end

        def value(on: date = on) -> Effect[ContractState]:
            prior = yield from get_at(contracts[client.id], on - timedelta(days=1))
            if isinstance(prior, EndedContract):
                return prior
            if not isinstance(prior, ActiveContract):
                raise TypeError(
                    f"No contract for {client.name} before {on.isoformat()}"
                )
            held = yield from get(book)
            judgment = yield from held.renewal(client.id, on)
            return apply_renewal(prior, judgment)

        return on, Thunk(value), next_renewal(client, on)

    return Series[date, ContractState, Maybe[ContractState]].unfold(
        f"{client.name} contract",
        query.last,
        seed=opening.start,
        step=step,
    )


contracts: dict[str, ContractSeries] = {c.id: build_contract(c) for c in clients}


if __name__ == "__main__":
    from orcaset import Context, isna

    ctx = Context()
    on = date(2035, 10, 1)
    for client in clients:
        state = ctx.get_at(contracts[client.id], on)
        if isna(state):
            print(f"{client.name}: no contract on {on.isoformat()}")
        elif isinstance(state, ActiveContract):
            print(
                f"{client.name:<28}  annual contract value of {state.annual_contract_value:,.0f} "
                f"with current contract ending {state.term.end.isoformat()}"
            )
        else:
            print(
                f"{client.name:<28}  terminated on {state.termination_date.isoformat()} "
                f"with reason '{state.termination_reason}'"
            )
