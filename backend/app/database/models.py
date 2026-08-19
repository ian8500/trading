from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def new_id() -> str:
    return str(uuid4())


class InstrumentRecord(Base):
    __tablename__ = "instruments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    asset_class: Mapped[str] = mapped_column(String(32), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    provider_symbol: Mapped[str | None] = mapped_column(String(64))
    ig_epic: Mapped[str | None] = mapped_column(String(128), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DataManifestRecord(Base):
    __tablename__ = "data_manifests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    instrument: Mapped[str] = mapped_column(String(64), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(64))
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    missing_intervals: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    usage_note: Mapped[str] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    cache_path: Mapped[str | None] = mapped_column(Text)


class HistoricalBarRecord(Base):
    __tablename__ = "historical_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "provider", "interval", "timestamp", name="uq_historical_bar"
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(ForeignKey("instruments.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    interval: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    volume: Mapped[Decimal] = mapped_column(Numeric(30, 8), default=Decimal("0"))
    complete: Mapped[bool] = mapped_column(Boolean, default=True)
    data_quality: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    manifest_checksum: Mapped[str] = mapped_column(String(64), index=True)


class BacktestRecord(Base):
    __tablename__ = "backtests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starting_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    final_equity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_manifest_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reproducibility_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    trades: Mapped[list[TradeRecord]] = relationship(back_populates="backtest")
    opportunities: Mapped[list[OpportunityRecord]] = relationship(back_populates="backtest")


class OpportunityRecord(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    backtest_id: Mapped[str | None] = mapped_column(ForeignKey("backtests.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    instrument: Mapped[str] = mapped_column(String(64), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    raw_score: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    expected_growth_score: Mapped[Decimal] = mapped_column(Numeric(20, 8), index=True)
    approved: Mapped[bool] = mapped_column(Boolean, index=True)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    candidate: Mapped[dict[str, Any]] = mapped_column(JSON)
    challenge: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_decision: Mapped[dict[str, Any]] = mapped_column(JSON)
    backtest: Mapped[BacktestRecord | None] = relationship(back_populates="opportunities")


class TradeRecord(Base):
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    backtest_id: Mapped[str | None] = mapped_column(ForeignKey("backtests.id"), index=True)
    order_intent_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    instrument: Mapped[str] = mapped_column(String(64), index=True)
    strategy: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    size: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    stop_price: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    equity_before: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    equity_after: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    regime: Mapped[str] = mapped_column(String(32))
    audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    backtest: Mapped[BacktestRecord | None] = relationship(back_populates="trades")


class ManagedCapitalLedgerRecord(Base):
    __tablename__ = "managed_capital_ledgers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    portfolio_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reference_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class SystemStateRecord(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


Index("ix_opportunity_rank", OpportunityRecord.timestamp, OpportunityRecord.expected_growth_score)
Index("ix_trade_instrument_time", TradeRecord.instrument, TradeRecord.opened_at)
Index(
    "ix_historical_bar_lookup",
    HistoricalBarRecord.instrument_id,
    HistoricalBarRecord.interval,
    HistoricalBarRecord.timestamp,
)
