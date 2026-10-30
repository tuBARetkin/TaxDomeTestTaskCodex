"""SQLAlchemy models for the firms and payments tables."""

from sqlalchemy import ForeignKey, Identity, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Firm(Base):
    __tablename__ = "firms"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    balance_cents: Mapped[int] = mapped_column(Integer)
    uuid: Mapped[str] = mapped_column(Text, unique=True)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    payer_firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"))
    payee_firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"))
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
