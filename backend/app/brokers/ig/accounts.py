"""IG Demo account discovery and explicit account switching."""

from __future__ import annotations

from decimal import Decimal

from ..base import AccountSnapshot
from .client import IGClient
from .errors import IGConfigurationError
from .utils import decimal_or_none, list_or_empty, mapping_or_empty, require_account_id


class IGAccountsService:
    def __init__(self, client: IGClient) -> None:
        self.client = client

    async def list(self) -> tuple[AccountSnapshot, ...]:
        payload = await self.client.request("GET", "/accounts", version=1)
        rows = list_or_empty(mapping_or_empty(payload).get("accounts"))
        results: list[AccountSnapshot] = []
        for raw_row in rows:
            row = mapping_or_empty(raw_row)
            account_id = row.get("accountId")
            if not isinstance(account_id, str):
                continue
            balance = mapping_or_empty(row.get("balance"))
            results.append(
                AccountSnapshot(
                    account_id=account_id,
                    account_name=str(row.get("accountName") or row.get("accountType") or "IG Demo"),
                    currency=str(row.get("currency") or ""),
                    balance=decimal_or_none(balance.get("balance")) or Decimal("0"),
                    available=decimal_or_none(balance.get("available")) or Decimal("0"),
                    profit_loss=decimal_or_none(balance.get("profitLoss")) or Decimal("0"),
                    preferred=bool(row.get("preferred")),
                    status=str(row["status"]) if row.get("status") is not None else None,
                )
            )
        return tuple(results)

    async def select(self, account_id: str) -> None:
        account_id = require_account_id(account_id)
        known = {account.account_id for account in await self.list()}
        if account_id not in known:
            raise IGConfigurationError("configured IG Demo account was not discovered")
        if self.client.credentials.account_id != account_id:
            raise IGConfigurationError("set IG_ACCOUNT_ID before connecting to select this account")
        await self.client.auth.refresh()
        session = self.client.auth.session
        if session is None or session.account_id != account_id:
            raise IGConfigurationError("configured IG Demo account switch could not be verified")
