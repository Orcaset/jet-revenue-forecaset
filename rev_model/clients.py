import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

from orcaset import Period
from pydantic import BaseModel, ConfigDict, PlainSerializer


@dataclass(frozen=True)
class CrmNote:
    date: date
    text: str


def _period_json(period: Period) -> dict[str, str]:
    return {"start": period.start.isoformat(), "end": period.end.isoformat()}


JsonPeriod = Annotated[Period, PlainSerializer(_period_json, when_used="json")]


class Client(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    opening_term: JsonPeriod
    opening_annual_contract_value: float
    first_contract_start: int
    ttm_usage_growth_pct: float
    crm_notes: tuple[CrmNote, ...]

    @property
    def cohort_year(self) -> int:
        return self.opening_term.start.year


def load_clients(path: str | Path) -> tuple[Client, ...]:
    records = json.loads(Path(path).read_text())
    return tuple(
        Client(
            id=r["id"],
            name=r["name"],
            opening_term=Period(
                date.fromisoformat(r["opening_term"]["start"]),
                date.fromisoformat(r["opening_term"]["end"]),
            ),
            opening_annual_contract_value=float(r["opening_annual_contract_value"]),
            first_contract_start=int(r["first_contract_start"]),
            ttm_usage_growth_pct=r["ttm_usage_growth_pct"],
            crm_notes=tuple(
                CrmNote(date=date.fromisoformat(n["date"]), text=n["text"])
                for n in r["crm_notes"]
            ),
        )
        for r in records
    )
