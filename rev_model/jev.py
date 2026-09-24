import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient, Choice

load_dotenv()

if TYPE_CHECKING:
    from rev_model.contracts import ActiveContract

RENEWAL_BUCKETS: dict[str, float] = {
    "non_renewal": -1.0,
    "down_10": -0.10,
    "down_5": -0.05,
    "flat": 0.0,
    "up_5": 0.05,
    "up_10": 0.10,
    "up_25": 0.25,
    "up_50": 0.50,
}

RENEWAL_CRITERIA: dict[str, str] = {
    "non_renewal": "Client does not renew; annual contract value goes to zero (-100%)",
    "down_10": "Renews at roughly 10% lower annual contract value (-10%)",
    "down_5": "Renews at roughly 5% lower annual contract value (-5%)",
    "flat": "Renews at the same annual contract value (0%)",
    "up_5": "Renews at roughly 5% higher annual contract value (+5%)",
    "up_10": "Renews at roughly 10% higher annual contract value (+10%)",
    "up_25": "Renews at roughly 25% higher annual contract value (+25%)",
    "up_50": "Renews with roughly 50% higher annual contract value — major expansion (+50%)",
}


class TerminationReason(StrEnum):
    BUDGET_CUT = "budget_cut"
    LOST_CHAMPION = "lost_champion"
    COMPETITOR = "competitor"
    LOW_ADOPTION = "low_adoption"
    UNCLEAR = "unclear"


TERMINATION_REASONS: dict[TerminationReason, str] = {
    TerminationReason.BUDGET_CUT: (
        "The contract ends because the client is cutting spend — a budget freeze, "
        "a finance cut list, or a failed funding vote — even if people still use the product."
    ),
    TerminationReason.LOST_CHAMPION: (
        "The contract ends because the sponsor left and the new owner will not keep it."
    ),
    TerminationReason.COMPETITOR: (
        "The contract ends because the client is switching to a competitor or alternative product."
    ),
    TerminationReason.LOW_ADOPTION: (
        "The contract ends because usage has collapsed and the product is no longer embedded, "
        "and the notes do not point to a budget cut, a lost champion, or a competitor."
    ),
    TerminationReason.UNCLEAR: "The contract ends, but the notes do not support a specific reason.",
}

RENEWAL_QUESTION = Choice(
    instructions=(
        "When `term` ends, what happens to `annual_contract_value` at renewal? "
        "Consider `client` — CRM notes, usage trend, and tenure — and any "
        "`prior_renewals`. Judge `term` and `annual_contract_value`. "
        "`client.opening_term` and `client.opening_annual_contract_value` are "
        "the contract at the start of the forecast."
    ),
    criteria=RENEWAL_CRITERIA,
)

TERMINATION_QUESTION = Choice(
    instructions=(
        "Assume `term` is not renewed. Why does the contract end? Consider "
        "`client` — CRM notes, usage trend, and tenure — and any "
        "`prior_renewals`. The in-force contract is `term` and "
        "`annual_contract_value`."
    ),
    criteria={reason.value: text for reason, text in TERMINATION_REASONS.items()},
)


@dataclass(frozen=True)
class Termination:
    reason: TerminationReason
    confidence: float
    probabilities: dict[TerminationReason, float]


@dataclass(frozen=True)
class Renewal:
    bucket: str
    confidence: float
    probabilities: dict[str, float]
    termination: Termination | None

    @property
    def value_step_up(self) -> float:
        return RENEWAL_BUCKETS[self.bucket]

    @property
    def multiplier(self) -> float:
        return 1.0 + self.value_step_up


num_calls = 0
"""Number of Jev `system_one` calls made in this process. Read as `rev_model.jev.num_calls`."""


class RenewalForecaster:
    def __init__(self, ts_client: AsyncTypeSafeClient | None = None) -> None:
        self._ts_client = ts_client

    @asynccontextmanager
    async def _client(self) -> AsyncGenerator[AsyncTypeSafeClient]:
        if self._ts_client is not None:
            yield self._ts_client
            return
        async with AsyncTypeSafeClient() as client:
            yield client

    async def _forecast(
        self, client: AsyncTypeSafeClient, contract: ActiveContract
    ) -> Renewal:
        global num_calls
        num_calls += 1
        response = await client.system_one(
            state=contract.model_dump(mode="json"),
            questions={
                "renewal_outcome": RENEWAL_QUESTION,
                "termination_reason": TERMINATION_QUESTION,
            },
            model="jev-latest",
        )
        outcome = response.choices["renewal_outcome"]
        termination = None
        if outcome.choice == "non_renewal":
            reason = response.choices["termination_reason"]
            termination = Termination(
                reason=TerminationReason(reason.choice),
                confidence=reason.confidence,
                probabilities={
                    TerminationReason(name): probability
                    for name, probability in reason.probabilities.items()
                },
            )
        return Renewal(
            bucket=outcome.choice,
            confidence=outcome.confidence,
            probabilities=dict(outcome.probabilities),
            termination=termination,
        )

    def forecast(self, contract: ActiveContract) -> Renewal:
        async def run() -> Renewal:
            async with self._client() as client:
                return await self._forecast(client, contract)

        return asyncio.run(run())

    def forecast_many(self, contracts: Sequence[ActiveContract]) -> dict[str, Renewal]:
        """Send every contract at once and gather the responses. One failure fails the batch."""
        if not contracts:
            return {}

        async def run() -> dict[str, Renewal]:
            async with self._client() as client:
                results = await asyncio.gather(
                    *(self._forecast(client, contract) for contract in contracts)
                )
            return {
                contract.client.id: renewal
                for contract, renewal in zip(contracts, results, strict=True)
            }

        return asyncio.run(run())


if __name__ == "__main__":
    from rev_model.contracts import ActiveContract, clients

    client = clients[0]
    contract = ActiveContract(
        client=client,
        term=client.opening_term,
        annual_contract_value=client.opening_annual_contract_value,
        prior_renewals=(),
    )
    forecaster = RenewalForecaster()
    r = forecaster.forecast(contract)
    print(f"Client: {client.name}")
    print(
        f"Forecast: bucket={r.bucket}, value_step_up={r.value_step_up:+.0%}, "
        f"confidence={r.confidence:.2f}, probabilities={r.probabilities}"
    )
    if r.termination is not None:
        print(
            f"Termination: reason={r.termination.reason}, "
            f"confidence={r.termination.confidence:.2f}, "
            f"probabilities={r.termination.probabilities}"
        )
