from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.backtesting.models import Bar
from app.core.clock import ensure_utc
from app.instruments import AssetClass, Instrument


class SessionPhase(StrEnum):
    SIGNAL = "SIGNAL"
    FILL = "FILL"


@dataclass(frozen=True, slots=True)
class SessionDecision:
    eligible: bool
    policy_id: str
    phase: SessionPhase
    evaluated_at: datetime
    reason: str

    def audit_details(self) -> dict[str, object]:
        return {
            "eligible": self.eligible,
            "policy_id": self.policy_id,
            "phase": self.phase.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "reason": self.reason,
            "historical_broker_hours": False,
        }


@dataclass(frozen=True, slots=True)
class MarketSessionPolicy:
    """Versioned research eligibility proxy, not historical broker hours."""

    policy_id: str = "research-market-sessions-v1"
    maximum_daily_fill_gap: timedelta = timedelta(days=7)
    maximum_intraday_fill_gap: timedelta = timedelta(hours=72)

    def at_signal(
        self,
        instrument: Instrument,
        completed_bar: Bar,
        *,
        interval: str,
    ) -> SessionDecision:
        return self._decision(
            instrument,
            completed_bar.timestamp,
            interval=interval,
            phase=SessionPhase.SIGNAL,
        )

    def at_fill(
        self,
        instrument: Instrument,
        signal_time: datetime,
        execution_bar: Bar,
        *,
        interval: str,
    ) -> SessionDecision:
        signal = ensure_utc(signal_time)
        completion = ensure_utc(execution_bar.timestamp)
        maximum_gap = (
            self.maximum_daily_fill_gap if interval == "1d" else self.maximum_intraday_fill_gap
        )
        gap = completion - signal
        if gap <= timedelta(0) or gap > maximum_gap:
            return SessionDecision(
                False,
                self.policy_id,
                SessionPhase.FILL,
                completion,
                f"next own-market bar gap {gap} exceeds research limit {maximum_gap}",
            )
        evaluated_at = completion - _interval_length(interval)
        return self._decision(
            instrument,
            evaluated_at,
            interval=interval,
            phase=SessionPhase.FILL,
        )

    def _decision(
        self,
        instrument: Instrument,
        timestamp: datetime,
        *,
        interval: str,
        phase: SessionPhase,
    ) -> SessionDecision:
        evaluated = ensure_utc(timestamp)
        if not instrument.tradeable or not instrument.market_open:
            return SessionDecision(
                False,
                self.policy_id,
                phase,
                evaluated,
                "instrument capability is not tradeable/open",
            )
        if interval == "1d":
            return SessionDecision(
                True,
                self.policy_id,
                phase,
                evaluated,
                "completed daily own-market bar is the session-availability proxy",
            )
        eligible, reason = self._intraday_window(instrument, evaluated, phase)
        return SessionDecision(eligible, self.policy_id, phase, evaluated, reason)

    @staticmethod
    def _intraday_window(
        instrument: Instrument,
        timestamp: datetime,
        phase: SessionPhase,
    ) -> tuple[bool, str]:
        if instrument.asset_class is AssetClass.CRYPTO:
            return True, "24/7 crypto research-session proxy"
        if instrument.asset_class is AssetClass.FX:
            weekday = timestamp.weekday()
            current = timestamp.time()
            eligible = (
                weekday < 4
                or (weekday == 4 and current < time(22))
                or (weekday == 6 and current >= time(22))
            )
            return eligible, "FX Sunday 22:00-Friday 22:00 UTC research-session proxy"

        if instrument.id in {"SP500", "NASDAQ100"}:
            return _local_window(
                timestamp,
                ZoneInfo("America/New_York"),
                time(9, 30),
                time(16),
                phase,
                "US cash-session research proxy",
            )
        if instrument.id == "FTSE100":
            return _local_window(
                timestamp,
                ZoneInfo("Europe/London"),
                time(8),
                time(16, 30),
                phase,
                "UK cash-session research proxy",
            )
        if instrument.id == "DAX":
            return _local_window(
                timestamp,
                ZoneInfo("Europe/Berlin"),
                time(9),
                time(17, 30),
                phase,
                "German cash-session research proxy",
            )
        if instrument.id == "GOLD":
            local = timestamp.astimezone(ZoneInfo("America/New_York"))
            weekday = local.weekday()
            current = local.time()
            eligible = (
                (weekday < 4 and not time(17) <= current < time(18))
                or (weekday == 4 and current < time(17))
                or (weekday == 6 and current >= time(18))
            )
            return eligible, "Gold futures-hours research proxy with daily maintenance break"
        return True, "no narrower versioned research-session proxy for this instrument"

    def audit_details(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "maximum_daily_fill_gap_seconds": int(self.maximum_daily_fill_gap.total_seconds()),
            "maximum_intraday_fill_gap_seconds": int(
                self.maximum_intraday_fill_gap.total_seconds()
            ),
            "historical_broker_hours": False,
            "description": "versioned research proxy based on causal timestamp and own-market bars",
        }


def _interval_length(interval: str) -> timedelta:
    return {
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
    }.get(interval, timedelta(0))


def _local_window(
    timestamp: datetime,
    timezone: ZoneInfo,
    opens: time,
    closes: time,
    phase: SessionPhase,
    label: str,
) -> tuple[bool, str]:
    local = timestamp.astimezone(timezone)
    current = local.time().replace(tzinfo=None)
    close_ok = current <= closes if phase is SessionPhase.SIGNAL else current < closes
    return local.weekday() < 5 and opens <= current and close_ok, label
