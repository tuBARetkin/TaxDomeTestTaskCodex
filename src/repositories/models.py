"""Models accepted by the persistence layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentWrite:
    payee_firm_uuid: str
    amount_cents: int
    description: str
