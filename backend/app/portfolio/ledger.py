from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.core.clock import ensure_utc
from app.core.decimal import ZERO, as_decimal, money


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    transaction_id: str
    timestamp: datetime
    gross_pnl: Decimal
    trading_costs: Decimal
    net_pnl: Decimal
    equity_before: Decimal
    equity_after: Decimal
    description: str = ""


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    timestamp: datetime
    starting_capital: Decimal
    cash: Decimal
    realised_pnl: Decimal
    unrealised_pnl: Decimal
    equity: Decimal
    margin_used: Decimal
    free_margin: Decimal
    effective_leverage: Decimal
    open_risk: Decimal
    broker_balance: Decimal | None = None


class ManagedCapitalLedger:
    """Authoritative managed-capital ledger, isolated from broker balance.

    The broker's displayed Demo balance is accepted for display/reconciliation
    only and never participates in ``equity`` or sizing calculations.
    """

    def __init__(self, starting_capital: Decimal | str | int = Decimal("500.00")) -> None:
        starting = money(starting_capital)
        if starting <= ZERO:
            raise ValueError("starting capital must be positive")
        self._starting_capital = starting
        self._realised_pnl = ZERO
        self._entries: list[LedgerEntry] = []
        self._ids: set[str] = set()
        self._broker_balance: Decimal | None = None

    @property
    def starting_capital(self) -> Decimal:
        return self._starting_capital

    @property
    def realised_pnl(self) -> Decimal:
        return money(self._realised_pnl)

    @property
    def equity(self) -> Decimal:
        return money(self._starting_capital + self._realised_pnl)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    @property
    def broker_balance(self) -> Decimal | None:
        return self._broker_balance

    def record_broker_balance(self, value: Decimal | str | int | None) -> None:
        self._broker_balance = None if value is None else money(value)

    def post_trade(
        self,
        transaction_id: str,
        gross_pnl: Decimal | str | int,
        trading_costs: Decimal | str | int = ZERO,
        *,
        timestamp: datetime | None = None,
        description: str = "",
    ) -> LedgerEntry:
        if not transaction_id:
            raise ValueError("transaction_id is required")
        if transaction_id in self._ids:
            raise DuplicateLedgerEntryError(transaction_id)
        gross = money(gross_pnl)
        costs = money(trading_costs)
        if costs < ZERO:
            raise ValueError("trading_costs must not be negative")
        before = self.equity
        net = money(gross - costs)
        after = money(before + net)
        ts = ensure_utc(timestamp or datetime.now(UTC))
        entry = LedgerEntry(
            transaction_id=transaction_id,
            timestamp=ts,
            gross_pnl=gross,
            trading_costs=costs,
            net_pnl=net,
            equity_before=before,
            equity_after=after,
            description=description,
        )
        self._entries.append(entry)
        self._ids.add(transaction_id)
        self._realised_pnl = money(self._realised_pnl + net)
        return entry

    def apply_return(
        self,
        transaction_id: str,
        return_fraction: Decimal | str | int,
        *,
        timestamp: datetime | None = None,
    ) -> LedgerEntry:
        """Convenience for research/accounting tests using an equity return."""

        pnl = money(self.equity * as_decimal(return_fraction))
        return self.post_trade(transaction_id, pnl, timestamp=timestamp)

    def snapshot(
        self,
        *,
        timestamp: datetime | None = None,
        unrealised_pnl: Decimal | str | int = ZERO,
        margin_used: Decimal | str | int = ZERO,
        open_risk: Decimal | str | int = ZERO,
        gross_exposure: Decimal | str | int = ZERO,
    ) -> AccountSnapshot:
        unrealised = money(unrealised_pnl)
        margin = money(margin_used)
        equity = money(self.equity + unrealised)
        free_margin = money(equity - margin)
        leverage = ZERO if equity <= ZERO else as_decimal(gross_exposure) / equity
        return AccountSnapshot(
            timestamp=ensure_utc(timestamp or datetime.now(UTC)),
            starting_capital=self.starting_capital,
            cash=self.equity,
            realised_pnl=self.realised_pnl,
            unrealised_pnl=unrealised,
            equity=equity,
            margin_used=margin,
            free_margin=free_margin,
            effective_leverage=leverage,
            open_risk=money(open_risk),
            broker_balance=self.broker_balance,
        )


class DuplicateLedgerEntryError(RuntimeError):
    pass
